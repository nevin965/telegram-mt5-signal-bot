"""
Test fixtures for creating sample signals, positions, and messages.

Provides helper functions for generating test data consistently across unit and integration tests.
"""

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

from src.correlation_engine.correlator import TelegramMessage
from src.database.models import Position, PositionStatus


@dataclass
class TestPosition:
    """Test position data structure."""
    id: int
    mt5_ticket: Optional[int]
    open_price: Optional[float]
    current_sl: Optional[float]
    current_tp: Optional[float]
    profit: float
    volume: float
    status: PositionStatus = PositionStatus.OPEN
    
    @property
    def is_open(self) -> bool:
        return self.status == PositionStatus.OPEN


def create_test_message(
    message_id: int,
    text: str,
    sender: str = "test_trader",
    chat_id: int = 12345,
    reply_to: Optional[int] = None
) -> TelegramMessage:
    """
    Create a test Telegram message for break even testing.
    
    Args:
        message_id: Unique message ID
        text: Message text content
        sender: Message sender username
        chat_id: Telegram chat ID
        reply_to: Optional reply-to message ID
        
    Returns:
        TelegramMessage instance for testing
    """
    return TelegramMessage(
        telegram_message_id=message_id,
        telegram_chat_id=chat_id,
        sender=sender,
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
        raw_text=text,
        reply_to_message_id=reply_to
    )


def create_test_position(
    position_id: int,
    ticket: Optional[int] = None,
    entry_price: float = 1850.00,
    current_sl: Optional[float] = 1849.50,
    current_tp: Optional[float] = 1851.00,
    profit: float = 5.0,
    volume: float = 0.1,
    status: PositionStatus = PositionStatus.OPEN
) -> TestPosition:
    """
    Create a test position for break even testing.
    
    Args:
        position_id: Unique position ID
        ticket: MT5 ticket number (defaults to position_id + 1000)
        entry_price: Position entry price
        current_sl: Current stop-loss level
        current_tp: Current take-profit level
        profit: Current profit/loss
        volume: Position volume in lots
        status: Position status
        
    Returns:
        TestPosition instance for testing
    """
    if ticket is None:
        ticket = position_id + 1000
        
    return TestPosition(
        id=position_id,
        mt5_ticket=ticket,
        open_price=entry_price,
        current_sl=current_sl,
        current_tp=current_tp,
        profit=profit,
        volume=volume,
        status=status
    )


def create_break_even_test_scenarios():
    """
    Create comprehensive test scenarios for break even functionality.
    
    Returns:
        List of tuples containing (message, position, expected_result)
    """
    scenarios = []
    
    # Scenario 1: Standard BUY position break even
    scenarios.append((
        create_test_message(1001, "BREAK EVEN"),
        create_test_position(
            position_id=1,
            entry_price=1850.00,
            current_sl=1849.50,
            profit=10.0
        ),
        {
            'should_succeed': True,
            'expected_new_sl': 1850.01,
            'description': 'Standard BUY position break even'
        }
    ))
    
    # Scenario 2: SELL position break even
    scenarios.append((
        create_test_message(1002, "BE"),
        create_test_position(
            position_id=2,
            entry_price=1855.25,
            current_sl=1855.75,  # SL above entry for SELL
            profit=15.0
        ),
        {
            'should_succeed': True,
            'expected_new_sl': 1855.26,  # Entry + 1 pip
            'description': 'SELL position break even'
        }
    ))
    
    # Scenario 3: French break even signal
    scenarios.append((
        create_test_message(1003, "SÉCURISER"),
        create_test_position(
            position_id=3,
            entry_price=1840.50,
            current_sl=1839.00,
            profit=25.0
        ),
        {
            'should_succeed': True,
            'expected_new_sl': 1840.51,
            'description': 'French break even signal'
        }
    ))
    
    # Scenario 4: Position with no entry price (should fail)
    scenarios.append((
        create_test_message(1004, "BREAK EVEN"),
        create_test_position(
            position_id=4,
            entry_price=None,  # No entry price
            current_sl=1849.50,
            profit=0.0
        ),
        {
            'should_succeed': False,
            'expected_error': 'entry price not available',
            'description': 'Position without entry price'
        }
    ))
    
    # Scenario 5: Closed position (should fail)
    scenarios.append((
        create_test_message(1005, "SECURE"),
        create_test_position(
            position_id=5,
            entry_price=1845.00,
            current_sl=1844.50,
            profit=0.0,
            status=PositionStatus.CLOSED
        ),
        {
            'should_succeed': False,
            'expected_error': 'not open',
            'description': 'Closed position'
        }
    ))
    
    # Scenario 6: Position without MT5 ticket
    scenarios.append((
        create_test_message(1006, "MOVE SL"),
        create_test_position(
            position_id=6,
            ticket=None,  # No MT5 ticket
            entry_price=1850.00,
            current_sl=1849.50,
            profit=5.0
        ),
        {
            'should_succeed': False,
            'expected_error': 'no MT5 ticket',
            'description': 'Position without MT5 ticket'
        }
    ))
    
    # Scenario 7: SL already at break even level
    scenarios.append((
        create_test_message(1007, "BREAK EVEN"),
        create_test_position(
            position_id=7,
            entry_price=1850.00,
            current_sl=1850.01,  # Already at BE level
            profit=1.0
        ),
        {
            'should_succeed': False,
            'expected_error': 'already at break even level',
            'description': 'SL already at break even'
        }
    ))
    
    # Scenario 8: Large position volume
    scenarios.append((
        create_test_message(1008, "ENTRY+1"),
        create_test_position(
            position_id=8,
            entry_price=1855.75,
            current_sl=1854.00,
            profit=50.0,
            volume=5.0  # Large volume
        ),
        {
            'should_succeed': True,
            'expected_new_sl': 1855.76,
            'description': 'Large volume position'
        }
    ))
    
    # Scenario 9: Position in loss
    scenarios.append((
        create_test_message(1009, "PROTÉGER"),
        create_test_position(
            position_id=9,
            entry_price=1850.00,
            current_sl=1849.50,
            profit=-10.0  # In loss
        ),
        {
            'should_succeed': True,
            'expected_new_sl': 1850.01,
            'description': 'Position currently in loss'
        }
    ))
    
    # Scenario 10: Different entry price precision
    scenarios.append((
        create_test_message(1010, "SL ON ENTRY"),
        create_test_position(
            position_id=10,
            entry_price=1847.33,
            current_sl=1846.80,
            profit=8.0
        ),
        {
            'should_succeed': True,
            'expected_new_sl': 1847.34,
            'description': 'Entry price with different precision'
        }
    ))
    
    return scenarios


def create_correlation_test_scenarios():
    """
    Create test scenarios for message-position correlation testing.
    
    Returns:
        List of correlation test scenarios
    """
    scenarios = []
    
    # High confidence correlation
    scenarios.append({
        'message': create_test_message(2001, "BREAK EVEN", reply_to=1500),
        'position': create_test_position(1),
        'correlation_confidence': 1.0,
        'correlation_type': 'REPLY',
        'should_correlate': True,
        'description': 'High confidence reply correlation'
    })
    
    # Time-based correlation
    scenarios.append({
        'message': create_test_message(2002, "BE"),
        'position': create_test_position(2),
        'correlation_confidence': 0.80,
        'correlation_type': 'TIME_BASED',
        'should_correlate': True,
        'description': 'Time-based correlation'
    })
    
    # Low confidence correlation (should fail)
    scenarios.append({
        'message': create_test_message(2003, "SECURE"),
        'position': create_test_position(3),
        'correlation_confidence': 0.60,
        'correlation_type': 'TIME_BASED',
        'should_correlate': False,
        'description': 'Low confidence correlation'
    })
    
    # No correlation found
    scenarios.append({
        'message': create_test_message(2004, "BREAK EVEN"),
        'position': None,
        'correlation_confidence': 0.0,
        'correlation_type': None,
        'should_correlate': False,
        'description': 'No correlation found'
    })
    
    return scenarios


def create_performance_test_data():
    """
    Create test data for performance testing.
    
    Returns:
        Dictionary with performance test scenarios
    """
    return {
        'concurrent_requests': [
            create_test_message(3000 + i, "BREAK EVEN")
            for i in range(10)
        ],
        'positions': [
            create_test_position(100 + i, entry_price=1850.00 + i * 0.25)
            for i in range(10)
        ],
        'expected_processing_time_seconds': 2.0,
        'concurrent_request_count': 10
    }


def create_mt5_response_scenarios():
    """
    Create MT5 response scenarios for testing.
    
    Returns:
        Dictionary with MT5 response test data
    """
    return {
        'successful_modification': {
            'success': True,
            'retcode': 10009,  # TRADE_RETCODE_DONE
            'old_sl': 1849.50,
            'new_sl': 1850.01,
            'execution_time_ms': 150.0
        },
        'position_not_found': {
            'success': False,
            'error_message': 'Position not found or already closed',
            'retcode': None
        },
        'modification_rejected': {
            'success': False,
            'retcode': 10004,  # TRADE_RETCODE_REJECT
            'error_message': 'Request rejected',
            'execution_time_ms': 100.0
        },
        'invalid_stops': {
            'success': False,
            'retcode': 10016,  # TRADE_RETCODE_INVALID_STOPS
            'error_message': 'Invalid stops in request',
            'execution_time_ms': 80.0
        },
        'connection_error': {
            'success': False,
            'error_message': 'MT5 connection not available',
            'execution_time_ms': None
        }
    }