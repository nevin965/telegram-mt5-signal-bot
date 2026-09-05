"""
Enhanced error handling and user-friendly error messages for Telegram authentication.
Provides comprehensive error mapping and retry logic for transient failures.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import ClassVar

from telethon.errors import (
    ApiIdInvalidError,
    BadRequestError,
    FloodWaitError,
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    RPCError,
    SessionPasswordNeededError,
)


@dataclass
class ErrorInfo:
    """Error information with user-friendly message and retry capability."""
    user_message: str
    technical_message: str
    is_retryable: bool
    retry_delay_seconds: int | None = None


class TelegramErrorHandler:
    """
    Provides comprehensive error handling for Telegram authentication operations.
    Maps technical errors to user-friendly messages and implements retry logic.
    """

    ERROR_MAP: ClassVar[dict[type, ErrorInfo]] = {
        ApiIdInvalidError: ErrorInfo(
            user_message="Invalid API credentials. Please check your TELEGRAM_API_ID and TELEGRAM_API_HASH in the .env file.",
            technical_message="Invalid API ID or API Hash provided",
            is_retryable=False,
        ),
        PhoneNumberInvalidError: ErrorInfo(
            user_message="Invalid phone number format. Please ensure your phone number includes the country code (e.g., +1234567890).",
            technical_message="Phone number format is invalid",
            is_retryable=False,
        ),
        PhoneNumberBannedError: ErrorInfo(
            user_message="This phone number has been banned from Telegram. Please contact Telegram support or use a different number.",
            technical_message="Phone number is banned by Telegram",
            is_retryable=False,
        ),
        PhoneCodeEmptyError: ErrorInfo(
            user_message="Please enter the verification code sent to your phone.",
            technical_message="Verification code was empty",
            is_retryable=True,
        ),
        PhoneCodeInvalidError: ErrorInfo(
            user_message="Invalid verification code. Please check the code and try again.",
            technical_message="Verification code is incorrect",
            is_retryable=True,
        ),
        PhoneCodeExpiredError: ErrorInfo(
            user_message="Verification code has expired. A new code will be requested.",
            technical_message="Verification code expired",
            is_retryable=True,
            retry_delay_seconds=5,
        ),
        SessionPasswordNeededError: ErrorInfo(
            user_message="Two-factor authentication is enabled. Please enter your cloud password.",
            technical_message="2FA password required",
            is_retryable=True,
        ),
        RPCError: ErrorInfo(
            user_message="Communication error with Telegram servers. Please try again.",
            technical_message="RPC communication error",
            is_retryable=True,
            retry_delay_seconds=10,
        ),
        BadRequestError: ErrorInfo(
            user_message="Invalid request sent to Telegram. Please check your input and try again.",
            technical_message="Bad request error",
            is_retryable=False,
        ),
    }

    def __init__(self):
        """Initialize error handler."""
        self.logger = logging.getLogger(__name__)

    def get_error_info(self, error: Exception) -> ErrorInfo:
        """
        Get error information for a given exception.

        Args:
            error: Exception to get information for

        Returns:
            ErrorInfo with user-friendly message and retry information
        """
        error_type = type(error)

        # Handle FloodWaitError specially as it has dynamic retry delay
        if isinstance(error, FloodWaitError):
            return ErrorInfo(
                user_message=f"Rate limited by Telegram. Please wait {error.seconds} seconds before trying again.",
                technical_message=f"Flood wait for {error.seconds} seconds",
                is_retryable=True,
                retry_delay_seconds=error.seconds,
            )

        # Check for known error types
        if error_type in self.ERROR_MAP:
            return self.ERROR_MAP[error_type]

        # Default error info for unknown errors
        return ErrorInfo(
            user_message=f"An unexpected error occurred: {error!s}. Please try again or contact support if the problem persists.",
            technical_message=str(error),
            is_retryable=True,
            retry_delay_seconds=5,
        )

    def handle_error(self, error: Exception, operation: str = "Telegram operation") -> tuple[str, bool]:
        """
        Handle an error and provide user-friendly feedback.

        Args:
            error: Exception that occurred
            operation: Description of the operation that failed

        Returns:
            Tuple of (user_message, is_retryable)
        """
        error_info = self.get_error_info(error)

        # Log technical details
        self.logger.error(f"{operation} failed: {error_info.technical_message} ({type(error).__name__})")

        # Log retry information
        if error_info.is_retryable:
            if error_info.retry_delay_seconds:
                self.logger.info(f"Error is retryable after {error_info.retry_delay_seconds} seconds")
            else:
                self.logger.info("Error is retryable")
        else:
            self.logger.info("Error is not retryable")

        return error_info.user_message, error_info.is_retryable

    async def retry_with_backoff(
        self,
        operation_func,
        max_retries: int = 3,
        base_delay: float = 1.0,
        operation_name: str = "operation"
    ) -> tuple[bool, Exception | None]:
        """
        Retry an async operation with exponential backoff.

        Args:
            operation_func: Async function to retry
            max_retries: Maximum number of retry attempts
            base_delay: Base delay between retries in seconds
            operation_name: Name of the operation for logging

        Returns:
            Tuple of (success, last_exception)
        """
        last_exception = None

        for attempt in range(max_retries + 1):  # +1 for initial attempt
            try:
                await operation_func()
                if attempt > 0:
                    self.logger.info(f"{operation_name} succeeded on attempt {attempt + 1}")
                return True, None

            except Exception as e:
                last_exception = e
                error_info = self.get_error_info(e)

                if not error_info.is_retryable:
                    self.logger.error(f"{operation_name} failed with non-retryable error: {error_info.technical_message}")
                    break

                if attempt < max_retries:
                    # Calculate delay
                    if error_info.retry_delay_seconds:
                        delay = error_info.retry_delay_seconds
                    else:
                        delay = base_delay * (2 ** attempt)  # Exponential backoff

                    self.logger.warning(
                        f"{operation_name} failed on attempt {attempt + 1}/{max_retries + 1}, "
                        f"retrying in {delay} seconds: {error_info.technical_message}"
                    )
                    await asyncio.sleep(delay)
                else:
                    self.logger.error(
                        f"{operation_name} failed after {max_retries + 1} attempts: {error_info.technical_message}"
                    )

        return False, last_exception

    def print_user_friendly_error(self, error: Exception, operation: str = "Operation"):
        """
        Display user-friendly error message to console.

        Note: This method uses print() for critical user feedback during authentication.
        This is an intentional exception to the logging rule for user interaction.

        Args:
            error: Exception that occurred
            operation: Description of the operation that failed
        """
        error_info = self.get_error_info(error)

        # Log the error details for debugging
        self.logger.error(f"{operation} failed: {error_info.technical_message}")

        # Display user-friendly message - authentication requires immediate user feedback
        print(f"\n❌ {operation} failed:")
        print(f"   {error_info.user_message}")

        if error_info.is_retryable:
            if error_info.retry_delay_seconds:
                print(f"   Please wait {error_info.retry_delay_seconds} seconds before trying again.")
            else:
                print("   Please try again.")
        else:
            print("   Please fix the issue and restart the application.")
        print()

    async def handle_network_connectivity(self, check_func, max_attempts: int = 5) -> bool:
        """
        Handle network connectivity issues with retry logic.

        Args:
            check_func: Async function that tests connectivity
            max_attempts: Maximum number of connection attempts

        Returns:
            True if connectivity established, False otherwise
        """
        for attempt in range(max_attempts):
            try:
                await check_func()
                if attempt > 0:
                    self.logger.info(f"Network connectivity restored on attempt {attempt + 1}")
                return True

            except (RPCError, ConnectionError, TimeoutError) as e:
                if attempt < max_attempts - 1:
                    delay = min(5 * (2 ** attempt), 60)  # Cap at 60 seconds
                    self.logger.warning(
                        f"Network connectivity issue (attempt {attempt + 1}/{max_attempts}), "
                        f"retrying in {delay} seconds: {e!s}"
                    )
                    await asyncio.sleep(delay)
                else:
                    self.logger.error(f"Failed to establish network connectivity after {max_attempts} attempts")
                    self.print_user_friendly_error(e, "Network connection")
                    return False

            except Exception as e:
                self.logger.error(f"Unexpected error during connectivity check: {e!s}")
                return False

        return False


# Global error handler instance
error_handler = TelegramErrorHandler()
