"""
Unit tests for message handler.
Tests event processing and message filtering with mocked Telethon client.
"""

import asyncio
import pytest
from datetime import datetime, UTC
from unittest.mock import Mock, AsyncMock, patch

from telethon.tl.types import Message, User, Channel

from src.telegram_client.message_handler import MessageHandler


class TestMessageHandler:
    """Test cases for MessageHandler class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.handler = MessageHandler()
        
    def test_init(self):
        """Test MessageHandler initialization."""
        assert self.handler._message_counter == 0
        assert len(self.handler._processed_messages) == 0
        assert self.handler._message_callback is None

    def test_set_message_callback(self):
        """Test setting message callback function."""
        callback = Mock()
        self.handler.set_message_callback(callback)
        assert self.handler._message_callback == callback

    @pytest.mark.asyncio
    async def test_handle_new_message_text_message(self):
        """Test handling of text messages."""
        # Mock message and event
        mock_message = Mock(spec=Message)
        mock_message.text = "Test trading signal"
        mock_message.id = 12345
        mock_message.date = datetime.now(UTC)
        mock_message.reply_to = None
        mock_message.forward = None
        mock_message.from_id = Mock(user_id=67890)
        mock_message.peer_id = Mock(channel_id=111222)
        
        mock_event = AsyncMock()
        mock_event.message = mock_message
        mock_chat = Mock(title="Test Signal Group")
        mock_event.get_chat.return_value = mock_chat
        
        # Set up callback
        callback = Mock()
        self.handler.set_message_callback(callback)
        
        # Handle message
        await self.handler.handle_new_message(mock_event)
        
        # Verify message was processed
        assert self.handler._message_counter == 1
        assert len(self.handler._processed_messages) == 1
        
        # Verify callback was called
        callback.assert_called_once()
        call_args = callback.call_args[0][0]
        
        assert call_args['telegram_message_id'] == 12345
        assert call_args['raw_text'] == "Test trading signal"
        assert call_args['sender'] == "user_67890"
        assert call_args['telegram_chat_id'] == 111222
        assert call_args['chat_title'] == "Test Signal Group"
        assert call_args['message_type'] == 'text'
        assert call_args['is_forwarded'] is False

    @pytest.mark.asyncio
    async def test_handle_new_message_non_text_ignored(self):
        """Test that non-text messages are ignored."""
        # Mock message without text
        mock_message = Mock(spec=Message)
        mock_message.text = None  # Non-text message
        
        mock_event = AsyncMock()
        mock_event.message = mock_message
        
        # Set up callback
        callback = Mock()
        self.handler.set_message_callback(callback)
        
        # Handle message
        await self.handler.handle_new_message(mock_event)
        
        # Verify message was ignored
        assert self.handler._message_counter == 0
        assert len(self.handler._processed_messages) == 0
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_new_message_duplicate_prevention(self):
        """Test that duplicate messages are not processed twice."""
        # Mock message
        mock_message = Mock(spec=Message)
        mock_message.text = "Duplicate message test"
        mock_message.id = 54321
        mock_message.date = datetime.now(UTC)
        mock_message.reply_to = None
        mock_message.forward = None
        mock_message.from_id = Mock(user_id=98765)
        mock_message.peer_id = Mock(channel_id=333444)
        
        mock_event = AsyncMock()
        mock_event.message = mock_message
        mock_chat = Mock(title="Test Group")
        mock_event.get_chat.return_value = mock_chat
        
        # Set up callback
        callback = Mock()
        self.handler.set_message_callback(callback)
        
        # Handle same message twice
        await self.handler.handle_new_message(mock_event)
        await self.handler.handle_new_message(mock_event)
        
        # Verify message was only processed once
        assert self.handler._message_counter == 1
        assert len(self.handler._processed_messages) == 1
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_new_message_async_callback(self):
        """Test handling with async callback function."""
        # Mock message
        mock_message = Mock(spec=Message)
        mock_message.text = "Async callback test"
        mock_message.id = 99999
        mock_message.date = datetime.now(UTC)
        mock_message.reply_to = None
        mock_message.forward = None
        mock_message.from_id = Mock(user_id=11111)
        mock_message.peer_id = Mock(channel_id=22222)
        
        mock_event = AsyncMock()
        mock_event.message = mock_message
        mock_chat = Mock(title="Async Test Group")
        mock_event.get_chat.return_value = mock_chat
        
        # Set up async callback
        async_callback = AsyncMock()
        self.handler.set_message_callback(async_callback)
        
        # Handle message
        await self.handler.handle_new_message(mock_event)
        
        # Verify async callback was awaited
        async_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_new_message_callback_error_handling(self):
        """Test that callback errors don't stop message processing."""
        # Mock message
        mock_message = Mock(spec=Message)
        mock_message.text = "Error handling test"
        mock_message.id = 77777
        mock_message.date = datetime.now(UTC)
        mock_message.reply_to = None
        mock_message.forward = None
        mock_message.from_id = Mock(user_id=33333)
        mock_message.peer_id = Mock(channel_id=44444)
        
        mock_event = AsyncMock()
        mock_event.message = mock_message
        mock_chat = Mock(title="Error Test Group")
        mock_event.get_chat.return_value = mock_chat
        
        # Set up callback that raises exception
        error_callback = Mock(side_effect=Exception("Callback error"))
        self.handler.set_message_callback(error_callback)
        
        # Handle message (should not raise exception)
        await self.handler.handle_new_message(mock_event)
        
        # Verify message was still processed despite callback error
        assert self.handler._message_counter == 1
        error_callback.assert_called_once()

    def test_get_sender_info_user_id(self):
        """Test sender info extraction for user ID."""
        mock_message = Mock(spec=Message)
        mock_message.from_id = Mock(user_id=12345)
        
        # Test with asyncio.run since it's a sync method calling async
        result = asyncio.run(self.handler._get_sender_info(mock_message))
        assert result == "user_12345"

    def test_get_sender_info_channel_id(self):
        """Test sender info extraction for channel ID."""
        mock_message = Mock(spec=Message)
        mock_message.from_id = Mock(channel_id=67890)
        mock_message.from_id.user_id = None  # No user_id attribute
        
        result = asyncio.run(self.handler._get_sender_info(mock_message))
        assert result == "channel_67890"

    def test_get_sender_info_anonymous(self):
        """Test sender info extraction for anonymous messages."""
        mock_message = Mock(spec=Message)
        mock_message.from_id = None
        
        result = asyncio.run(self.handler._get_sender_info(mock_message))
        assert result == "anonymous"

    def test_sanitize_message_content_normal_text(self):
        """Test message content sanitization for normal text."""
        text = "Buy GOLD at 2000.50, TP at 2010.00, SL at 1990.00"
        result = self.handler._sanitize_message_content(text)
        assert result == text
        assert len(result) <= 100

    def test_sanitize_message_content_long_text(self):
        """Test message content sanitization for long text."""
        long_text = "x" * 150  # 150 character string
        result = self.handler._sanitize_message_content(long_text)
        assert len(result) == 103  # 100 chars + "..."
        assert result.endswith("...")

    def test_sanitize_message_content_empty(self):
        """Test message content sanitization for empty text."""
        result = self.handler._sanitize_message_content("")
        assert result == "[Empty message]"

    def test_sanitize_message_content_newlines(self):
        """Test message content sanitization removes newlines."""
        text = "Line 1\nLine 2\rLine 3"
        result = self.handler._sanitize_message_content(text)
        assert "\n" not in result
        assert "\r" not in result
        assert result == "Line 1 Line 2 Line 3"

    def test_create_event_handler(self):
        """Test event handler creation."""
        mock_entities = [Mock(), Mock(), Mock()]
        
        with patch('src.telegram_client.message_handler.events.NewMessage') as mock_new_message:
            mock_handler = Mock()
            mock_new_message.return_value = mock_handler
            
            result = self.handler.create_event_handler(mock_entities)
            
            # Verify NewMessage was called with correct parameters
            mock_new_message.assert_called_once_with(
                chats=mock_entities,
                incoming=True
            )
            assert result == mock_handler

    def test_get_monitoring_stats_initial(self):
        """Test monitoring stats with initial values."""
        stats = self.handler.get_monitoring_stats()
        
        assert stats['messages_processed'] == 0
        assert stats['runtime_minutes'] >= 0
        assert stats['messages_per_minute'] == 0
        assert stats['unique_messages_tracked'] == 0
        assert 'start_time' in stats

    def test_get_monitoring_stats_with_messages(self):
        """Test monitoring stats after processing messages."""
        # Simulate processed messages
        self.handler._message_counter = 5
        self.handler._processed_messages = ['msg1', 'msg2', 'msg3']
        
        stats = self.handler.get_monitoring_stats()
        
        assert stats['messages_processed'] == 5
        assert stats['unique_messages_tracked'] == 3
        assert stats['messages_per_minute'] >= 0

    def test_processed_messages_limit(self):
        """Test that processed messages list is limited to prevent memory issues."""
        # Add more than 1000 messages
        test_messages = [f"msg_{i}" for i in range(1200)]
        self.handler._processed_messages = test_messages
        
        # Simulate adding one more message (triggers cleanup)
        mock_message = Mock(spec=Message)
        mock_message.text = "Cleanup test"
        mock_message.id = 99999
        mock_message.date = datetime.now(UTC)
        mock_message.reply_to = None
        mock_message.forward = None
        mock_message.from_id = Mock(user_id=11111)
        mock_message.peer_id = Mock(channel_id=22222)
        
        mock_event = AsyncMock()
        mock_event.message = mock_message
        mock_chat = Mock(title="Cleanup Test")
        mock_event.get_chat.return_value = mock_chat
        
        # Run the handler
        asyncio.run(self.handler.handle_new_message(mock_event))
        
        # Verify list was trimmed
        assert len(self.handler._processed_messages) <= 501  # 500 kept + 1 new message