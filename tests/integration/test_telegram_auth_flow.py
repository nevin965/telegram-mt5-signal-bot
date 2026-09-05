"""
Integration tests for complete Telegram authentication flow.
Tests end-to-end authentication scenarios with mocked Telethon client.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from src.telegram_client.auth_manager import AuthManager


class TestTelegramAuthFlow:
    """Integration tests for complete authentication flow."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings with valid configuration."""
        with patch("src.telegram_client.client.settings") as mock_settings, \
             patch("src.telegram_client.session_manager.settings", mock_settings):
            
            mock_settings.validate_telegram_config.return_value = True
            mock_settings.get_telegram_api_id_int.return_value = 12345
            mock_settings.telegram_api_hash = "test_api_hash"
            mock_settings.phone_number = "+1234567890"
            mock_settings.data_dir = Path("test_data")
            mock_settings.log_dir = Path("test_logs")
            
            yield mock_settings

    @pytest.fixture
    def mock_telethon_client(self):
        """Mock Telethon client with typical behavior."""
        with patch("src.telegram_client.client.TelethonClient") as mock_telethon_class:
            mock_client = AsyncMock()
            mock_telethon_class.return_value = mock_client
            
            # Default behavior - not connected initially
            mock_client.connect = AsyncMock()
            mock_client.is_connected.return_value = False
            mock_client.is_user_authorized = AsyncMock(return_value=False)
            mock_client.disconnect = AsyncMock()
            
            yield mock_client

    @pytest.mark.asyncio
    async def test_first_time_authentication_success(self, mock_settings, mock_telethon_client):
        """Test complete first-time authentication flow."""
        # Setup mock responses
        mock_telethon_client.is_user_authorized.side_effect = [False, False, True]  # Auth after sign_in
        
        # Mock session file doesn't exist initially
        with patch("pathlib.Path.exists", return_value=False):
            # Mock phone code request
            mock_sent_code = MagicMock()
            mock_sent_code.phone_code_hash = "test_hash_123"
            mock_sent_code.type.__class__.__name__ = "SentCodeTypeSms"
            mock_telethon_client.send_code_request = AsyncMock(return_value=mock_sent_code)
            
            # Mock successful sign in
            mock_telethon_client.sign_in = AsyncMock()
            
            # Mock user info
            mock_user = MagicMock()
            mock_user.id = 123456
            mock_user.first_name = "Test User"
            mock_telethon_client.get_me = AsyncMock(return_value=mock_user)
            
            # Mock user input
            with patch("builtins.input", return_value="12345"), \
                 patch("builtins.print"):
                
                auth_manager = AuthManager("integration_test")
                result = await auth_manager.startup_authentication()
                
                # Verify success
                assert result is True
                assert auth_manager.is_authenticated() is True
                
                # Verify authentication calls were made
                mock_telethon_client.send_code_request.assert_called_once_with("+1234567890")
                mock_telethon_client.sign_in.assert_called_once()
                
                # Cleanup
                await auth_manager.cleanup()

    @pytest.mark.asyncio
    async def test_existing_session_validation_success(self, mock_settings, mock_telethon_client):
        """Test authentication with existing valid session."""
        # Setup mock responses - session exists and is valid
        mock_telethon_client.is_user_authorized.return_value = True
        mock_telethon_client.is_connected.return_value = True
        
        # Mock session file exists
        with patch("pathlib.Path.exists", return_value=True):
            # Mock user info
            mock_user = MagicMock()
            mock_user.id = 123456
            mock_user.first_name = "Test User"
            mock_telethon_client.get_me = AsyncMock(return_value=mock_user)
            
            auth_manager = AuthManager("integration_test")
            result = await auth_manager.startup_authentication()
            
            # Verify success without going through auth flow
            assert result is True
            assert auth_manager.is_authenticated() is True
            
            # Verify no authentication calls were made (session was valid)
            assert not mock_telethon_client.send_code_request.called
            assert not mock_telethon_client.sign_in.called
            
            # Cleanup
            await auth_manager.cleanup()

    @pytest.mark.asyncio
    async def test_existing_session_validation_failed_reauthentication(self, mock_settings, mock_telethon_client):
        """Test re-authentication when existing session is invalid."""
        # Mock session file exists but validation fails
        with patch("pathlib.Path.exists", return_value=True):
            # First get_me call fails (invalid session), second succeeds (after re-auth)
            mock_telethon_client.get_me = AsyncMock(
                side_effect=[Exception("Session invalid"), MagicMock(first_name="Test User")]
            )
            
            # Mock authorization status - false initially, true after auth
            mock_telethon_client.is_user_authorized.side_effect = [False, False, True]
            
            # Mock phone code request
            mock_sent_code = MagicMock()
            mock_sent_code.phone_code_hash = "test_hash_123"
            mock_telethon_client.send_code_request = AsyncMock(return_value=mock_sent_code)
            
            # Mock successful sign in
            mock_telethon_client.sign_in = AsyncMock()
            
            # Mock user input
            with patch("builtins.input", return_value="12345"), \
                 patch("builtins.print"):
                
                auth_manager = AuthManager("integration_test")
                result = await auth_manager.startup_authentication()
                
                # Verify success after re-authentication
                assert result is True
                assert auth_manager.is_authenticated() is True
                
                # Verify authentication calls were made
                mock_telethon_client.send_code_request.assert_called_once()
                mock_telethon_client.sign_in.assert_called_once()
                
                # Cleanup
                await auth_manager.cleanup()

    @pytest.mark.asyncio
    async def test_two_factor_authentication_flow(self, mock_settings, mock_telethon_client):
        """Test authentication flow with 2FA enabled."""
        from telethon.errors import SessionPasswordNeededError
        
        # Mock session file doesn't exist
        with patch("pathlib.Path.exists", return_value=False):
            # Mock phone code request
            mock_sent_code = MagicMock()
            mock_sent_code.phone_code_hash = "test_hash_123"
            mock_telethon_client.send_code_request = AsyncMock(return_value=mock_sent_code)
            
            # Mock sign in that triggers 2FA
            mock_telethon_client.sign_in = AsyncMock(
                side_effect=[SessionPasswordNeededError("2FA required"), None]  # First call triggers 2FA, second succeeds
            )
            
            # Mock authorization status
            mock_telethon_client.is_user_authorized.side_effect = [False, False, False, True]
            
            # Mock get_me that initially triggers 2FA, then succeeds
            mock_telethon_client.get_me = AsyncMock(
                side_effect=[SessionPasswordNeededError("2FA required"), MagicMock(first_name="Test User")]
            )
            
            # Mock user input for both code and password
            with patch("builtins.input", return_value="12345"), \
                 patch("getpass.getpass", return_value="my_2fa_password"), \
                 patch("builtins.print"):
                
                auth_manager = AuthManager("integration_test")
                result = await auth_manager.startup_authentication()
                
                # Verify success
                assert result is True
                assert auth_manager.is_authenticated() is True
                
                # Verify both authentication steps were called
                assert mock_telethon_client.sign_in.call_count == 2
                mock_telethon_client.send_code_request.assert_called_once()
                
                # Cleanup
                await auth_manager.cleanup()

    @pytest.mark.asyncio
    async def test_connection_status_comprehensive(self, mock_settings, mock_telethon_client):
        """Test comprehensive connection status checking."""
        # Setup successful authentication first
        with patch("pathlib.Path.exists", return_value=True):
            mock_telethon_client.is_user_authorized.return_value = True
            mock_telethon_client.is_connected.return_value = True
            
            mock_user = MagicMock()
            mock_user.id = 123456
            mock_user.first_name = "Test"
            mock_user.username = "testuser"
            mock_user.phone = "+1234567890"
            mock_telethon_client.get_me = AsyncMock(return_value=mock_user)
            
            auth_manager = AuthManager("integration_test")
            await auth_manager.startup_authentication()
            
            # Check connection status
            status = await auth_manager.check_connection_status()
            
            # Verify comprehensive status
            expected_status = {
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
            
            assert status == expected_status
            
            # Cleanup
            await auth_manager.cleanup()

    @pytest.mark.asyncio
    async def test_re_authentication_after_session_loss(self, mock_settings, mock_telethon_client):
        """Test re-authentication after losing session during runtime."""
        # Setup initial successful authentication
        with patch("pathlib.Path.exists", return_value=True):
            mock_telethon_client.is_user_authorized.return_value = True
            mock_telethon_client.is_connected.return_value = True
            mock_telethon_client.get_me = AsyncMock(return_value=MagicMock(first_name="Test User"))
            
            auth_manager = AuthManager("integration_test")
            await auth_manager.startup_authentication()
            
            assert auth_manager.is_authenticated() is True
            
            # Simulate session loss and re-authentication
            mock_sent_code = MagicMock()
            mock_sent_code.phone_code_hash = "new_hash_456"
            mock_telethon_client.send_code_request = AsyncMock(return_value=mock_sent_code)
            mock_telethon_client.sign_in = AsyncMock()
            
            # Mock new user input for re-authentication
            with patch("builtins.input", return_value="54321"), \
                 patch("builtins.print"):
                
                result = await auth_manager.re_authenticate()
                
                # Verify successful re-authentication
                assert result is True
                assert auth_manager.is_authenticated() is True
                
                # Verify disconnect and reconnect happened
                mock_telethon_client.disconnect.assert_called()
                
                # Cleanup
                await auth_manager.cleanup()

    @pytest.mark.asyncio
    async def test_async_context_manager_integration(self, mock_settings, mock_telethon_client):
        """Test using AuthManager as async context manager."""
        # Mock successful authentication
        with patch("pathlib.Path.exists", return_value=True):
            mock_telethon_client.is_user_authorized.return_value = True
            mock_telethon_client.is_connected.return_value = True
            mock_telethon_client.get_me = AsyncMock(return_value=MagicMock(first_name="Test User"))
            
            # Test async context manager
            async with AuthManager("integration_test") as auth_mgr:
                assert auth_mgr is not None
                assert auth_mgr.is_authenticated() is True
                
                # Should be able to check status
                status = await auth_mgr.check_connection_status()
                assert status["authenticated"] is True
            
            # After context exit, cleanup should have been called
            mock_telethon_client.disconnect.assert_called()

    @pytest.mark.asyncio
    async def test_authentication_failure_scenarios(self, mock_settings, mock_telethon_client):
        """Test various authentication failure scenarios."""
        from telethon.errors import PhoneNumberInvalidError, FloodWaitError
        
        # Test invalid phone number
        with patch("pathlib.Path.exists", return_value=False):
            mock_telethon_client.send_code_request = AsyncMock(
                side_effect=PhoneNumberInvalidError("Invalid phone")
            )
            
            auth_manager = AuthManager("integration_test")
            result = await auth_manager.startup_authentication()
            
            assert result is False
            assert auth_manager.is_authenticated() is False
            
            await auth_manager.cleanup()
        
        # Test flood wait error
        with patch("pathlib.Path.exists", return_value=False):
            mock_telethon_client.send_code_request = AsyncMock(
                side_effect=FloodWaitError(60)
            )
            
            auth_manager = AuthManager("integration_test")
            result = await auth_manager.startup_authentication()
            
            assert result is False
            assert auth_manager.is_authenticated() is False
            
            await auth_manager.cleanup()