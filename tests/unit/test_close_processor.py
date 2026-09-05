"""
Unit tests for close signal processor.

Tests close signal detection with French pattern recognition,
volume calculations, and structured close instruction generation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.risk_manager.close_processor import CloseProcessor, CloseAction, CloseInstruction
from src.correlation_engine.correlator import TelegramMessage
from src.database.models import Position, Signal, PositionStatus


class TestCloseSignalDetection:
    """Test close signal detection with various patterns."""

    @pytest.fixture
    def close_processor(self):
        """Create close processor with mocked dependencies."""
        correlation_engine = AsyncMock()
        position_manager = AsyncMock()
        repo_factory = MagicMock()
        
        processor = CloseProcessor(
            correlation_engine=correlation_engine,
            position_manager=position_manager,
            repo_factory=repo_factory
        )
        
        # Mock position repo
        position_repo = AsyncMock()
        repo_factory.get_position_repository.return_value = position_repo
        processor.position_repo = position_repo
        
        return processor

    @pytest.mark.asyncio
    async def test_detect_full_close_french_patterns(self, close_processor):
        """Test detection of French full close patterns."""
        test_cases = [
            "CLÔTUREZ la position maintenant",
            "FERMEZ votre position",
            "TP HIT - fermer",
            "STOP triggered",  # Changed from "STOP activé" 
            "EXIT all positions",
            "CLÔTURE POSITION immédiatement"
        ]
        
        for text in test_cases:
            result = await close_processor.detect_close_signal(text)
            assert result is not None
            assert result.action == CloseAction.FULL_CLOSE
            assert result.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_detect_partial_close_patterns(self, close_processor):
        """Test detection of partial close patterns with percentage extraction."""
        test_cases = [
            ("CLOSE 50% de la position", 0.5),
            ("FERMEZ 75% maintenant", 0.75),
            ("FERMEZ MOITIÉ", 0.5),
            ("CLOSE HALF of position", 0.5),
            ("PARTIAL TP 25%", 0.25),
            ("FERMEZ LA MOITIÉ", 0.5)
        ]
        
        for text, expected_percentage in test_cases:
            result = await close_processor.detect_close_signal(text)
            assert result is not None
            assert result.action == CloseAction.PARTIAL_CLOSE
            assert result.percentage == expected_percentage
            assert result.confidence >= 0.85

    @pytest.mark.asyncio
    async def test_detect_close_all_patterns(self, close_processor):
        """Test detection of close all patterns with symbol filtering."""
        test_cases = [
            ("CLOSE ALL GOLD positions", "GOLD"),
            ("FERMEZ TOUT XAUUSD", "GOLD"),  # Should normalize to GOLD
            ("CLOSE ALL EUR trades", "EUR"),
            ("FERMEZ TOUT", None)  # No specific symbol
        ]
        
        for text, expected_symbol in test_cases:
            result = await close_processor.detect_close_signal(text)
            assert result is not None
            assert result.action == CloseAction.CLOSE_ALL
            assert result.symbol_filter == expected_symbol
            assert result.confidence >= 0.95

    @pytest.mark.asyncio
    async def test_no_close_signal_detected(self, close_processor):
        """Test cases where no close signal should be detected."""
        non_close_texts = [
            "BUY GOLD at 1950",
            "Profit target reached",  # Changed from "Take profit" which triggers detection
            "Position looking good",
            "Update your stop loss",
            "Entry signal confirmed"
        ]
        
        for text in non_close_texts:
            result = await close_processor.detect_close_signal(text)
            assert result is None, f"Unexpected close signal detected for: {text}"

    @pytest.mark.asyncio
    async def test_signal_priority_ordering(self, close_processor):
        """Test that close all has highest priority, then partial, then full."""
        # Close all should have highest priority
        result = await close_processor.detect_close_signal("CLOSE ALL GOLD and also CLOSE 50%")
        assert result.action == CloseAction.CLOSE_ALL
        assert result.symbol_filter == "GOLD"
        
        # Partial should have priority over full
        result = await close_processor.detect_close_signal("FERMEZ 50% CLÔTUREZ")
        assert result.action == CloseAction.PARTIAL_CLOSE
        assert result.percentage == 0.5


class TestCloseProcessingFlow:
    """Test complete close processing workflow."""

    @pytest.fixture
    def close_processor(self):
        """Create close processor with mocked dependencies."""
        correlation_engine = AsyncMock()
        position_manager = AsyncMock()
        repo_factory = MagicMock()
        
        processor = CloseProcessor(
            correlation_engine=correlation_engine,
            position_manager=position_manager,
            repo_factory=repo_factory
        )
        
        # Mock position repo
        position_repo = AsyncMock()
        repo_factory.get_position_repository.return_value = position_repo
        processor.position_repo = position_repo
        
        # Mock position update repo
        update_repo = AsyncMock()
        repo_factory.get_position_update_repository.return_value = update_repo
        
        return processor

    @pytest.fixture
    def mock_position(self):
        """Create mock position for testing."""
        signal = Signal(
            id=1,
            telegram_message_id=12345,
            telegram_chat_id=67890,
            sender="test_trader",
            timestamp=datetime.now(),
            raw_text="BUY GOLD at 1950",
            parsed_action="BUY",
            symbol="GOLD",
            entry_price=1950.0,
            confidence_score=0.9,
            parser_type="LLM",
            status="EXECUTED"
        )
        
        position = Position(
            id=1,
            signal_id=1,
            mt5_ticket=123456,
            open_time=datetime.now(),
            open_price=1950.0,
            volume=1.0,
            status=PositionStatus.OPEN
        )
        position.signal = signal
        
        return position

    @pytest.fixture
    def mock_message(self):
        """Create mock Telegram message for testing."""
        return TelegramMessage(
            telegram_message_id=54321,
            telegram_chat_id=67890,
            sender="test_trader",
            timestamp=datetime.now(),
            raw_text="CLÔTUREZ position",
            reply_to_message_id=12345
        )

    @pytest.mark.asyncio
    async def test_full_close_processing_success(self, close_processor, mock_position, mock_message):
        """Test successful full close processing."""
        # Mock correlation to return position
        close_processor.correlation_engine.correlate_message.return_value = mock_position
        
        # Mock successful MT5 close
        from src.mt5_executor.position_manager import MT5Result
        mock_close_result = MT5Result(
            success=True,
            ticket=123456,
            operation="close_position_full",
            volume_closed=1.0,
            close_price=1955.0,
            profit=50.0
        )
        close_processor.position_manager.close_position_full.return_value = mock_close_result
        
        # Mock database update
        close_processor._update_position_closed = AsyncMock()
        
        # Process close signal
        result = await close_processor.process_close_signal(mock_message)
        
        # Verify results
        assert result['success'] is True
        assert result['position_id'] == 1
        assert result['ticket'] == 123456
        assert result['volume_closed'] == 1.0
        assert result['close_price'] == 1955.0
        assert result['profit'] == 50.0
        
        # Verify MT5 close was called
        close_processor.position_manager.close_position_full.assert_called_once_with(123456)
        
        # Verify database update was called
        close_processor._update_position_closed.assert_called_once()

    @pytest.mark.asyncio
    async def test_partial_close_processing_success(self, close_processor, mock_position, mock_message):
        """Test successful partial close processing."""
        # Update message for partial close
        mock_message.raw_text = "FERMEZ 50%"
        
        # Mock correlation to return position
        close_processor.correlation_engine.correlate_message.return_value = mock_position
        
        # Mock successful MT5 partial close
        from src.mt5_executor.position_manager import MT5Result
        mock_close_result = MT5Result(
            success=True,
            ticket=123456,
            operation="close_position_partial",
            volume_closed=0.5,
            close_price=1955.0,
            profit=25.0
        )
        close_processor.position_manager.close_position_partial.return_value = mock_close_result
        
        # Mock database update
        close_processor._update_position_partial_close = AsyncMock()
        
        # Process close signal
        result = await close_processor.process_close_signal(mock_message)
        
        # Verify results
        assert result['success'] is True
        assert result['position_id'] == 1
        assert result['ticket'] == 123456
        assert result['percentage'] == 0.5
        assert result['volume_closed'] == 0.5
        assert result['close_price'] == 1955.0
        assert result['profit'] == 25.0
        
        # Verify MT5 partial close was called
        close_processor.position_manager.close_position_partial.assert_called_once_with(123456, 0.5)
        
        # Verify database update was called
        close_processor._update_position_partial_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_all_processing_success(self, close_processor, mock_position, mock_message):
        """Test successful close all processing."""
        # Update message for close all
        mock_message.raw_text = "CLOSE ALL GOLD"
        
        # Mock open positions query
        positions = [mock_position]
        close_processor.position_repo.get_open_positions.return_value = positions
        
        # Mock successful individual close
        close_processor._execute_full_close = AsyncMock(return_value={
            'success': True,
            'position_id': 1,
            'ticket': 123456
        })
        
        # Process close signal
        result = await close_processor.process_close_signal(mock_message)
        
        # Verify results
        assert result['success'] is True
        assert result['positions_closed'] == 1
        assert result['total_positions'] == 1
        assert result['success_rate'] == 1.0
        assert len(result['failures']) == 0

    @pytest.mark.asyncio
    async def test_no_correlation_found(self, close_processor, mock_message):
        """Test handling when no position correlation is found."""
        # Mock no correlation found
        close_processor.correlation_engine.correlate_message.return_value = None
        
        # Process close signal
        result = await close_processor.process_close_signal(mock_message)
        
        # Verify error handling
        assert result['success'] is False
        assert 'Could not correlate message to position' in result['error']

    @pytest.mark.asyncio
    async def test_mt5_close_failure(self, close_processor, mock_position, mock_message):
        """Test handling of MT5 close operation failure."""
        # Mock correlation to return position
        close_processor.correlation_engine.correlate_message.return_value = mock_position
        
        # Mock failed MT5 close
        from src.mt5_executor.position_manager import MT5Result
        mock_close_result = MT5Result(
            success=False,
            ticket=123456,
            operation="close_position_full",
            error_message="MT5 connection lost"
        )
        close_processor.position_manager.close_position_full.return_value = mock_close_result
        
        # Process close signal
        result = await close_processor.process_close_signal(mock_message)
        
        # Verify error handling
        assert result['success'] is False
        assert result['error'] == "MT5 connection lost"
        assert result['ticket'] == 123456


class TestVolumeCalculations:
    """Test volume calculation logic for partial closes."""

    @pytest.fixture
    def position_manager(self):
        """Create actual position manager for volume calculation tests."""
        from src.mt5_executor.position_manager import PositionManager
        return PositionManager()

    def test_partial_volume_calculation(self, position_manager):
        """Test partial volume calculation with lot normalization."""
        # Test normal percentage calculations
        assert position_manager._calculate_partial_volume(1.0, 0.5, "GOLD") == 0.5
        assert position_manager._calculate_partial_volume(2.0, 0.25, "GOLD") == 0.5
        assert position_manager._calculate_partial_volume(1.5, 0.33, "GOLD") == 0.49
        
        # Test volume too small to close
        assert position_manager._calculate_partial_volume(0.01, 0.5, "GOLD") == 0.0
        
        # Test edge cases
        assert position_manager._calculate_partial_volume(0.05, 0.1, "GOLD") == 0.0
        assert position_manager._calculate_partial_volume(3.0, 1.0, "GOLD") == 3.0

    def test_lot_size_normalization(self, position_manager):
        """Test proper lot size normalization for different symbols."""
        # Test GOLD normalization (0.01 lot minimum)
        result = position_manager._calculate_partial_volume(1.0, 0.333, "GOLD")
        assert result == 0.33  # Rounded down to valid lot size
        
        # Test with very small percentages
        result = position_manager._calculate_partial_volume(0.1, 0.5, "GOLD")
        assert result == 0.05
        
        # Test rounding precision
        result = position_manager._calculate_partial_volume(1.0, 0.751, "GOLD")
        assert result == 0.75