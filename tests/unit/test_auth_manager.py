"""
Unit tests for AuthManager.
Tests complete authentication flow orchestration and health checks.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.telegram_client.auth_manager import AuthManager


class TestAuthManager:
    """Test cases for AuthManager."""

    @pytest.fixture
    def mock_telegram_client(self):
        """Mock TelegramClient for testing."""
        mock_client = AsyncMock()
        mock_client.initialize = AsyncMock(return_value=True)
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.disconnect = AsyncMock()
        mock_client.is_connected = AsyncMock(return_value=True)
        mock_client.is_authorized = AsyncMock(return_value=True)
        mock_client.client = AsyncMock()
        return mock_client

    @pytest.fixture
    def mock_session_manager(self):
        """Mock SessionManager for testing."""
        mock_session = AsyncMock()
        mock_session.session_exists = MagicMock(return_value=True)
        mock_session.validate_session = AsyncMock(return_value=True)
        mock_session.authenticate = AsyncMock(return_value=True)
        return mock_session

    @pytest.fixture
    def auth_manager(self, mock_telegram_client, mock_session_manager):
        """Create AuthManager instance with mocked dependencies."""
        with patch("src.telegram_client.auth_manager.TelegramClient", return_value=mock_telegram_client), \
             patch("src.telegram_client.auth_manager.SessionManager", return_value=mock_session_manager):
            manager = AuthManager("test_session")
            manager.telegram_client = mock_telegram_client
            manager.session_manager = mock_session_manager
            return manager

    @pytest.mark.asyncio
    async def test_startup_authentication_success_existing_session(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test successful startup authentication with existing valid session."""
        mock_telegram_client.initialize.return_value = True
        mock_telegram_client.connect.return_value = True
        
        with patch.object(auth_manager, '_validate_existing_session', return_value=True):
            result = await auth_manager.startup_authentication()
            
            assert result is True
            assert auth_manager._is_authenticated is True
            mock_telegram_client.initialize.assert_called_once()
            mock_telegram_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_authentication_success_new_authentication(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test successful startup authentication with new authentication."""
        mock_telegram_client.initialize.return_value = True
        mock_telegram_client.connect.return_value = True
        mock_session_manager.authenticate.return_value = True
        
        with patch.object(auth_manager, '_validate_existing_session', return_value=False):
            result = await auth_manager.startup_authentication()
            
            assert result is True
            assert auth_manager._is_authenticated is True
            mock_session_manager.authenticate.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_authentication_initialize_fails(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test startup authentication when client initialization fails."""
        mock_telegram_client.initialize.return_value = False
        
        result = await auth_manager.startup_authentication()
        
        assert result is False
        assert auth_manager._is_authenticated is False

    @pytest.mark.asyncio
    async def test_startup_authentication_connect_fails(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test startup authentication when client connection fails."""
        mock_telegram_client.initialize.return_value = True
        mock_telegram_client.connect.return_value = False
        
        result = await auth_manager.startup_authentication()
        
        assert result is False
        assert auth_manager._is_authenticated is False

    @pytest.mark.asyncio
    async def test_startup_authentication_new_auth_fails(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test startup authentication when new authentication fails."""
        mock_telegram_client.initialize.return_value = True
        mock_telegram_client.connect.return_value = True
        mock_session_manager.authenticate.return_value = False
        
        with patch.object(auth_manager, '_validate_existing_session', return_value=False):
            result = await auth_manager.startup_authentication()
            
            assert result is False
            assert auth_manager._is_authenticated is False

    @pytest.mark.asyncio
    async def test_validate_existing_session_no_file(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test validating existing session when no session file exists."""
        mock_session_manager.session_exists.return_value = False
        
        result = await auth_manager._validate_existing_session()
        
        assert result is False
        mock_session_manager.session_exists.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_existing_session_invalid(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test validating existing session when session is invalid."""
        mock_session_manager.session_exists.return_value = True
        mock_session_manager.validate_session.return_value = False
        
        result = await auth_manager._validate_existing_session()
        
        assert result is False
        mock_session_manager.validate_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_existing_session_valid(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test validating existing session when session is valid."""
        mock_session_manager.session_exists.return_value = True
        mock_session_manager.validate_session.return_value = True
        
        result = await auth_manager._validate_existing_session()
        
        assert result is True

    @pytest.mark.asyncio
    async def test_re_authenticate_success(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test successful re-authentication."""
        mock_telegram_client.disconnect = AsyncMock()
        mock_telegram_client.connect.return_value = True
        mock_session_manager.authenticate.return_value = True
        auth_manager._is_authenticated = True
        
        result = await auth_manager.re_authenticate()
        
        assert result is True
        assert auth_manager._is_authenticated is True
        mock_telegram_client.disconnect.assert_called_once()
        mock_telegram_client.connect.assert_called_once()
        mock_session_manager.authenticate.assert_called_once()

    @pytest.mark.asyncio
    async def test_re_authenticate_connect_fails(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test re-authentication when reconnection fails."""
        mock_telegram_client.disconnect = AsyncMock()
        mock_telegram_client.connect.return_value = False
        
        result = await auth_manager.re_authenticate()
        
        assert result is False
        assert auth_manager._is_authenticated is False

    @pytest.mark.asyncio
    async def test_re_authenticate_auth_fails(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test re-authentication when authentication fails."""
        mock_telegram_client.disconnect = AsyncMock()
        mock_telegram_client.connect.return_value = True
        mock_session_manager.authenticate.return_value = False
        
        result = await auth_manager.re_authenticate()
        
        assert result is False
        assert auth_manager._is_authenticated is False

    @pytest.mark.asyncio
    async def test_check_connection_status_success(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test checking connection status with all positive results."""
        mock_telegram_client.is_connected.return_value = True
        mock_telegram_client.is_authorized.return_value = True
        mock_session_manager.session_exists.return_value = True
        auth_manager._is_authenticated = True
        
        # Mock user info
        mock_user = MagicMock()
        mock_user.id = 123456
        mock_user.first_name = "Test"
        mock_user.username = "testuser"
        mock_user.phone = "+1234567890"
        mock_telegram_client.client.get_me = AsyncMock(return_value=mock_user)
        
        result = await auth_manager.check_connection_status()
        
        expected = {
            "connected": True,
            "authorized": True,
            "session_file_exists": True,
            "authenticated": True,
            "user_info": {
                "id": 123456,
                "first_name": "Test",
                "username": "testuser",
                "phone": "+1234567890",
            },
        }
        
        assert result == expected

    @pytest.mark.asyncio
    async def test_check_connection_status_not_authorized(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test checking connection status when not authorized."""
        mock_telegram_client.is_connected.return_value = True
        mock_telegram_client.is_authorized.return_value = False
        mock_session_manager.session_exists.return_value = False
        auth_manager._is_authenticated = False
        
        result = await auth_manager.check_connection_status()
        
        expected = {
            "connected": True,
            "authorized": False,
            "session_file_exists": False,
            "authenticated": False,
        }
        
        assert result == expected

    @pytest.mark.asyncio
    async def test_check_connection_status_get_me_fails(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test checking connection status when get_me fails."""
        mock_telegram_client.is_connected.return_value = True
        mock_telegram_client.is_authorized.return_value = True
        mock_session_manager.session_exists.return_value = True
        auth_manager._is_authenticated = True
        mock_telegram_client.client.get_me = AsyncMock(side_effect=Exception("API error"))
        
        result = await auth_manager.check_connection_status()
        
        expected = {
            "connected": True,
            "authorized": True,
            "session_file_exists": True,
            "authenticated": True,
            "user_info": None,
        }
        
        assert result == expected

    @pytest.mark.asyncio
    async def test_periodic_health_check_connection_lost(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test periodic health check when connection is lost."""
        mock_telegram_client.is_connected.side_effect = [False, True]  # Lost, then reconnected
        mock_telegram_client.connect.return_value = True
        mock_telegram_client.is_authorized.return_value = True
        
        # Create a task that we'll cancel after one iteration
        health_check_task = asyncio.create_task(auth_manager.periodic_health_check(0.1))
        
        # Let it run for a short time
        await asyncio.sleep(0.2)
        
        # Cancel the task
        health_check_task.cancel()
        
        try:
            await health_check_task
        except asyncio.CancelledError:
            pass
        
        # Verify reconnection was attempted
        mock_telegram_client.connect.assert_called()

    @pytest.mark.asyncio
    async def test_periodic_health_check_authorization_lost(
        self, auth_manager, mock_telegram_client, mock_session_manager
    ):
        """Test periodic health check when authorization is lost."""
        mock_telegram_client.is_connected.return_value = True
        mock_telegram_client.is_authorized.side_effect = [False, True]  # Lost, then re-authenticated
        
        with patch.object(auth_manager, 're_authenticate', return_value=True) as mock_reauth:
            # Create a task that we'll cancel after one iteration
            health_check_task = asyncio.create_task(auth_manager.periodic_health_check(0.1))
            
            # Let it run for a short time
            await asyncio.sleep(0.2)
            
            # Cancel the task
            health_check_task.cancel()
            
            try:
                await health_check_task
            except asyncio.CancelledError:
                pass
            
            # Verify re-authentication was attempted
            mock_reauth.assert_called()

    @pytest.mark.asyncio
    async def test_cleanup(self, auth_manager, mock_telegram_client, mock_session_manager):
        """Test cleanup disconnects and resets state."""
        auth_manager._is_authenticated = True
        mock_telegram_client.disconnect = AsyncMock()
        
        await auth_manager.cleanup()
        
        assert auth_manager._is_authenticated is False
        mock_telegram_client.disconnect.assert_called_once()

    def test_is_authenticated_true(self, auth_manager):
        """Test is_authenticated when authenticated."""
        auth_manager._is_authenticated = True
        
        result = auth_manager.is_authenticated()
        
        assert result is True

    def test_is_authenticated_false(self, auth_manager):
        """Test is_authenticated when not authenticated."""
        auth_manager._is_authenticated = False
        
        result = auth_manager.is_authenticated()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_async_context_manager_success(self, mock_telegram_client, mock_session_manager):
        """Test async context manager with successful authentication."""
        with patch.object(AuthManager, 'startup_authentication', return_value=True):
            async with AuthManager("test") as auth_mgr:
                assert auth_mgr is not None

    @pytest.mark.asyncio
    async def test_async_context_manager_failure(self, mock_telegram_client, mock_session_manager):
        """Test async context manager with authentication failure."""
        with patch.object(AuthManager, 'startup_authentication', return_value=False):
            with pytest.raises(RuntimeError, match="Failed to authenticate Telegram session"):
                async with AuthManager("test"):
                    pass