"""
Telethon client wrapper for Telegram integration.
Follows coding standards: use logger instead of print(), handle async cancellation.
"""

import asyncio
import logging
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from telethon import TelegramClient as TelethonClient
from telethon.errors import (
    ApiIdInvalidError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
    UsernameNotOccupiedError,
)
from telethon.tl.types import Channel, Chat

from config.settings import settings
from src.utils.circuit_breaker import circuit_breaker


class TelegramClient:
    """
    Wrapper for Telethon client with proper error handling and logging.
    Manages connection establishment and session persistence.
    """

    def __init__(self, session_name: str = "telegram"):
        """
        Initialize Telegram client wrapper.

        Args:
            session_name: Name for the session file (without .session extension)
        """
        self.logger = logging.getLogger(__name__)
        self.session_name = session_name
        self.session_path = settings.data_dir / f"{session_name}.session"
        self.client: TelethonClient | None = None
        self._is_connected = False
        self._connected_groups: dict[str, Any] = {}

        # Connection monitoring attributes
        self._health_check_task: asyncio.Task | None = None
        self._last_health_check = datetime.now(UTC)
        self._connection_failures = 0
        self._max_connection_failures = 3
        self._health_check_interval = 30  # seconds
        self._auto_reconnect_enabled = True

        
    async def _auto_init(self):
        """
        Auto-initialize and connect on startup.
        This bypasses the lazy-loading issue where the bot never initializes the client.
        """
        try:
            self.logger.info("Running auto-initialization...")
            if await self.initialize():
                self.logger.info("Auto-initialization successful")
                if await self.connect():
                    self.logger.info("Auto-connection successful")
                    # Connect to groups if configured
                    if settings.get_telegram_groups():
                        await self.connect_to_groups()
                        self.logger.info("Connected to configured groups")
                else:
                    self.logger.warning("Auto-connection failed")
            else:
                self.logger.warning("Auto-initialization failed")
        except asyncio.CancelledError:
            self.logger.info("Auto-init task cancelled")
        except Exception as e:
            self.logger.error(f"Error in auto-init: {e}")

    async def initialize(self) -> bool:
        """
        Initialize Telethon client with API credentials from environment.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            if not settings.validate_telegram_config():
                self.logger.error("Missing required Telegram configuration")
                return False

            api_id = settings.get_telegram_api_id_int()
            api_hash = settings.telegram_api_hash

            self.logger.info(f"Initializing Telegram client with session: {self.session_path}")

            # Create Telethon client
            self.client = TelethonClient(
                session=str(self.session_path),
                api_id=api_id,
                api_hash=api_hash,
            )

            self.logger.info("Telegram client initialized successfully")
            return True

        except ValueError as e:
            self.logger.error(f"Invalid API credentials: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to initialize Telegram client: {e}")
            return False

    async def connect(self) -> bool:
        """
        Establish connection to Telegram servers with timeout.
        
        Returns:
            True if connection successful, False otherwise
        """
        if not self.client:
            self.logger.error("Client not initialized. Call initialize() first")
            return False

        try:
            self.logger.info("Connecting to Telegram servers (timeout: 15s)...")
            
            # Add timeout to prevent hanging
            await asyncio.wait_for(self.client.connect(), timeout=15.0)

            if await self.client.is_user_authorized():
                self._is_connected = True
                self.logger.info("✅ Connected to Telegram successfully (user authorized)")
                return True
            else:
                self.logger.info("Connected to Telegram but user not authorized")
                return True  # Connection successful, authentication needed separately

        except asyncio.TimeoutError:
            self.logger.error("Telegram connection timed out after 15 seconds")
            return False
        except ApiIdInvalidError:
            self.logger.error("Invalid API ID or API Hash")
            return False
        except FloodWaitError as e:
            self.logger.warning(f"Rate limited by Telegram, wait {e.seconds} seconds")
            return False
        except Exception as e:
            self.logger.error(f"Failed to connect to Telegram: {e}")
            return False

    async def disconnect(self) -> None:
        """
        Disconnect from Telegram servers and cleanup resources.
        Handles async cancellation properly.
        """
        # Stop health monitoring
        await self._stop_health_monitoring()

        # Cancel auto-init task if running
        if hasattr(self, '_init_task') and self._init_task:
            try:
                self._init_task.cancel()
                await self._init_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.logger.error(f"Error cancelling auto-init task: {e}")

        if not self.client:
            return

        try:
            self.logger.info("Disconnecting from Telegram...")
            await self.client.disconnect()
            self._is_connected = False
            self.logger.info("Disconnected from Telegram successfully")
        except Exception as e:
            self.logger.error(f"Error during disconnect: {e}")
        finally:
            self._is_connected = False

    async def is_connected(self) -> bool:
        """
        Check if client is connected to Telegram.

        Returns:
            True if connected, False otherwise
        """
        if not self.client:
            return False

        try:
            return self.client.is_connected() and self._is_connected
        except Exception as e:
            self.logger.error(f"Error checking connection status: {e}")
            return False

    async def is_authorized(self) -> bool:
        """
        Check if user is authorized (logged in).

        Returns:
            True if authorized, False otherwise
        """
        if not self.client:
            return False

        try:
            result = await self.client.is_user_authorized()
            return bool(result) if result is not None else False
        except Exception as e:
            self.logger.error(f"Error checking authorization status: {e}")
            return False

    def get_session_path(self) -> Path:
        """
        Get the path to the session file.

        Returns:
            Path to the session file
        """
        return self.session_path

    async def connect_to_groups(self) -> dict[str, Any]:
        """
        Connect to configured Telegram groups.

        Returns:
            Dict mapping group identifiers to connection results
        """
        if not self.client:
            self.logger.error("Client not initialized")
            return {}

        if not await self.is_authorized():
            self.logger.error("User not authorized, cannot connect to groups")
            return {}

        groups = settings.get_telegram_groups()
        if not groups:
            self.logger.warning("No Telegram groups configured")
            return {}

        # Validate group formats first
        valid_groups, invalid_groups = settings.validate_telegram_groups()
        if not valid_groups:
            self.logger.error(f"Invalid group formats: {invalid_groups}")
            return {}

        connection_results = {}

        for group in groups:
            try:
                self.logger.info(f"Attempting to connect to group: {group}")
                entity = await self._get_group_entity(group)

                if entity:
                    self._connected_groups[group] = entity
                    connection_results[group] = {
                        'success': True,
                        'entity': entity,
                        'title': getattr(entity, 'title', getattr(entity, 'first_name', group)),
                        'id': entity.id
                    }
                    self.logger.info(f"Successfully connected to group: {group}")
                else:
                    connection_results[group] = {
                        'success': False,
                        'error': 'Failed to get group entity'
                    }
                    self.logger.error(f"Failed to connect to group: {group}")

            except Exception as e:
                connection_results[group] = {
                    'success': False,
                    'error': str(e)
                }
                self.logger.error(f"Error connecting to group {group}: {e}")

        successful_connections = sum(1 for result in connection_results.values() if result['success'])
        self.logger.info(f"Connected to {successful_connections}/{len(groups)} groups")

        return connection_results

    @circuit_breaker(failure_threshold=3, recovery_timeout=30)
    async def _get_group_entity(self, group: str) -> Any | None:
        """
        Get Telegram entity for a group by username or ID.
        Protected by circuit breaker to prevent cascade failures.

        Args:
            group: Group username (@username) or numeric ID

        Returns:
            Telegram entity or None if not found
        """
        try:
            if group.startswith('@'):
                # Username format
                entity = await self.client.get_entity(group)
            else:
                # Numeric ID format
                entity = await self.client.get_entity(int(group))

            # Validate entity is a group or channel
            if not isinstance(entity, Channel | Chat):
                self.logger.warning(f"Entity {group} is not a group or channel")
                return None

            return entity

        except UsernameNotOccupiedError:
            self.logger.error(f"Group not found: {group}")
            return None
        except ChatAdminRequiredError:
            self.logger.error(f"Admin rights required for group: {group}")
            return None
        except ChannelPrivateError:
            self.logger.error(f"Group is private and you're not a member: {group}")
            return None
        except ValueError as e:
            self.logger.error(f"Invalid group ID format {group}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting entity for group {group}: {e}")
            return None

    def get_connected_groups(self) -> dict[str, Any]:
        """
        Get currently connected groups.

        Returns:
            Dict of connected group entities
        """
        return self._connected_groups.copy()

    def get_connected_group_entities(self) -> list[Any]:
        """
        Get list of connected group entities for event handlers.

        Returns:
            List of Telegram group entities
        """
        return list(self._connected_groups.values())

    async def start_health_monitoring(self) -> None:
        """
        Start connection health monitoring with auto-reconnection.
        Runs health checks every 30 seconds as per requirements.
        """
        if self._health_check_task and not self._health_check_task.done():
            self.logger.info("Health monitoring already running")
            return

        self.logger.info("Starting connection health monitoring")
        self._health_check_task = asyncio.create_task(self._health_monitor_loop())

    async def stop_health_monitoring(self) -> None:
        """
        Stop connection health monitoring.
        """
        await self._stop_health_monitoring()

    async def _stop_health_monitoring(self) -> None:
        """
        Internal method to stop health monitoring task.
        """
        if self._health_check_task:
            try:
                self._health_check_task.cancel()
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.logger.error(f"Error stopping health monitoring: {e}")
            finally:
                self._health_check_task = None

        self.logger.info("Health monitoring stopped")

    async def _health_monitor_loop(self) -> None:
        """
        Main health monitoring loop.
        Performs health checks every 30 seconds and handles reconnection.
        """
        try:
            while True:
                await asyncio.sleep(self._health_check_interval)

                try:
                    # Perform health check
                    is_healthy = await self._perform_health_check()

                    if is_healthy:
                        self._connection_failures = 0
                        self._last_health_check = datetime.now(UTC)
                    else:
                        self._connection_failures += 1
                        self.logger.warning(
                            f"Health check failed (attempt {self._connection_failures}/"
                            f"{self._max_connection_failures})"
                        )

                        # Attempt auto-reconnection if enabled and failures exceed threshold
                        if (self._auto_reconnect_enabled and
                            self._connection_failures >= self._max_connection_failures):

                            self.logger.warning("Max connection failures reached, attempting auto-reconnection")

                            success = await self._attempt_auto_reconnection()
                            if success:
                                self._connection_failures = 0
                                self.logger.info("Auto-reconnection successful")
                            else:
                                self.logger.error("Auto-reconnection failed")

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.logger.error(f"Error in health monitoring loop: {e}")

        except asyncio.CancelledError:
            self.logger.info("Health monitoring loop cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Health monitoring loop terminated with error: {e}")

    @circuit_breaker(failure_threshold=2, recovery_timeout=10)
    async def _get_me_with_circuit_breaker(self) -> Any:
        """Get current user info with circuit breaker protection."""
        return await self.client.get_me()
    
    async def _perform_health_check(self) -> bool:
        """
        Perform connection health check.

        Returns:
            True if connection is healthy, False otherwise
        """
        try:
            if not self.client:
                return False

            # Check basic connection
            if not self.client.is_connected():
                self.logger.warning("Client reports as disconnected")
                return False

            # Check authorization status
            if not await self.client.is_user_authorized():
                self.logger.warning("User authorization lost")
                return False

            # Perform lightweight operation to test connection
            try:
                await self._get_me_with_circuit_breaker()
                return True
            except (ConnectionError, TimeoutError, OSError) as e:
                self.logger.warning(f"Network connectivity test failed: {e}")
                return False

        except Exception as e:
            self.logger.error(f"Error during health check: {e}")
            return False

    async def _attempt_auto_reconnection(self) -> bool:
        """
        Attempt automatic reconnection with exponential backoff.
        Max recovery time: 60 seconds as per requirements.

        Returns:
            True if reconnection successful, False otherwise
        """
        max_attempts = 3
        base_delay = 5  # Start with 5 seconds
        max_delay = 60  # Max 60 seconds as per requirements

        for attempt in range(max_attempts):
            try:
                # Calculate delay with exponential backoff
                delay = min(base_delay * (2 ** attempt), max_delay)

                if attempt > 0:
                    self.logger.info(f"Reconnection attempt {attempt + 1}/{max_attempts} in {delay}s")
                    await asyncio.sleep(delay)

                # Mark as disconnected and attempt reconnection
                self._is_connected = False

                # Reinitialize and connect
                if not await self.initialize():
                    continue

                if not await self.connect():
                    continue

                # Reconnect to groups if previously connected
                if self._connected_groups:
                    self.logger.info("Reconnecting to previously connected groups")
                    # Clear previous connections and reconnect
                    old_groups = list(self._connected_groups.keys())
                    self._connected_groups.clear()

                    connection_results = await self.connect_to_groups()
                    successful_reconnects = sum(1 for r in connection_results.values() if r['success'])

                    self.logger.info(f"Reconnected to {successful_reconnects}/{len(old_groups)} groups")

                self.logger.info("Auto-reconnection completed successfully")
                return True

            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(f"Reconnection attempt {attempt + 1} failed: {e}")

        self.logger.error(f"All {max_attempts} reconnection attempts failed")
        return False

    def get_connection_status(self) -> dict[str, Any]:
        """
        Get detailed connection status and monitoring information.

        Returns:
            Dictionary with connection status details
        """
        return {
            'connected': self._is_connected,
            'health_monitoring_active': self._health_check_task is not None and not self._health_check_task.done(),
            'last_health_check': self._last_health_check.isoformat(),
            'connection_failures': self._connection_failures,
            'max_connection_failures': self._max_connection_failures,
            'auto_reconnect_enabled': self._auto_reconnect_enabled,
            'connected_groups_count': len(self._connected_groups),
            'health_check_interval': self._health_check_interval
        }

    async def __aenter__(self):
        """Async context manager entry."""
        if not await self.initialize():
            raise RuntimeError("Failed to initialize Telegram client")
        if not await self.connect():
            raise RuntimeError("Failed to connect to Telegram")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with proper cleanup."""
        await self.disconnect()