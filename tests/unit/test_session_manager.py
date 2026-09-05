"""
Unit tests for SessionManager.
Tests authentication flow, session validation, and error handling.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from telethon.errors import (
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
    FloodWaitError,
)

from src.telegram_client.session_manager import SessionManager
from src.telegram_client.client import TelegramClient


class TestSessionManager:
    """Test cases for SessionManager."""

    @pytest.fixture
    def mock_telegram_client(self):
        """Create mock TelegramClient for testing."""
        mock_client = MagicMock(spec=TelegramClient)
        mock_client.client = AsyncMock()
        mock_client.is_authorized = AsyncMock()
        mock_client.is_connected = AsyncMock()
        mock_client.get_session_path.return_value = Path("test_data/test.session")
        return mock_client

    @pytest.fixture
    def session_manager(self, mock_telegram_client):
        """Create SessionManager instance for testing."""
        return SessionManager(mock_telegram_client)

    @pytest.fixture
    def mock_settings(self):
        """Mock settings configuration."""
        with patch("src.telegram_client.session_manager.settings") as mock_settings:
            mock_settings.phone_number = "+1234567890"
            yield mock_settings

    @pytest.mark.asyncio
    async def test_authenticate_already_authorized(self, session_manager, mock_telegram_client):
        """Test authentication when user is already authorized."""
        mock_telegram_client.is_authorized.return_value = True
        
        result = await session_manager.authenticate()
        
        assert result is True
        mock_telegram_client.is_authorized.assert_called_once()

    @pytest.mark.asyncio
    async def test_authenticate_no_client(self, session_manager, mock_telegram_client):
        """Test authentication when client is not initialized."""
        mock_telegram_client.client = None
        
        result = await session_manager.authenticate()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_full_flow_success(self, session_manager, mock_telegram_client, mock_settings):
        """Test complete successful authentication flow."""
        mock_telegram_client.is_authorized.return_value = False
        
        # Mock phone code request
        with patch.object(session_manager, '_request_phone_code', return_value=True), \
             patch.object(session_manager, '_verify_phone_code', return_value=True), \
             patch.object(session_manager, '_handle_2fa_if_needed', return_value=True):
            
            result = await session_manager.authenticate()
            
            assert result is True

    @pytest.mark.asyncio
    async def test_authenticate_phone_code_request_fails(self, session_manager, mock_telegram_client, mock_settings):
        """Test authentication when phone code request fails."""
        mock_telegram_client.is_authorized.return_value = False
        
        with patch.object(session_manager, '_request_phone_code', return_value=False):
            result = await session_manager.authenticate()
            
            assert result is False

    @pytest.mark.asyncio
    async def test_request_phone_code_success(self, session_manager, mock_telegram_client, mock_settings):
        """Test successful phone code request."""
        mock_sent_code = MagicMock()
        mock_sent_code.phone_code_hash = "test_hash"
        mock_sent_code.type.__class__.__name__ = "SentCodeTypeSms"
        
        mock_telegram_client.client.send_code_request = AsyncMock(return_value=mock_sent_code)
        
        result = await session_manager._request_phone_code()
        
        assert result is True
        assert session_manager._phone_code_hash == "test_hash"
        mock_telegram_client.client.send_code_request.assert_called_once_with("+1234567890")

    @pytest.mark.asyncio
    async def test_request_phone_code_invalid_phone(self, session_manager, mock_telegram_client, mock_settings):
        """Test phone code request with invalid phone number."""
        mock_telegram_client.client.send_code_request = AsyncMock(
            side_effect=PhoneNumberInvalidError("Invalid phone")
        )
        
        result = await session_manager._request_phone_code()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_request_phone_code_flood_wait(self, session_manager, mock_telegram_client, mock_settings):
        """Test phone code request with flood wait error."""
        mock_telegram_client.client.send_code_request = AsyncMock(
            side_effect=FloodWaitError(60)
        )
        
        result = await session_manager._request_phone_code()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_phone_code_success(self, session_manager, mock_telegram_client, mock_settings):
        """Test successful phone code verification."""
        session_manager._phone_code_hash = "test_hash"
        mock_telegram_client.client.sign_in = AsyncMock()
        
        with patch("builtins.input", return_value="12345"), \
             patch("builtins.print"):
            
            result = await session_manager._verify_phone_code()
            
            assert result is True
            mock_telegram_client.client.sign_in.assert_called_once_with(
                phone="+1234567890",
                code="12345",
                phone_code_hash="test_hash",
            )

    @pytest.mark.asyncio
    async def test_verify_phone_code_invalid_code(self, session_manager, mock_telegram_client, mock_settings):
        """Test phone code verification with invalid code."""
        session_manager._phone_code_hash = "test_hash"
        mock_telegram_client.client.sign_in = AsyncMock(
            side_effect=PhoneCodeInvalidError("Invalid code")
        )
        
        with patch("builtins.input", side_effect=["wrong1", "wrong2", "wrong3"]), \
             patch("builtins.print"):
            
            result = await session_manager._verify_phone_code()
            
            assert result is False
            assert mock_telegram_client.client.sign_in.call_count == 3

    @pytest.mark.asyncio
    async def test_verify_phone_code_expired(self, session_manager, mock_telegram_client, mock_settings):
        """Test phone code verification with expired code."""
        session_manager._phone_code_hash = "test_hash"
        mock_telegram_client.client.sign_in = AsyncMock(
            side_effect=PhoneCodeExpiredError("Code expired")
        )
        
        with patch("builtins.input", return_value="12345"), \
             patch("builtins.print"):
            
            result = await session_manager._verify_phone_code()
            
            assert result is False

    @pytest.mark.asyncio
    async def test_verify_phone_code_2fa_needed(self, session_manager, mock_telegram_client, mock_settings):
        """Test phone code verification when 2FA is needed."""
        session_manager._phone_code_hash = "test_hash"
        mock_telegram_client.client.sign_in = AsyncMock(
            side_effect=SessionPasswordNeededError("2FA required")
        )
        
        with patch("builtins.input", return_value="12345"), \
             patch("builtins.print"):
            
            result = await session_manager._verify_phone_code()
            
            assert result is True  # Will be handled by 2FA handler

    @pytest.mark.asyncio
    async def test_verify_phone_code_no_hash(self, session_manager, mock_telegram_client, mock_settings):
        """Test phone code verification without phone code hash."""
        session_manager._phone_code_hash = None
        
        result = await session_manager._verify_phone_code()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_2fa_if_needed_not_needed(self, session_manager, mock_telegram_client):
        """Test 2FA handling when not needed."""
        mock_telegram_client.is_authorized.return_value = True
        
        result = await session_manager._handle_2fa_if_needed()
        
        assert result is True

    @pytest.mark.asyncio
    async def test_handle_2fa_if_needed_with_2fa(self, session_manager, mock_telegram_client):
        """Test 2FA handling when 2FA is required."""
        mock_telegram_client.is_authorized.return_value = False
        mock_telegram_client.client.get_me = AsyncMock(
            side_effect=SessionPasswordNeededError("2FA required")
        )
        
        with patch.object(session_manager, '_handle_2fa_password', return_value=True):
            result = await session_manager._handle_2fa_if_needed()
            
            assert result is True

    @pytest.mark.asyncio
    async def test_handle_2fa_password_success(self, session_manager, mock_telegram_client):
        """Test successful 2FA password verification."""
        mock_telegram_client.client.sign_in = AsyncMock()
        
        with patch("getpass.getpass", return_value="password123"), \
             patch("builtins.print"):
            
            result = await session_manager._handle_2fa_password()
            
            assert result is True
            mock_telegram_client.client.sign_in.assert_called_once_with(password="password123")

    @pytest.mark.asyncio
    async def test_handle_2fa_password_invalid(self, session_manager, mock_telegram_client):
        """Test 2FA password verification with invalid password."""
        mock_telegram_client.client.sign_in = AsyncMock(
            side_effect=Exception("Invalid password")
        )
        
        with patch("getpass.getpass", side_effect=["wrong1", "wrong2", "wrong3"]), \
             patch("builtins.print"):
            
            result = await session_manager._handle_2fa_password()
            
            assert result is False
            assert mock_telegram_client.client.sign_in.call_count == 3

    @pytest.mark.asyncio
    async def test_validate_session_success(self, session_manager, mock_telegram_client):
        """Test successful session validation."""
        mock_telegram_client.is_connected.return_value = True
        mock_telegram_client.is_authorized.return_value = True
        
        mock_user = MagicMock()
        mock_user.first_name = "Test User"
        mock_telegram_client.client.get_me = AsyncMock(return_value=mock_user)
        
        result = await session_manager.validate_session()
        
        assert result is True
        mock_telegram_client.client.get_me.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_session_not_connected(self, session_manager, mock_telegram_client):
        """Test session validation when not connected."""
        mock_telegram_client.is_connected.return_value = False
        mock_telegram_client.connect = AsyncMock(return_value=False)
        
        result = await session_manager.validate_session()
        
        assert result is False
        mock_telegram_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_session_not_authorized(self, session_manager, mock_telegram_client):
        """Test session validation when not authorized."""
        mock_telegram_client.is_connected.return_value = True
        mock_telegram_client.is_authorized.return_value = False
        
        result = await session_manager.validate_session()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_session_get_me_fails(self, session_manager, mock_telegram_client):
        """Test session validation when get_me fails."""
        mock_telegram_client.is_connected.return_value = True
        mock_telegram_client.is_authorized.return_value = True
        mock_telegram_client.client.get_me = AsyncMock(side_effect=Exception("API error"))
        
        result = await session_manager.validate_session()
        
        assert result is False

    def test_session_exists_true(self, session_manager, mock_telegram_client):
        """Test session_exists when session file exists."""
        with patch("pathlib.Path.exists", return_value=True):
            result = session_manager.session_exists()
            
            assert result is True

    def test_session_exists_false(self, session_manager, mock_telegram_client):
        """Test session_exists when session file doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = session_manager.session_exists()
            
            assert result is False