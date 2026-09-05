"""
Unit tests for LLM parser functionality.
Tests OpenAI integration, rate limiting, caching, and signal parsing.
"""

import pytest
import pytest_asyncio
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from decimal import Decimal
from datetime import datetime

from src.signal_parser.llm_parser import LLMParser
from src.signal_parser import ParsedSignal, ParsedAction
from src.utils.rate_limiter import RateLimitConfig, APIRateLimiter
from src.database.cache import LLMResponseCache


class TestLLMParser:
    """Test cases for LLMParser class."""

    @pytest.fixture
    def llm_parser(self):
        """Create LLMParser instance for testing."""
        return LLMParser()

    @pytest.fixture
    def mock_openai_response(self):
        """Mock OpenAI API response."""
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

    def test_initialization(self, llm_parser):
        """Test LLMParser initialization."""
        assert llm_parser is not None
        assert hasattr(llm_parser, '_prompt_template')
        assert len(llm_parser._prompt_template) > 0
        assert 'trading' in llm_parser._prompt_template.lower()

    def test_prompt_template_loading(self, llm_parser):
        """Test prompt template is loaded correctly."""
        template = llm_parser._prompt_template
        
        # Check for key components
        assert 'BUY' in template or 'ACHAT' in template
        assert 'SELL' in template or 'VENTE' in template
        assert 'GOLD' in template or 'OR' in template
        assert 'JSON' in template
        assert 'confidence_score' in template

    def test_prepare_prompt(self, llm_parser):
        """Test prompt preparation with message text."""
        test_message = "BUY GOLD maintenant, SL à 3350, TP 3375"
        prompt = llm_parser._prepare_prompt(test_message, "")
        
        assert test_message in prompt
        assert llm_parser._prompt_template in prompt

    @pytest.mark.asyncio
    async def test_parse_with_llm_success(self, llm_parser, mock_openai_response):
        """Test successful LLM parsing."""
        test_text = "BUY GOLD maintenant, SL à 3350, TP 3375"
        
        with patch('src.signal_parser.llm_parser.llm_rate_limiter') as mock_limiter, \
             patch('src.signal_parser.llm_parser.llm_cache') as mock_cache, \
             patch.object(llm_parser, '_make_openai_request', new_callable=AsyncMock) as mock_request:
            
            # Setup mocks
            mock_limiter.acquire = AsyncMock(return_value=True)
            mock_limiter.wait_for_backoff = AsyncMock()
            mock_limiter.record_success = Mock()
            mock_limiter.get_metrics.return_value = {"requests_this_minute": 1}
            
            mock_cache.get = AsyncMock(return_value=None)  # Cache miss
            mock_cache.set = AsyncMock()
            
            mock_request.return_value = {
                "content": mock_openai_response.choices[0].message.content,
                "usage": {"total_tokens": 45}
            }
            
            # Execute
            result = await llm_parser.parse_with_llm(test_text)
            
            # Verify
            assert result is not None
            assert isinstance(result, ParsedSignal)
            assert result.parsed_action == ParsedAction.BUY
            assert result.symbol == "GOLD"
            assert result.entry_price == Decimal("3362.50")
            assert result.stop_loss == Decimal("3350.00")
            assert result.take_profit == Decimal("3375.00")
            assert result.confidence_score == 0.80
            assert result.parser_type == "LLM"
            
            # Verify interactions
            mock_limiter.acquire.assert_called_once()
            mock_request.assert_called_once()
            mock_cache.set.assert_called_once()
            mock_limiter.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_parse_with_llm_cache_hit(self, llm_parser):
        """Test LLM parsing with cache hit."""
        test_text = "BUY GOLD maintenant, SL à 3350, TP 3375"
        cached_data = {
            "parsed_action": "BUY",
            "symbol": "GOLD", 
            "entry_price": 3362.50,
            "stop_loss": 3350.00,
            "take_profit": 3375.00,
            "confidence_score": 0.80,
            "parser_type": "LLM"
        }
        
        with patch('src.signal_parser.llm_parser.llm_cache') as mock_cache:
            mock_cache.get = AsyncMock(return_value=cached_data)
            
            result = await llm_parser.parse_with_llm(test_text)
            
            assert result is not None
            assert result.parsed_action == ParsedAction.BUY
            assert result.symbol == "GOLD"
            mock_cache.get.assert_called_once_with(test_text)

    @pytest.mark.asyncio 
    async def test_parse_with_llm_rate_limited(self, llm_parser):
        """Test LLM parsing when rate limited."""
        test_text = "BUY GOLD maintenant"
        
        with patch('src.signal_parser.llm_parser.llm_rate_limiter') as mock_limiter, \
             patch('src.signal_parser.llm_parser.llm_cache') as mock_cache:
            
            mock_limiter.acquire = AsyncMock(return_value=False)
            mock_limiter.get_metrics.return_value = {"requests_this_minute": 100}
            mock_cache.get = AsyncMock(return_value=None)
            
            result = await llm_parser.parse_with_llm(test_text)
            
            assert result is None
            mock_limiter.acquire.assert_called_once()

    @pytest.mark.asyncio
    async def test_parse_with_llm_api_failure(self, llm_parser):
        """Test LLM parsing with API failure."""
        test_text = "BUY GOLD maintenant"
        
        with patch('src.signal_parser.llm_parser.llm_rate_limiter') as mock_limiter, \
             patch('src.signal_parser.llm_parser.llm_cache') as mock_cache, \
             patch.object(llm_parser, '_make_openai_request', new_callable=AsyncMock) as mock_request:
            
            mock_limiter.acquire = AsyncMock(return_value=True)
            mock_limiter.wait_for_backoff = AsyncMock()
            mock_limiter.record_failure = Mock()
            mock_limiter.get_metrics.return_value = {"requests_this_minute": 1}
            
            mock_cache.get = AsyncMock(return_value=None)
            
            mock_request.side_effect = Exception("API Error")
            
            result = await llm_parser.parse_with_llm(test_text)
            
            assert result is None
            mock_limiter.record_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_make_openai_request_success(self, llm_parser, mock_openai_response):
        """Test successful OpenAI API request."""
        with patch('config.openai_config.openai_client') as mock_client:
            mock_client.client.chat.completions.create = AsyncMock(return_value=mock_openai_response)
            mock_client.get_model_config.return_value = {
                "model": "gpt-5-mini",
                "max_tokens": 1000,
                "temperature": 0.1
            }
            
            result = await llm_parser._make_openai_request("test prompt")
            
            assert result is not None
            assert "content" in result
            assert "usage" in result
            mock_client.client.chat.completions.create.assert_called_once()

    def test_validate_api_response_valid(self, llm_parser, mock_openai_response):
        """Test API response validation with valid response."""
        is_valid = llm_parser._validate_api_response(mock_openai_response)
        assert is_valid is True

    def test_validate_api_response_invalid(self, llm_parser):
        """Test API response validation with invalid response."""
        invalid_response = Mock()
        invalid_response.choices = []
        
        is_valid = llm_parser._validate_api_response(invalid_response)
        assert is_valid is False

    def test_parse_llm_response_success(self, llm_parser):
        """Test parsing valid LLM JSON response."""
        response_data = {
            "content": json.dumps({
                "parsed_action": "BUY",
                "symbol": "GOLD",
                "entry_price": 3362.50,
                "stop_loss": 3350.00,
                "take_profit": 3375.00,
                "confidence_score": 0.80,
                "parser_type": "LLM"
            }),
            "usage": {"total_tokens": 45}
        }
        
        original_text = "BUY GOLD maintenant"
        result = llm_parser._parse_llm_response(response_data, original_text, "test-correlation-id")
        
        assert result is not None
        assert result.parsed_action == ParsedAction.BUY
        assert result.symbol == "GOLD"
        assert result.entry_price == Decimal("3362.50")

    def test_parse_llm_response_null(self, llm_parser):
        """Test parsing LLM response that returns null."""
        response_data = {"content": "null"}
        
        result = llm_parser._parse_llm_response(response_data, "test text", "test-id")
        
        assert result is None

    def test_parse_llm_response_invalid_json(self, llm_parser):
        """Test parsing invalid JSON from LLM."""
        response_data = {"content": "invalid json"}
        
        result = llm_parser._parse_llm_response(response_data, "test text", "test-id")
        
        assert result is None

    def test_parse_llm_response_missing_fields(self, llm_parser):
        """Test parsing LLM response with missing required fields."""
        response_data = {
            "content": json.dumps({
                "parsed_action": "BUY",
                # Missing required fields
            })
        }
        
        result = llm_parser._parse_llm_response(response_data, "test text", "test-id")
        
        assert result is None

    def test_parse_llm_response_break_even(self, llm_parser):
        """Test parsing LLM response with break even stop loss."""
        response_data = {
            "content": json.dumps({
                "parsed_action": "MODIFY",
                "symbol": "GOLD",
                "entry_price": None,
                "stop_loss": "break_even",
                "take_profit": None,
                "confidence_score": 0.80,
                "parser_type": "LLM"
            })
        }
        
        result = llm_parser._parse_llm_response(response_data, "BREAK EVEN sur ma position", "test-id")
        
        assert result is not None
        assert result.parsed_action == ParsedAction.MODIFY
        assert result.stop_loss == "break_even"

    def test_parse_decimal_field_valid(self, llm_parser):
        """Test decimal field parsing with valid values."""
        assert llm_parser._parse_decimal_field(3362.50) == Decimal("3362.50")
        assert llm_parser._parse_decimal_field("3362.50") == Decimal("3362.50")
        assert llm_parser._parse_decimal_field(None) is None

    def test_parse_decimal_field_invalid(self, llm_parser):
        """Test decimal field parsing with invalid values."""
        assert llm_parser._parse_decimal_field("invalid") is None
        assert llm_parser._parse_decimal_field([]) is None

    def test_validate_signal_valid_buy(self, llm_parser):
        """Test signal validation for valid BUY signal."""
        signal = ParsedSignal(
            parsed_action=ParsedAction.BUY,
            symbol="GOLD",
            entry_price=Decimal("3362.50"),
            stop_loss=Decimal("3350.00"),
            take_profit=Decimal("3375.00"),
            confidence_score=0.80,
            parser_type="LLM"
        )
        
        validation = llm_parser._validate_signal(signal)
        
        assert validation.is_valid is True
        assert len(validation.errors) == 0

    def test_validate_signal_invalid_sl_buy(self, llm_parser):
        """Test signal validation for BUY with invalid stop loss."""
        signal = ParsedSignal(
            parsed_action=ParsedAction.BUY,
            symbol="GOLD", 
            entry_price=Decimal("3362.50"),
            stop_loss=Decimal("3370.00"),  # SL above entry for BUY
            confidence_score=0.80,
            parser_type="LLM"
        )
        
        validation = llm_parser._validate_signal(signal)
        
        assert validation.is_valid is False
        assert len(validation.errors) > 0
        assert any("SL for BUY order must be below entry price" in error for error in validation.errors)

    def test_validate_signal_price_range(self, llm_parser):
        """Test signal validation for price outside valid range."""
        signal = ParsedSignal(
            parsed_action=ParsedAction.BUY,
            symbol="GOLD",
            entry_price=Decimal("2500.00"),  # Below valid range
            confidence_score=0.80,
            parser_type="LLM"
        )
        
        validation = llm_parser._validate_signal(signal)
        
        assert validation.is_valid is False
        assert any("outside valid range" in error for error in validation.errors)

    def test_reconstruct_signal_from_cache_success(self, llm_parser):
        """Test successful signal reconstruction from cache."""
        cached_data = {
            "parsed_action": "BUY",
            "symbol": "GOLD",
            "entry_price": 3362.50,
            "stop_loss": 3350.00,
            "take_profit": 3375.00,
            "confidence_score": 0.80,
            "parser_type": "LLM"
        }
        
        result = llm_parser._reconstruct_signal_from_cache(cached_data, "test text", "test-id")
        
        assert result is not None
        assert result.parsed_action == ParsedAction.BUY
        assert result.symbol == "GOLD"
        assert result.entry_price == Decimal("3362.50")

    def test_reconstruct_signal_from_cache_failure(self, llm_parser):
        """Test signal reconstruction failure with invalid cached data."""
        invalid_cached_data = {
            "invalid_action": "INVALID",  # Wrong field name
        }
        
        result = llm_parser._reconstruct_signal_from_cache(invalid_cached_data, "test text", "test-id")
        
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_response_success(self, llm_parser):
        """Test successful response caching."""
        signal = ParsedSignal(
            parsed_action=ParsedAction.BUY,
            symbol="GOLD",
            entry_price=Decimal("3362.50"),
            stop_loss=Decimal("3350.00"),
            confidence_score=0.80,
            parser_type="LLM"
        )
        
        api_response = {"usage": {"total_tokens": 45}}
        
        with patch('src.signal_parser.llm_parser.llm_cache') as mock_cache:
            mock_cache.set = AsyncMock()
            
            await llm_parser._cache_response("test text", signal, api_response)
            
            mock_cache.set.assert_called_once()
            
            # Verify cached data structure
            call_args = mock_cache.set.call_args
            cached_data = call_args[0][1]  # Second argument (cache data)
            
            assert cached_data["parsed_action"] == "BUY"
            assert cached_data["symbol"] == "GOLD"
            assert cached_data["entry_price"] == 3362.50
            assert "cached_at" in cached_data
            assert "api_usage" in cached_data

    def test_hash_text(self, llm_parser):
        """Test text hashing for logging."""
        text = "BUY GOLD maintenant"
        hash1 = llm_parser._hash_text(text)
        hash2 = llm_parser._hash_text(text)
        
        assert hash1 == hash2  # Same input produces same hash
        assert len(hash1) == 16  # Hash is truncated to 16 chars
        assert hash1 != text  # Hash is different from original text


class TestRateLimiter:
    """Test cases for APIRateLimiter."""

    @pytest.fixture
    def rate_limiter(self):
        """Create rate limiter for testing."""
        config = RateLimitConfig(
            requests_per_minute=60,  # 1 per second for faster testing
            burst_limit=5,
            queue_max_size=10
        )
        return APIRateLimiter(config)

    @pytest.mark.asyncio
    async def test_acquire_immediate_success(self, rate_limiter):
        """Test immediate request approval within limits."""
        result = await rate_limiter.acquire()
        assert result is True
        
        metrics = rate_limiter.get_metrics()
        assert metrics["requests_this_minute"] == 1

    @pytest.mark.asyncio
    async def test_acquire_burst_limit(self, rate_limiter):
        """Test burst limit handling."""
        # Make burst limit requests
        for _ in range(5):
            result = await rate_limiter.acquire()
            assert result is True
        
        # Next request should be queued
        result = await rate_limiter.acquire()
        assert result is True
        
        metrics = rate_limiter.get_metrics()
        assert metrics["queue_size"] >= 0

    def test_backoff_calculation(self, rate_limiter):
        """Test exponential backoff calculation."""
        # No failures initially
        assert rate_limiter.calculate_backoff_delay() == 0.0
        
        # Record some failures
        rate_limiter.record_failure()
        assert rate_limiter.calculate_backoff_delay() == 1.0
        
        rate_limiter.record_failure() 
        assert rate_limiter.calculate_backoff_delay() == 2.0
        
        rate_limiter.record_failure()
        assert rate_limiter.calculate_backoff_delay() == 4.0

    def test_success_resets_backoff(self, rate_limiter):
        """Test that success resets backoff counter."""
        rate_limiter.record_failure()
        rate_limiter.record_failure()
        assert rate_limiter.calculate_backoff_delay() == 2.0
        
        rate_limiter.record_success()
        assert rate_limiter.calculate_backoff_delay() == 0.0


class TestLLMResponseCache:
    """Test cases for LLMResponseCache."""

    @pytest_asyncio.fixture
    async def cache(self, tmp_path):
        """Create cache instance for testing."""
        cache_instance = LLMResponseCache(
            db_path=tmp_path / "test_cache.db",
            ttl_hours=1
        )
        await cache_instance.initialize()
        return cache_instance

    @pytest.mark.asyncio
    async def test_cache_set_and_get(self, cache):
        """Test basic cache set and get operations."""
        test_text = "BUY GOLD maintenant"
        test_data = {"parsed_action": "BUY", "symbol": "GOLD"}
        
        # Cache miss initially
        result = await cache.get(test_text)
        assert result is None
        
        # Set cache
        await cache.set(test_text, test_data)
        
        # Cache hit
        result = await cache.get(test_text)
        assert result == test_data

    @pytest.mark.asyncio
    async def test_cache_normalization(self, cache):
        """Test message text normalization for caching."""
        test_data = {"parsed_action": "BUY", "symbol": "GOLD"}
        
        # Set with one format
        await cache.set("  BUY   GOLD   maintenant  ", test_data)
        
        # Get with different whitespace should hit cache
        result = await cache.get("BUY GOLD maintenant")
        assert result == test_data
        
        # Case variations should also hit
        result = await cache.get("buy gold maintenant")
        assert result == test_data

    @pytest.mark.asyncio  
    async def test_cache_key_generation(self, cache):
        """Test cache key generation consistency."""
        text1 = "BUY GOLD maintenant"
        text2 = "  buy   gold   maintenant  "  # Different case/spacing
        
        key1 = cache._generate_cache_key(text1)
        key2 = cache._generate_cache_key(text2)
        
        assert key1 == key2  # Should generate same key
        assert len(key1) == 64  # SHA256 hex length

    @pytest.mark.asyncio
    async def test_cache_stats(self, cache):
        """Test cache statistics reporting."""
        # Add some test data
        await cache.set("test1", {"action": "BUY"})
        await cache.set("test2", {"action": "SELL"})
        
        stats = await cache.get_stats()
        
        assert "total_entries" in stats
        assert "valid_entries" in stats  
        assert "memory_cache_size" in stats
        assert stats["total_entries"] >= 2

    @pytest.mark.asyncio
    async def test_cache_cleanup(self, cache):
        """Test cache cleanup functionality."""
        await cache.cleanup()  # Should not raise errors