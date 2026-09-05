"""
Telegram client module for user session management and authentication.
Provides comprehensive Telegram integration with proper error handling.
"""

from .auth_manager import AuthManager
from .client import TelegramClient
from .errors import TelegramErrorHandler, error_handler
from .session_manager import SessionManager

__all__ = [
    "AuthManager",
    "SessionManager",
    "TelegramClient",
    "TelegramErrorHandler",
    "error_handler",
]
