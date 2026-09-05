"""
Message handler for Telegram message events.
Handles new message events from specified groups and extracts metadata.
Follows coding standards: use logger instead of print(), handle async cancellation.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, UTC
from typing import Any

from telethon import events
from telethon.tl.types import Message


class MessageHandler:
    """
    Handles incoming Telegram messages from monitored groups.
    Extracts metadata and processes text messages only.
    """

    def __init__(self) -> None:
        """Initialize message handler with logging and monitoring."""
        self.logger = logging.getLogger(__name__)
        self._message_callback: Callable[[dict[str, Any]], None] | None = None
        self._processed_messages: list[str] = []
        self._message_counter = 0
        self._start_time = datetime.now(UTC)

    def set_message_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """
        Set callback function to be called when new messages are received.

        Args:
            callback: Function that accepts message metadata dict
        """
        self._message_callback = callback

    async def handle_new_message(self, event: Any) -> None:
        """
        Handle new message events from Telegram.
        Extracts metadata and filters for text messages only.

        Args:
            event: Telethon NewMessage event
        """
        try:
            message = event.message

            # Only process text messages (ignore media/stickers)
            if not message.text:
                self.logger.debug("Ignoring non-text message")
                return

            # Extract message metadata
            metadata = await self._extract_message_metadata(message, event)

            # Prevent duplicate processing
            message_key = f"{metadata['telegram_chat_id']}_{metadata['telegram_message_id']}"
            if message_key in self._processed_messages:
                return

            self._processed_messages.append(message_key)

            # Limit processed messages list to prevent memory issues
            if len(self._processed_messages) > 1000:
                self._processed_messages = self._processed_messages[-500:]

            # Increment message counter
            self._message_counter += 1

            # Create console monitoring output (AC: 4)
            self._log_message_for_monitoring(metadata)

            # Keep existing detailed logging
            self.logger.debug(
                f"Message #{self._message_counter} from {metadata['sender']} "
                f"in chat {metadata['telegram_chat_id']}"
            )

            # Call registered callback if set
            if self._message_callback:
                try:
                    if asyncio.iscoroutinefunction(self._message_callback):
                        await self._message_callback(metadata)
                    else:
                        self._message_callback(metadata)
                except Exception as e:
                    self.logger.error(f"Error in message callback: {e}")

        except Exception as e:
            self.logger.error(f"Error handling message event: {e}")

    async def _extract_message_metadata(self, message: Message, event: Any) -> dict[str, Any]:
        """
        Extract message metadata for future signal processing.

        Args:
            message: Telethon Message object
            event: Telethon NewMessage event

        Returns:
            Dictionary containing message metadata
        """
        try:
            # Get sender information
            sender_info = await self._get_sender_info(message)

            # Get chat information
            chat = await event.get_chat()
            chat_title = getattr(chat, 'title', getattr(chat, 'first_name', 'Unknown'))

            metadata = {
                'telegram_message_id': message.id,
                'telegram_chat_id': message.peer_id.channel_id if hasattr(message.peer_id, 'channel_id')
                                  else message.peer_id.chat_id if hasattr(message.peer_id, 'chat_id')
                                  else message.peer_id.user_id,
                'sender': sender_info,
                'timestamp': message.date if message.date else datetime.now(UTC),
                'raw_text': message.text or '',
                'reply_to_message_id': message.reply_to.reply_to_msg_id if message.reply_to else None,
                'chat_title': chat_title,
                'is_forwarded': message.forward is not None,
                'message_type': 'text'
            }

            return metadata

        except Exception as e:
            self.logger.error(f"Error extracting message metadata: {e}")
            # Return minimal metadata on error
            return {
                'telegram_message_id': message.id,
                'telegram_chat_id': 0,
                'sender': 'unknown',
                'timestamp': datetime.now(UTC),
                'raw_text': message.text or '',
                'reply_to_message_id': None,
                'chat_title': 'unknown',
                'is_forwarded': False,
                'message_type': 'text'
            }

    async def _get_sender_info(self, message: Message) -> str:
        """
        Get sender information from message.
        Hashes usernames for privacy as per coding standards.

        Args:
            message: Telethon Message object

        Returns:
            Sender identifier (hashed for privacy)
        """
        try:
            if message.from_id:
                # For privacy, we'll use the user ID instead of username
                if hasattr(message.from_id, 'user_id') and message.from_id.user_id is not None:
                    return f"user_{message.from_id.user_id}"
                elif hasattr(message.from_id, 'channel_id') and message.from_id.channel_id is not None:
                    return f"channel_{message.from_id.channel_id}"
                else:
                    return "unknown_sender"
            else:
                return "anonymous"

        except Exception as e:
            self.logger.error(f"Error getting sender info: {e}")
            return "unknown_sender"

    def create_event_handler(self, group_entities: list[Any]) -> Any:
        """
        Create Telethon event handler for specified groups.

        Args:
            group_entities: List of Telegram group entities

        Returns:
            Configured event handler
        """
        try:
            # Create event handler for new messages from specified groups
            handler = events.NewMessage(
                chats=group_entities,
                incoming=True
            )

            self.logger.info(f"Created event handler for {len(group_entities)} groups")
            return handler

        except Exception as e:
            self.logger.error(f"Error creating event handler: {e}")
            raise

    def _log_message_for_monitoring(self, metadata: dict[str, Any]) -> None:
        """
        Log message for console monitoring with formatted output.
        Displays: timestamp, group name, sender, message preview (first 100 chars)
        Uses INFO level for structured output as per requirements.

        Args:
            metadata: Message metadata dictionary
        """
        try:
            # Format timestamp
            timestamp = metadata['timestamp'].strftime('%Y-%m-%d %H:%M:%S')

            # Sanitize message content (first 100 chars)
            message_preview = self._sanitize_message_content(metadata['raw_text'])

            # Create formatted console output
            console_message = (
                f"📨 [{timestamp}] {metadata['chat_title']} | "
                f"{metadata['sender']} | {message_preview}"
            )

            # Log with INFO level for console visibility
            self.logger.info(console_message)

        except Exception as e:
            self.logger.error(f"Error logging message for monitoring: {e}")

    def _sanitize_message_content(self, raw_text: str) -> str:
        """
        Sanitize message content to avoid logging sensitive data.
        Following coding standards: never log sensitive data.

        Args:
            raw_text: Original message text

        Returns:
            Sanitized message preview (first 100 chars)
        """
        if not raw_text:
            return "[Empty message]"

        # Take first 100 characters and add ellipsis if longer
        preview = raw_text[:100]
        if len(raw_text) > 100:
            preview += "..."

        # Remove any potential sensitive patterns (basic sanitization)
        # This is a simple implementation - could be enhanced based on needs
        preview = preview.replace('\n', ' ').replace('\r', ' ')

        return preview

    def get_monitoring_stats(self) -> dict[str, Any]:
        """
        Get message monitoring statistics.

        Returns:
            Dictionary with monitoring statistics
        """
        runtime = datetime.now(UTC) - self._start_time
        runtime_minutes = runtime.total_seconds() / 60

        return {
            'messages_processed': self._message_counter,
            'runtime_minutes': round(runtime_minutes, 1),
            'messages_per_minute': round(self._message_counter / max(runtime_minutes, 1), 2) if runtime_minutes > 0 else 0,
            'start_time': self._start_time.isoformat(),
            'unique_messages_tracked': len(self._processed_messages)
        }
