"""
Integration tests for complete close processing flow.

Tests end-to-end close processing from Telegram message detection
to MT5 execution and database updates.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from typing import Dict, Any

from src.risk_manager.close_processor import CloseProcessor, CloseAction
from src.correlation_engine.correlator import CorrelationEngine, TelegramMessage
from src.mt5_executor.position_manager import PositionManager, MT5Result
from src.database.repository import RepositoryFactory, DatabaseManager
from src.database.models import Position, Signal, PositionStatus, UpdateType


@pytest.fixture
async def database_manager():
    """Create in-memory database manager for testing."""
    db_manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await db_manager.initialize()
    return db_manager


@pytest.fixture
def repo_factory(database_manager):
    """Create repository factory with test database."""
    return RepositoryFactory(database_manager)


@pytest.fixture
def mock_correlation_engine():
    """Create mock correlation engine."""
    return AsyncMock(spec=CorrelationEngine)


@pytest.fixture
def mock_position_manager():
    """Create mock position manager with MT5 operations."""
    manager = AsyncMock(spec=PositionManager)
    return manager


@pytest.fixture
def close_processor(mock_correlation_engine, mock_position_manager, repo_factory):
    """Create close processor with mocked dependencies."""
    return CloseProcessor(
        correlation_engine=mock_correlation_engine,
        position_manager=mock_position_manager,
        repo_factory=repo_factory
    )


@pytest.fixture
async def test_signal_and_position(repo_factory):
    """Create test signal and position in database."""
    signal_repo = repo_factory.get_signal_repository()
    position_repo = repo_factory.get_position_repository()
    
    # Create signal
    signal_data = {
        'telegram_message_id': 12345,
        'telegram_chat_id': 67890,
        'sender': 'test_trader',
        'timestamp': datetime.now(timezone.utc).replace(tzinfo=None),
        'raw_text': 'BUY GOLD at 1950',
        'parsed_action': 'BUY',
        'symbol': 'GOLD',
        'entry_price': 1950.0,
        'confidence_score': 0.9,
        'parser_type': 'LLM',
        'status': 'EXECUTED'
    }
    signal_id = await signal_repo.save_signal(signal_data)
    
    # Create position
    position_data = {
        'signal_id': signal_id,
        'mt5_ticket': 123456,
        'open_time': datetime.now(timezone.utc).replace(tzinfo=None),
        'open_price': 1950.0,
        'volume': 1.0,
        'status': PositionStatus.OPEN
    }
    position = await position_repo.create(**position_data)
    
    # Load signal relationship
    signal = await signal_repo.get_by_id(signal_id)
    position.signal = signal
    
    return signal, position


class TestFullCloseIntegration:
    """Test complete full close flow integration."""

    @pytest.mark.asyncio
    async def test_full_close_success_flow(
        self,
        close_processor,
        mock_correlation_engine,
        mock_position_manager,
        test_signal_and_position,
        repo_factory
    ):
        """Test successful full close from message to database update."""
        signal, position = test_signal_and_position
        
        # Create close message
        close_message = TelegramMessage(
            telegram_message_id=54321,
            telegram_chat_id=67890,
            sender='test_trader',
            timestamp=datetime.now(),
            raw_text='CLÔTUREZ position',
            reply_to_message_id=12345
        )
        
        # Mock correlation engine to find position
        mock_correlation_engine.correlate_message.return_value = position
        
        # Mock successful MT5 close
        mock_close_result = MT5Result(
            success=True,
            ticket=123456,
            operation="close_position_full",
            volume_closed=1.0,
            close_price=1955.0,
            profit=50.0,
            retcode=10009  # TRADE_RETCODE_DONE
        )
        mock_position_manager.close_position_full.return_value = mock_close_result
        
        # Process close signal
        result = await close_processor.process_close_signal(close_message)
        
        # Verify processing result
        assert result['success'] is True
        assert result['position_id'] == position.id
        assert result['ticket'] == 123456
        assert result['volume_closed'] == 1.0
        assert result['close_price'] == 1955.0
        assert result['profit'] == 50.0
        assert 'execution_time_ms' in result
        
        # Verify MT5 operation was called correctly
        mock_position_manager.close_position_full.assert_called_once_with(123456)
        
        # Verify database was updated
        position_repo = repo_factory.get_position_repository()
        updated_position = await position_repo.get_by_id(position.id)
        assert updated_position.status == PositionStatus.CLOSED
        assert updated_position.close_price == 1955.0
        assert updated_position.profit == 50.0
        assert updated_position.volume == 0.0
        assert updated_position.close_time is not None
        
        # Verify audit trail was created
        update_repo = repo_factory.get_position_update_repository()
        updates = await update_repo.find_by_filters(position_id=position.id)
        assert len(updates) > 0
        
        close_update = next((u for u in updates if u.update_type == UpdateType.FULL_CLOSE), None)
        assert close_update is not None
        assert close_update.success is True
        assert close_update.field_name == "status"
        assert close_update.old_value == "OPEN"
        assert close_update.new_value == "0.0"

    @pytest.mark.asyncio
    async def test_full_close_mt5_failure(
        self,
        close_processor,
        mock_correlation_engine,
        mock_position_manager,
        test_signal_and_position,
        repo_factory
    ):
        """Test full close handling when MT5 operation fails."""
        signal, position = test_signal_and_position
        
        # Create close message
        close_message = TelegramMessage(
            telegram_message_id=54321,
            telegram_chat_id=67890,
            sender='test_trader',
            timestamp=datetime.now(),
            raw_text='FERMEZ position',
            reply_to_message_id=12345
        )
        
        # Mock correlation engine to find position
        mock_correlation_engine.correlate_message.return_value = position
        
        # Mock failed MT5 close
        mock_close_result = MT5Result(
            success=False,
            ticket=123456,
            operation="close_position_full",
            error_message="Market is closed",
            retcode=10018  # TRADE_RETCODE_MARKET_CLOSED
        )
        mock_position_manager.close_position_full.return_value = mock_close_result
        
        # Process close signal
        result = await close_processor.process_close_signal(close_message)
        
        # Verify processing result shows failure
        assert result['success'] is False
        assert result['error'] == "Market is closed"
        assert result['position_id'] == position.id
        assert result['ticket'] == 123456
        
        # Verify database position was NOT updated
        position_repo = repo_factory.get_position_repository()
        updated_position = await position_repo.get_by_id(position.id)
        assert updated_position.status == PositionStatus.OPEN  # Still open
        assert updated_position.close_price is None
        assert updated_position.close_time is None


class TestPartialCloseIntegration:
    """Test complete partial close flow integration."""

    @pytest.mark.asyncio
    async def test_partial_close_success_flow(
        self,
        close_processor,
        mock_correlation_engine,
        mock_position_manager,
        test_signal_and_position,
        repo_factory
    ):
        """Test successful partial close from message to database update."""
        signal, position = test_signal_and_position
        
        # Create partial close message
        close_message = TelegramMessage(
            telegram_message_id=54321,
            telegram_chat_id=67890,
            sender='test_trader',
            timestamp=datetime.now(),
            raw_text='FERMEZ 50% de la position',
            reply_to_message_id=12345
        )
        
        # Mock correlation engine to find position
        mock_correlation_engine.correlate_message.return_value = position
        
        # Mock successful MT5 partial close
        mock_close_result = MT5Result(
            success=True,
            ticket=123456,
            operation="close_position_partial",
            volume_closed=0.5,
            close_price=1955.0,
            profit=25.0,
            retcode=10009  # TRADE_RETCODE_DONE
        )
        mock_position_manager.close_position_partial.return_value = mock_close_result
        
        # Process close signal
        result = await close_processor.process_close_signal(close_message)
        
        # Verify processing result
        assert result['success'] is True
        assert result['position_id'] == position.id
        assert result['ticket'] == 123456
        assert result['percentage'] == 0.5
        assert result['volume_closed'] == 0.5
        assert result['close_price'] == 1955.0
        assert result['profit'] == 25.0
        
        # Verify MT5 operation was called correctly
        mock_position_manager.close_position_partial.assert_called_once_with(123456, 0.5)
        
        # Verify database was updated for partial close
        position_repo = repo_factory.get_position_repository()
        updated_position = await position_repo.get_by_id(position.id)
        assert updated_position.status == PositionStatus.OPEN  # Still open
        assert updated_position.volume == 0.5  # Reduced volume
        assert updated_position.profit == 25.0  # Updated profit
        
        # Verify audit trail was created
        update_repo = repo_factory.get_position_update_repository()
        updates = await update_repo.find_by_filters(position_id=position.id)
        assert len(updates) > 0
        
        partial_update = next((u for u in updates if u.update_type == UpdateType.PARTIAL_CLOSE), None)
        assert partial_update is not None
        assert partial_update.success is True
        assert partial_update.field_name == "volume"


class TestCloseAllIntegration:
    """Test close all functionality integration."""

    @pytest.mark.asyncio
    async def test_close_all_gold_success(
        self,
        close_processor,
        mock_correlation_engine,
        mock_position_manager,
        repo_factory
    ):
        """Test successful close all GOLD positions."""
        # Create multiple GOLD positions
        signal_repo = repo_factory.get_signal_repository()
        position_repo = repo_factory.get_position_repository()
        
        # Create signals and positions
        positions = []
        for i in range(3):
            signal_data = {
                'telegram_message_id': 12345 + i,
                'telegram_chat_id': 67890,
                'sender': 'test_trader',
                'timestamp': datetime.now(timezone.utc).replace(tzinfo=None),
                'raw_text': f'BUY GOLD at {1950 + i}',
                'parsed_action': 'BUY',
                'symbol': 'GOLD',
                'entry_price': 1950.0 + i,
                'confidence_score': 0.9,
                'parser_type': 'LLM',
                'status': 'EXECUTED'
            }
            signal_id = await signal_repo.save_signal(signal_data)
            
            position_data = {
                'signal_id': signal_id,
                'mt5_ticket': 123456 + i,
                'open_time': datetime.now(timezone.utc).replace(tzinfo=None),
                'open_price': 1950.0 + i,
                'volume': 1.0,
                'status': PositionStatus.OPEN
            }
            position = await position_repo.create(**position_data)
            signal = await signal_repo.get_by_id(signal_id)
            position.signal = signal
            positions.append(position)
        
        # Create close all message
        close_message = TelegramMessage(
            telegram_message_id=99999,
            telegram_chat_id=67890,
            sender='test_trader',
            timestamp=datetime.now(),
            raw_text='CLOSE ALL GOLD positions',
            reply_to_message_id=None
        )
        
        # Mock successful MT5 closes for all positions
        def mock_close_full(ticket):
            return MT5Result(
                success=True,
                ticket=ticket,
                operation="close_position_full",
                volume_closed=1.0,
                close_price=1955.0,
                profit=50.0,
                retcode=10009
            )
        
        mock_position_manager.close_position_full.side_effect = mock_close_full
        
        # Process close all signal
        result = await close_processor.process_close_signal(close_message)
        
        # Verify processing result
        assert result['success'] is True
        assert result['positions_closed'] == 3
        assert result['total_positions'] == 3
        assert result['success_rate'] == 1.0
        assert len(result['failures']) == 0
        
        # Verify all positions were closed
        for position in positions:
            updated_position = await position_repo.get_by_id(position.id)
            assert updated_position.status == PositionStatus.CLOSED

    @pytest.mark.asyncio
    async def test_close_all_with_partial_failures(
        self,
        close_processor,
        mock_correlation_engine,
        mock_position_manager,
        repo_factory
    ):
        """Test close all with some positions failing to close."""
        # Create multiple positions (similar setup as above)
        signal_repo = repo_factory.get_signal_repository()
        position_repo = repo_factory.get_position_repository()
        
        positions = []
        for i in range(3):
            signal_data = {
                'telegram_message_id': 12345 + i,
                'telegram_chat_id': 67890,
                'sender': 'test_trader',
                'timestamp': datetime.now(timezone.utc).replace(tzinfo=None),
                'raw_text': f'BUY GOLD at {1950 + i}',
                'parsed_action': 'BUY',
                'symbol': 'GOLD',
                'entry_price': 1950.0 + i,
                'confidence_score': 0.9,
                'parser_type': 'LLM',
                'status': 'EXECUTED'
            }
            signal_id = await signal_repo.save_signal(signal_data)
            
            position_data = {
                'signal_id': signal_id,
                'mt5_ticket': 123456 + i,
                'open_time': datetime.now(timezone.utc).replace(tzinfo=None),
                'open_price': 1950.0 + i,
                'volume': 1.0,
                'status': PositionStatus.OPEN
            }
            position = await position_repo.create(**position_data)
            signal = await signal_repo.get_by_id(signal_id)
            position.signal = signal
            positions.append(position)
        
        # Create close all message
        close_message = TelegramMessage(
            telegram_message_id=99999,
            telegram_chat_id=67890,
            sender='test_trader',
            timestamp=datetime.now(),
            raw_text='FERMEZ TOUT GOLD',
            reply_to_message_id=None
        )
        
        # Mock mixed success/failure MT5 closes
        def mock_close_full(ticket):
            if ticket == 123456:  # First position fails
                return MT5Result(
                    success=False,
                    ticket=ticket,
                    operation="close_position_full",
                    error_message="Position locked",
                    retcode=10031
                )
            else:  # Other positions succeed
                return MT5Result(
                    success=True,
                    ticket=ticket,
                    operation="close_position_full",
                    volume_closed=1.0,
                    close_price=1955.0,
                    profit=50.0,
                    retcode=10009
                )
        
        mock_position_manager.close_position_full.side_effect = mock_close_full
        
        # Process close all signal
        result = await close_processor.process_close_signal(close_message)
        
        # Verify processing result shows partial success
        assert result['success'] is False  # Less than 80% success rate
        assert result['positions_closed'] == 2
        assert result['total_positions'] == 3
        assert result['success_rate'] == 2/3
        assert len(result['failures']) == 1
        assert result['failures'][0]['ticket'] == 123456
        assert "Position locked" in result['failures'][0]['error']


class TestPerformanceRequirements:
    """Test performance requirements for close processing."""

    @pytest.mark.asyncio
    async def test_close_processing_speed(
        self,
        close_processor,
        mock_correlation_engine,
        mock_position_manager,
        test_signal_and_position
    ):
        """Test that close processing completes within 3 seconds."""
        signal, position = test_signal_and_position
        
        # Create close message
        close_message = TelegramMessage(
            telegram_message_id=54321,
            telegram_chat_id=67890,
            sender='test_trader',
            timestamp=datetime.now(),
            raw_text='CLÔTUREZ',
            reply_to_message_id=12345
        )
        
        # Mock correlation and MT5 operations
        mock_correlation_engine.correlate_message.return_value = position
        mock_position_manager.close_position_full.return_value = MT5Result(
            success=True,
            ticket=123456,
            operation="close_position_full",
            volume_closed=1.0,
            close_price=1955.0,
            profit=50.0
        )
        
        # Measure processing time
        start_time = datetime.now()
        result = await close_processor.process_close_signal(close_message)
        end_time = datetime.now()
        
        execution_time_ms = (end_time - start_time).total_seconds() * 1000
        
        # Verify performance requirement (< 3 seconds = 3000ms)
        assert execution_time_ms < 3000
        assert result['success'] is True
        assert 'execution_time_ms' in result
        
        # The processor should also report its own execution time
        assert result['execution_time_ms'] < 3000