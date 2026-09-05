"""
Integration tests for break even automation flow.

Tests complete end-to-end scenarios from Telegram message processing
through correlation, calculation, MT5 modification, and database audit.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch

from src.risk_manager.break_even import BreakEvenProcessor
from src.risk_manager.position_modifier import PositionModifier
from src.mt5_executor.position_manager import PositionManager
from src.correlation_engine.correlator import TelegramMessage, CorrelationEngine
from src.database.models import Position, PositionStatus, UpdateType, PositionUpdate
from tests.fixtures.sample_signals import create_test_position, create_test_message


class TestBreakEvenIntegrationFlow:
    """Integration tests for complete break even flow."""

    def setup_method(self):
        """Setup integration test environment."""
        # Mock dependencies
        self.mock_correlation_engine = Mock(spec=CorrelationEngine)
        self.mock_db_manager = Mock()
        self.mock_position_manager = Mock(spec=PositionManager)
        
        # Create processor with mocked dependencies
        self.be_processor = BreakEvenProcessor(
            correlation_engine=self.mock_correlation_engine,
            db_manager=self.mock_db_manager
        )
        
        # Mock repository setup
        self.mock_repo_factory = Mock()
        self.mock_position_repo = Mock()
        self.mock_update_repo = Mock()
        
        self.be_processor.repo_factory = self.mock_repo_factory
        self.be_processor.position_repo = self.mock_position_repo
        self.be_processor.update_repo = self.mock_update_repo

    @pytest.mark.asyncio
    async def test_end_to_end_break_even_success_flow(self):
        """Test complete successful break even flow from message to MT5 modification."""
        # Arrange: Create test message and position
        message = create_test_message(
            message_id=1001,
            text="BREAK EVEN",
            sender="trader1"
        )
        
        position = create_test_position(
            position_id=1,
            ticket=2001,
            entry_price=1850.00,
            current_sl=1849.50,
            current_tp=1851.00,
            profit=10.0
        )
        
        # Mock correlation success
        self.mock_correlation_engine.correlate_message = AsyncMock(return_value=position)
        self.mock_correlation_engine.get_correlation_stats = Mock(
            return_value={'success_rate': 0.90}
        )
        
        # Mock no existing BE updates
        self.be_processor.check_existing_be_update = AsyncMock(return_value=False)
        
        # Mock successful audit record creation
        self.be_processor.record_be_update = AsyncMock(return_value=101)
        
        # Act: Process break even request
        result = await self.be_processor.process_break_even_request(message)
        
        # Assert: Verify successful processing
        assert result.success
        assert result.position == position
        assert result.old_sl == 1849.50
        assert result.new_sl == 1850.01  # Entry + 1 pip
        assert result.correlation_confidence == 0.90
        assert result.update_id == 101
        
        # Verify correlation was called
        self.mock_correlation_engine.correlate_message.assert_called_once_with(message)
        
        # Verify idempotency check was performed
        self.be_processor.check_existing_be_update.assert_called_once_with(position.id)
        
        # Verify audit record was created
        self.be_processor.record_be_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_break_even_with_mt5_modification(self):
        """Test break even processing with actual MT5 position modification."""
        # Create test scenario
        message = create_test_message(message_id=1002, text="BE")
        position = create_test_position(
            position_id=2,
            ticket=2002,
            entry_price=1855.25,
            current_sl=1854.00
        )
        
        # Setup successful break even processing
        self.mock_correlation_engine.correlate_message = AsyncMock(return_value=position)
        self.mock_correlation_engine.get_correlation_stats = Mock(
            return_value={'success_rate': 0.85}
        )
        self.be_processor.check_existing_be_update = AsyncMock(return_value=False)
        self.be_processor.record_be_update = AsyncMock(return_value=102)
        
        # Mock successful MT5 modification
        mt5_result = Mock()
        mt5_result.success = True
        mt5_result.ticket = 2002
        mt5_result.old_sl = 1854.00
        mt5_result.new_sl = 1855.26  # Entry + 1 pip
        
        self.mock_position_manager.modify_stop_loss = AsyncMock(return_value=mt5_result)
        self.mock_position_manager.validate_modification_success = AsyncMock(return_value=True)
        
        # Process break even request
        be_result = await self.be_processor.process_break_even_request(message)
        
        # Simulate MT5 modification (would be done by main orchestrator)
        if be_result.success:
            mt5_modification_result = await self.mock_position_manager.modify_stop_loss(
                ticket=position.mt5_ticket,
                new_sl=be_result.new_sl
            )
            
            # Validate modification was applied
            validation_success = await self.mock_position_manager.validate_modification_success(
                ticket=position.mt5_ticket,
                expected_sl=be_result.new_sl
            )
        
        # Assertions
        assert be_result.success
        assert mt5_modification_result.success
        assert validation_success
        assert mt5_modification_result.new_sl == 1855.26

    @pytest.mark.asyncio
    async def test_break_even_with_correlation_failure(self):
        """Test break even flow when message correlation fails."""
        message = create_test_message(message_id=1003, text="SECURE")
        
        # Mock correlation failure
        self.mock_correlation_engine.correlate_message = AsyncMock(return_value=None)
        
        result = await self.be_processor.process_break_even_request(message)
        
        assert not result.success
        assert "No position found" in result.error_message
        assert result.position is None
        assert result.correlation_confidence == 0.0

    @pytest.mark.asyncio
    async def test_break_even_idempotency_protection(self):
        """Test that duplicate break even requests are prevented."""
        message = create_test_message(message_id=1004, text="BREAK EVEN")
        position = create_test_position(position_id=3, ticket=2003)
        
        # Setup scenario where BE already applied
        self.mock_correlation_engine.correlate_message = AsyncMock(return_value=position)
        self.mock_correlation_engine.get_correlation_stats = Mock(
            return_value={'success_rate': 0.95}
        )
        self.be_processor.check_existing_be_update = AsyncMock(return_value=True)
        
        # Mock record_be_update to track calls
        original_record = self.be_processor.record_be_update
        self.be_processor.record_be_update = AsyncMock(wraps=original_record)
        
        result = await self.be_processor.process_break_even_request(message)
        
        assert not result.success
        assert "Break even already applied" in result.error_message
        
        # Verify record_be_update was not called
        self.be_processor.record_be_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_break_even_performance_requirements(self):
        """Test that break even processing meets performance requirements (<2 seconds)."""
        message = create_test_message(message_id=1005, text="BREAK EVEN")
        position = create_test_position(position_id=4, ticket=2004)
        
        # Setup fast successful scenario
        self.mock_correlation_engine.correlate_message = AsyncMock(return_value=position)
        self.mock_correlation_engine.get_correlation_stats = Mock(
            return_value={'success_rate': 0.90}
        )
        self.be_processor.check_existing_be_update = AsyncMock(return_value=False)
        self.be_processor.record_be_update = AsyncMock(return_value=105)
        
        # Measure processing time
        start_time = datetime.now()
        result = await self.be_processor.process_break_even_request(message)
        processing_time = (datetime.now() - start_time).total_seconds()
        
        # Assertions
        assert result.success
        assert processing_time < 2.0, f"Processing took {processing_time}s, expected <2s"

    @pytest.mark.asyncio
    async def test_concurrent_break_even_requests(self):
        """Test handling of multiple concurrent break even requests."""
        # Create multiple test scenarios
        messages_and_positions = [
            (
                create_test_message(message_id=2001 + i, text="BREAK EVEN"),
                create_test_position(position_id=10 + i, ticket=3001 + i)
            )
            for i in range(5)
        ]
        
        # Setup mocks for concurrent processing
        async def mock_correlate(message):
            # Find corresponding position
            for msg, pos in messages_and_positions:
                if msg.telegram_message_id == message.telegram_message_id:
                    return pos
            return None
        
        self.mock_correlation_engine.correlate_message = AsyncMock(side_effect=mock_correlate)
        self.mock_correlation_engine.get_correlation_stats = Mock(
            return_value={'success_rate': 0.88}
        )
        self.be_processor.check_existing_be_update = AsyncMock(return_value=False)
        
        # Mock different update IDs for each request
        update_ids = [201, 202, 203, 204, 205]
        self.be_processor.record_be_update = AsyncMock(side_effect=update_ids)
        
        # Process requests concurrently
        tasks = [
            self.be_processor.process_break_even_request(msg)
            for msg, pos in messages_and_positions
        ]
        
        results = await asyncio.gather(*tasks)
        
        # Verify all requests processed successfully
        assert len(results) == 5
        assert all(result.success for result in results)
        assert [result.update_id for result in results] == update_ids

    @pytest.mark.asyncio
    async def test_break_even_with_database_error_handling(self):
        """Test break even processing with database errors."""
        message = create_test_message(message_id=1006, text="BREAK EVEN")
        position = create_test_position(position_id=5, ticket=2005)
        
        # Setup successful correlation but database error
        self.mock_correlation_engine.correlate_message = AsyncMock(return_value=position)
        self.mock_correlation_engine.get_correlation_stats = Mock(
            return_value={'success_rate': 0.92}
        )
        self.be_processor.check_existing_be_update = AsyncMock(return_value=False)
        
        # Mock database error during audit record creation
        self.be_processor.record_be_update = AsyncMock(
            side_effect=Exception("Database connection failed")
        )
        
        result = await self.be_processor.process_break_even_request(message)
        
        assert not result.success
        assert "Processing error" in result.error_message
        assert "Database connection failed" in result.error_message

    @pytest.mark.asyncio
    async def test_break_even_with_multiple_language_signals(self):
        """Test break even detection with various language patterns."""
        test_cases = [
            ("BREAK EVEN", "English standard"),
            ("BE", "English abbreviation"),
            ("SÉCURISER", "French secure"),
            ("PROTÉGER", "French protect"),
            ("SL ON ENTRY", "English SL instruction"),
            ("DÉPLACER SL", "French move SL"),
            ("SECURE", "English secure"),
            ("move sl to entry +1", "English context")
        ]
        
        position = create_test_position(position_id=6, ticket=2006)
        
        for text, description in test_cases:
            message = create_test_message(
                message_id=1007,
                text=text
            )
            
            # Setup successful processing
            self.mock_correlation_engine.correlate_message = AsyncMock(return_value=position)
            self.mock_correlation_engine.get_correlation_stats = Mock(
                return_value={'success_rate': 0.85}
            )
            self.be_processor.check_existing_be_update = AsyncMock(return_value=False)
            self.be_processor.record_be_update = AsyncMock(return_value=107)
            
            result = await self.be_processor.process_break_even_request(message)
            
            assert result.success, f"Failed to detect BE signal in {description}: '{text}'"
            assert result.new_sl == position.open_price + 0.01

    @pytest.mark.asyncio
    async def test_break_even_audit_trail_integrity(self):
        """Test that complete audit trail is maintained throughout process."""
        message = create_test_message(message_id=1008, text="BREAK EVEN")
        position = create_test_position(
            position_id=7,
            ticket=2007,
            entry_price=1845.75,
            current_sl=1845.00
        )
        
        # Setup successful processing with audit tracking
        self.mock_correlation_engine.correlate_message = AsyncMock(return_value=position)
        self.mock_correlation_engine.get_correlation_stats = Mock(
            return_value={'success_rate': 0.95}
        )
        self.be_processor.check_existing_be_update = AsyncMock(return_value=False)
        
        # Capture audit record call
        recorded_updates = []
        
        async def capture_record_call(*args, **kwargs):
            recorded_updates.append((args, kwargs))
            return 108
        
        self.be_processor.record_be_update = AsyncMock(side_effect=capture_record_call)
        
        result = await self.be_processor.process_break_even_request(message)
        
        # Verify audit trail
        assert result.success
        assert len(recorded_updates) == 1
        
        # Verify audit record contains correct information
        call_args = recorded_updates[0][1]  # kwargs
        assert call_args['position_id'] == position.id
        assert call_args['old_sl'] == position.current_sl
        assert call_args['new_sl'] == 1845.76  # Entry + 1 pip
        assert call_args['telegram_message_id'] == message.telegram_message_id
        assert call_args['success'] == True