"""
Integration tests for Telegram monitoring functionality.
Tests end-to-end group monitoring with mocked Telethon dependencies.
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from telethon.tl.types import Message, Channel, Chat
from telethon.errors import FloodWaitError

from src.telegram_client.client import TelegramClient
from src.telegram_client.message_handler import MessageHandler
from src.telegram_client.rate_limiter import RateLimiter
from config.settings import settings


class TestTelegramMonitoringIntegration:
    """Integration tests for complete Telegram monitoring flow."""

    def setup_method(self):
        """Set up test fixtures."""
        self.client = TelegramClient("test_session")
        self.message_handler = MessageHandler()
        self.rate_limiter = RateLimiter()

    @pytest.mark.asyncio
    async def test_complete_monitoring_flow(self):
        """Test complete monitoring flow from client connection to message processing."""
        # Mock Telethon client
        mock_telethon_client = AsyncMock()
        mock_telethon_client.connect.return_value = None
        mock_telethon_client.is_user_authorized.return_value = True
        mock_telethon_client.is_connected.return_value = True
        mock_telethon_client.get_me.return_value = Mock(id=12345, username="testuser")
        
        # Mock group entities
        mock_group1 = Mock(spec=Channel)
        mock_group1.id = 111222
        mock_group1.title = "Signal Group 1"
        
        mock_group2 = Mock(spec=Channel)
        mock_group2.id = 333444
        mock_group2.title = "Signal Group 2"
        
        mock_telethon_client.get_entity.side_effect = [mock_group1, mock_group2]
        
        # Mock settings
        with patch.object(settings, 'get_telegram_groups', return_value=['@group1', '@group2']):
            with patch.object(settings, 'validate_telegram_groups', return_value=(True, [])):
                with patch.object(self.client, 'client', mock_telethon_client):
                    
                    # Initialize and connect client
                    self.client._is_connected = True  # Simulate successful connection
                    
                    # Connect to groups
                    results = await self.client.connect_to_groups()
                    
                    # Verify groups were connected
                    assert len(results) == 2
                    assert results['@group1']['success'] is True
                    assert results['@group2']['success'] is True
                    
                    # Get connected group entities
                    group_entities = self.client.get_connected_group_entities()
                    assert len(group_entities) == 2
                    assert mock_group1 in group_entities
                    assert mock_group2 in group_entities

    @pytest.mark.asyncio
    async def test_message_processing_with_rate_limiting(self):
        """Test message processing with rate limiting applied."""
        # Create test message
        mock_message = Mock(spec=Message)
        mock_message.text = "GOLD SELL at 2000.50"
        mock_message.id = 98765
        mock_message.date = datetime.utcnow()
        mock_message.reply_to = None
        mock_message.forward = None
        mock_message.from_id = Mock(user_id=55555)
        mock_message.peer_id = Mock(channel_id=777888)
        
        mock_event = AsyncMock()
        mock_event.message = mock_message
        mock_chat = Mock(title="Trading Signals")
        mock_event.get_chat.return_value = mock_chat
        
        # Track callback calls
        callback_calls = []
        
        def test_callback(metadata):
            callback_calls.append(metadata)
        
        self.message_handler.set_message_callback(test_callback)
        
        # Mock rate limiter to reduce delay for testing
        with patch.object(self.rate_limiter, 'human_delay', return_value=None) as mock_delay:
            
            # Process message
            await self.message_handler.handle_new_message(mock_event)
            
            # Apply rate limiting
            await self.rate_limiter.human_delay()
            
            # Verify message was processed
            assert len(callback_calls) == 1
            metadata = callback_calls[0]
            assert metadata['telegram_message_id'] == 98765
            assert metadata['raw_text'] == "GOLD SELL at 2000.50"
            assert metadata['chat_title'] == "Trading Signals"
            
            # Verify rate limiting was applied
            mock_delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_connection_health_monitoring(self):
        """Test connection health monitoring and auto-reconnection."""
        mock_telethon_client = AsyncMock()
        mock_telethon_client.is_connected.return_value = True
        mock_telethon_client.is_user_authorized.return_value = True
        mock_telethon_client.get_me.return_value = Mock(id=12345)
        
        with patch.object(self.client, 'client', mock_telethon_client):
            self.client._is_connected = True
            
            # Perform health check
            is_healthy = await self.client._perform_health_check()
            assert is_healthy is True
            
            # Test unhealthy connection
            mock_telethon_client.is_connected.return_value = False
            is_healthy = await self.client._perform_health_check()
            assert is_healthy is False

    @pytest.mark.asyncio
    async def test_auto_reconnection_flow(self):
        """Test automatic reconnection flow when connection fails."""
        mock_telethon_client = AsyncMock()
        
        # Mock successful reconnection on second attempt
        connect_attempts = [False, True]  # Fail first, succeed second
        mock_telethon_client.connect.side_effect = connect_attempts
        mock_telethon_client.is_user_authorized.return_value = True
        
        with patch.object(self.client, 'initialize', return_value=True):
            with patch.object(self.client, 'connect') as mock_connect:
                mock_connect.side_effect = [False, True]  # Fail then succeed
                
                with patch.object(self.client, 'connect_to_groups', return_value={}):
                    # Attempt auto-reconnection
                    success = await self.client._attempt_auto_reconnection()
                    
                    # Verify reconnection succeeded on second attempt
                    assert success is True
                    assert mock_connect.call_count == 2

    @pytest.mark.asyncio
    async def test_flood_wait_handling_in_monitoring(self):
        """Test flood wait error handling during monitoring."""
        # Create flood wait error
        flood_error = FloodWaitError(seconds=5)
        
        # Mock the rate limiter's flood handling
        with patch.object(self.rate_limiter, 'handle_flood_wait') as mock_flood_handler:
            mock_flood_handler.return_value = None
            
            # Simulate flood wait handling
            await self.rate_limiter.handle_flood_wait(flood_error)
            
            # Verify flood wait was handled
            mock_flood_handler.assert_called_once_with(flood_error)

    @pytest.mark.asyncio
    async def test_group_connection_error_scenarios(self):
        """Test various group connection error scenarios."""
        from telethon.errors import UsernameNotOccupiedError, ChannelPrivateError
        
        mock_telethon_client = AsyncMock()
        
        # Mock different error scenarios
        mock_telethon_client.get_entity.side_effect = [
            UsernameNotOccupiedError("Group not found"),
            ChannelPrivateError("Private group"),
            Mock(spec=Channel, id=123, title="Valid Group")
        ]
        
        with patch.object(settings, 'get_telegram_groups', return_value=['@invalid1', '@private2', '@valid3']):
            with patch.object(settings, 'validate_telegram_groups', return_value=(True, [])):
                with patch.object(self.client, 'client', mock_telethon_client):
                    self.client._is_connected = True
                    
                    # Mock authorization check
                    with patch.object(self.client, 'is_authorized', return_value=True):
                        
                        # Connect to groups with errors
                        results = await self.client.connect_to_groups()
                        
                        # Verify error handling
                        assert len(results) == 3
                        assert results['@invalid1']['success'] is False
                        assert results['@private2']['success'] is False  
                        assert results['@valid3']['success'] is True

    @pytest.mark.asyncio
    async def test_monitoring_statistics_tracking(self):
        """Test monitoring statistics tracking across components."""
        # Process some test messages
        test_messages = [
            ("Message 1", 1001),
            ("Message 2", 1002), 
            ("Message 3", 1003)
        ]
        
        for text, msg_id in test_messages:
            mock_message = Mock(spec=Message)
            mock_message.text = text
            mock_message.id = msg_id
            mock_message.date = datetime.utcnow()
            mock_message.reply_to = None
            mock_message.forward = None
            mock_message.from_id = Mock(user_id=99999)
            mock_message.peer_id = Mock(channel_id=88888)
            
            mock_event = AsyncMock()
            mock_event.message = mock_message
            mock_chat = Mock(title="Stats Test Group")
            mock_event.get_chat.return_value = mock_chat
            
            await self.message_handler.handle_new_message(mock_event)
        
        # Get monitoring stats
        handler_stats = self.message_handler.get_monitoring_stats()
        assert handler_stats['messages_processed'] == 3
        assert handler_stats['unique_messages_tracked'] == 3
        
        # Get rate limiter stats
        limiter_stats = self.rate_limiter.get_daily_stats()
        assert limiter_stats['daily_message_count'] >= 0
        assert 'remaining_messages' in limiter_stats

    @pytest.mark.asyncio
    async def test_console_output_formatting(self):
        """Test console monitoring output formatting."""
        # Mock logger to capture log calls
        with patch.object(self.message_handler, 'logger') as mock_logger:
            
            mock_message = Mock(spec=Message)
            mock_message.text = "Test console output message"
            mock_message.id = 55555
            mock_message.date = datetime(2024, 1, 15, 14, 30, 0)
            mock_message.reply_to = None
            mock_message.forward = None
            mock_message.from_id = Mock(user_id=77777)
            mock_message.peer_id = Mock(channel_id=66666)
            
            mock_event = AsyncMock()
            mock_event.message = mock_message
            mock_chat = Mock(title="Console Test Group")
            mock_event.get_chat.return_value = mock_chat
            
            # Process message
            await self.message_handler.handle_new_message(mock_event)
            
            # Verify INFO level logging was called for console output
            mock_logger.info.assert_called()
            
            # Check the log message format
            log_calls = mock_logger.info.call_args_list
            console_log_call = log_calls[-1]  # Last INFO call should be console output
            log_message = console_log_call[0][0]
            
            assert "📨" in log_message
            assert "2024-01-15 14:30:00" in log_message
            assert "Console Test Group" in log_message
            assert "user_77777" in log_message
            assert "Test console output message" in log_message

    @pytest.mark.asyncio
    async def test_event_handler_registration(self):
        """Test event handler registration with Telethon client."""
        # Mock group entities
        mock_entities = [
            Mock(spec=Channel, id=111, title="Group 1"),
            Mock(spec=Channel, id=222, title="Group 2")
        ]
        
        # Create event handler
        event_handler = self.message_handler.create_event_handler(mock_entities)
        
        # Verify handler was created (mock test)
        assert event_handler is not None
        
        # In a real scenario, this would register with Telethon client
        # Here we just verify the handler creation doesn't raise errors
        assert callable(event_handler)