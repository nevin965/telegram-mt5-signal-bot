"""
Emergency stop system for halting all trading operations.
Follows coding standards: use logger instead of print(), thread-safe implementation.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any


class EmergencyStopManager:
    """
    Global emergency stop manager for the trading system.
    Provides thread-safe access to emergency stop flag across all components.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._stop_flag = False
        self._stop_time: datetime | None = None
        self._stop_reason: str | None = None
        self._lock = asyncio.Lock()

        self.logger.info("Emergency stop manager initialized")

    async def trigger_emergency_stop(self, reason: str = "Manual stop command") -> None:
        """
        Trigger emergency stop with reason.

        Args:
            reason: Reason for emergency stop
        """
        async with self._lock:
            if not self._stop_flag:
                self._stop_flag = True
                self._stop_time = datetime.now(UTC)
                self._stop_reason = reason

                self.logger.critical(f"EMERGENCY STOP TRIGGERED: {reason}")
            else:
                self.logger.warning(f"Emergency stop already active: {self._stop_reason}")

    async def resume_operations(self) -> None:
        """Resume normal operations after emergency stop."""
        async with self._lock:
            if self._stop_flag:
                self._stop_flag = False
                previous_reason = self._stop_reason
                self._stop_time = None
                self._stop_reason = None

                self.logger.warning(f"Operations resumed after emergency stop: {previous_reason}")
            else:
                self.logger.info("Resume called but emergency stop was not active")

    def is_stopped(self) -> bool:
        """
        Check if emergency stop is active.

        Returns:
            True if emergency stop is active
        """
        return self._stop_flag

    def get_stop_info(self) -> dict[str, Any]:
        """
        Get information about current emergency stop status.

        Returns:
            Dictionary with stop status information
        """
        return {
            "is_stopped": self._stop_flag,
            "stop_time": self._stop_time.isoformat() if self._stop_time else None,
            "stop_reason": self._stop_reason,
            "duration_seconds": (
                (datetime.now(UTC) - self._stop_time).total_seconds()
                if self._stop_time else None
            )
        }


# Global instance for use across the application
emergency_stop_manager = EmergencyStopManager()

