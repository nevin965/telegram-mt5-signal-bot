"""
Unit tests for MT5 connection manager with comprehensive mocking.
Tests connection pooling, validation, error handling, and recovery.
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, UTC
import json

from src.mt5_executor.connection import (
    MT5ConnectionManager,
    MT5Connection,
    TerminalInfo,
    AccountInfo,
    ConnectionHealth
)
from config.settings import MT5Settings


class TestMT5Connection:
    """Test cases for individual MT5 connections."""
    
    @pytest.fixture
    def mock_mt5_module(self):
        """Mock the MT5 module for testing."""
        mock_mt5 = Mock()
        mock_mt5.initialize = Mock(return_value=True)
        mock_mt5.login = Mock(return_value=True)
        mock_mt5.shutdown = Mock()
        mock_mt5.last_error = Mock(return_value=(0, "Success"))
        mock_mt5.account_info = Mock(return_value=Mock(
            login=12345,
            balance=10000.0,
            equity=10000.0,
            profit=0.0,
            margin=500.0,
            leverage=100,
            server="TestServer-Demo",
            currency="USD",
            company="Test Broker"
        ))
        
        with patch('src.mt5_executor.connection.mt5', mock_mt5):
            yield mock_mt5
    
    @pytest.fixture
    def connection(self, mock_mt5_module):
        """Create MT5Connection instance for testing."""
        return MT5Connection(connection_id=1)
    
    @pytest.mark.asyncio
    async def test_successful_connection(self, connection, mock_mt5_module):
        """Test successful MT5 connection establishment."""
        # Test connection
        result = await connection.connect(
            login=12345,
            password="test_password",
            server="TestServer-Demo"
        )
        
        # Verify connection succeeded
        assert result is True
        assert connection.connected is True
        assert connection.connection_time is not None
        assert connection.error_count == 0
        
        # Verify MT5 methods were called
        mock_mt5_module.initialize.assert_called_once()
        mock_mt5_module.login.assert_called_once_with(12345, "test_password", "TestServer-Demo")
    
    @pytest.mark.asyncio
    async def test_connection_initialization_failure(self, connection, mock_mt5_module):
        """Test MT5 initialization failure."""
        mock_mt5_module.initialize.return_value = False
        mock_mt5_module.last_error.return_value = (1, "Initialization failed")
        
        result = await connection.connect(12345, "test_password", "TestServer-Demo")
        
        assert result is False
        assert connection.connected is False
        assert connection.error_count == 0  # Initialization error doesn't increment error count
    
    @pytest.mark.asyncio
    async def test_connection_login_failure(self, connection, mock_mt5_module):
        """Test MT5 login failure."""
        mock_mt5_module.login.return_value = False
        mock_mt5_module.last_error.return_value = (2, "Invalid credentials")
        
        result = await connection.connect(12345, "wrong_password", "TestServer-Demo")
        
        assert result is False
        assert connection.connected is False
        mock_mt5_module.shutdown.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_connection_exception_handling(self, connection, mock_mt5_module):
        """Test exception handling during connection."""
        mock_mt5_module.initialize.side_effect = Exception("Connection error")
        
        result = await connection.connect(12345, "test_password", "TestServer-Demo")
        
        assert result is False
        assert connection.connected is False
        assert connection.error_count == 1
    
    @pytest.mark.asyncio
    async def test_disconnect(self, connection, mock_mt5_module):
        """Test connection disconnection."""
        # First connect
        await connection.connect(12345, "test_password", "TestServer-Demo")
        assert connection.connected is True
        
        # Then disconnect
        await connection.disconnect()
        assert connection.connected is False
        mock_mt5_module.shutdown.assert_called()
    
    @pytest.mark.asyncio
    async def test_ping_healthy_connection(self, connection, mock_mt5_module):
        """Test ping on healthy connection."""
        await connection.connect(12345, "test_password", "TestServer-Demo")
        
        health = await connection.ping()
        
        assert isinstance(health, ConnectionHealth)
        assert health.is_healthy is True
        assert health.connected is True
        assert health.error_message is None
        assert health.response_time_ms is not None
    
    @pytest.mark.asyncio
    async def test_ping_disconnected_connection(self, connection):
        """Test ping on disconnected connection."""
        health = await connection.ping()
        
        assert health.is_healthy is False
        assert health.connected is False
        assert health.error_message == "Not connected"


class TestMT5ConnectionManager:
    """Test cases for MT5 connection manager."""
    
    @pytest.fixture
    def mock_mt5_settings(self):
        """Mock MT5Settings for testing."""
        return MT5Settings(
            login=12345,
            password="test_password",
            server="TestServer-Demo",
            timeout_seconds=30,
            max_connections=3,
            reconnect_delay=2
        )
    
    @pytest.fixture
    def mock_settings(self, mock_mt5_settings):
        """Mock settings.get_mt5_settings()."""
        with patch('src.mt5_executor.connection.settings') as mock_settings:
            mock_settings.get_mt5_settings.return_value = mock_mt5_settings
            yield mock_settings
    
    @pytest.fixture
    def mock_mt5_module(self):
        """Mock the MT5 module."""
        mock_mt5 = Mock()
        mock_mt5.initialize = Mock(return_value=True)
        mock_mt5.login = Mock(return_value=True)
        mock_mt5.shutdown = Mock()
        mock_mt5.last_error = Mock(return_value=(0, "Success"))
        
        # Mock account info
        mock_account = Mock(
            login=12345,
            trade_mode=1,  # Hedge account
            leverage=100,
            limit_orders=100,
            margin_so_mode=0,
            trade_allowed=True,
            trade_expert=True,
            margin_mode=0,
            currency_digits=2,
            balance=10000.0,
            credit=0.0,
            profit=0.0,
            equity=10000.0,
            margin=500.0,
            margin_free=9500.0,
            margin_level=2000.0,
            margin_so_call=50.0,
            margin_so_so=25.0,
            name="Test Account",
            server="TestServer-Demo",
            currency="USD",
            company="Test Broker"
        )
        mock_mt5.account_info = Mock(return_value=mock_account)
        
        # Mock terminal info
        mock_terminal = Mock(
            name="MetaTrader 5",
            build=3980,
            version="5.00 build 3980",
            connected=True,
            trade_allowed=True,
            tradeapi_disabled=False,
            maxbars=100000,
            mqid=True,
            dlls_allowed=True,
            mail_enabled=True,
            ftp_enabled=False,
            notifications_enabled=True
        )
        mock_mt5.terminal_info = Mock(return_value=mock_terminal)
        
        # Mock symbol tick
        mock_tick = Mock(
            time=int(datetime.now(UTC).timestamp()),
            bid=2535.50,
            ask=2535.70,
            last=2535.60,
            volume=100
        )
        mock_mt5.symbol_info_tick = Mock(return_value=mock_tick)
        
        with patch('src.mt5_executor.connection.mt5', mock_mt5):
            yield mock_mt5
    
    @pytest.fixture
    def connection_manager(self, mock_settings, mock_mt5_module):
        """Create MT5ConnectionManager instance for testing."""
        # Mock asyncio.create_task to avoid actual initialization during testing
        with patch('asyncio.create_task') as mock_task:
            manager = MT5ConnectionManager(max_connections=3)
            # Manually set initialized to avoid initialization task
            manager._initialized = True
            return manager
    
    @pytest.mark.asyncio
    async def test_connection_manager_initialization(self, mock_settings, mock_mt5_module):
        """Test connection manager initialization with lazy loading."""
        manager = MT5ConnectionManager(max_connections=2)
        
        # Verify settings were loaded
        assert manager.login == 12345
        assert manager.server == "TestServer-Demo"
        assert manager.max_connections == 2
        
        # Verify lazy initialization - pool not initialized yet
        assert manager._initialized is False
        assert manager._initialization_task is None
        
        # Trigger initialization by calling _ensure_initialized
        await manager._ensure_initialized()
        
        # Now verify pool is initialized
        assert manager._initialized is True
        assert len(manager.connections) > 0
    
    @pytest.mark.asyncio
    async def test_get_connection_context_manager(self, connection_manager, mock_mt5_module):
        """Test connection acquisition via context manager."""
        # Manually add a connection to the pool
        test_connection = MT5Connection(1)
        test_connection.connected = True
        connection_manager.connections[1] = test_connection
        await connection_manager.connection_queue.put(test_connection)
        
        # Trigger lazy initialization
        connection_manager._initialized = True  # Skip actual init for this test
        
        async with connection_manager.get_connection() as conn:
            assert conn is not None
            assert isinstance(conn, MT5Connection)
            assert conn.connected is True
    
    @pytest.mark.asyncio
    async def test_get_connection_timeout(self, connection_manager):
        """Test connection timeout when no connections available."""
        connection_manager.timeout_seconds = 0.1  # Very short timeout
        
        with pytest.raises(RuntimeError, match="Timeout waiting for MT5 connection"):
            async with connection_manager.get_connection():
                pass
    
    @pytest.mark.asyncio
    async def test_validate_account_success(self, connection_manager, mock_mt5_module):
        """Test successful account validation."""
        # Mock the connection context manager
        mock_connection = Mock()
        mock_connection.connected = True
        
        with patch.object(connection_manager, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            with patch.object(connection_manager, 'get_account_info') as mock_account_info, \
                 patch.object(connection_manager, 'get_terminal_info') as mock_terminal_info:
                
                # Mock return values
                mock_account_info.return_value = AccountInfo(
                    login=12345, trade_mode=1, leverage=100, limit_orders=100,
                    margin_so_mode=0, trade_allowed=True, trade_expert=True,
                    margin_mode=0, currency_digits=2, balance=10000.0,
                    credit=0.0, profit=0.0, equity=10000.0, margin=500.0,
                    margin_free=9500.0, margin_level=2000.0, margin_so_call=50.0,
                    margin_so_so=25.0, name="Test Account", server="TestServer-Demo",
                    currency="USD", company="Test Broker"
                )
                
                mock_terminal_info.return_value = TerminalInfo(
                    name="MetaTrader 5", build=3980, version="5.00 build 3980",
                    connected=True, trade_allowed=True, tradeapi_disabled=False,
                    maxbars=100000, mqid=True, dlls_allowed=True,
                    mail_enabled=True, ftp_enabled=False, notifications_enabled=True
                )
                
                result = await connection_manager.validate_account()
                
                assert result['valid'] is True
                assert result['account_type'] == 'hedge'
                assert result['permissions']['trade_allowed'] is True
                assert result['permissions']['automated_trading'] is True
                assert result['balance_check'] is True
                assert result['broker_info']['company'] == "Test Broker"
    
    @pytest.mark.asyncio
    async def test_validate_account_insufficient_balance(self, connection_manager, mock_mt5_module):
        """Test account validation with insufficient balance."""
        mock_connection = Mock()
        mock_connection.connected = True
        
        with patch.object(connection_manager, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            with patch.object(connection_manager, 'get_account_info') as mock_account_info, \
                 patch.object(connection_manager, 'get_terminal_info') as mock_terminal_info:
                
                # Account with insufficient balance
                mock_account_info.return_value = AccountInfo(
                    login=12345, trade_mode=1, leverage=100, limit_orders=100,
                    margin_so_mode=0, trade_allowed=True, trade_expert=True,
                    margin_mode=0, currency_digits=2, balance=50.0,  # Below minimum
                    credit=0.0, profit=0.0, equity=50.0, margin=0.0,
                    margin_free=50.0, margin_level=0.0, margin_so_call=50.0,
                    margin_so_so=25.0, name="Test Account", server="TestServer-Demo",
                    currency="USD", company="Test Broker"
                )
                
                mock_terminal_info.return_value = TerminalInfo(
                    name="MetaTrader 5", build=3980, version="5.00 build 3980",
                    connected=True, trade_allowed=True, tradeapi_disabled=False,
                    maxbars=100000, mqid=True, dlls_allowed=True,
                    mail_enabled=True, ftp_enabled=False, notifications_enabled=True
                )
                
                result = await connection_manager.validate_account()
                
                assert result['valid'] is False
                assert result['balance_check'] is False
                assert result['balance'] == 50.0
                assert result['minimum_balance'] == 100.0
    
    @pytest.mark.asyncio
    async def test_check_time_synchronization(self, connection_manager, mock_mt5_module):
        """Test time synchronization check."""
        mock_connection = Mock()
        mock_connection.connected = True
        
        with patch.object(connection_manager, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            # Set up mock tick with current time
            current_time = datetime.now(UTC)
            mock_tick = Mock(time=int(current_time.timestamp()))
            mock_mt5_module.symbol_info_tick.return_value = mock_tick
            
            result = await connection_manager.check_time_synchronization()
            
            assert result['synchronized'] is True
            assert result['error'] is None
            assert result['time_diff_seconds'] <= 60  # Should be very small
    
    @pytest.mark.asyncio
    async def test_check_connection_health(self, connection_manager):
        """Test connection pool health check."""
        # Add mock connections to the pool
        conn1 = Mock()
        conn1.ping = AsyncMock(return_value=ConnectionHealth(
            is_healthy=True, connected=True, last_ping=datetime.now(UTC),
            error_message=None, response_time_ms=50.0
        ))
        conn1.last_used = datetime.now(UTC)
        conn1.error_count = 0
        
        conn2 = Mock()
        conn2.ping = AsyncMock(return_value=ConnectionHealth(
            is_healthy=False, connected=False, last_ping=None,
            error_message="Connection lost", response_time_ms=None
        ))
        conn2.last_used = datetime.now(UTC)
        conn2.error_count = 3
        
        connection_manager.connections = {1: conn1, 2: conn2}
        
        health_status = await connection_manager.check_connection_health()
        
        assert health_status['pool_size'] == 2
        assert health_status['max_connections'] == 3
        assert health_status['active_connections'] == 1
        assert health_status['healthy_connections'] == 1
        assert len(health_status['connections']) == 2
    
    @pytest.mark.asyncio
    async def test_detect_terminal_status_running(self, connection_manager, mock_mt5_module):
        """Test terminal detection when MT5 is running."""
        with patch('psutil.process_iter') as mock_process_iter:
            # Mock MT5 process
            mock_process = Mock()
            mock_process.info = {
                'pid': 1234,
                'name': 'terminal64.exe',
                'exe': 'C:\\Program Files\\MetaTrader 5\\terminal64.exe',
                'status': 'running'
            }
            mock_process_iter.return_value = [mock_process]
            
            # Mock platform detection
            with patch('platform.system', return_value='Windows'):
                result = await connection_manager.detect_mt5_terminal_status()
                
                assert result['status'] == 'running'
                assert result['processes_found'] == 1
                assert result['module_available'] is True
                assert result['can_initialize'] is True
                assert result['error'] is None
    
    @pytest.mark.asyncio
    async def test_detect_terminal_status_not_running(self, connection_manager, mock_mt5_module):
        """Test terminal detection when MT5 is not running."""
        with patch('psutil.process_iter', return_value=[]):  # No MT5 processes
            with patch('platform.system', return_value='Windows'):
                result = await connection_manager.detect_mt5_terminal_status()
                
                assert result['status'] == 'not_running'
                assert result['processes_found'] == 0
                assert 'Please start MetaTrader 5' in result['guidance']
    
    @pytest.mark.asyncio
    async def test_validate_credentials_basic_validation(self, connection_manager):
        """Test basic credential validation without connection test."""
        result = await connection_manager.validate_credentials(test_connection=False)
        
        assert result['valid'] is True
        assert result['connection_tested'] is False
        assert len(result['errors']) == 0
    
    @pytest.mark.asyncio
    async def test_validate_credentials_invalid_login(self, connection_manager):
        """Test credential validation with invalid login."""
        connection_manager.login = -1  # Invalid login
        
        result = await connection_manager.validate_credentials(test_connection=False)
        
        assert result['valid'] is False
        assert result['connection_tested'] is False
        assert any('Invalid login' in error for error in result['errors'])
    
    @pytest.mark.asyncio
    async def test_graceful_degradation_full_mode(self, connection_manager):
        """Test graceful degradation in full operation mode."""
        with patch.object(connection_manager, 'detect_mt5_terminal_status') as mock_terminal, \
             patch.object(connection_manager, 'validate_credentials') as mock_credentials:
            
            mock_terminal.return_value = {'status': 'running', 'guidance': 'All good'}
            mock_credentials.return_value = {'valid': True}
            
            result = await connection_manager.graceful_degradation()
            
            assert result['mode'] == 'full'
            assert 'full_trading' in result['available_operations']
            assert len(result['unavailable_operations']) == 0
    
    @pytest.mark.asyncio
    async def test_graceful_degradation_offline_mode(self, connection_manager):
        """Test graceful degradation in offline mode."""
        with patch.object(connection_manager, 'detect_mt5_terminal_status') as mock_terminal, \
             patch.object(connection_manager, 'validate_credentials') as mock_credentials:
            
            mock_terminal.return_value = {'status': 'not_running', 'guidance': 'Start MT5'}
            mock_credentials.return_value = {'valid': False}
            
            result = await connection_manager.graceful_degradation()
            
            assert result['mode'] == 'offline'
            assert len(result['available_operations']) == 0
            assert 'all_mt5_operations' in result['unavailable_operations']
    
    @pytest.mark.asyncio
    async def test_handle_connection_timeout(self, connection_manager):
        """Test connection timeout handling."""
        with patch.object(connection_manager, 'detect_mt5_terminal_status') as mock_terminal:
            mock_terminal.return_value = {
                'status': 'running',
                'processes_found': 1,
                'guidance': 'Terminal is running'
            }
            
            # This should not raise an exception, just log
            await connection_manager.handle_connection_timeout('test_operation', 30)
            
            mock_terminal.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_reconnect_connection_success(self, connection_manager, mock_mt5_module):
        """Test successful connection reconnection."""
        mock_connection = Mock()
        mock_connection.disconnect = AsyncMock()
        mock_connection.connect = AsyncMock(return_value=True)
        mock_connection.id = 1
        
        result = await connection_manager._reconnect_connection(mock_connection)
        
        assert result is True
        mock_connection.disconnect.assert_called_once()
        mock_connection.connect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_reconnect_connection_failure(self, connection_manager, mock_mt5_module):
        """Test failed connection reconnection."""
        mock_connection = Mock()
        mock_connection.disconnect = AsyncMock()
        mock_connection.connect = AsyncMock(return_value=False)
        mock_connection.id = 1
        
        result = await connection_manager._reconnect_connection(mock_connection)
        
        assert result is False
        # Should attempt multiple times (3 retries)
        assert mock_connection.connect.call_count == 3
    
    @pytest.mark.asyncio
    async def test_shutdown(self, connection_manager):
        """Test connection manager shutdown."""
        # Add mock connections
        mock_conn1 = Mock()
        mock_conn1.disconnect = AsyncMock()
        mock_conn2 = Mock()
        mock_conn2.disconnect = AsyncMock()
        
        connection_manager.connections = {1: mock_conn1, 2: mock_conn2}
        
        await connection_manager.shutdown()
        
        assert connection_manager._shutdown is True
        assert len(connection_manager.connections) == 0
        mock_conn1.disconnect.assert_called_once()
        mock_conn2.disconnect.assert_called_once()


class TestMT5ErrorHandling:
    """Test cases for MT5 error handling and recovery scenarios."""
    
    @pytest.fixture
    def mock_settings(self):
        """Mock settings for error testing."""
        mock_settings = Mock()
        mock_settings.get_mt5_settings.return_value = MT5Settings(
            login=12345,
            password="test_password",
            server="TestServer-Demo",
            timeout_seconds=30,
            max_connections=3,
            reconnect_delay=2
        )
        return mock_settings
    
    @pytest.mark.asyncio
    async def test_mt5_module_not_available(self, mock_settings):
        """Test behavior when MT5 module is not available."""
        with patch('src.mt5_executor.connection.mt5', None), \
             patch('src.mt5_executor.connection.settings', mock_settings):
            
            connection = MT5Connection(1)
            
            with pytest.raises(RuntimeError, match="MetaTrader5 module not available"):
                await connection.connect(12345, "password", "server")
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self, mock_settings):
        """Test circuit breaker integration with MT5 operations."""
        mock_mt5 = Mock()
        mock_mt5.initialize = Mock(return_value=True)
        mock_mt5.login = Mock(return_value=True)
        mock_mt5.account_info = Mock(side_effect=Exception("Connection lost"))
        
        with patch('src.mt5_executor.connection.mt5', mock_mt5), \
             patch('src.mt5_executor.connection.settings', mock_settings), \
             patch('asyncio.create_task'):
            
            manager = MT5ConnectionManager()
            manager._initialized = True
            
            # Mock connection context
            mock_connection = Mock()
            mock_connection.connected = True
            
            with patch.object(manager, 'get_connection') as mock_get_conn:
                mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
                mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
                
                # First call should fail and trigger circuit breaker
                with pytest.raises(Exception, match="Connection lost"):
                    await manager.get_account_info()
                
                # Verify circuit breaker is attached to the method
                assert hasattr(manager.get_account_info, 'circuit_breaker')


@pytest.mark.integration
class TestMT5Integration:
    """Integration tests for MT5 connection (require actual MT5 setup)."""
    
    @pytest.mark.skip(reason="Requires actual MT5 terminal for integration testing")
    async def test_real_mt5_connection(self):
        """Test with real MT5 connection - skipped by default."""
        # This would test with actual MT5 terminal
        # Only run when MT5 is available and configured
        pass
    
    @pytest.mark.skip(reason="Requires demo account for integration testing")
    async def test_demo_account_validation(self):
        """Test account validation with real demo account - skipped by default."""
        # This would test with actual demo account
        pass


# Test fixtures for MT5 responses
@pytest.fixture
def mt5_account_response():
    """Sample MT5 account info response."""
    return {
        "login": 12345,
        "trade_mode": 1,
        "leverage": 100,
        "balance": 10000.0,
        "equity": 10000.0,
        "margin": 500.0,
        "currency": "USD",
        "server": "TestServer-Demo",
        "company": "Test Broker"
    }


@pytest.fixture
def mt5_terminal_response():
    """Sample MT5 terminal info response."""
    return {
        "name": "MetaTrader 5",
        "build": 3980,
        "connected": True,
        "trade_allowed": True,
        "dlls_allowed": True
    }


@pytest.fixture
def mt5_error_responses():
    """Sample MT5 error responses for testing."""
    return {
        "invalid_credentials": (64, "Invalid account"),
        "terminal_not_running": (4, "MT5 terminal not found"),
        "network_error": (5, "Network connection failed"),
        "trading_disabled": (133, "Trading is disabled")
    }