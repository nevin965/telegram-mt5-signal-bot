"""
Unit tests for TelegramClient wrapper.
Tests client initialization, connection, and error handling.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from pathlib import Path

from telethon.errors import ApiIdInvalidError, FloodWaitError

from src.telegram_client.client import TelegramClient


class TestTelegramClient:
    """Test cases for TelegramClient wrapper."""

    @pytest.fixture
    def client(self):
        """Create TelegramClient instance for testing."""
        return TelegramClient("test_session")

    @pytest.fixture
    def mock_settings(self):
        """Mock settings configuration."""
        with patch("src.telegram_client.client.settings") as mock_settings:
            mock_settings.validate_telegram_config.return_value = True
            mock_settings.get_telegram_api_id_int.return_value = 12345
            mock_settings.telegram_api_hash = "test_hash"
            mock_settings.data_dir = Path("test_data")
            yield mock_settings

    @pytest.mark.asyncio
    async def test_initialize_success(self, client, mock_settings):
        """Test successful client initialization."""
        with patch("src.telegram_client.client.TelethonClient") as mock_telethon:
            result = await client.initialize()
            
            assert result is True
            assert client.client is not None
            # Check that TelethonClient was called with correct parameters
            call_args = mock_telethon.call_args
            assert call_args[1]['api_id'] == 12345
            assert call_args[1]['api_hash'] == "test_hash"
            assert call_args[1]['session'].endswith("test_session.session")

    @pytest.mark.asyncio
    async def test_initialize_invalid_config(self, client, mock_settings):
        """Test initialization with invalid configuration."""
        mock_settings.validate_telegram_config.return_value = False
        
        result = await client.initialize()
        
        assert result is False
        assert client.client is None

    @pytest.mark.asyncio
    async def test_initialize_invalid_api_id(self, client, mock_settings):
        """Test initialization with invalid API ID."""
        mock_settings.get_telegram_api_id_int.side_effect = ValueError("Invalid API ID")
        
        result = await client.initialize()
        
        assert result is False
        assert client.client is None

    @pytest.mark.asyncio
    async def test_connect_success_authorized(self, client, mock_settings):
        """Test successful connection with authorized user."""
        mock_telethon_client = AsyncMock()
        mock_telethon_client.connect = AsyncMock()
        mock_telethon_client.is_user_authorized = AsyncMock(return_value=True)
        client.client = mock_telethon_client
        
        result = await client.connect()
        
        assert result is True
        assert client._is_connected is True
        mock_telethon_client.connect.assert_called_once()
        mock_telethon_client.is_user_authorized.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_success_unauthorized(self, client, mock_settings):
        """Test successful connection with unauthorized user."""
        mock_telethon_client = AsyncMock()
        mock_telethon_client.connect = AsyncMock()
        mock_telethon_client.is_user_authorized = AsyncMock(return_value=False)
        client.client = mock_telethon_client
        
        result = await client.connect()
        
        assert result is True  # Connection successful, auth needed separately
        mock_telethon_client.connect.assert_called_once()
        mock_telethon_client.is_user_authorized.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_api_id_invalid_error(self, client, mock_settings):
        """Test connection with invalid API ID error."""
        mock_telethon_client = AsyncMock()
        mock_telethon_client.connect = AsyncMock(side_effect=ApiIdInvalidError("Invalid API ID"))
        client.client = mock_telethon_client
        
        result = await client.connect()
        
        assert result is False
        assert client._is_connected is False

    @pytest.mark.asyncio
    async def test_connect_flood_wait_error(self, client, mock_settings):
        """Test connection with flood wait error."""
        mock_telethon_client = AsyncMock()
        mock_telethon_client.connect = AsyncMock(side_effect=FloodWaitError(60))
        client.client = mock_telethon_client
        
        result = await client.connect()
        
        assert result is False
        assert client._is_connected is False

    @pytest.mark.asyncio
    async def test_connect_no_client(self, client, mock_settings):
        """Test connection when client is not initialized."""
        result = await client.connect()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_success(self, client, mock_settings):
        """Test successful disconnect."""
        mock_telethon_client = AsyncMock()
        mock_telethon_client.disconnect = AsyncMock()
        client.client = mock_telethon_client
        client._is_connected = True
        
        await client.disconnect()
        
        assert client._is_connected is False
        mock_telethon_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_with_error(self, client, mock_settings):
        """Test disconnect with error handling."""
        mock_telethon_client = AsyncMock()
        mock_telethon_client.disconnect = AsyncMock(side_effect=Exception("Disconnect error"))
        client.client = mock_telethon_client
        client._is_connected = True
        
        await client.disconnect()
        
        # Should still mark as disconnected even if error occurs
        assert client._is_connected is False
        mock_telethon_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_no_client(self, client, mock_settings):
        """Test disconnect when no client exists."""
        await client.disconnect()  # Should not raise exception
        assert client._is_connected is False

    @pytest.mark.asyncio
    async def test_is_connected_true(self, client, mock_settings):
        """Test is_connected when client is connected."""
        mock_telethon_client = MagicMock()
        mock_telethon_client.is_connected.return_value = True
        client.client = mock_telethon_client
        client._is_connected = True
        
        result = await client.is_connected()
        
        assert result is True

    @pytest.mark.asyncio
    async def test_is_connected_false(self, client, mock_settings):
        """Test is_connected when client is not connected."""
        mock_telethon_client = MagicMock()
        mock_telethon_client.is_connected.return_value = False
        client.client = mock_telethon_client
        client._is_connected = False
        
        result = await client.is_connected()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_is_connected_no_client(self, client, mock_settings):
        """Test is_connected when no client exists."""
        result = await client.is_connected()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_is_authorized_true(self, client, mock_settings):
        """Test is_authorized when user is authorized."""
        mock_telethon_client = AsyncMock()
        mock_telethon_client.is_user_authorized = AsyncMock(return_value=True)
        client.client = mock_telethon_client
        
        result = await client.is_authorized()
        
        assert result is True
        mock_telethon_client.is_user_authorized.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_authorized_false(self, client, mock_settings):
        """Test is_authorized when user is not authorized."""
        mock_telethon_client = AsyncMock()
        mock_telethon_client.is_user_authorized = AsyncMock(return_value=False)
        client.client = mock_telethon_client
        
        result = await client.is_authorized()
        
        assert result is False
        mock_telethon_client.is_user_authorized.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_authorized_no_client(self, client, mock_settings):
        """Test is_authorized when no client exists."""
        result = await client.is_authorized()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_is_authorized_with_error(self, client, mock_settings):
        """Test is_authorized when error occurs."""
        mock_telethon_client = AsyncMock()
        mock_telethon_client.is_user_authorized = AsyncMock(side_effect=Exception("Auth check error"))
        client.client = mock_telethon_client
        
        result = await client.is_authorized()
        
        assert result is False

    def test_get_session_path(self, client, mock_settings):
        """Test get_session_path returns correct path."""
        result = client.get_session_path()
        
        assert result.name == "test_session.session"
        assert str(result).endswith("test_session.session")

    @pytest.mark.asyncio
    async def test_async_context_manager_success(self, mock_settings):
        """Test async context manager with successful initialization."""
        with patch("src.telegram_client.client.TelethonClient") as mock_telethon:
            mock_client_instance = AsyncMock()
            mock_client_instance.connect = AsyncMock(return_value=None)
            mock_client_instance.is_connected.return_value = True
            mock_client_instance.is_user_authorized = AsyncMock(return_value=True)
            mock_telethon.return_value = mock_client_instance
            
            async with TelegramClient("test") as client:
                assert client is not None
                assert await client.is_connected() is True

    @pytest.mark.asyncio
    async def test_async_context_manager_init_failure(self, mock_settings):
        """Test async context manager with initialization failure."""
        mock_settings.validate_telegram_config.return_value = False
        
        with pytest.raises(RuntimeError, match="Failed to initialize Telegram client"):
            async with TelegramClient("test"):
                pass

    @pytest.mark.asyncio
    async def test_async_context_manager_connect_failure(self, mock_settings):
        """Test async context manager with connection failure."""
        with patch("src.telegram_client.client.TelethonClient") as mock_telethon:
            mock_client = AsyncMock()
            mock_client.connect = AsyncMock(side_effect=ApiIdInvalidError("Invalid"))
            mock_telethon.return_value = mock_client
            
            with pytest.raises(RuntimeError, match="Failed to connect to Telegram"):
                async with TelegramClient("test"):
                    pass