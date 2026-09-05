"""
Health Monitor component for system health checks.
Follows coding standards: use logger, handle async cancellation, circuit breaker for external calls.
"""

import asyncio
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.utils.circuit_breaker import circuit_breaker


class HealthStatus(Enum):
    """Health status levels for system components."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth:
    """Health information for a single component."""

    def __init__(
        self,
        name: str,
        status: HealthStatus = HealthStatus.UNHEALTHY,
        message: str = "",
        last_check: datetime | None = None,
        details: dict[str, Any] | None = None
    ):
        self.name = name
        self.status = status
        self.message = message
        self.last_check = last_check or datetime.now(UTC)
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging and display."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "last_check": self.last_check.isoformat(),
            "details": self.details
        }


class HealthMonitor:
    """
    System health monitoring component.
    Performs health checks on all system components every 60 seconds.
    """

    def __init__(self, check_interval: int = 60):
        """
        Initialize health monitor.
        
        Args:
            check_interval: Health check interval in seconds (default 60)
        """
        self.logger = logging.getLogger(__name__)
        self.check_interval = check_interval
        self._monitoring_task: asyncio.Task | None = None
        self._component_healths: dict[str, ComponentHealth] = {}
        self._is_running = False

        # Component references (set by main application)
        self.telegram_client = None
        self.mt5_connection = None
        self.openai_client = None

        self.logger.info(f"Health monitor initialized with {check_interval}s interval")

    def set_telegram_client(self, client) -> None:
        """Set reference to Telegram client for health checks."""
        self.telegram_client = client
        self.logger.debug("Telegram client reference set")

    def set_mt5_connection(self, connection) -> None:
        """Set reference to MT5 connection for health checks."""
        self.mt5_connection = connection
        self.logger.debug("MT5 connection reference set")

    def set_openai_client(self, client) -> None:
        """Set reference to OpenAI client for health checks."""
        self.openai_client = client
        self.logger.debug("OpenAI client reference set")

    async def start_monitoring(self) -> None:
        """Start health monitoring loop."""
        if self._is_running:
            self.logger.warning("Health monitoring already running")
            return

        self.logger.info("Starting health monitoring")
        self._is_running = True
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())

    async def stop_monitoring(self) -> None:
        """Stop health monitoring loop with proper cleanup."""
        if not self._is_running:
            return

        self.logger.info("Stopping health monitoring")
        self._is_running = False

        if self._monitoring_task:
            try:
                self._monitoring_task.cancel()
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.logger.error(f"Error stopping monitoring task: {e}")
            finally:
                self._monitoring_task = None

        self.logger.info("Health monitoring stopped")

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop - runs health checks every interval."""
        try:
            # Perform initial health check immediately
            await self._perform_health_checks()

            while self._is_running:
                await asyncio.sleep(self.check_interval)

                if not self._is_running:
                    break

                try:
                    await self._perform_health_checks()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.logger.error(f"Error during health checks: {e}")

        except asyncio.CancelledError:
            self.logger.info("Health monitoring loop cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Health monitoring loop terminated with error: {e}")

    async def _perform_health_checks(self) -> None:
        """Perform health checks on all configured components."""
        self.logger.debug("Performing health checks")

        # Check Telegram connection
        if self.telegram_client:
            await self._check_telegram_health()
        else:
            self._update_component_health(
                "telegram",
                HealthStatus.UNHEALTHY,
                "Telegram client not configured"
            )

        # Check MT5 connection
        if self.mt5_connection:
            await self._check_mt5_health()
        else:
            self._update_component_health(
                "mt5",
                HealthStatus.DEGRADED,
                "MT5 connection not configured"
            )

        # Check OpenAI client
        if self.openai_client:
            await self._check_openai_health()
        else:
            self._update_component_health(
                "openai",
                HealthStatus.DEGRADED,
                "OpenAI client not configured"
            )

        # Log overall system health status
        self._log_system_health_summary()

    @circuit_breaker(failure_threshold=3, recovery_timeout=30)
    async def _check_telegram_health(self) -> None:
        """Check Telegram connection health with circuit breaker protection."""
        try:
            # Use existing health check from TelegramClient
            is_connected = await self.telegram_client.is_connected()
            is_authorized = await self.telegram_client.is_authorized()

            if is_connected and is_authorized:
                # Get additional status information
                status = self.telegram_client.get_connection_status()

                self._update_component_health(
                    "telegram",
                    HealthStatus.HEALTHY,
                    "Connection active and authorized",
                    details={
                        "connected_groups": status.get("connected_groups_count", 0),
                        "connection_failures": status.get("connection_failures", 0),
                        "last_client_health_check": status.get("last_health_check"),
                        "auto_reconnect_enabled": status.get("auto_reconnect_enabled", False)
                    }
                )
            elif is_connected and not is_authorized:
                self._update_component_health(
                    "telegram",
                    HealthStatus.DEGRADED,
                    "Connected but not authorized"
                )
                # Log ERROR level alert as required by AC 5
                self.logger.error("Telegram connection degraded: user not authorized")
            else:
                self._update_component_health(
                    "telegram",
                    HealthStatus.UNHEALTHY,
                    "Not connected to Telegram"
                )
                # Log ERROR level alert as required by AC 5
                self.logger.error("Telegram connection failed: not connected")

        except Exception as e:
            self._update_component_health(
                "telegram",
                HealthStatus.UNHEALTHY,
                f"Health check failed: {e}"
            )
            # Log ERROR level alert as required by AC 5
            self.logger.error(f"Telegram health check exception: {e}")

    async def _check_mt5_health(self) -> None:
        """
        Check MT5 connection health.
        Calls the health_check method on the MT5 connection manager.
        """
        if not self.mt5_connection:
            self._update_component_health(
                "mt5",
                HealthStatus.DEGRADED,
                "MT5 connection not configured"
            )
            return

        try:
            # Check if the connection has an async health_check method
            if hasattr(self.mt5_connection, 'health_check'):
                is_healthy = await self.mt5_connection.health_check()
                if is_healthy:
                    self._update_component_health(
                        "mt5",
                        HealthStatus.HEALTHY,
                        "MT5 connection is healthy"
                    )
                else:
                    self._update_component_health(
                        "mt5",
                        HealthStatus.DEGRADED,
                        "MT5 connection is unhealthy"
                    )
            # Fallback: check for synchronous is_connected
            elif hasattr(self.mt5_connection, 'is_connected'):
                try:
                    is_connected = self.mt5_connection.is_connected()
                    if is_connected:
                        self._update_component_health(
                            "mt5",
                            HealthStatus.HEALTHY,
                            "MT5 connection is connected"
                        )
                    else:
                        self._update_component_health(
                            "mt5",
                            HealthStatus.DEGRADED,
                            "MT5 connection is not connected"
                        )
                except Exception as e:
                    self._update_component_health(
                        "mt5",
                        HealthStatus.DEGRADED,
                        f"MT5 connection check failed: {e}"
                    )
            else:
                # No health check method available
                self._update_component_health(
                    "mt5",
                    HealthStatus.DEGRADED,
                    "MT5 health check method not available"
                )
        except Exception as e:
            self._update_component_health(
                "mt5",
                HealthStatus.DEGRADED,
                f"MT5 health check error: {e}"
            )

    async def _check_openai_health(self) -> None:
        """Check OpenAI client health."""
        if not self.openai_client:
            self._update_component_health(
                "openai",
                HealthStatus.DEGRADED,
                "OpenAI client not configured"
            )
            return

        try:
            # Check if the client has a health_check method
            if hasattr(self.openai_client, 'health_check'):
                is_healthy = await self.openai_client.health_check()
                if is_healthy:
                    self._update_component_health(
                        "openai",
                        HealthStatus.HEALTHY,
                        "OpenAI client is healthy"
                    )
                else:
                    self._update_component_health(
                        "openai",
                        HealthStatus.DEGRADED,
                        "OpenAI client is unhealthy"
                    )
            else:
                # If no health_check, mark as healthy if client exists
                self._update_component_health(
                    "openai",
                    HealthStatus.HEALTHY,
                    "OpenAI client available"
                )
        except Exception as e:
            self._update_component_health(
                "openai",
                HealthStatus.DEGRADED,
                f"OpenAI health check error: {e}"
            )

    def _update_component_health(
        self,
        component: str,
        status: HealthStatus,
        message: str,
        details: dict[str, Any] | None = None
    ) -> None:
        """Update health status for a component."""
        self._component_healths[component] = ComponentHealth(
            name=component,
            status=status,
            message=message,
            last_check=datetime.now(UTC),
            details=details or {}
        )

        # Log health status changes
        if status == HealthStatus.UNHEALTHY:
            self.logger.error(f"Component {component} unhealthy: {message}")
        elif status == HealthStatus.DEGRADED:
            self.logger.warning(f"Component {component} degraded: {message}")
        else:
            self.logger.debug(f"Component {component} healthy: {message}")

    def _log_system_health_summary(self) -> None:
        """Log summary of overall system health."""
        if not self._component_healths:
            return

        healthy_count = sum(1 for h in self._component_healths.values()
                          if h.status == HealthStatus.HEALTHY)
        degraded_count = sum(1 for h in self._component_healths.values()
                           if h.status == HealthStatus.DEGRADED)
        unhealthy_count = sum(1 for h in self._component_healths.values()
                            if h.status == HealthStatus.UNHEALTHY)

        total_count = len(self._component_healths)

        # Determine overall health
        if unhealthy_count > 0:
            overall_status = "UNHEALTHY"
            log_level = logging.ERROR
        elif degraded_count > 0:
            overall_status = "DEGRADED"
            log_level = logging.WARNING
        else:
            overall_status = "HEALTHY"
            log_level = logging.INFO

        summary_msg = (
            f"System health: {overall_status} "
            f"({healthy_count} healthy, {degraded_count} degraded, "
            f"{unhealthy_count} unhealthy out of {total_count} components)"
        )

        self.logger.log(log_level, summary_msg)

    def get_component_health(self, component: str) -> ComponentHealth | None:
        """Get health status for a specific component."""
        return self._component_healths.get(component)

    def get_all_component_healths(self) -> dict[str, ComponentHealth]:
        """Get health status for all components."""
        return self._component_healths.copy()

    def get_overall_health_status(self) -> HealthStatus:
        """Get overall system health status."""
        if not self._component_healths:
            return HealthStatus.UNHEALTHY

        # System is unhealthy if any component is unhealthy
        if any(h.status == HealthStatus.UNHEALTHY for h in self._component_healths.values()):
            return HealthStatus.UNHEALTHY

        # System is degraded if any component is degraded
        if any(h.status == HealthStatus.DEGRADED for h in self._component_healths.values()):
            return HealthStatus.DEGRADED

        return HealthStatus.HEALTHY

    def is_monitoring_active(self) -> bool:
        """Check if health monitoring is currently active."""
        return self._is_running and self._monitoring_task is not None

    async def force_health_check(self) -> dict[str, ComponentHealth]:
        """Force immediate health check and return results."""
        self.logger.info("Forcing immediate health check")
        await self._perform_health_checks()
        return self.get_all_component_healths()

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start_monitoring()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with proper cleanup."""
        await self.stop_monitoring()