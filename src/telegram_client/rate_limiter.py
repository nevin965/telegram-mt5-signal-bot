"""
Human-like rate limiting for Telegram operations.
Implements Gaussian delay distribution with time-of-day variations and flood error handling.
Follows coding standards: use logger instead of print(), handle async cancellation.
"""

import asyncio
import logging
import random
from datetime import datetime

from telethon.errors import FloodWaitError


class RateLimiter:
    """
    Implements human-like delays for Telegram operations to avoid detection.
    Uses Gaussian distribution with time-of-day variations.
    """

    def __init__(self, base_delay_ms: float = 2000.0, std_dev_ms: float = 500.0):
        """
        Initialize rate limiter with configuration.

        Args:
            base_delay_ms: Base delay in milliseconds (default: 2000ms)
            std_dev_ms: Standard deviation for Gaussian distribution (default: 500ms)
        """
        self.logger = logging.getLogger(__name__)
        self.base_delay_ms = base_delay_ms
        self.std_dev_ms = std_dev_ms
        self.min_delay_ms = 1000.0  # Minimum delay of 1 second
        self.max_delay_ms = 5000.0  # Maximum delay of 5 seconds
        self._daily_message_count = 0
        self._last_reset_date = datetime.now().date()
        self._max_daily_messages = 1000

    async def human_delay(self) -> None:
        """
        Apply human-like delay with Gaussian distribution and time-of-day variation.
        Cancellation-safe according to coding standards.
        """
        try:
            # Check daily message limit
            await self._check_daily_limit()

            # Calculate base delay with Gaussian distribution
            delay_ms = random.gauss(self.base_delay_ms, self.std_dev_ms)

            # Apply time-of-day factor
            time_factor = self._get_time_of_day_factor()
            adjusted_delay_ms = delay_ms * time_factor

            # Clamp to min/max bounds
            final_delay_ms = max(self.min_delay_ms, min(self.max_delay_ms, adjusted_delay_ms))

            # Convert to seconds and apply delay
            delay_seconds = final_delay_ms / 1000.0

            self.logger.debug(f"Applying human delay: {delay_seconds:.2f}s (factor: {time_factor:.1f})")
            await asyncio.sleep(delay_seconds)

            # Increment message count
            self._daily_message_count += 1

        except asyncio.CancelledError:
            # Handle cancellation gracefully as per coding standards
            self.logger.info("Rate limiter delay cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error in human delay: {e}")
            # Fall back to minimum delay
            await asyncio.sleep(self.min_delay_ms / 1000.0)

    def _get_time_of_day_factor(self) -> float:
        """
        Get time-of-day factor for delay adjustment.
        Active hours (8:00-23:00) have factor 1.0, night hours have factor 1.5.

        Returns:
            Time factor multiplier (0.5-1.5)
        """
        current_hour = datetime.now().hour

        if 8 <= current_hour < 23:
            # Active hours - normal activity
            return 1.0
        else:
            # Night hours - slower activity to simulate human behavior
            return 1.5

    async def _check_daily_limit(self) -> None:
        """
        Check and reset daily message counter if needed.
        Enforces maximum daily message limit for anti-detection.
        """
        current_date = datetime.now().date()

        # Reset counter if it's a new day
        if current_date != self._last_reset_date:
            self.logger.info(f"New day detected, resetting message count. Previous count: {self._daily_message_count}")
            self._daily_message_count = 0
            self._last_reset_date = current_date

        # Check if we've exceeded daily limit
        if self._daily_message_count >= self._max_daily_messages:
            self.logger.warning(f"Daily message limit reached ({self._max_daily_messages}). Applying extended delay.")
            # Apply extended delay to reduce activity
            await asyncio.sleep(60)  # 1 minute delay

    async def handle_flood_wait(self, error: FloodWaitError) -> None:
        """
        Handle Telegram flood wait errors with exponential backoff.

        Args:
            error: FloodWaitError from Telegram API
        """
        wait_seconds = error.seconds * 1.5  # Add 50% buffer as per strategy

        self.logger.warning(
            f"Flood wait error: waiting {wait_seconds:.1f} seconds "
            f"(original: {error.seconds}s with 1.5x buffer)"
        )

        try:
            await asyncio.sleep(wait_seconds)
        except asyncio.CancelledError:
            self.logger.info("Flood wait handling cancelled")
            raise

    def get_daily_stats(self) -> dict:
        """
        Get daily rate limiting statistics.

        Returns:
            Dictionary with daily statistics
        """
        return {
            'daily_message_count': self._daily_message_count,
            'max_daily_messages': self._max_daily_messages,
            'remaining_messages': max(0, self._max_daily_messages - self._daily_message_count),
            'current_date': self._last_reset_date.isoformat(),
            'time_factor': self._get_time_of_day_factor()
        }

    def reset_daily_counter(self) -> None:
        """
        Manually reset daily message counter.
        Useful for testing or administrative purposes.
        """
        old_count = self._daily_message_count
        self._daily_message_count = 0
        self._last_reset_date = datetime.now().date()
        self.logger.info(f"Manually reset daily counter from {old_count} to 0")


# Global rate limiter instance
rate_limiter = RateLimiter()
