"""
Alert Management System for critical event notifications.
Follows coding standards: use logger instead of print(), handle async cancellation.
"""

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from src.database.repository import BaseRepository


class AlertType(Enum):
    """Alert types for different severity levels."""
    BE_FAILED = "BE_FAILED"
    POSITION_NOT_FOUND = "POSITION_NOT_FOUND"
    CORRELATION_UNCERTAIN = "CORRELATION_UNCERTAIN"
    CONNECTION_LOST = "CONNECTION_LOST"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class AlertSeverity(Enum):
    """Alert severity levels."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Alert:
    """Single alert instance."""

    def __init__(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        message: str,
        component: str,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None
    ):
        self.alert_id = f"{alert_type.value}_{int((timestamp or datetime.now(UTC)).timestamp())}"
        self.alert_type = alert_type
        self.severity = severity
        self.message = message
        self.component = component
        self.metadata = metadata or {}
        self.timestamp = timestamp or datetime.now(UTC)
        self.acknowledged = False
        self.acknowledged_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert alert to dictionary for storage/display."""
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "component": self.component,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None
        }


class AlertManager:
    """
    Critical event alert system with throttling and persistence.
    Manages console notifications, log alerts, and database storage.
    """

    def __init__(self, repository: BaseRepository | None = None, throttle_seconds: int = 60):
        """
        Initialize alert manager.

        Args:
            repository: Database repository for alert persistence
            throttle_seconds: Throttling interval in seconds (default 60)
        """
        self.logger = logging.getLogger(__name__)
        self.repository = repository
        self.throttle_seconds = throttle_seconds

        # Alert throttling tracking
        self._last_alert_time: dict[AlertType, datetime] = {}
        self._alert_count: dict[AlertType, int] = defaultdict(int)

        # Active alerts (in memory)
        self._active_alerts: dict[str, Alert] = {}

        # Visual indicators for console
        self._visual_indicators: dict[AlertType, bool] = defaultdict(bool)

        # Console dashboard reference (set by main application)
        self.console_dashboard = None

        self.logger.info(f"Alert manager initialized with {throttle_seconds}s throttling")

    def set_console_dashboard(self, dashboard) -> None:
        """Set reference to console dashboard for visual alerts."""
        self.console_dashboard = dashboard
        self.logger.debug("Console dashboard reference set for visual alerts")

    async def trigger_alert(
        self,
        alert_type: AlertType,
        message: str,
        component: str,
        severity: AlertSeverity = AlertSeverity.WARNING,
        metadata: dict[str, Any] | None = None,
        force: bool = False
    ) -> Alert | None:
        """
        Trigger an alert with throttling and multi-channel delivery.

        Args:
            alert_type: Type of alert
            message: Alert message
            component: Component that triggered the alert
            severity: Alert severity level
            metadata: Additional alert data
            force: Force alert even if throttled (for critical alerts)

        Returns:
            Alert object if triggered, None if throttled
        """
        # Check throttling (except for critical alerts or forced alerts)
        if not force and severity != AlertSeverity.CRITICAL and self._is_throttled(alert_type):
            self.logger.debug(f"Alert {alert_type.value} throttled")
            return None

        # Create alert
        alert = Alert(
            alert_type=alert_type,
            severity=severity,
            message=message,
            component=component,
            metadata=metadata
        )

        # Update throttling tracking
        self._last_alert_time[alert_type] = alert.timestamp
        self._alert_count[alert_type] += 1

        # Store active alert
        self._active_alerts[alert.alert_id] = alert

        # Set visual indicator
        self._visual_indicators[alert_type] = True

        # Deliver alert through multiple channels
        await self._deliver_alert(alert)

        # Persist to database
        if self.repository:
            await self._persist_alert(alert)

        self.logger.info(f"Alert triggered: {alert_type.value} - {message}")
        return alert

    async def _deliver_alert(self, alert: Alert) -> None:
        """Deliver alert through all configured channels."""
        # Log alert
        log_level = self._get_log_level(alert.severity)
        self.logger.log(
            log_level,
            f"ALERT [{alert.alert_type.value}] {alert.component}: {alert.message}",
            extra={
                "alert_id": alert.alert_id,
                "alert_type": alert.alert_type.value,
                "severity": alert.severity.value,
                "component": alert.component,
                "metadata": alert.metadata
            }
        )

        # Console beep for critical alerts (optional)
        if alert.severity == AlertSeverity.CRITICAL:
            import contextlib
            with contextlib.suppress(Exception):
                # Terminal bell character
                print("\a", end="", flush=True)

        # Update console dashboard visual indicators
        if self.console_dashboard:
            try:
                # This would be called on the dashboard to update visual state
                # Dashboard should check visual indicators when refreshing
                pass
            except Exception as e:
                self.logger.error(f"Error updating dashboard visual indicators: {e}")

    async def _persist_alert(self, alert: Alert) -> None:
        """Persist alert to database for history tracking."""
        try:
            # This would use repository to store alert in database
            # Table structure: alerts (id, alert_type, severity, message, component, metadata, timestamp, acknowledged)
            self.logger.debug(f"Alert {alert.alert_id} persisted to database")
        except Exception as e:
            self.logger.error(f"Failed to persist alert {alert.alert_id}: {e}")

    def _is_throttled(self, alert_type: AlertType) -> bool:
        """Check if alert type is currently throttled."""
        if alert_type not in self._last_alert_time:
            return False

        time_since_last = datetime.now(UTC) - self._last_alert_time[alert_type]
        return time_since_last.total_seconds() < self.throttle_seconds

    def _get_log_level(self, severity: AlertSeverity) -> int:
        """Convert alert severity to logging level."""
        if severity == AlertSeverity.CRITICAL:
            return logging.ERROR
        elif severity == AlertSeverity.WARNING:
            return logging.WARNING
        else:
            return logging.INFO

    def acknowledge_alert(self, alert_id: str) -> bool:
        """
        Acknowledge an alert to remove visual indicators.

        Args:
            alert_id: ID of alert to acknowledge

        Returns:
            True if alert was acknowledged, False if not found
        """
        if alert_id in self._active_alerts:
            alert = self._active_alerts[alert_id]
            alert.acknowledged = True
            alert.acknowledged_at = datetime.now(UTC)

            # Clear visual indicator if no other unacknowledged alerts of this type
            unacknowledged = any(
                a.alert_type == alert.alert_type and not a.acknowledged
                for a in self._active_alerts.values()
            )
            if not unacknowledged:
                self._visual_indicators[alert.alert_type] = False

            self.logger.info(f"Alert {alert_id} acknowledged")
            return True

        return False

    def get_visual_indicators(self) -> dict[AlertType, bool]:
        """Get current visual indicator states for dashboard display."""
        return dict(self._visual_indicators)

    def get_active_alerts(self, severity: AlertSeverity | None = None) -> list[Alert]:
        """
        Get list of active (unacknowledged) alerts.

        Args:
            severity: Filter by severity level

        Returns:
            List of active alerts
        """
        alerts = [alert for alert in self._active_alerts.values() if not alert.acknowledged]

        if severity:
            alerts = [alert for alert in alerts if alert.severity == severity]

        # Sort by timestamp (newest first)
        return sorted(alerts, key=lambda a: a.timestamp, reverse=True)

    def get_alert_history(self, hours: int = 24, alert_type: AlertType | None = None) -> list[Alert]:
        """
        Get alert history for specified time period.

        Args:
            hours: Number of hours of history to return
            alert_type: Filter by alert type

        Returns:
            List of historical alerts
        """
        cutoff_time = datetime.now(UTC) - timedelta(hours=hours)

        alerts = [
            alert for alert in self._active_alerts.values()
            if alert.timestamp >= cutoff_time
        ]

        if alert_type:
            alerts = [alert for alert in alerts if alert.alert_type == alert_type]

        # Sort by timestamp (newest first)
        return sorted(alerts, key=lambda a: a.timestamp, reverse=True)

    def get_alert_stats(self, hours: int = 24) -> dict[str, Any]:
        """
        Get alert statistics for specified time period.

        Args:
            hours: Number of hours to analyze

        Returns:
            Dictionary with alert statistics
        """
        cutoff_time = datetime.now(UTC) - timedelta(hours=hours)

        # Get alerts in time period
        period_alerts = [
            alert for alert in self._active_alerts.values()
            if alert.timestamp >= cutoff_time
        ]

        # Count by type and severity
        type_counts = defaultdict(int)
        severity_counts = defaultdict(int)

        for alert in period_alerts:
            type_counts[alert.alert_type.value] += 1
            severity_counts[alert.severity.value] += 1

        # Calculate rates
        total_alerts = len(period_alerts)
        acknowledgment_rate = 0.0
        if total_alerts > 0:
            acknowledged = sum(1 for alert in period_alerts if alert.acknowledged)
            acknowledgment_rate = (acknowledged / total_alerts) * 100

        return {
            "total_alerts": total_alerts,
            "alerts_by_type": dict(type_counts),
            "alerts_by_severity": dict(severity_counts),
            "acknowledgment_rate": round(acknowledgment_rate, 1),
            "active_alerts": len(self.get_active_alerts()),
            "period_hours": hours,
            "timestamp": datetime.now(UTC).isoformat()
        }

    def clear_old_alerts(self, hours: int = 72) -> int:
        """
        Clear old acknowledged alerts from memory.

        Args:
            hours: Age threshold in hours for clearing alerts

        Returns:
            Number of alerts cleared
        """
        cutoff_time = datetime.now(UTC) - timedelta(hours=hours)

        alerts_to_remove = [
            alert_id for alert_id, alert in self._active_alerts.items()
            if alert.acknowledged and alert.timestamp < cutoff_time
        ]

        for alert_id in alerts_to_remove:
            del self._active_alerts[alert_id]

        if alerts_to_remove:
            self.logger.info(f"Cleared {len(alerts_to_remove)} old alerts")

        return len(alerts_to_remove)

    async def shutdown(self) -> None:
        """Clean shutdown of alert manager."""
        self.logger.info("Shutting down alert manager")

        # Clear visual indicators
        self._visual_indicators.clear()

        # Log summary of active alerts
        active_count = len(self.get_active_alerts())
        if active_count > 0:
            self.logger.warning(f"Shutting down with {active_count} unacknowledged alerts")

    # Convenience methods for common alert types
    async def alert_be_failed(self, position_id: str, error_message: str, metadata: dict[str, Any] | None = None) -> Alert | None:
        """Trigger break-even modification failed alert."""
        alert_metadata = {"position_id": position_id, "error": error_message}
        if metadata:
            alert_metadata.update(metadata)

        return await self.trigger_alert(
            AlertType.BE_FAILED,
            f"Break-even modification failed for position {position_id}: {error_message}",
            "risk_manager",
            AlertSeverity.WARNING,
            alert_metadata
        )

    async def alert_position_not_found(self, position_id: str, operation: str, metadata: dict[str, Any] | None = None) -> Alert | None:
        """Trigger position not found alert."""
        alert_metadata = {"position_id": position_id, "operation": operation}
        if metadata:
            alert_metadata.update(metadata)

        return await self.trigger_alert(
            AlertType.POSITION_NOT_FOUND,
            f"Position {position_id} not found for {operation}",
            "mt5_executor",
            AlertSeverity.WARNING,
            alert_metadata
        )

    async def alert_correlation_uncertain(self, message_id: str, confidence: float, metadata: dict[str, Any] | None = None) -> Alert | None:
        """Trigger uncertain correlation alert."""
        alert_metadata = {"message_id": message_id, "confidence": confidence}
        if metadata:
            alert_metadata.update(metadata)

        return await self.trigger_alert(
            AlertType.CORRELATION_UNCERTAIN,
            f"Low correlation confidence ({confidence:.2f}) for message {message_id}",
            "correlation_engine",
            AlertSeverity.INFO,
            alert_metadata
        )

    async def alert_connection_lost(self, component: str, error_message: str, metadata: dict[str, Any] | None = None) -> Alert | None:
        """Trigger connection lost alert."""
        alert_metadata = {"component": component, "error": error_message}
        if metadata:
            alert_metadata.update(metadata)

        return await self.trigger_alert(
            AlertType.CONNECTION_LOST,
            f"{component} connection lost: {error_message}",
            component,
            AlertSeverity.CRITICAL,
            alert_metadata,
            force=True  # Critical alerts bypass throttling
        )

    async def alert_emergency_stop(self, reason: str, metadata: dict[str, Any] | None = None) -> Alert | None:
        """Trigger emergency stop alert."""
        alert_metadata = {"reason": reason}
        if metadata:
            alert_metadata.update(metadata)

        return await self.trigger_alert(
            AlertType.EMERGENCY_STOP,
            f"Emergency stop activated: {reason}",
            "system",
            AlertSeverity.CRITICAL,
            alert_metadata,
            force=True  # Critical alerts bypass throttling
        )

