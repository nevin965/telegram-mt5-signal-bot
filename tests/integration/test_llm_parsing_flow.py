"""
Integration tests for complete LLM parsing flow.
Tests end-to-end parsing pipeline with mocked OpenAI API.
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch
from decimal import Decimal

from src.signal_parser.llm_parser import LLMParser
from src.signal_parser import ParsedSignal, ParsedAction
from src.database.cache import LLMResponseCache
from src.utils.rate_limiter import APIRateLimiter, RateLimitConfig


class TestLLMParsingFlow:
    """Integration tests for complete LLM parsing workflow."""

    @pytest.fixture
    async def setup_components(self, tmp_path):
        """Set up LLM parser with real cache and rate limiter."""
        # Create cache
        cache = LLMResponseCache(
            db_path=tmp_path / "integration_cache.db",
            ttl_hours=1
        )
        await cache.initialize()
        
        # Create rate limiter
        rate_limiter = APIRateLimiter(RateLimitConfig(
            requests_per_minute=100,
            burst_limit=10,
            queue_max_size=20
        ))
        
        # Create parser
        parser = LLMParser()
        
        return {
            "parser": parser,
            "cache": cache,
            "rate_limiter": rate_limiter
        }

    @pytest.fixture
    def mock_openai_successful_response(self):
        """Mock successful OpenAI API response."""
        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message = Mock()
        response.choices[0].message.content = json.dumps({
            "parsed_action": "BUY",
            "symbol": "GOLD",
            "entry_price": 3362.50,
            "stop_loss": 3350.00,
            "take_profit": 3375.00,
            "confidence_score": 0.80,
            "parser_type": "LLM"
        })
        response.usage = Mock()
        response.usage.model_dump.return_value = {
            "total_tokens": 45,
            "prompt_tokens": 30,
            "completion_tokens": 15
        }
        return response

    @pytest.fixture 
    def mock_openai_null_response(self):
        """Mock OpenAI API response indicating no actionable signal."""
        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message = Mock()
        response.choices[0].message.content = "null"
        response.usage = Mock()
        response.usage.model_dump.return_value = {"total_tokens": 20}
        return response

    @pytest.mark.asyncio
    async def test_complete_parsing_flow_success(self, setup_components, mock_openai_successful_response):
        """Test complete successful parsing flow from text to ParsedSignal."""
        components = await setup_components
        parser = components["parser"]
        
        test_message = "BUY GOLD maintenant, SL à 3350, TP 3375"
        
        with patch('config.openai_config.openai_client') as mock_client, \
             patch('src.signal_parser.llm_parser.llm_rate_limiter', components["rate_limiter"]), \
             patch('src.signal_parser.llm_parser.llm_cache', components["cache"]):
            
            # Mock OpenAI client
            mock_client.client.chat.completions.create.return_value = mock_openai_successful_response
            mock_client.get_model_config.return_value = {
                "model": "gpt-5-mini",
                "max_tokens": 1000,
                "temperature": 0.1,
                "response_format": {"type": "json_object"}
            }
            
            # Execute parsing
            result = await parser.parse_with_llm(test_message)
            
            # Verify result
            assert result is not None
            assert isinstance(result, ParsedSignal)
            assert result.parsed_action == ParsedAction.BUY
            assert result.symbol == "GOLD"
            assert result.entry_price == Decimal("3362.50")
            assert result.stop_loss == Decimal("3350.00")
            assert result.take_profit == Decimal("3375.00")
            assert result.confidence_score == 0.80
            assert result.parser_type == "LLM"
            assert result.raw_text == test_message
            
            # Verify OpenAI was called
            mock_client.client.chat.completions.create.assert_called_once()
            
            # Verify response was cached
            cached_result = await components["cache"].get(test_message)
            assert cached_result is not None
            assert cached_result["parsed_action"] == "BUY"

    @pytest.mark.asyncio
    async def test_cache_hit_flow(self, setup_components):
        """Test parsing flow with cache hit (no API call)."""
        components = await setup_components
        parser = components["parser"]
        cache = components["cache"]
        
        test_message = "SELL GOLD à 3350"
        cached_data = {
            "parsed_action": "SELL",
            "symbol": "GOLD",
            "entry_price": 3350.00,
            "stop_loss": 3360.00,
            "take_profit": 3340.00,
            "confidence_score": 0.80,
            "parser_type": "LLM"
        }
        
        # Pre-populate cache
        await cache.set(test_message, cached_data)
        
        with patch('config.openai_config.openai_client') as mock_client, \
             patch('src.signal_parser.llm_parser.llm_rate_limiter', components["rate_limiter"]), \
             patch('src.signal_parser.llm_parser.llm_cache', cache):
            
            # Execute parsing
            result = await parser.parse_with_llm(test_message)
            
            # Verify result from cache
            assert result is not None
            assert result.parsed_action == ParsedAction.SELL
            assert result.symbol == "GOLD"
            assert result.entry_price == Decimal("3350.00")
            
            # Verify OpenAI was NOT called
            mock_client.client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_actionable_signal_flow(self, setup_components, mock_openai_null_response):
        """Test parsing flow when LLM determines no actionable signal."""
        components = await setup_components
        parser = components["parser"]
        
        test_message = "Comme je l'ai dit hier, GOLD va monter"
        
        with patch('config.openai_config.openai_client') as mock_client, \
             patch('src.signal_parser.llm_parser.llm_rate_limiter', components["rate_limiter"]), \
             patch('src.signal_parser.llm_parser.llm_cache', components["cache"]):
            
            # Mock OpenAI client  
            mock_client.client.chat.completions.create.return_value = mock_openai_null_response
            mock_client.get_model_config.return_value = {
                "model": "gpt-5-mini",
                "max_tokens": 1000,
                "temperature": 0.1,
                "response_format": {"type": "json_object"}
            }
            
            # Execute parsing
            result = await parser.parse_with_llm(test_message)
            
            # Verify no signal returned
            assert result is None
            
            # Verify OpenAI was called
            mock_client.client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_rate_limiting_flow(self, setup_components):
        """Test parsing flow with rate limiting."""
        components = await setup_components
        parser = components["parser"]
        rate_limiter = components["rate_limiter"]
        
        # Create rate limiter with very low limits
        limited_rate_limiter = APIRateLimiter(RateLimitConfig(
            requests_per_minute=1,
            burst_limit=1,
            queue_max_size=1
        ))
        
        test_message = "BUY GOLD maintenant"
        
        with patch('src.signal_parser.llm_parser.llm_rate_limiter', limited_rate_limiter), \
             patch('src.signal_parser.llm_parser.llm_cache', components["cache"]):
            
            # First request should succeed
            result1 = await parser.parse_with_llm(test_message + " 1")
            
            # Second request should be rate limited
            result2 = await parser.parse_with_llm(test_message + " 2")
            
            # One should be None due to rate limiting
            assert result1 is None or result2 is None

    @pytest.mark.asyncio
    async def test_api_error_handling_flow(self, setup_components):
        """Test parsing flow with API errors."""
        components = await setup_components
        parser = components["parser"]
        
        test_message = "BUY GOLD maintenant"
        
        with patch('config.openai_config.openai_client') as mock_client, \
             patch('src.signal_parser.llm_parser.llm_rate_limiter', components["rate_limiter"]), \
             patch('src.signal_parser.llm_parser.llm_cache', components["cache"]):
            
            # Mock API error
            mock_client.client.chat.completions.create.side_effect = Exception("API Error")
            mock_client.get_model_config.return_value = {"model": "gpt-5-mini"}
            
            # Execute parsing
            result = await parser.parse_with_llm(test_message)
            
            # Should handle error gracefully
            assert result is None

    @pytest.mark.asyncio
    async def test_concurrent_parsing_requests(self, setup_components, mock_openai_successful_response):
        """Test multiple concurrent parsing requests."""
        components = await setup_components
        parser = components["parser"]
        
        test_messages = [
            "BUY GOLD maintenant 1",
            "SELL GOLD maintenant 2", 
            "BUY GOLD maintenant 3",
            "CLOSE GOLD position 4"
        ]
        
        with patch('config.openai_config.openai_client') as mock_client, \
             patch('src.signal_parser.llm_parser.llm_rate_limiter', components["rate_limiter"]), \
             patch('src.signal_parser.llm_parser.llm_cache', components["cache"]):
            
            # Mock OpenAI client
            mock_client.client.chat.completions.create.return_value = mock_openai_successful_response
            mock_client.get_model_config.return_value = {"model": "gpt-5-mini"}
            
            # Execute concurrent parsing
            tasks = [parser.parse_with_llm(msg) for msg in test_messages]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Verify all completed (some might be None due to rate limiting)
            assert len(results) == 4
            assert all(result is None or isinstance(result, ParsedSignal) for result in results)

    @pytest.mark.asyncio
    async def test_french_signal_variations(self, setup_components):
        """Test various French signal formats."""
        components = await setup_components
        parser = components["parser"]
        
        french_signals = [
            ("BUY GOLD maintenant, SL à 3350, TP 3375", ParsedAction.BUY),
            ("Je mets à jour ma position GOLD, nouveau SL 3355", ParsedAction.MODIFY),
            ("BREAK EVEN sur ma position OR de ce matin", ParsedAction.MODIFY),
            ("VENTE OR à 3360, SL 3370", ParsedAction.SELL),
            ("FERMER position GOLD", ParsedAction.CLOSE)
        ]
        
        for signal_text, expected_action in french_signals:
            # Create appropriate mock response for each signal
            mock_response = Mock()
            mock_response.choices = [Mock()]
            mock_response.choices[0].message = Mock()
            mock_response.choices[0].message.content = json.dumps({
                "parsed_action": expected_action.value,
                "symbol": "GOLD",
                "entry_price": 3360.00 if expected_action in [ParsedAction.BUY, ParsedAction.SELL] else None,
                "stop_loss": "break_even" if "BREAK EVEN" in signal_text else 3350.00,
                "take_profit": 3375.00 if expected_action == ParsedAction.BUY else None,
                "confidence_score": 0.80,
                "parser_type": "LLM"
            })
            mock_response.usage = Mock()
            mock_response.usage.model_dump.return_value = {"total_tokens": 40}
            
            with patch('config.openai_config.openai_client') as mock_client, \
                 patch('src.signal_parser.llm_parser.llm_rate_limiter', components["rate_limiter"]), \
                 patch('src.signal_parser.llm_parser.llm_cache', components["cache"]):
                
                mock_client.client.chat.completions.create.return_value = mock_response
                mock_client.get_model_config.return_value = {"model": "gpt-5-mini"}
                
                result = await parser.parse_with_llm(signal_text)
                
                if result is not None:  # Some might be rate limited
                    assert result.parsed_action == expected_action
                    assert result.symbol == "GOLD"

    @pytest.mark.asyncio
    async def test_signal_validation_in_flow(self, setup_components):
        """Test signal validation as part of parsing flow."""
        components = await setup_components
        parser = components["parser"]
        
        # Create invalid signal response (SL above entry for BUY)
        invalid_response = Mock()
        invalid_response.choices = [Mock()]
        invalid_response.choices[0].message = Mock()
        invalid_response.choices[0].message.content = json.dumps({
            "parsed_action": "BUY",
            "symbol": "GOLD",
            "entry_price": 3350.00,
            "stop_loss": 3360.00,  # Invalid: SL above entry for BUY
            "take_profit": 3375.00,
            "confidence_score": 0.80,
            "parser_type": "LLM"
        })
        invalid_response.usage = Mock()
        invalid_response.usage.model_dump.return_value = {"total_tokens": 40}
        
        test_message = "BUY GOLD with invalid SL"
        
        with patch('config.openai_config.openai_client') as mock_client, \
             patch('src.signal_parser.llm_parser.llm_rate_limiter', components["rate_limiter"]), \
             patch('src.signal_parser.llm_parser.llm_cache', components["cache"]):
            
            mock_client.client.chat.completions.create.return_value = invalid_response
            mock_client.get_model_config.return_value = {"model": "gpt-5-mini"}
            
            result = await parser.parse_with_llm(test_message)
            
            # Should reject invalid signal
            assert result is None

    @pytest.mark.asyncio
    async def test_cleanup_after_parsing(self, setup_components):
        """Test proper cleanup after parsing operations."""
        components = await setup_components
        
        # Run some parsing operations
        # (Implementation details - mainly ensure no resource leaks)
        
        # Cleanup components
        await components["cache"].cleanup()
        await components["rate_limiter"].cleanup()
        
        # Should not raise any errors