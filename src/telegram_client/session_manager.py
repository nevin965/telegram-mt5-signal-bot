"""
Session authentication manager for Telegram user sessions.
Follows coding standards: use logger instead of print(), handle SMS/code verification.
"""

import logging

from telethon.errors import (
    FloodWaitError,
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeHashEmptyError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from config.settings import settings

from .client import TelegramClient


class SessionManager:
    """
    Manages Telegram session authentication including phone verification.
    Handles the complete authentication flow with user prompts.
    """

    def __init__(self, telegram_client: TelegramClient):
        """
        Initialize session manager with a TelegramClient instance.

        Args:
            telegram_client: TelegramClient instance to manage authentication for
        """
        self.logger = logging.getLogger(__name__)
        self.client = telegram_client
        self._phone_code_hash: str | None = None

    async def authenticate(self) -> bool:
        """
        Complete authentication flow for Telegram user session.
        Handles phone number verification and SMS/code input.

        Returns:
            True if authentication successful, False otherwise
        """
        if not self.client.client:
            self.logger.error("Telegram client not initialized")
            return False

        try:
            # Check if already authorized
            if await self.client.is_authorized():
                self.logger.info("User already authenticated")
                return True

            # Start phone authentication flow
            if not await self._request_phone_code():
                return False

            # Get verification code from user
            if not await self._verify_phone_code():
                return False

            # Handle two-factor authentication if needed
            if not await self._handle_2fa_if_needed():
                return False

            self.logger.info("Authentication completed successfully")
            return True

        except Exception as e:
            self.logger.error(f"Authentication failed: {e}")
            return False

    async def _request_phone_code(self) -> bool:
        """
        Request SMS/call code for phone number verification.

        Returns:
            True if code request successful, False otherwise
        """
        phone_number = settings.phone_number

        try:
            self.logger.info(f"Requesting verification code for phone: {phone_number}")

            # Request code from Telegram
            sent_code = await self.client.client.send_code_request(phone_number)
            self._phone_code_hash = sent_code.phone_code_hash

            # Log the type of verification sent
            code_type = getattr(sent_code.type, '__class__.__name__', 'Unknown')
            self.logger.info(f"Verification code sent via {code_type}")

            return True

        except PhoneNumberInvalidError:
            self.logger.error(f"Invalid phone number: {phone_number}")
            return False
        except PhoneNumberBannedError:
            self.logger.error(f"Phone number banned: {phone_number}")
            return False
        except FloodWaitError as e:
            self.logger.warning(f"Rate limited, wait {e.seconds} seconds before retrying")
            return False
        except Exception as e:
            self.logger.error(f"Failed to request phone code: {e}")
            return False

    async def _verify_phone_code(self) -> bool:
        """
        Verify phone code entered by user.
        Prompts user for verification code input.

        Returns:
            True if verification successful, False otherwise
        """
        if not self._phone_code_hash:
            self.logger.error("No phone code hash available")
            return False

        max_attempts = 3
        phone_number = settings.phone_number

        for attempt in range(max_attempts):
            try:
                # Prompt user for verification code
                self.logger.info(f"Verification code sent to {phone_number}")
                self.logger.info("Please check your phone for the verification code")
                # User interaction requires console output - this is an exception to the print rule
                self.logger.info("Prompting user for verification code input")

                # Get code from user input
                # Note: input() requires terminal interaction, acceptable for authentication flow
                verification_code = input("\nVerification code sent. Please enter it (usually 5-6 digits): ").strip()

                if not verification_code:
                    self.logger.warning("Empty verification code entered")
                    continue

                self.logger.info(f"Attempting to verify code (attempt {attempt + 1}/{max_attempts})")

                # Sign in with the verification code
                await self.client.client.sign_in(
                    phone=phone_number,
                    code=verification_code,
                    phone_code_hash=self._phone_code_hash,
                )

                self.logger.info("Phone verification successful")
                return True

            except PhoneCodeEmptyError:
                self.logger.warning("Empty verification code provided")
            except PhoneCodeInvalidError:
                self.logger.warning(f"Invalid verification code (attempt {attempt + 1}/{max_attempts})")
            except PhoneCodeExpiredError:
                self.logger.error("Verification code expired, need to request new code")
                return False
            except PhoneCodeHashEmptyError:
                self.logger.error("Phone code hash is empty")
                return False
            except SessionPasswordNeededError:
                self.logger.info("Two-factor authentication required")
                return True  # Will be handled in _handle_2fa_if_needed
            except Exception as e:
                self.logger.error(f"Verification failed: {e}")

            if attempt < max_attempts - 1:
                self.logger.warning(f"Invalid code. {max_attempts - attempt - 1} attempts remaining")
                # User feedback requires console output during interactive authentication
                if attempt < max_attempts - 1:
                    print(f"Invalid code. Please try again ({max_attempts - attempt - 1} attempts remaining)")

        self.logger.error("Max verification attempts reached")
        return False

    async def _handle_2fa_if_needed(self) -> bool:
        """
        Handle two-factor authentication if required.

        Returns:
            True if 2FA successful or not needed, False otherwise
        """
        try:
            # Check if user is already authorized after phone verification
            if await self.client.is_authorized():
                return True

            # If we reach here, 2FA might be needed
            self.logger.info("Checking if two-factor authentication is required...")

            # Try to get user info to trigger 2FA prompt if needed
            try:
                await self.client.client.get_me()
                return True
            except SessionPasswordNeededError:
                return await self._handle_2fa_password()

        except Exception as e:
            self.logger.error(f"Error checking 2FA status: {e}")
            return False

        return True

    async def _handle_2fa_password(self) -> bool:
        """
        Handle two-factor authentication password entry.

        Returns:
            True if 2FA successful, False otherwise
        """
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                self.logger.info("Two-factor authentication required")
                # User interaction requires console output for password prompt
                print("\nTwo-factor authentication required")

                # Get password from user - use getpass for secure password input
                import getpass
                password = getpass.getpass("Cloud password: ").strip()

                if not password:
                    self.logger.warning("Empty password entered")
                    continue

                self.logger.info(f"Attempting 2FA verification (attempt {attempt + 1}/{max_attempts})")

                # Sign in with password
                await self.client.client.sign_in(password=password)

                self.logger.info("Two-factor authentication successful")
                return True

            except Exception as e:
                self.logger.warning(f"2FA verification failed (attempt {attempt + 1}/{max_attempts}): {e}")

            if attempt < max_attempts - 1:
                self.logger.warning(f"Invalid password. {max_attempts - attempt - 1} attempts remaining")
                if attempt < max_attempts - 1:
                    print(f"Invalid password. Please try again ({max_attempts - attempt - 1} attempts remaining)")

        self.logger.error("Max 2FA attempts reached")
        return False

    async def validate_session(self) -> bool:
        """
        Validate existing session and check if it's still active.

        Returns:
            True if session is valid and active, False otherwise
        """
        try:
            if not await self.client.is_connected():
                self.logger.info("Client not connected, attempting to connect...")
                if not await self.client.connect():
                    return False

            if not await self.client.is_authorized():
                self.logger.info("Session not authorized")
                return False

            # Try to get user info to confirm session is working
            me = await self.client.client.get_me()
            if me:
                self.logger.info(f"Session validated successfully for user: {me.first_name}")
                return True
            else:
                self.logger.warning("Could not retrieve user information")
                return False

        except Exception as e:
            self.logger.error(f"Session validation failed: {e}")
            return False

    def session_exists(self) -> bool:
        """
        Check if a session file exists on disk.

        Returns:
            True if session file exists, False otherwise
        """
        session_path = self.client.get_session_path()
        exists = session_path.exists()

        if exists:
            self.logger.info(f"Session file found at: {session_path}")
        else:
            self.logger.info(f"No session file found at: {session_path}")

        return exists
