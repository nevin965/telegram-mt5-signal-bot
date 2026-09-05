"""
Authentication manager for Telegram session startup and validation.
Orchestrates the complete authentication flow with startup checks.
"""

import asyncio
import logging

from .client import TelegramClient
from .session_manager import SessionManager


class AuthManager:
    """
    High-level authentication manager that orchestrates the complete
    authentication flow including startup checks and re-authentication.
    """

    def __init__(self, session_name: str = "telegram"):
        """
        Initialize authentication manager.

        Args:
            session_name: Name for the session file (without .session extension)
        """
        self.logger = logging.getLogger(__name__)
        self.session_name = session_name
        self.telegram_client = TelegramClient(session_name)
        self.session_manager = SessionManager(self.telegram_client)
        self._is_authenticated = False

    async def startup_authentication(self) -> bool:
        """
        Complete startup authentication flow.
        Validates existing session or performs new authentication.

        Returns:
            True if authentication successful, False otherwise
        """
        try:
            self.logger.info("Starting Telegram authentication process...")

            # Initialize client
            if not await self.telegram_client.initialize():
                self.logger.error("Failed to initialize Telegram client")
                return False

            # Connect to Telegram
            if not await self.telegram_client.connect():
                self.logger.error("Failed to connect to Telegram")
                return False

            # Check if existing session is valid
            if await self._validate_existing_session():
                self.logger.info("Existing session validated successfully")
                self._is_authenticated = True
                return True

            # Existing session invalid or doesn't exist, perform new authentication
            self.logger.info("No valid session found, starting authentication flow...")

            if await self.session_manager.authenticate():
                self.logger.info("New authentication successful")
                self._is_authenticated = True
                return True
            else:
                self.logger.error("Authentication failed")
                return False

        except Exception as e:
            self.logger.error(f"Startup authentication failed: {e}")
            return False

    async def _validate_existing_session(self) -> bool:
        """
        Validate existing session if it exists.

        Returns:
            True if existing session is valid, False otherwise
        """
        try:
            # Check if session file exists
            if not self.session_manager.session_exists():
                self.logger.info("No existing session file found")
                return False

            # Validate the session
            if await self.session_manager.validate_session():
                self.logger.info("Existing session is valid and active")
                return True
            else:
                self.logger.info("Existing session is invalid or expired")
                return False

        except Exception as e:
            self.logger.error(f"Error validating existing session: {e}")
            return False

    async def re_authenticate(self) -> bool:
        """
        Re-authenticate if current session becomes invalid.
        Used when session expires during runtime.

        Returns:
            True if re-authentication successful, False otherwise
        """
        try:
            self.logger.info("Re-authenticating Telegram session...")
            self._is_authenticated = False

            # Disconnect and reconnect
            await self.telegram_client.disconnect()

            # Wait a moment before reconnecting
            await asyncio.sleep(1.0)

            if not await self.telegram_client.connect():
                self.logger.error("Failed to reconnect during re-authentication")
                return False

            # Perform authentication
            if await self.session_manager.authenticate():
                self.logger.info("Re-authentication successful")
                self._is_authenticated = True
                return True
            else:
                self.logger.error("Re-authentication failed")
                return False

        except Exception as e:
            self.logger.error(f"Re-authentication failed: {e}")
            return False

    async def check_connection_status(self) -> dict:
        """
        Check current connection and authentication status.

        Returns:
            Dictionary with connection status information
        """
        try:
            status = {
                "connected": await self.telegram_client.is_connected(),
                "authorized": await self.telegram_client.is_authorized(),
                "session_file_exists": self.session_manager.session_exists(),
                "authenticated": self._is_authenticated,
            }

            # Get user info if authorized
            if status["authorized"]:
                try:
                    me = await self.telegram_client.client.get_me()
                    status["user_info"] = {
                        "id": me.id,
                        "first_name": me.first_name,
                        "username": getattr(me, 'username', None),
                        "phone": getattr(me, 'phone', None),
                    }
                except Exception as e:
                    self.logger.warning(f"Could not get user info: {e}")
                    status["user_info"] = None

            return status

        except Exception as e:
            self.logger.error(f"Error checking connection status: {e}")
            return {
                "connected": False,
                "authorized": False,
                "session_file_exists": False,
                "authenticated": False,
                "error": str(e),
            }

    async def periodic_health_check(self, interval_seconds: int = 300) -> None:
        """
        Periodic health check that validates session and re-authenticates if needed.
        Run this as a background task.

        Args:
            interval_seconds: Interval between health checks in seconds
        """
        self.logger.info(f"Starting periodic health check (interval: {interval_seconds}s)")

        while True:
            try:
                await asyncio.sleep(interval_seconds)

                self.logger.debug("Performing periodic health check...")

                # Check if still connected and authorized
                if not await self.telegram_client.is_connected():
                    self.logger.warning("Connection lost, attempting to reconnect...")
                    if not await self.telegram_client.connect():
                        self.logger.error("Failed to reconnect during health check")
                        continue

                if not await self.telegram_client.is_authorized():
                    self.logger.warning("Authorization lost, attempting to re-authenticate...")
                    if not await self.re_authenticate():
                        self.logger.error("Failed to re-authenticate during health check")
                        continue

                self.logger.debug("Health check passed")

            except asyncio.CancelledError:
                self.logger.info("Periodic health check cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error during periodic health check: {e}")

    async def cleanup(self) -> None:
        """
        Cleanup resources and disconnect from Telegram.
        Call this when shutting down the application.
        """
        try:
            self.logger.info("Cleaning up authentication manager...")
            await self.telegram_client.disconnect()
            self._is_authenticated = False
            self.logger.info("Authentication manager cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

    def is_authenticated(self) -> bool:
        """
        Check if currently authenticated.

        Returns:
            True if authenticated, False otherwise
        """
        return self._is_authenticated

    async def __aenter__(self):
        """Async context manager entry."""
        if not await self.startup_authentication():
            raise RuntimeError("Failed to authenticate Telegram session")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with proper cleanup."""
        await self.cleanup()
