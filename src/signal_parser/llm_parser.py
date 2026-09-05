"""LLM-based signal parser for contextual French trading message understanding."""

import asyncio
import hashlib
import json
import orjson
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from config.openai_config import openai_client
from config.logging_config import (
    get_contextual_logger,
    set_correlation_id,
    set_service_context,
)
from src.utils.circuit_breaker import circuit_breaker
from src.utils.rate_limiter import llm_rate_limiter
from src.database.cache import llm_cache

from . import ParsedAction, ParsedSignal, ValidationResult


class LLMParser:
    """GPT-5-mini based parser for complex French trading signals."""

    def __init__(self) -> None:
        """Initialize LLM parser with prompt template and configuration."""
        self.logger = get_contextual_logger(__name__)
        self._prompt_template = self._load_prompt_template()
        
    def _load_prompt_template(self) -> str:
        """Load prompt template from config file."""
        try:
            prompt_path = Path(__file__).parent.parent.parent / "config" / "prompts" / "signal_parser.txt"
            return prompt_path.read_text(encoding='utf-8')
        except Exception as e:
            self.logger.error(f"Failed to load prompt template: {e}")
            raise

    async def parse_with_llm(self, text: str, context: str = "") -> Optional[ParsedSignal]:
        """
        Parse trading signal using GPT-5-mini with contextual understanding.
        
        Args:
            text: Raw message text to parse
            context: Additional context for parsing (unused in current implementation)
            
        Returns:
            ParsedSignal object if successful, None if no actionable signal found
        """
        if not text or not text.strip():
            return None

        # Set service context for logging
        set_service_context("LLMParser", "parse_with_llm")
        correlation_id = set_correlation_id()

        # Check cache first
        cached_response = await llm_cache.get(text)
        if cached_response:
            # Reconstruct ParsedSignal from cached data
            try:
                signal = self._reconstruct_signal_from_cache(cached_response, text, correlation_id)
                if signal:
                    self.logger.info(
                        "LLM parsing completed from cache",
                        extra_fields={
                            "llm_data": {
                                "action": signal.parsed_action.value,
                                "symbol": signal.symbol,
                                "entry": str(signal.entry_price) if signal.entry_price else None,
                                "confidence": signal.confidence_score,
                                "parser": "LLM",
                                "cache_hit": True,
                                "raw_text_hash": self._hash_text(text)
                            }
                        }
                    )
                    return signal
            except Exception as e:
                self.logger.warning(f"Failed to reconstruct signal from cache: {e}")
                # Continue with API call if cache reconstruction fails

        # Acquire rate limit permission
        if not await llm_rate_limiter.acquire():
            self.logger.warning(
                "LLM rate limit exceeded, request rejected",
                extra_fields={
                    "llm_data": {
                        **llm_rate_limiter.get_metrics(),
                        "raw_text_hash": self._hash_text(text)
                    }
                }
            )
            return None

        # Wait for any exponential backoff delay
        await llm_rate_limiter.wait_for_backoff()

        # Log parse attempt start
        start_time = datetime.now()
        self.logger.info(
            "LLM parse attempt started",
            extra_fields={
                "llm_data": {
                    "raw_text_hash": self._hash_text(text),
                    "text_length": len(text),
                    "parser": "LLM",
                    "model": openai_client.model,
                    **llm_rate_limiter.get_metrics()
                }
            }
        )

        try:
            # Prepare the prompt with the message text
            prompt = self._prepare_prompt(text, context)
            
            # Make API call to OpenAI
            response = await self._make_openai_request(prompt)
            
            if response:
                # Record successful API call
                llm_rate_limiter.record_success()
                
                # Parse the LLM response
                signal = self._parse_llm_response(response, text, correlation_id)
                
                if signal:
                    # Store in cache for future requests
                    await self._cache_response(text, signal, response)
                    
                    # Calculate API latency
                    latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    
                    self.logger.info(
                        "LLM parsing completed successfully",
                        extra_fields={
                            "llm_data": {
                                "action": signal.parsed_action.value,
                                "symbol": signal.symbol,
                                "entry": str(signal.entry_price) if signal.entry_price else None,
                                "confidence": signal.confidence_score,
                                "parser": "LLM",
                                "api_latency_ms": latency_ms,
                                "tokens_used": response.get("usage", {}).get("total_tokens", 0),
                                "cache_hit": False,
                                "raw_text_hash": self._hash_text(text)
                            }
                        }
                    )
                    return signal
                else:
                    self.logger.info(
                        "LLM determined no actionable signal in message",
                        extra_fields={
                            "llm_data": {
                                "parser": "LLM", 
                                "raw_text_hash": self._hash_text(text),
                                "api_latency_ms": int((datetime.now() - start_time).total_seconds() * 1000)
                            }
                        }
                    )
            
        except Exception as e:
            # Record API failure for backoff calculation
            llm_rate_limiter.record_failure()
            
            self.logger.error(
                f"LLM parsing failed: {e}",
                extra_fields={
                    "llm_data": {
                        "parser": "LLM",
                        "raw_text_hash": self._hash_text(text),
                        "error": str(e),
                        "api_latency_ms": int((datetime.now() - start_time).total_seconds() * 1000),
                        **llm_rate_limiter.get_metrics()
                    }
                }
            )
            
        return None

    def _prepare_prompt(self, text: str, context: str) -> str:
        """
        Prepare the prompt for GPT-5 by combining template with message text.
        
        Args:
            text: Message text to parse
            context: Additional context (currently unused)
            
        Returns:
            Complete prompt string for the LLM
        """
        # For now, append the user message to parse after the system prompt
        return f"{self._prompt_template}\n\nMessage à analyser:\n{text}"

    @circuit_breaker(failure_threshold=5, recovery_timeout=60, expected_exception=Exception)
    async def _make_openai_request(self, prompt: str) -> Optional[dict]:
        """
        Make the actual request to OpenAI API with error handling and circuit breaker.
        
        Args:
            prompt: Complete prompt to send to the API
            
        Returns:
            API response dictionary or None if failed
        """
        try:
            # Get model configuration
            model_config = openai_client.get_model_config()
            
            # Make chat completion request
            response = await openai_client.client.chat.completions.create(
                messages=[
                    {
                        "role": "system", 
                        "content": self._prompt_template
                    },
                    {
                        "role": "user",
                        "content": f"Message à analyser:\n{prompt.split('Message à analyser:')[-1].strip()}"
                    }
                ],
                **model_config
            )
            
            # Validate API response structure
            if self._validate_api_response(response):
                return {
                    "content": response.choices[0].message.content,
                    "usage": response.usage.model_dump() if response.usage else {}
                }
            
        except Exception as e:
            self.logger.error(f"OpenAI API request failed: {e}")
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

    def _parse_llm_response(self, response: dict, original_text: str, correlation_id: str) -> Optional[ParsedSignal]:
        """
        Parse the JSON response from GPT-5 into ParsedSignal object.
        
        Args:
            response: API response dictionary
            original_text: Original message text
            correlation_id: Correlation ID for logging
            
        Returns:
            ParsedSignal object or None if parsing failed
        """
        try:
            content = response.get("content", "").strip()
            
            # Handle null response (no actionable signal)
            if content.lower() == "null" or not content:
                return None
                
            # Try to parse JSON response
            try:
                signal_data = orjson.loads(content)
            except orjson.JSONDecodeError:
                # Fallback to standard json for better error messages
                signal_data = json.loads(content)
            
            # Validate required fields
            required_fields = ["parsed_action", "symbol", "confidence_score", "parser_type"]
            if not all(field in signal_data for field in required_fields):
                self.logger.warning(f"LLM response missing required fields: {signal_data}")
                return None
            
            # Parse action enum
            try:
                parsed_action = ParsedAction(signal_data["parsed_action"].upper())
            except (ValueError, KeyError):
                self.logger.warning(f"Invalid action in LLM response: {signal_data.get('parsed_action')}")
                return None
            
            # Parse decimal values safely
            entry_price = self._parse_decimal_field(signal_data.get("entry_price"))
            stop_loss = self._parse_decimal_field(signal_data.get("stop_loss"))
            take_profit = self._parse_decimal_field(signal_data.get("take_profit"))
            
            # Handle special case for break even
            if isinstance(signal_data.get("stop_loss"), str) and signal_data["stop_loss"].lower() == "break_even":
                stop_loss = "break_even"  # This will be handled by the risk manager
            
            # Create ParsedSignal object
            signal = ParsedSignal(
                telegram_message_id=0,  # Will be set by caller
                telegram_chat_id=0,     # Will be set by caller  
                sender="",              # Will be set by caller
                timestamp=datetime.now(),
                raw_text=original_text,
                parsed_action=parsed_action,
                symbol=signal_data["symbol"],
                entry_price=entry_price or Decimal("0.0"),
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence_score=float(signal_data["confidence_score"]),
                parser_type="LLM",
                status="PENDING"
            )
            
            # Validate the signal before returning
            if entry_price is not None or parsed_action in [ParsedAction.CLOSE, ParsedAction.MODIFY]:
                validation = self._validate_signal(signal)
                if validation.is_valid:
                    return signal
                else:
                    self.logger.warning(
                        "LLM-parsed signal validation failed",
                        extra_fields={
                            "llm_data": {
                                "validation_errors": validation.errors,
                                "parser": "LLM",
                                "raw_text_hash": self._hash_text(original_text)
                            }
                        }
                    )
            
        except Exception as e:
            self.logger.error(
                f"Error parsing LLM response: {e}",
                extra_fields={
                    "llm_data": {
                        "response_content": response.get("content", "")[:200],  # First 200 chars
                        "error": str(e),
                        "raw_text_hash": self._hash_text(original_text)
                    }
                }
            )
            
        return None

    def _parse_decimal_field(self, value) -> Optional[Decimal]:
        """
        Safely parse decimal field from LLM response.
        
        Args:
            value: Value to parse as Decimal
            
        Returns:
            Decimal value or None if invalid
        """
        if value is None:
            return None
        
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    def _validate_signal(self, signal: ParsedSignal) -> ValidationResult:
        """Validate parsed signal according to GOLD trading specs."""
        errors = []
        warnings = []

        # Validate GOLD price range (3000-4000 as per specs)
        if (signal.symbol in ['GOLD', 'XAUUSD'] and signal.entry_price and
            (signal.entry_price < Decimal('3000.0') or signal.entry_price > Decimal('4000.0'))):
            errors.append(f"GOLD price {signal.entry_price} outside valid range (3000-4000)")

        # Basic logical validations for non-zero entry prices
        if signal.entry_price and signal.entry_price > Decimal('0.0'):
            # Validate SL logic
            if signal.stop_loss and isinstance(signal.stop_loss, Decimal):
                if signal.parsed_action == ParsedAction.BUY:
                    if signal.stop_loss >= signal.entry_price:
                        errors.append("SL for BUY order must be below entry price")
                elif signal.parsed_action == ParsedAction.SELL:
                    if signal.stop_loss <= signal.entry_price:
                        errors.append("SL for SELL order must be above entry price")

            # Validate TP logic 
            if signal.take_profit and isinstance(signal.take_profit, Decimal):
                if signal.parsed_action == ParsedAction.BUY:
                    if signal.take_profit <= signal.entry_price:
                        errors.append("TP for BUY order must be above entry price")
                elif signal.parsed_action == ParsedAction.SELL:
                    if signal.take_profit >= signal.entry_price:
                        errors.append("TP for SELL order must be below entry price")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )


    def _reconstruct_signal_from_cache(self, cached_data: dict, original_text: str, correlation_id: str) -> Optional[ParsedSignal]:
        """
        Reconstruct ParsedSignal from cached data.
        
        Args:
            cached_data: Cached response data
            original_text: Original message text
            correlation_id: Current correlation ID
            
        Returns:
            ParsedSignal object or None if reconstruction failed
        """
        try:
            return ParsedSignal(
                telegram_message_id=0,
                telegram_chat_id=0,
                sender="",
                timestamp=datetime.now(),
                raw_text=original_text,
                parsed_action=ParsedAction(cached_data["parsed_action"]),
                symbol=cached_data["symbol"],
                entry_price=Decimal(str(cached_data["entry_price"])) if cached_data["entry_price"] else Decimal("0.0"),
                stop_loss=self._parse_decimal_field(cached_data.get("stop_loss")),
                take_profit=self._parse_decimal_field(cached_data.get("take_profit")),
                confidence_score=float(cached_data["confidence_score"]),
                parser_type="LLM",
                status="PENDING"
            )
        except Exception as e:
            self.logger.error(f"Failed to reconstruct signal from cache: {e}")
            return None

    async def _cache_response(self, original_text: str, signal: ParsedSignal, api_response: dict) -> None:
        """
        Cache the successful parsing response.
        
        Args:
            original_text: Original message text
            signal: Parsed signal object
            api_response: Raw API response data
        """
        try:
            cache_data = {
                "parsed_action": signal.parsed_action.value,
                "symbol": signal.symbol,
                "entry_price": float(signal.entry_price) if signal.entry_price else None,
                "stop_loss": float(signal.stop_loss) if isinstance(signal.stop_loss, Decimal) else signal.stop_loss,
                "take_profit": float(signal.take_profit) if isinstance(signal.take_profit, Decimal) else signal.take_profit,
                "confidence_score": signal.confidence_score,
                "parser_type": signal.parser_type,
                "cached_at": datetime.now().isoformat(),
                "api_usage": api_response.get("usage", {})
            }
            
            await llm_cache.set(original_text, cache_data)
            
        except Exception as e:
            self.logger.warning(f"Failed to cache response: {e}")

    def _hash_text(self, text: str) -> str:
        """Hash text for logging without exposing content."""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]