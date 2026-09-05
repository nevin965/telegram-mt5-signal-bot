"""Integration tests for LLM context analysis flow."""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import json

from src.signal_parser.context_analyzer import ContextAnalyzer, TelegramMessage
from src.risk_manager.context_processor import ContextProcessor, ExecutionResult
from src.database.models import Position, Signal, PositionStatus, ParsedAction


class TestLLMContextFlow:
    """Integration tests for end-to-end LLM context analysis flow."""
    
    @pytest.fixture
    def mock_repository(self):
        """Create mock repository for testing."""
        repo = MagicMock()
        repo.get_session = AsyncMock()
        return repo
    
    @pytest.fixture
    def context_analyzer(self):
        """Create ContextAnalyzer with mocked dependencies."""
        with patch.object(ContextAnalyzer, '_load_prompt_template') as mock_load:
            mock_load.return_value = "Test prompt template for context analysis"
            return ContextAnalyzer()
    
    @pytest.fixture
    def context_processor(self, mock_repository):
        """Create ContextProcessor with mocked repository."""
        return ContextProcessor(mock_repository)
    
    @pytest.fixture
    def sample_positions(self):
        """Create sample positions for testing."""
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
        
        return [position]
    
    @pytest.mark.asyncio
    async def test_end_to_end_break_even_high_confidence(self, context_analyzer, context_processor, sample_positions):
        """Test complete flow: analysis → high confidence → automatic execution."""
        
        # Create test message
        message = TelegramMessage(
            telegram_message_id=12345,
            telegram_chat_id=67890,
            sender="user_123",
            timestamp=datetime.now(),
            raw_text="BE sur la position GOLD"
        )
        
        parent_message = TelegramMessage(
            telegram_message_id=11111,
            telegram_chat_id=67890,
            sender="signal_provider",
            timestamp=datetime.now(),
            raw_text="BUY GOLD 3362.50, SL 3355, TP 3375"
        )
        
        # Mock LLM response for break even with high confidence
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
                "reasoning": "Clear break even request for GOLD position"
            }),
            "usage": {"total_tokens": 150}
        }
        
        # Mock all dependencies
        with patch('src.database.cache.llm_cache') as mock_cache, \
             patch('src.utils.rate_limiter.llm_rate_limiter') as mock_limiter, \
             patch.object(context_analyzer, '_make_openai_request') as mock_api:
            
            mock_cache.get.return_value = None  # No cache hit
            mock_cache.set = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_limiter.wait_for_backoff.return_value = None
            mock_limiter.record_success.return_value = None
            mock_limiter.get_metrics.return_value = {}
            mock_api.return_value = api_response
            
            # Step 1: Analyze context
            analysis_result = await context_analyzer.analyze_update_context(
                message, parent_message, sample_positions
            )
            
            assert analysis_result is not None
            assert analysis_result.action == "breakeven"
            assert analysis_result.confidence == 0.90
            
            # Step 2: Process with context processor
            with patch.object(context_processor, '_route_to_break_even_processor') as mock_be_router:
                mock_be_router.return_value = {"success": True, "processor": "break_even"}
                
                with patch.object(context_processor, '_create_audit_trail') as mock_audit:
                    execution_result, details = await context_processor.process_context_analysis(
                        analysis_result, message, sample_positions
                    )
            
            # Verify execution
            assert execution_result == ExecutionResult.EXECUTED
            assert details["action"] == "breakeven"
            assert details["confidence"] == 0.90
            mock_be_router.assert_called_once()
            mock_audit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_end_to_end_partial_close_high_confidence(self, context_analyzer, context_processor, sample_positions):
        """Test complete flow for partial close with high confidence."""
        
        message = TelegramMessage(
            telegram_message_id=12346,
            telegram_chat_id=67890,
            sender="user_123",
            timestamp=datetime.now(),
            raw_text="Fermez 50% de la position GOLD"
        )
        
        parent_message = TelegramMessage(
            telegram_message_id=11111,
            telegram_chat_id=67890,
            sender="signal_provider",
            timestamp=datetime.now(),
            raw_text="BUY GOLD 3362.50, SL 3355, TP 3375"
        )
        
        # Mock LLM response for partial close
        api_response = {
            "content": json.dumps({
                "action": "close",
                "target_position": "123456789",
                "parameters": {
                    "percentage": 0.5,
                    "new_sl": None,
                    "new_tp": None
                },
                "confidence": 0.85,
                "reasoning": "French instruction to close 50% of GOLD position"
            }),
            "usage": {"total_tokens": 160}
        }
        
        with patch('src.database.cache.llm_cache') as mock_cache, \
             patch('src.utils.rate_limiter.llm_rate_limiter') as mock_limiter, \
             patch.object(context_analyzer, '_make_openai_request') as mock_api:
            
            mock_cache.get.return_value = None
            mock_cache.set = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_limiter.wait_for_backoff.return_value = None
            mock_limiter.record_success.return_value = None
            mock_limiter.get_metrics.return_value = {}
            mock_api.return_value = api_response
            
            # Analyze context
            analysis_result = await context_analyzer.analyze_update_context(
                message, parent_message, sample_positions
            )
            
            assert analysis_result is not None
            assert analysis_result.action == "close"
            assert analysis_result.parameters["percentage"] == 0.5
            
            # Process with high confidence
            with patch.object(context_processor, '_route_to_close_processor') as mock_close_router:
                mock_close_router.return_value = {"success": True, "processor": "close", "close_percentage": 0.5}
                
                with patch.object(context_processor, '_create_audit_trail') as mock_audit:
                    execution_result, details = await context_processor.process_context_analysis(
                        analysis_result, message, sample_positions
                    )
            
            assert execution_result == ExecutionResult.EXECUTED
            assert details["action"] == "close"
            assert details["parameters"]["percentage"] == 0.5
            mock_close_router.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_end_to_end_low_confidence_manual_review(self, context_analyzer, context_processor, sample_positions):
        """Test complete flow for low confidence requiring manual review."""
        
        message = TelegramMessage(
            telegram_message_id=12347,
            telegram_chat_id=67890,
            sender="user_123",
            timestamp=datetime.now(),
            raw_text="maybe do something with position"
        )
        
        # Mock LLM response with low confidence
        api_response = {
            "content": json.dumps({
                "action": "modify",
                "target_position": None,
                "parameters": {},
                "confidence": 0.40,
                "reasoning": "Ambiguous instruction, unclear intent"
            }),
            "usage": {"total_tokens": 140}
        }
        
        with patch('src.database.cache.llm_cache') as mock_cache, \
             patch('src.utils.rate_limiter.llm_rate_limiter') as mock_limiter, \
             patch.object(context_analyzer, '_make_openai_request') as mock_api:
            
            mock_cache.get.return_value = None
            mock_cache.set = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_limiter.wait_for_backoff.return_value = None
            mock_limiter.record_success.return_value = None
            mock_limiter.get_metrics.return_value = {}
            mock_api.return_value = api_response
            
            # Analyze context
            analysis_result = await context_analyzer.analyze_update_context(
                message, None, sample_positions
            )
            
            assert analysis_result is not None
            assert analysis_result.action == "modify"
            assert analysis_result.confidence == 0.40
            
            # Process with low confidence - should queue for manual review
            with patch.object(context_processor, '_queue_for_manual_review') as mock_queue:
                mock_queue.return_value = {
                    "action": "modify",
                    "confidence": 0.40,
                    "review_required": True,
                    "queued_at": datetime.now().isoformat()
                }
                
                execution_result, details = await context_processor.process_context_analysis(
                    analysis_result, message, sample_positions
                )
            
            assert execution_result == ExecutionResult.QUEUED_FOR_REVIEW
            assert details["review_required"] is True
            assert details["confidence"] == 0.40
            mock_queue.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_end_to_end_api_failure_fallback(self, context_analyzer, context_processor, sample_positions):
        """Test complete flow when LLM API fails."""
        
        message = TelegramMessage(
            telegram_message_id=12348,
            telegram_chat_id=67890,
            sender="user_123",
            timestamp=datetime.now(),
            raw_text="BE on position"
        )
        
        with patch('src.database.cache.llm_cache') as mock_cache, \
             patch('src.utils.rate_limiter.llm_rate_limiter') as mock_limiter, \
             patch.object(context_analyzer, '_make_openai_request') as mock_api:
            
            mock_cache.get.return_value = None
            mock_limiter.acquire.return_value = True
            mock_limiter.wait_for_backoff.return_value = None
            mock_limiter.record_failure.return_value = None
            mock_limiter.get_metrics.return_value = {}
            mock_api.side_effect = Exception("OpenAI API error")
            
            # Analyze context - should fail gracefully
            analysis_result = await context_analyzer.analyze_update_context(
                message, None, sample_positions
            )
            
            assert analysis_result is None
            
            # Process with failed analysis
            execution_result, details = await context_processor.process_context_analysis(
                analysis_result, message, sample_positions
            )
            
            assert execution_result == ExecutionResult.FAILED
            assert "No analysis result provided" in details["error"]
    
    @pytest.mark.asyncio
    async def test_end_to_end_cache_hit_flow(self, context_analyzer, context_processor, sample_positions):
        """Test complete flow with cache hit."""
        
        message = TelegramMessage(
            telegram_message_id=12349,
            telegram_chat_id=67890,
            sender="user_123",
            timestamp=datetime.now(),
            raw_text="BE sur la position"
        )
        
        parent_message = TelegramMessage(
            telegram_message_id=11111,
            telegram_chat_id=67890,
            sender="signal_provider",
            timestamp=datetime.now(),
            raw_text="BUY GOLD 3362.50, SL 3355, TP 3375"
        )
        
        # Mock cache hit
        cached_data = {
            "action": "breakeven",
            "target_position": "123456789",
            "parameters": {"new_sl": 3362.50},
            "confidence": 0.92,
            "reasoning": "Cached break even analysis"
        }
        
        with patch('src.database.cache.llm_cache') as mock_cache:
            mock_cache.get.return_value = cached_data
            
            # Should not call OpenAI API
            with patch.object(context_analyzer, '_make_openai_request') as mock_api:
                analysis_result = await context_analyzer.analyze_update_context(
                    message, parent_message, sample_positions
                )
                
                assert analysis_result is not None
                assert analysis_result.action == "breakeven"
                assert analysis_result.confidence == 0.92
                mock_api.assert_not_called()  # Should use cache
                
                # Process cached result
                with patch.object(context_processor, '_route_to_break_even_processor') as mock_be_router:
                    mock_be_router.return_value = {"success": True, "processor": "break_even"}
                    
                    with patch.object(context_processor, '_create_audit_trail'):
                        execution_result, details = await context_processor.process_context_analysis(
                            analysis_result, message, sample_positions
                        )
                
                assert execution_result == ExecutionResult.EXECUTED
                assert details["confidence"] == 0.92
    
    @pytest.mark.asyncio
    async def test_end_to_end_validation_failure(self, context_analyzer, context_processor, sample_positions):
        """Test complete flow with validation failure."""
        
        message = TelegramMessage(
            telegram_message_id=12350,
            telegram_chat_id=67890,
            sender="user_123",
            timestamp=datetime.now(),
            raw_text="BE on position"
        )
        
        # Mock LLM response with invalid target position
        api_response = {
            "content": json.dumps({
                "action": "breakeven",
                "target_position": "999999999",  # Non-existent position
                "parameters": {},
                "confidence": 0.90,
                "reasoning": "BE request for non-existent position"
            }),
            "usage": {"total_tokens": 150}
        }
        
        with patch('src.database.cache.llm_cache') as mock_cache, \
             patch('src.utils.rate_limiter.llm_rate_limiter') as mock_limiter, \
             patch.object(context_analyzer, '_make_openai_request') as mock_api:
            
            mock_cache.get.return_value = None
            mock_cache.set = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_limiter.wait_for_backoff.return_value = None
            mock_limiter.record_success.return_value = None
            mock_limiter.get_metrics.return_value = {}
            mock_api.return_value = api_response
            
            analysis_result = await context_analyzer.analyze_update_context(
                message, None, sample_positions
            )
            
            assert analysis_result is not None
            assert analysis_result.target_position == "999999999"
            
            # Should fail validation
            execution_result, details = await context_processor.process_context_analysis(
                analysis_result, message, sample_positions
            )
            
            assert execution_result == ExecutionResult.INVALID_ACTION
            assert "not found in open positions" in str(details["errors"])
    
    @pytest.mark.asyncio
    async def test_end_to_end_performance_within_limits(self, context_analyzer, context_processor, sample_positions):
        """Test that complete flow completes within performance requirements (<5 seconds)."""
        
        message = TelegramMessage(
            telegram_message_id=12351,
            telegram_chat_id=67890,
            sender="user_123",
            timestamp=datetime.now(),
            raw_text="BE sur la position GOLD"
        )
        
        parent_message = TelegramMessage(
            telegram_message_id=11111,
            telegram_chat_id=67890,
            sender="signal_provider",
            timestamp=datetime.now(),
            raw_text="BUY GOLD 3362.50, SL 3355, TP 3375"
        )
        
        api_response = {
            "content": json.dumps({
                "action": "breakeven",
                "target_position": "123456789",
                "parameters": {},
                "confidence": 0.88,
                "reasoning": "Performance test analysis"
            }),
            "usage": {"total_tokens": 150}
        }
        
        start_time = datetime.now()
        
        with patch('src.database.cache.llm_cache') as mock_cache, \
             patch('src.utils.rate_limiter.llm_rate_limiter') as mock_limiter, \
             patch.object(context_analyzer, '_make_openai_request') as mock_api:
            
            mock_cache.get.return_value = None
            mock_cache.set = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_limiter.wait_for_backoff.return_value = None
            mock_limiter.record_success.return_value = None
            mock_limiter.get_metrics.return_value = {}
            mock_api.return_value = api_response
            
            # Complete analysis and processing
            analysis_result = await context_analyzer.analyze_update_context(
                message, parent_message, sample_positions
            )
            
            with patch.object(context_processor, '_route_to_break_even_processor') as mock_router:
                mock_router.return_value = {"success": True}
                
                with patch.object(context_processor, '_create_audit_trail'):
                    execution_result, details = await context_processor.process_context_analysis(
                        analysis_result, message, sample_positions
                    )
        
        end_time = datetime.now()
        total_time = (end_time - start_time).total_seconds()
        
        # Should complete within 5 seconds (requirement from story)
        assert total_time < 5.0
        assert execution_result == ExecutionResult.EXECUTED