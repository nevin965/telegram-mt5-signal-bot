"""Unit tests for context analyzer component."""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import json

from src.signal_parser.context_analyzer import (
    ContextAnalyzer,
    ContextAnalysisResult,
    TelegramMessage
)
from src.database.models import Position, Signal, PositionStatus, ParsedAction


class TestContextAnalyzer:
    """Test suite for ContextAnalyzer class."""
    
    @pytest.fixture
    def context_analyzer(self):
        """Create ContextAnalyzer instance with mocked prompt template."""
        with patch.object(ContextAnalyzer, '_load_prompt_template') as mock_load:
            mock_load.return_value = "Test prompt template for context analysis"
            analyzer = ContextAnalyzer()
            return analyzer
    
    @pytest.fixture
    def sample_message(self):
        """Create sample TelegramMessage for testing."""
        return TelegramMessage(
            telegram_message_id=12345,
            telegram_chat_id=67890,
            sender="user_123",
            timestamp=datetime.now(),
            raw_text="BE sur la position",
            reply_to_message_id=11111
        )
    
    @pytest.fixture
    def sample_parent_message(self):
        """Create sample parent TelegramMessage."""
        return TelegramMessage(
            telegram_message_id=11111,
            telegram_chat_id=67890,
            sender="signal_provider",
            timestamp=datetime.now(),
            raw_text="BUY GOLD 3362.50, SL 3355, TP 3375"
        )
    
    @pytest.fixture
    def sample_position(self):
        """Create sample Position for testing."""
        signal = Signal(
            id=1,
            telegram_message_id=11111,
            telegram_chat_id=67890,
            sender="signal_provider",
            timestamp=datetime.now(),
            raw_text="BUY GOLD 3362.50, SL 3355, TP 3375",
            parsed_action=ParsedAction.BUY,
            symbol="GOLD",
            entry_price=3362.50,
            stop_loss=3355.00,
            take_profit=3375.00
        )
        
        position = Position(
            id=1,
            signal_id=1,
            mt5_ticket=123456789,
            open_time=datetime.now(),
            open_price=3362.50,
            volume=0.01,
            current_sl=3355.00,
            current_tp=3375.00,
            status=PositionStatus.OPEN,
            signal=signal
        )
        
        return position
    
    @pytest.mark.asyncio
    async def test_analyze_update_context_empty_message(self, context_analyzer, sample_parent_message, sample_position):
        """Test analysis with empty message returns None."""
        empty_message = TelegramMessage(
            telegram_message_id=12345,
            telegram_chat_id=67890,
            sender="user_123",
            timestamp=datetime.now(),
            raw_text=""
        )
        
        result = await context_analyzer.analyze_update_context(
            empty_message, sample_parent_message, [sample_position]
        )
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_analyze_update_context_cache_hit(self, context_analyzer, sample_message, sample_parent_message, sample_position):
        """Test cache hit returns cached result."""
        # Mock cache hit
        cached_data = {
            "action": "breakeven",
            "target_position": "123456789",
            "parameters": {"new_sl": 3362.50},
            "confidence": 0.90,
            "reasoning": "Cached result"
        }
        
        with patch('src.database.cache.llm_cache') as mock_cache:
            mock_cache.get.return_value = cached_data
            
            result = await context_analyzer.analyze_update_context(
                sample_message, sample_parent_message, [sample_position]
            )
            
            assert result is not None
            assert result.action == "breakeven"
            assert result.target_position == "123456789"
            assert result.confidence == 0.90
    
    @pytest.mark.asyncio
    async def test_analyze_update_context_rate_limited(self, context_analyzer, sample_message, sample_parent_message, sample_position):
        """Test rate limiting prevents API call."""
        with patch('src.database.cache.llm_cache') as mock_cache, \
             patch('src.utils.rate_limiter.llm_rate_limiter') as mock_limiter:
            
            mock_cache.get.return_value = None  # No cache hit
            mock_limiter.acquire.return_value = False  # Rate limited
            
            result = await context_analyzer.analyze_update_context(
                sample_message, sample_parent_message, [sample_position]
            )
            
            assert result is None
    
    @pytest.mark.asyncio
    async def test_analyze_update_context_successful_analysis(self, context_analyzer, sample_message, sample_parent_message, sample_position):
        """Test successful context analysis with high confidence."""
        # Mock successful API response
        api_response = {
            "content": json.dumps({
                "action": "breakeven",
                "target_position": "123456789",
                "parameters": {
                    "new_sl": 3362.50,
                    "new_tp": None,
                    "percentage": None
                },
                "confidence": 0.90,
                "reasoning": "Clear break even request on GOLD position"
            }),
            "usage": {"total_tokens": 150}
        }
        
        with patch('src.database.cache.llm_cache') as mock_cache, \
             patch('src.utils.rate_limiter.llm_rate_limiter') as mock_limiter, \
             patch.object(context_analyzer, '_make_openai_request') as mock_api:
            
            mock_cache.get.return_value = None  # No cache hit
            mock_limiter.acquire.return_value = True  # Not rate limited
            mock_limiter.wait_for_backoff.return_value = None
            mock_api.return_value = api_response
            
            result = await context_analyzer.analyze_update_context(
                sample_message, sample_parent_message, [sample_position]
            )
            
            assert result is not None
            assert result.action == "breakeven"
            assert result.target_position == "123456789"
            assert result.confidence == 0.90
            assert result.reasoning == "Clear break even request on GOLD position"
            assert result.parameters["new_sl"] == 3362.50
    
    @pytest.mark.asyncio
    async def test_analyze_update_context_low_confidence(self, context_analyzer, sample_message, sample_parent_message, sample_position):
        """Test low confidence result is not cached."""
        # Mock low confidence API response
        api_response = {
            "content": json.dumps({
                "action": "unknown",
                "target_position": None,
                "parameters": {},
                "confidence": 0.30,
                "reasoning": "Insufficient context to determine intent"
            }),
            "usage": {"total_tokens": 120}
        }
        
        with patch('src.database.cache.llm_cache') as mock_cache, \
             patch('src.utils.rate_limiter.llm_rate_limiter') as mock_limiter, \
             patch.object(context_analyzer, '_make_openai_request') as mock_api:
            
            mock_cache.get.return_value = None
            mock_cache.set = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_limiter.wait_for_backoff.return_value = None
            mock_api.return_value = api_response
            
            result = await context_analyzer.analyze_update_context(
                sample_message, sample_parent_message, [sample_position]
            )
            
            assert result is None  # Low confidence results not returned
            mock_cache.set.assert_not_called()  # Low confidence not cached
    
    def test_generate_cache_key_consistency(self, context_analyzer, sample_message, sample_parent_message, sample_position):
        """Test cache key generation is consistent."""
        key1 = context_analyzer._generate_cache_key(sample_message, sample_parent_message, [sample_position])
        key2 = context_analyzer._generate_cache_key(sample_message, sample_parent_message, [sample_position])
        
        assert key1 == key2
        assert len(key1) == 64  # SHA256 hex digest length
    
    def test_generate_cache_key_different_messages(self, context_analyzer, sample_parent_message, sample_position):
        """Test different messages generate different cache keys."""
        message1 = TelegramMessage(
            telegram_message_id=1,
            telegram_chat_id=1,
            sender="user",
            timestamp=datetime.now(),
            raw_text="BE sur la position"
        )
        
        message2 = TelegramMessage(
            telegram_message_id=2,
            telegram_chat_id=1,
            sender="user",
            timestamp=datetime.now(),
            raw_text="fermez 50%"
        )
        
        key1 = context_analyzer._generate_cache_key(message1, sample_parent_message, [sample_position])
        key2 = context_analyzer._generate_cache_key(message2, sample_parent_message, [sample_position])
        
        assert key1 != key2
    
    def test_prepare_context_prompt_structure(self, context_analyzer, sample_message, sample_parent_message, sample_position):
        """Test context prompt preparation includes all required elements."""
        prompt = context_analyzer._prepare_context_prompt(sample_message, sample_parent_message, [sample_position])
        
        assert "CONTEXT DATA:" in prompt
        assert sample_message.raw_text in prompt
        assert sample_parent_message.raw_text in prompt
        assert str(sample_position.mt5_ticket) in prompt
        assert sample_position.signal.symbol in prompt
    
    @pytest.mark.asyncio
    async def test_make_openai_request_json_mode(self, context_analyzer):
        """Test OpenAI request uses JSON mode for structured output."""
        with patch('config.openai_config.openai_client') as mock_client:
            mock_response = MagicMock()
            mock_response.choices[0].message.content = '{"action": "test"}'
            mock_response.usage.model_dump.return_value = {"total_tokens": 100}
            
            mock_client.get_model_config.return_value = {"model": "gpt-5-mini"}
            mock_client.client.chat.completions.create.return_value = mock_response
            
            result = await context_analyzer._make_openai_request("test prompt", "test_correlation")
            
            # Verify JSON mode was used
            call_args = mock_client.client.chat.completions.create.call_args
            assert call_args[1]["response_format"] == {"type": "json_object"}
            assert result is not None
            assert result["content"] == '{"action": "test"}'
    
    def test_parse_llm_response_valid_json(self, context_analyzer):
        """Test parsing valid LLM JSON response."""
        response = {
            "content": json.dumps({
                "action": "close",
                "target_position": "123456789",
                "parameters": {"percentage": 0.5},
                "confidence": 0.85,
                "reasoning": "Partial close request"
            })
        }
        
        result = context_analyzer._parse_llm_response(response, "test_correlation", datetime.now())
        
        assert result is not None
        assert result.action == "close"
        assert result.target_position == "123456789"
        assert result.parameters["percentage"] == 0.5
        assert result.confidence == 0.85
    
    def test_parse_llm_response_invalid_action(self, context_analyzer):
        """Test parsing response with invalid action."""
        response = {
            "content": json.dumps({
                "action": "invalid_action",
                "confidence": 0.85,
                "reasoning": "Test"
            })
        }
        
        result = context_analyzer._parse_llm_response(response, "test_correlation", datetime.now())
        assert result is None
    
    def test_parse_llm_response_invalid_confidence(self, context_analyzer):
        """Test parsing response with invalid confidence score."""
        response = {
            "content": json.dumps({
                "action": "close",
                "confidence": 1.5,  # Invalid: > 1.0
                "reasoning": "Test"
            })
        }
        
        result = context_analyzer._parse_llm_response(response, "test_correlation", datetime.now())
        assert result is None
    
    def test_parse_llm_response_malformed_json(self, context_analyzer):
        """Test parsing malformed JSON response."""
        response = {
            "content": "invalid json content"
        }
        
        result = context_analyzer._parse_llm_response(response, "test_correlation", datetime.now())
        assert result is None
    
    def test_parse_llm_response_null_content(self, context_analyzer):
        """Test parsing null/empty response content."""
        response = {"content": "null"}
        result = context_analyzer._parse_llm_response(response, "test_correlation", datetime.now())
        assert result is None
        
        response = {"content": ""}
        result = context_analyzer._parse_llm_response(response, "test_correlation", datetime.now())
        assert result is None
    
    @pytest.mark.asyncio
    async def test_cache_response_successful(self, context_analyzer):
        """Test successful response caching."""
        result = ContextAnalysisResult(
            action="breakeven",
            target_position="123456789",
            parameters={"new_sl": 3362.50},
            confidence=0.90,
            reasoning="Test",
            correlation_id="test_id",
            analysis_latency_ms=100
        )
        
        api_response = {"usage": {"total_tokens": 150}}
        
        with patch('src.database.cache.llm_cache') as mock_cache:
            mock_cache.set = AsyncMock()
            
            await context_analyzer._cache_response("test_key", result, api_response)
            
            mock_cache.set.assert_called_once()
            call_args = mock_cache.set.call_args[0]
            cached_data = call_args[1]
            
            assert cached_data["action"] == "breakeven"
            assert cached_data["confidence"] == 0.90
            assert "cached_at" in cached_data
            assert "api_usage" in cached_data
    
    def test_hash_text_consistency(self, context_analyzer):
        """Test text hashing is consistent."""
        text = "Test message for hashing"
        hash1 = context_analyzer._hash_text(text)
        hash2 = context_analyzer._hash_text(text)
        
        assert hash1 == hash2
        assert len(hash1) == 16  # Truncated to 16 chars
        assert isinstance(hash1, str)
    
    def test_hash_text_different_inputs(self, context_analyzer):
        """Test different text inputs produce different hashes."""
        hash1 = context_analyzer._hash_text("message one")
        hash2 = context_analyzer._hash_text("message two")
        
        assert hash1 != hash2
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_protection(self, context_analyzer):
        """Test circuit breaker protects against API failures."""
        with patch.object(context_analyzer, '_make_openai_request') as mock_api:
            # Simulate circuit breaker triggering
            mock_api.side_effect = Exception("Circuit breaker open")
            
            with patch('src.database.cache.llm_cache') as mock_cache, \
                 patch('src.utils.rate_limiter.llm_rate_limiter') as mock_limiter:
                
                mock_cache.get.return_value = None
                mock_limiter.acquire.return_value = True
                mock_limiter.wait_for_backoff.return_value = None
                
                message = TelegramMessage(
                    telegram_message_id=1,
                    telegram_chat_id=1,
                    sender="user",
                    timestamp=datetime.now(),
                    raw_text="test message"
                )
                
                result = await context_analyzer.analyze_update_context(
                    message, message, []
                )
                
                assert result is None
                mock_limiter.record_failure.assert_called_once()
    
    def test_validate_api_response_valid(self, context_analyzer):
        """Test API response validation with valid response."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "test content"
        
        assert context_analyzer._validate_api_response(mock_response) is True
    
    def test_validate_api_response_invalid(self, context_analyzer):
        """Test API response validation with invalid responses."""
        # No choices
        mock_response = MagicMock()
        mock_response.choices = []
        assert context_analyzer._validate_api_response(mock_response) is False
        
        # No message content
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None
        assert context_analyzer._validate_api_response(mock_response) is False
        
        # Exception during validation
        mock_response.choices = None
        assert context_analyzer._validate_api_response(mock_response) is False