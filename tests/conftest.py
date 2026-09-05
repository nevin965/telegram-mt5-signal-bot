"""
Pytest configuration and shared fixtures for the test suite.
"""

import asyncio
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

# Test configuration
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def temp_log_dir(temp_dir: Path) -> Path:
    """Create a temporary logging directory."""
    log_dir = temp_dir / "logs"
    log_dir.mkdir()
    return log_dir


@pytest.fixture
def test_env_vars() -> dict[str, str]:
    """Provide test environment variables."""
    return {
        "TELEGRAM_API_ID": "12345",
        "TELEGRAM_API_HASH": "test_hash",
        "PHONE_NUMBER": "+1234567890",
        "OPENAI_API_KEY": "test_openai_key",
        "MT5_LOGIN": "12345",
        "MT5_PASSWORD": "test_password",
        "MT5_SERVER": "test_server",
        "DATABASE_URL": "sqlite+aiosqlite:///test.db",
        "DEV_MODE": "true",
        "LOG_LEVEL": "DEBUG",
    }


@pytest.fixture
def mock_logging_setup():
    """Mock logging setup for tests."""
    with pytest.MonkeyPatch.context() as m:
        mock_setup = Mock(
            return_value={
                "level": "DEBUG",
                "handlers": 3,
                "log_dir": "/tmp/test_logs",
                "files": ["app.log", "error.log", "trades.log"],
            }
        )
        m.setattr("config.logging_config.setup_logging", mock_setup)
        yield mock_setup


@pytest.fixture
def mock_logger():
    """Provide a mock logger for tests."""
    logger = Mock()
    logger.info = Mock()
    logger.error = Mock()
    logger.warning = Mock()
    logger.debug = Mock()
    return logger


@pytest.fixture
def sample_telegram_message():
    """Provide sample Telegram message data for testing."""
    return {
        "id": 12345,
        "date": "2025-08-12 10:30:00",
        "text": "🔥 GOLD SELL SIGNAL\n📈 Entry: 2535.50\n🎯 TP: 2515.50\n🛡️ SL: 2545.50",
        "chat_id": -1001234567890,
        "from_user": {"id": 987654321, "username": "signal_provider"},
    }


@pytest.fixture
def sample_signal_data():
    """Provide sample parsed signal data for testing."""
    return {
        "symbol": "XAUUSD",
        "action": "SELL",
        "entry_price": 2535.50,
        "take_profit": 2515.50,
        "stop_loss": 2545.50,
        "lot_size": 0.1,
        "signal_id": "test_signal_123",
        "timestamp": "2025-08-12T10:30:00Z",
    }


@pytest.fixture
def mock_mt5_connection():
    """Mock MetaTrader5 connection for testing."""
    mock_mt5 = Mock()
    mock_mt5.initialize = Mock(return_value=True)
    mock_mt5.login = Mock(return_value=True)
    mock_mt5.shutdown = Mock()
    mock_mt5.account_info = Mock(
        return_value=Mock(login=12345, balance=10000.0, equity=10000.0, profit=0.0, margin=0.0)
    )
    return mock_mt5


@pytest.fixture
def mock_telegram_client():
    """Mock Telegram client for testing."""
    client = AsyncMock()
    client.connect = AsyncMock(return_value=True)
    client.disconnect = AsyncMock()
    client.is_connected = Mock(return_value=True)
    client.get_me = AsyncMock(
        return_value=Mock(id=123456789, username="test_user", phone="1234567890")
    )
    return client


@pytest.fixture
def mock_database_session():
    """Mock database session for testing."""
    session = AsyncMock()
    session.add = Mock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.execute = AsyncMock()
    return session


# Pytest marks for test categorization
def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line("markers", "unit: mark test as unit test")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "external: mark test as requiring external services")
