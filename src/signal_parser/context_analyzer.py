"""Context analyzer for understanding ambiguous update messages using GPT-5-mini."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import orjson

from config.logging_config import (
    get_contextual_logger,
    set_correlation_id,
    set_service_context,
)
from config.openai_config import openai_client
from src.database.cache import llm_cache
from src.database.models import Position
from src.utils.circuit_breaker import circuit_breaker
from src.utils.rate_limiter import llm_rate_limiter


@dataclass
class TelegramMessage:
    """Telegram message structure for context analysis."""
    telegram_message_id: int
    telegram_chat_id: int
    sender: str
    timestamp: datetime
    raw_text: str
    reply_to_message_id: int | None = None
    chat_title: str = ""
    is_forwarded: bool = False
    message_type: str = "text"


@dataclass
class ContextAnalysisResult:
    """Result from LLM context analysis of update messages."""
    action: str  # "breakeven|close|modify|unknown"
    target_position: str | None  # mt5_ticket or null
    parameters: dict[str, Any]  # percentage, new_sl, new_tp
    confidence: float  # 0.0-1.0
    reasoning: str
    correlation_id: str
    analysis_latency_ms: int


class ContextAnalyzer:
    """GPT-5-mini based analyzer for ambiguous message context interpretation."""

    def __init__(self) -> None:
        """Initialize context analyzer with prompt template and configuration."""
        self.logger = get_contextual_logger(__name__)
        self._prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load context analysis prompt template from config file."""
        try:
            prompt_path = Path(__file__).parent.parent.parent / "config" / "prompts" / "context_analyzer.txt"
            return prompt_path.read_text(encoding='utf-8')
        except Exception as e:
            self.logger.error(f"Failed to load context analyzer prompt template: {e}")
            raise

    async def analyze_update_context(
        self,
        message: TelegramMessage,
        parent_message: TelegramMessage,
        positions: list[Position]
    ) -> ContextAnalysisResult | None:
        """
        Analyze ambiguous update message context using GPT-5-mini.
        
        Args:
            message: Current update message to analyze
            parent_message: Parent message for context (original signal)
            positions: List of open positions for target identification
            
        Returns:
            ContextAnalysisResult if analysis successful, None if failed or low confidence
        """
        if not message.raw_text or not message.raw_text.strip():
            return None

        # Set service context for logging
        set_service_context("ContextAnalyzer", "analyze_update_context")
        correlation_id = set_correlation_id()
        start_time = datetime.now()

        # Generate cache key from message content and context
        cache_key = self._generate_cache_key(message, parent_message, positions)

        # Check cache first
        cached_response = await llm_cache.get(cache_key)
        if cached_response:
            try:
                result = self._reconstruct_result_from_cache(cached_response, correlation_id, start_time)
                if result:
                    self.logger.info(
                        "Context analysis completed from cache",
                        extra_fields={
                            "context_analysis": {
                                "action": result.action,
                                "target_position": result.target_position,
                                "confidence": result.confidence,
                                "cache_hit": True,
                                "correlation_id": correlation_id,
                                "message_hash": self._hash_text(message.raw_text)
                            }
                        }
                    )
                    return result
            except Exception as e:
                self.logger.warning(f"Failed to reconstruct context analysis from cache: {e}")

        # Acquire rate limit permission
        if not await llm_rate_limiter.acquire():
            self.logger.warning(
                "LLM rate limit exceeded for context analysis",
                extra_fields={
                    "context_analysis": {
                        **llm_rate_limiter.get_metrics(),
                        "correlation_id": correlation_id,
                        "message_hash": self._hash_text(message.raw_text)
                    }
                }
            )
            return None

        # Wait for any exponential backoff delay
        await llm_rate_limiter.wait_for_backoff()

        # Log analysis attempt start
        self.logger.info(
            "Context analysis attempt started",
            extra_fields={
                "context_analysis": {
                    "message_hash": self._hash_text(message.raw_text),
                    "parent_message_hash": self._hash_text(parent_message.raw_text),
                    "open_positions_count": len(positions),
                    "correlation_id": correlation_id,
                    "model": openai_client.model,
                    **llm_rate_limiter.get_metrics()
                }
            }
        )

        try:
            # Prepare the context prompt
            prompt = self._prepare_context_prompt(message, parent_message, positions)

            # Make API call to OpenAI
            response = await self._make_openai_request(prompt, correlation_id)

            if response:
                # Record successful API call
                llm_rate_limiter.record_success()

                # Parse the LLM response
                result = self._parse_llm_response(response, correlation_id, start_time)

                if result and result.confidence >= 0.5:  # Store even medium confidence results in cache
                    # Store in cache for future requests
                    await self._cache_response(cache_key, result, response)

                    # Calculate API latency
                    latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    result.analysis_latency_ms = latency_ms

                    self.logger.info(
                        "Context analysis completed successfully",
                        extra_fields={
                            "context_analysis": {
                                "action": result.action,
                                "target_position": result.target_position,
                                "confidence": result.confidence,
                                "api_latency_ms": latency_ms,
                                "tokens_used": response.get("usage", {}).get("total_tokens", 0),
                                "cache_hit": False,
                                "correlation_id": correlation_id,
                                "message_hash": self._hash_text(message.raw_text)
                            }
                        }
                    )
                    return result
                else:
                    self.logger.info(
                        "Context analysis yielded low confidence or no actionable result",
                        extra_fields={
                            "context_analysis": {
                                "confidence": result.confidence if result else 0.0,
                                "action": result.action if result else "unknown",
                                "correlation_id": correlation_id,
                                "api_latency_ms": int((datetime.now() - start_time).total_seconds() * 1000)
                            }
                        }
                    )

        except Exception as e:
            # Record API failure for backoff calculation
            llm_rate_limiter.record_failure()

            self.logger.error(
                f"Context analysis failed: {e}",
                extra_fields={
                    "context_analysis": {
                        "correlation_id": correlation_id,
                        "message_hash": self._hash_text(message.raw_text),
                        "error": str(e),
                        "api_latency_ms": int((datetime.now() - start_time).total_seconds() * 1000),
                        **llm_rate_limiter.get_metrics()
                    }
                }
            )

        return None

    def _generate_cache_key(self, message: TelegramMessage, parent_message: TelegramMessage, positions: list[Position]) -> str:
        """
        Generate cache key from normalized message content and context hash.
        
        Args:
            message: Current message
            parent_message: Parent message context
            positions: Open positions list
            
        Returns:
            Unique cache key string
        """
        # Normalize message text (lowercase, remove extra whitespace)
        normalized_message = ' '.join(message.raw_text.lower().split())
        normalized_parent = ' '.join(parent_message.raw_text.lower().split())

        # Create context hash from positions
        positions_context = f"{len(positions)}_" + "_".join([
            f"{p.mt5_ticket}_{p.signal.symbol}_{p.status.value}"
            for p in positions[:5]  # Limit to first 5 positions for consistency
        ])

        # Combine all context elements
        cache_content = f"{normalized_message}|{normalized_parent}|{positions_context}"

        # Generate hash
        return hashlib.sha256(cache_content.encode('utf-8')).hexdigest()

    def _prepare_context_prompt(self, message: TelegramMessage, parent_message: TelegramMessage, positions: list[Position]) -> str:
        """
        Prepare the context analysis prompt for GPT-5-mini.
        
        Args:
            message: Current update message
            parent_message: Parent message for context
            positions: Open positions list
            
        Returns:
            Complete prompt string for the LLM
        """
        # Format positions list for context
        positions_context = []
        for pos in positions[:10]:  # Limit to 10 positions to keep prompt manageable
            pos_info = {
                "ticket": pos.mt5_ticket,
                "symbol": pos.signal.symbol,
                "action": pos.signal.parsed_action.value,
                "entry_price": float(pos.open_price) if pos.open_price else None,
                "current_sl": float(pos.current_sl) if pos.current_sl else None,
                "current_tp": float(pos.current_tp) if pos.current_tp else None,
                "status": pos.status.value,
                "profit": float(pos.profit)
            }
            positions_context.append(pos_info)

        # Format context data
        context_data = {
            "current_message": {
                "text": message.raw_text,
                "timestamp": message.timestamp.isoformat(),
                "sender": message.sender
            },
            "parent_message": {
                "text": parent_message.raw_text,
                "timestamp": parent_message.timestamp.isoformat(),
                "sender": parent_message.sender
            },
            "open_positions": positions_context
        }

        # Combine template with context
        return f"{self._prompt_template}\n\nCONTEXT DATA:\n{json.dumps(context_data, indent=2, ensure_ascii=False)}"

    @circuit_breaker(failure_threshold=5, recovery_timeout=60, expected_exception=Exception)
    async def _make_openai_request(self, prompt: str, correlation_id: str) -> dict | None:
        """
        Make the actual request to OpenAI API with error handling and circuit breaker.
        
        Args:
            prompt: Complete prompt to send to the API
            correlation_id: Correlation ID for logging
            
        Returns:
            API response dictionary or None if failed
        """
        try:
            # Get model configuration
            model_config = openai_client.get_model_config()

            # Extract context data from prompt
            context_start = prompt.find("CONTEXT DATA:")
            system_prompt = prompt[:context_start].strip()
            context_data = prompt[context_start:].strip()

            # Make chat completion request with JSON mode for structured output
            response = await openai_client.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": context_data
                    }
                ],
                response_format={"type": "json_object"},  # Enforce JSON mode
                **model_config
            )

            # Validate API response structure
            if self._validate_api_response(response):
                return {
                    "content": response.choices[0].message.content,
                    "usage": response.usage.model_dump() if response.usage else {}
                }

        except Exception as e:
            self.logger.error(f"OpenAI API request failed for context analysis: {e}")
            raise

        return None

    def _validate_api_response(self, response) -> bool:
        """
        Validate that API response has expected structure.
        
        Args:
            response: OpenAI API response object
            
        Returns:
            True if response is valid, False otherwise
        """
        try:
            return (
                hasattr(response, 'choices') and
                len(response.choices) > 0 and
                hasattr(response.choices[0], 'message') and
                hasattr(response.choices[0].message, 'content') and
                response.choices[0].message.content is not None
            )
        except Exception:
            return False

    def _parse_llm_response(self, response: dict, correlation_id: str, start_time: datetime) -> ContextAnalysisResult | None:
        """
        Parse the JSON response from GPT-5-mini into ContextAnalysisResult object.
        
        Args:
            response: API response dictionary
            correlation_id: Correlation ID for this analysis
            start_time: Analysis start time for latency calculation
            
        Returns:
            ContextAnalysisResult object or None if parsing failed
        """
        try:
            content = response.get("content", "").strip()

            # Handle null or empty response
            if not content or content.lower() == "null":
                return None

            # Try to parse JSON response
            try:
                analysis_data = orjson.loads(content)
            except orjson.JSONDecodeError:
                # Fallback to standard json for better error messages
                analysis_data = json.loads(content)

            # Validate required fields according to schema
            required_fields = ["action", "confidence"]
            if not all(field in analysis_data for field in required_fields):
                self.logger.warning(f"LLM context analysis response missing required fields: {analysis_data}")
                return None

            # Validate action value
            valid_actions = ["breakeven", "close", "modify", "unknown"]
            action = analysis_data["action"].lower()
            if action not in valid_actions:
                self.logger.warning(f"Invalid action in context analysis response: {action}")
                return None

            # Parse confidence
            confidence = float(analysis_data["confidence"])
            if confidence < 0.0 or confidence > 1.0:
                self.logger.warning(f"Invalid confidence score in context analysis: {confidence}")
                return None

            # Parse optional fields
            target_position = analysis_data.get("target_position")
            parameters = analysis_data.get("parameters", {})
            reasoning = analysis_data.get("reasoning", "")

            # Calculate latency
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Create result object
            result = ContextAnalysisResult(
                action=action,
                target_position=target_position,
                parameters=parameters,
                confidence=confidence,
                reasoning=reasoning,
                correlation_id=correlation_id,
                analysis_latency_ms=latency_ms
            )

            return result

        except Exception as e:
            self.logger.error(
                f"Error parsing context analysis response: {e}",
                extra_fields={
                    "context_analysis": {
                        "response_content": response.get("content", "")[:200],  # First 200 chars
                        "error": str(e),
                        "correlation_id": correlation_id
                    }
                }
            )

        return None

    def _reconstruct_result_from_cache(self, cached_data: dict, correlation_id: str, start_time: datetime) -> ContextAnalysisResult | None:
        """
        Reconstruct ContextAnalysisResult from cached data.
        
        Args:
            cached_data: Cached response data
            correlation_id: Current correlation ID
            start_time: Start time for latency calculation
            
        Returns:
            ContextAnalysisResult object or None if reconstruction failed
        """
        try:
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            return ContextAnalysisResult(
                action=cached_data["action"],
                target_position=cached_data.get("target_position"),
                parameters=cached_data.get("parameters", {}),
                confidence=float(cached_data["confidence"]),
                reasoning=cached_data.get("reasoning", ""),
                correlation_id=correlation_id,
                analysis_latency_ms=latency_ms
            )
        except Exception as e:
            self.logger.error(f"Failed to reconstruct context analysis from cache: {e}")
            return None

    async def _cache_response(self, cache_key: str, result: ContextAnalysisResult, api_response: dict) -> None:
        """
        Cache the successful context analysis response.
        
        Args:
            cache_key: Cache key for this analysis
            result: Analysis result object
            api_response: Raw API response data
        """
        try:
            cache_data = {
                "action": result.action,
                "target_position": result.target_position,
                "parameters": result.parameters,
                "confidence": result.confidence,
                "reasoning": result.reasoning,
                "cached_at": datetime.now().isoformat(),
                "api_usage": api_response.get("usage", {})
            }

            await llm_cache.set(cache_key, cache_data, expiry_hours=24)

        except Exception as e:
            self.logger.warning(f"Failed to cache context analysis response: {e}")

    def _hash_text(self, text: str) -> str:
        """Hash text for logging without exposing content."""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
