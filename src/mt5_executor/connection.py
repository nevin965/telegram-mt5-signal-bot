"""
MT5 connection manager with connection pool pattern and automatic reconnection.
Follows coding standards: circuit breaker decorator for external APIs, structured logging.
"""

import asyncio
import hashlib
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, NamedTuple

try:
    import MetaTrader5 as mt5
except ImportError:
    # For testing environments where MT5 is not available
    mt5 = None

from config.logging_config import (
    get_contextual_logger,
    set_correlation_id,
    set_service_context,
)
from config.settings import settings
from src.utils.circuit_breaker import circuit_breaker


def _hash_account_info(value: str) -> str:
    """Hash sensitive account information for logging."""
    if not value:
        return "none"
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:12]


def log_mt5_operation(logger, operation: str, success: bool, **extra_data):
    """
    Log MT5 operation with structured format and correlation ID.
    
    Args:
        logger: Logger instance
        operation: Operation name (e.g., "connection_established", "account_validation")
        success: Whether operation was successful
        **extra_data: Additional data to include in log
    """
    correlation_id = set_correlation_id()
    set_service_context("MT5ConnectionManager", operation)

    # Prepare MT5-specific data with sensitive info hashing
    mt5_data = {}
    connection_metrics = {}

    for key, value in extra_data.items():
        if key in ['account_number', 'login', 'user_id']:
            mt5_data[f"{key}_hash"] = _hash_account_info(value)
        elif key in ['password', 'api_key', 'secret']:
            continue  # Never log sensitive credentials
        elif key.startswith('pool_') or key.endswith('_count') or key.endswith('_ms'):
            connection_metrics[key] = value
        else:
            mt5_data[key] = value

    # Build structured log entry
    extra_fields = {
        "mt5_data": mt5_data if mt5_data else None,
        "connection_metrics": connection_metrics if connection_metrics else None,
        "operation_success": success
    }

    level = logging.INFO if success else logging.ERROR
    message = f"MT5 {operation}: {'SUCCESS' if success else 'FAILED'}"

    logger.log(level, message, extra_fields=extra_fields)


class TerminalInfo(NamedTuple):
    """Terminal information structure."""
    name: str
    build: int
    version: str
    connected: bool
    trade_allowed: bool
    tradeapi_disabled: bool
    maxbars: int
    mqid: bool
    dlls_allowed: bool
    mail_enabled: bool
    ftp_enabled: bool
    notifications_enabled: bool


class AccountInfo(NamedTuple):
    """Account information structure."""
    login: int
    trade_mode: int
    leverage: int
    limit_orders: int
    margin_so_mode: int
    trade_allowed: bool
    trade_expert: bool
    margin_mode: int
    currency_digits: int
    balance: float
    credit: float
    profit: float
    equity: float
    margin: float
    margin_free: float
    margin_level: float
    margin_so_call: float
    margin_so_so: float
    name: str
    server: str
    currency: str
    company: str


class ConnectionHealth(NamedTuple):
    """Connection health status."""
    is_healthy: bool
    connected: bool
    last_ping: datetime | None
    error_message: str | None
    response_time_ms: float | None


class MT5Connection:
    """Represents a single MT5 connection with health tracking."""

    def __init__(self, connection_id: int):
        self.id = connection_id
        self.connected = False
        self.last_used = datetime.now(UTC)
        self.last_ping = None
        self.connection_time = None
        self.error_count = 0
        self.logger = get_contextual_logger(f"{__name__}.Connection{connection_id}")

    async def connect(self, login: int, password: str, server: str, path: str = None) -> bool:
        """
        Connect to MT5 terminal.
        
        Args:
            login: MT5 account login
            password: MT5 account password  
            server: MT5 broker server
            path: Optional MT5 terminal path
            
        Returns:
            True if connection successful
        """
        if mt5 is None:
            raise RuntimeError("MetaTrader5 module not available")

        try:
            # Initialize MT5 terminal
            if path:
                initialized = mt5.initialize(path)
            else:
                initialized = mt5.initialize()

            if not initialized:
                error = mt5.last_error()
                log_mt5_operation(
                    self.logger,
                    "initialization_failed",
                    False,
                    connection_id=self.id,
                    error=str(error),
                    path=path
                )
                return False

            # Login to account
            authorized = mt5.login(login, password, server)
            if not authorized:
                error = mt5.last_error()
                log_mt5_operation(
                    self.logger,
                    "login_failed",
                    False,
                    connection_id=self.id,
                    account_number=login,
                    server=server,
                    error=str(error)
                )
                mt5.shutdown()
                return False

            self.connected = True
            self.connection_time = datetime.now(UTC)
            self.error_count = 0
            self.last_used = datetime.now(UTC)

            log_mt5_operation(
                self.logger,
                "connection_established",
                True,
                connection_id=self.id,
                account_number=login,
                server=server,
                connection_time=self.connection_time.isoformat()
            )
            return True

        except Exception as e:
            log_mt5_operation(
                self.logger,
                "connection_error",
                False,
                connection_id=self.id,
                account_number=login,
                server=server,
                error=str(e),
                error_count=self.error_count + 1
            )
            self.error_count += 1
            self.connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from MT5 terminal."""
        if mt5 and self.connected:
            mt5.shutdown()

        self.connected = False
        self.connection_time = None
        self.logger.info(f"MT5 connection {self.id} disconnected")

    async def health_check(self) -> bool:
        """
        Health check for MT5 connection.
        Returns True if connection is healthy, False otherwise.
        """
        health = await self.ping()
        return health.is_healthy

    async def ping(self) -> ConnectionHealth:
        """
        Check connection health.
        
        Returns:
            Connection health status
        """
        start_time = datetime.now(UTC)

        try:
            if not self.connected or mt5 is None:
                return ConnectionHealth(
                    is_healthy=False,
                    connected=False,
                    last_ping=start_time,
                    error_message="Not connected",
                    response_time_ms=None
                )

            # Check if we can get account info (quick health check)
            account_info = mt5.account_info()
            response_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

            if account_info is None:
                error = mt5.last_error()
                self.error_count += 1
                return ConnectionHealth(
                    is_healthy=False,
                    connected=False,
                    last_ping=start_time,
                    error_message=f"Account info failed: {error}",
                    response_time_ms=response_time
                )

            self.last_ping = start_time
            self.last_used = start_time

            return ConnectionHealth(
                is_healthy=True,
                connected=True,
                last_ping=start_time,
                error_message=None,
                response_time_ms=response_time
            )

        except Exception as e:
            self.error_count += 1
            response_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

            return ConnectionHealth(
                is_healthy=False,
                connected=False,
                last_ping=start_time,
                error_message=str(e),
                response_time_ms=response_time
            )


class MT5ConnectionManager:
    """
    MT5 connection pool manager with automatic reconnection and health monitoring.
    Implements connection pool pattern with configurable max connections.
    """

    def __init__(self, max_connections: int = None):
        """
        Initialize connection manager.
        
        Args:
            max_connections: Maximum number of concurrent connections
        """
        mt5_settings = settings.get_mt5_settings()

        self.login = mt5_settings.login
        self.password = mt5_settings.password
        self.server = mt5_settings.server
        self.path = mt5_settings.path
        self.timeout_seconds = mt5_settings.timeout_seconds
        self.max_connections = max_connections or mt5_settings.max_connections
        self.reconnect_delay = mt5_settings.reconnect_delay

        self.connections: dict[int, MT5Connection] = {}
        self.connection_queue = asyncio.Queue(maxsize=self.max_connections)
        self.next_connection_id = 1
        self._initialized = False
        self._shutdown = False
        self._initialization_lock = asyncio.Lock()
        self._initialization_task = None

        self.logger = get_contextual_logger(__name__)

    async def _initialize_pool(self) -> None:
        """Initialize connection pool with initial connections."""
        try:
            for i in range(self.max_connections):
                connection = MT5Connection(self.next_connection_id)
                self.next_connection_id += 1

                # Try to connect
                if await connection.connect(self.login, self.password, self.server, self.path):
                    self.connections[connection.id] = connection
                    await self.connection_queue.put(connection)
                else:
                    self.logger.warning(f"Failed to initialize connection {connection.id}")

            self._initialized = True
            log_mt5_operation(
                self.logger,
                "pool_initialized",
                True,
                pool_size=len(self.connections),
                pool_max=self.max_connections,
                account_number=self.login,
                server=self.server
            )

        except Exception as e:
            self.logger.error(f"Failed to initialize MT5 connection pool: {e}")
            raise

    async def _ensure_initialized(self) -> None:
        """Ensure connection pool is initialized (lazy initialization)."""
        if self._initialized:
            return
            
        async with self._initialization_lock:
            # Double-check after acquiring lock
            if self._initialized:
                return
                
            # Initialize the pool
            if self._initialization_task is None:
                self._initialization_task = asyncio.create_task(self._initialize_pool())
            
            await self._initialization_task
    
    @asynccontextmanager
    async def get_connection(self):
        """
        Get connection from pool using context manager.
        
        Yields:
            MT5Connection: Available connection from pool
            
        Raises:
            RuntimeError: If no connections available or pool not initialized
        """
        # Ensure pool is initialized (lazy initialization)
        await self._ensure_initialized()
        
        if not self._initialized:
            raise RuntimeError("Connection pool initialization failed")

        if self._shutdown:
            raise RuntimeError("Connection manager is shutting down")

        connection = None
        try:
            # Get connection from pool with timeout
            connection = await asyncio.wait_for(
                self.connection_queue.get(),
                timeout=self.timeout_seconds
            )

            # Check connection health before use
            health = await connection.ping()
            if not health.is_healthy:
                self.logger.warning(f"Unhealthy connection {connection.id}, attempting reconnect")
                await self._reconnect_connection(connection)

            connection.last_used = datetime.now(UTC)
            yield connection

        except TimeoutError:
            raise RuntimeError(f"Timeout waiting for MT5 connection (>{self.timeout_seconds}s)")

        finally:
            if connection:
                # Return connection to pool
                await self.connection_queue.put(connection)

    async def _reconnect_connection(self, connection: MT5Connection) -> bool:
        """
        Reconnect a failed connection with exponential backoff.
        
        Args:
            connection: Connection to reconnect
            
        Returns:
            True if reconnection successful
        """
        max_retries = 3
        base_delay = self.reconnect_delay

        for attempt in range(max_retries):
            try:
                await connection.disconnect()

                # Exponential backoff: 5s, 10s, 20s
                delay = base_delay * (2 ** attempt)
                if delay > 60:  # Cap at 60 seconds
                    delay = 60

                if attempt > 0:
                    self.logger.info(f"Reconnection attempt {attempt + 1} for connection {connection.id} in {delay}s")
                    await asyncio.sleep(delay)

                success = await connection.connect(self.login, self.password, self.server, self.path)
                if success:
                    self.logger.info(f"Successfully reconnected connection {connection.id}")
                    return True

            except Exception as e:
                self.logger.error(f"Reconnection attempt {attempt + 1} failed for connection {connection.id}: {e}")

        self.logger.error(f"Failed to reconnect connection {connection.id} after {max_retries} attempts")
        return False

    @circuit_breaker(failure_threshold=3, recovery_timeout=30)
    async def get_terminal_info(self) -> TerminalInfo | None:
        """
        Get MT5 terminal information with circuit breaker protection.
        
        Returns:
            Terminal information or None if failed
        """
        await self._ensure_initialized()
        async with self.get_connection() as connection:
            if mt5 is None or not connection.connected:
                return None

            try:
                info = mt5.terminal_info()
                if info is None:
                    return None

                return TerminalInfo(
                    name=info.name,
                    build=info.build,
                    version=f"{info.version}",
                    connected=info.connected,
                    trade_allowed=info.trade_allowed,
                    tradeapi_disabled=info.tradeapi_disabled,
                    maxbars=info.maxbars,
                    mqid=info.mqid,
                    dlls_allowed=info.dlls_allowed,
                    mail_enabled=info.mail_enabled,
                    ftp_enabled=info.ftp_enabled,
                    notifications_enabled=info.notifications_enabled
                )

            except Exception as e:
                self.logger.error(f"Failed to get terminal info: {e}")
                raise

    @circuit_breaker(failure_threshold=3, recovery_timeout=30)
    async def get_account_info(self) -> AccountInfo | None:
        """
        Get MT5 account information with circuit breaker protection.
        
        Returns:
            Account information or None if failed
        """
        async with self.get_connection() as connection:
            if mt5 is None or not connection.connected:
                return None

            try:
                info = mt5.account_info()
                if info is None:
                    return None

                return AccountInfo(
                    login=info.login,
                    trade_mode=info.trade_mode,
                    leverage=info.leverage,
                    limit_orders=info.limit_orders,
                    margin_so_mode=info.margin_so_mode,
                    trade_allowed=info.trade_allowed,
                    trade_expert=info.trade_expert,
                    margin_mode=info.margin_mode,
                    currency_digits=info.currency_digits,
                    balance=info.balance,
                    credit=info.credit,
                    profit=info.profit,
                    equity=info.equity,
                    margin=info.margin,
                    margin_free=info.margin_free,
                    margin_level=info.margin_level,
                    margin_so_call=info.margin_so_call,
                    margin_so_so=info.margin_so_so,
                    name=info.name,
                    server=info.server,
                    currency=info.currency,
                    company=info.company
                )

            except Exception as e:
                self.logger.error(f"Failed to get account info: {e}")
                raise

    @circuit_breaker(failure_threshold=3, recovery_timeout=30)
    async def validate_account(self) -> dict[str, Any]:
        """
        Validate account type, permissions, and requirements.
        
        Returns:
            Dictionary with validation results and account details
        """
        async with self.get_connection() as connection:
            if mt5 is None or not connection.connected:
                return {
                    'valid': False,
                    'error': 'MT5 not connected',
                    'account_type': None,
                    'permissions': {},
                    'balance_check': False,
                    'broker_info': {}
                }

            try:
                # Get account and terminal info
                account_info = await self.get_account_info()
                terminal_info = await self.get_terminal_info()

                if not account_info or not terminal_info:
                    return {
                        'valid': False,
                        'error': 'Failed to get account or terminal info',
                        'account_type': None,
                        'permissions': {},
                        'balance_check': False,
                        'broker_info': {}
                    }

                # Validate account type (0=netting, 1=hedge)
                account_type = 'hedge' if account_info.trade_mode == 1 else 'netting'

                # Check trading permissions
                permissions = {
                    'trade_allowed': account_info.trade_allowed and terminal_info.trade_allowed,
                    'automated_trading': account_info.trade_expert,
                    'dll_allowed': terminal_info.dlls_allowed,
                    'trade_api_enabled': not terminal_info.tradeapi_disabled
                }

                # Currency validation for USD trading
                expected_currency = os.getenv('MT5_ACCOUNT_CURRENCY', 'USD')
                currency_check = account_info.currency == expected_currency
                
                # Minimum balance check (example: $100 minimum for USD accounts)
                min_balance = 100.0 if account_info.currency == 'USD' else 100.0
                balance_check = account_info.balance >= min_balance

                # Broker and server validation
                broker_info = {
                    'company': account_info.company,
                    'server': account_info.server,
                    'currency': account_info.currency,
                    'leverage': account_info.leverage,
                    'terminal_build': terminal_info.build,
                    'connected': terminal_info.connected
                }

                # Overall validation
                is_valid = (
                    permissions['trade_allowed'] and
                    permissions['automated_trading'] and
                    permissions['trade_api_enabled'] and
                    balance_check and
                    currency_check and
                    terminal_info.connected
                )

                validation_result = {
                    'valid': is_valid,
                    'error': None if is_valid else 'Account validation failed - check permissions, balance and currency',
                    'account_type': account_type,
                    'permissions': permissions,
                    'balance_check': balance_check,
                    'currency_check': currency_check,
                    'balance': account_info.balance,
                    'minimum_balance': min_balance,
                    'account_currency': account_info.currency,
                    'expected_currency': expected_currency,
                    'broker_info': broker_info
                }

                # Log validation results with structured format
                if is_valid:
                    log_mt5_operation(
                        self.logger,
                        "account_validation_success",
                        True,
                        account_type=account_type,
                        account_number=account_info.login,
                        balance=account_info.balance,
                        currency=account_info.currency,
                        leverage=account_info.leverage,
                        margin=account_info.margin,
                        broker=account_info.company,
                        server=account_info.server,
                        terminal_build=terminal_info.build,
                        terminal_version=f"{terminal_info.name} {terminal_info.version}",
                        trade_allowed=permissions['trade_allowed'],
                        automated_trading=permissions['automated_trading'],
                        dll_allowed=permissions['dll_allowed']
                    )
                else:
                    failed_checks = []
                    if not permissions['trade_allowed']:
                        failed_checks.append('trading disabled')
                    if not permissions['automated_trading']:
                        failed_checks.append('expert trading disabled')
                    if not permissions['trade_api_enabled']:
                        failed_checks.append('trade API disabled')
                    if not balance_check:
                        failed_checks.append(f'insufficient balance ({account_info.balance} < {min_balance})')
                    if not currency_check:
                        failed_checks.append(f'wrong currency ({account_info.currency} != {expected_currency})')

                    log_mt5_operation(
                        self.logger,
                        "account_validation_failed",
                        False,
                        account_type=account_type,
                        account_number=account_info.login,
                        balance=account_info.balance,
                        currency=account_info.currency,
                        broker=account_info.company,
                        server=account_info.server,
                        failed_checks=failed_checks,
                        terminal_build=terminal_info.build if terminal_info else None
                    )

                return validation_result

            except Exception as e:
                self.logger.error(f"Account validation error: {e}")
                return {
                    'valid': False,
                    'error': f'Validation error: {e!s}',
                    'account_type': None,
                    'permissions': {},
                    'balance_check': False,
                    'broker_info': {}
                }

    @circuit_breaker(failure_threshold=3, recovery_timeout=30)
    async def check_time_synchronization(self) -> dict[str, Any]:
        """
        Check broker server time synchronization.
        
        Returns:
            Dictionary with time sync status
        """
        async with self.get_connection() as connection:
            if mt5 is None or not connection.connected:
                return {
                    'synchronized': False,
                    'error': 'MT5 not connected',
                    'server_time': None,
                    'local_time': None,
                    'time_diff_seconds': None
                }

            try:
                # Get server time from MT5
                server_time_struct = mt5.symbol_info_tick('EURUSD')
                if server_time_struct is None:
                    return {
                        'synchronized': False,
                        'error': 'Failed to get server time',
                        'server_time': None,
                        'local_time': None,
                        'time_diff_seconds': None
                    }

                server_time = datetime.fromtimestamp(server_time_struct.time, tz=UTC)
                local_time = datetime.now(UTC)
                time_diff = abs((local_time - server_time).total_seconds())

                # Consider synchronized if within 60 seconds
                synchronized = time_diff <= 60

                result = {
                    'synchronized': synchronized,
                    'error': None if synchronized else f'Time difference too large: {time_diff:.1f}s',
                    'server_time': server_time.isoformat(),
                    'local_time': local_time.isoformat(),
                    'time_diff_seconds': time_diff
                }

                if synchronized:
                    self.logger.info(f"Time synchronization OK (diff: {time_diff:.1f}s)")
                else:
                    self.logger.warning(f"Time synchronization issue (diff: {time_diff:.1f}s)")

                return result

            except Exception as e:
                self.logger.error(f"Time synchronization check failed: {e}")
                return {
                    'synchronized': False,
                    'error': f'Time sync error: {e!s}',
                    'server_time': None,
                    'local_time': None,
                    'time_diff_seconds': None
                }

    async def check_connection_health(self) -> dict[str, Any]:
        """
        Check health of all connections in pool.
        
        Returns:
            Dictionary with health status of all connections
        """
        health_status = {
            'pool_size': len(self.connections),
            'max_connections': self.max_connections,
            'active_connections': 0,
            'healthy_connections': 0,
            'connections': {}
        }

        for conn_id, connection in self.connections.items():
            health = await connection.ping()
            health_status['connections'][conn_id] = {
                'healthy': health.is_healthy,
                'connected': health.connected,
                'last_ping': health.last_ping.isoformat() if health.last_ping else None,
                'last_used': connection.last_used.isoformat(),
                'error_count': connection.error_count,
                'response_time_ms': health.response_time_ms,
                'error_message': health.error_message
            }

            if health.connected:
                health_status['active_connections'] += 1
            if health.is_healthy:
                health_status['healthy_connections'] += 1

        return health_status

    # ✅ ADDED HEALTH_CHECK METHOD FOR THE HEALTH MONITOR
    async def health_check(self) -> bool:
        """
        Health check for the MT5 connection manager.
        Returns True if at least one connection is healthy.
        """
        health_status = await self.check_connection_health()
        return health_status.get('healthy_connections', 0) > 0

    async def detect_mt5_terminal_status(self) -> dict[str, Any]:
        """
        Detect MT5 terminal status and provide guidance if not running.
        
        Returns:
            Dictionary with terminal detection results
        """
        try:
            import os
            import platform

            import psutil

            # Look for MT5 processes
            mt5_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'status']):
                try:
                    proc_name = proc.info['name'].lower() if proc.info['name'] else ""
                    if any(term in proc_name for term in ['terminal64', 'metatrader', 'mt5']):
                        mt5_processes.append({
                            'pid': proc.info['pid'],
                            'name': proc.info['name'],
                            'exe': proc.info['exe'],
                            'status': proc.info['status']
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # Check if MT5 module can initialize
            mt5_module_available = mt5 is not None
            can_initialize = False

            if mt5_module_available:
                try:
                    # Try a quick initialize/shutdown test
                    can_initialize = mt5.initialize()
                    if can_initialize:
                        mt5.shutdown()
                except Exception:
                    pass

            # Determine status and provide guidance
            if mt5_processes and can_initialize:
                status = "running"
                guidance = "MT5 terminal is running and accessible"
                error = None
            elif mt5_processes and not can_initialize:
                status = "running_but_inaccessible"
                guidance = "MT5 terminal is running but not accessible. Check if EA trading is enabled and try restarting the terminal."
                error = "MT5 terminal found but initialization failed"
            elif not mt5_processes:
                status = "not_running"
                system_info = platform.system()
                if system_info == "Windows":
                    guidance = "MT5 terminal is not running. Please start MetaTrader 5 and login to your account. Common locations: C:\\Program Files\\MetaTrader 5\\terminal64.exe"
                elif system_info == "Linux":
                    guidance = "MT5 terminal is not running. Install MT5 via Wine or use a Windows VPS. Linux native support is limited."
                else:
                    guidance = "MT5 terminal is not running. Please start MetaTrader 5 and login to your account."
                error = "No MT5 processes detected"
            else:
                status = "unknown"
                guidance = "Unable to determine MT5 terminal status. Please ensure MetaTrader 5 is installed and running."
                error = "Terminal status detection failed"

            result = {
                'status': status,
                'processes_found': len(mt5_processes),
                'processes': mt5_processes,
                'module_available': mt5_module_available,
                'can_initialize': can_initialize,
                'guidance': guidance,
                'error': error,
                'platform': platform.system()
            }

            log_mt5_operation(
                self.logger,
                "terminal_detection",
                status == "running",
                terminal_status=status,
                processes_found=len(mt5_processes),
                module_available=mt5_module_available,
                platform=platform.system()
            )

            return result

        except ImportError:
            # psutil not available
            return {
                'status': 'unknown',
                'processes_found': 0,
                'processes': [],
                'module_available': mt5 is not None,
                'can_initialize': False,
                'guidance': 'Cannot detect terminal status - psutil not available. Please ensure MetaTrader 5 is running.',
                'error': 'Process detection unavailable',
                'platform': 'unknown'
            }
        except Exception as e:
            log_mt5_operation(
                self.logger,
                "terminal_detection_error",
                False,
                error=str(e)
            )
            return {
                'status': 'error',
                'processes_found': 0,
                'processes': [],
                'module_available': mt5 is not None,
                'can_initialize': False,
                'guidance': f'Terminal detection failed: {e!s}',
                'error': str(e),
                'platform': 'unknown'
            }

    async def validate_credentials(self, test_connection: bool = True) -> dict[str, Any]:
        """
        Validate MT5 credentials with clear error messages.
        
        Args:
            test_connection: Whether to test actual connection
            
        Returns:
            Dictionary with credential validation results
        """
        try:
            # Basic credential validation
            validation_errors = []

            if not str(self.login).isdigit() or self.login <= 0:
                validation_errors.append("Invalid login: must be a positive integer")

            if not self.password or len(self.password.strip()) < 1:
                validation_errors.append("Invalid password: cannot be empty")

            if not self.server or len(self.server.strip()) < 1:
                validation_errors.append("Invalid server: cannot be empty")

            # Check for common server name patterns
            if self.server and not any(pattern in self.server.lower() for pattern in
                ['demo', 'live', 'real', 'server', 'trade', '-']):
                validation_errors.append(
                    f"Suspicious server name '{self.server}'. "
                    f"Expected format: 'BrokerName-Demo' or 'BrokerName-Live'"
                )

            if validation_errors:
                result = {
                    'valid': False,
                    'errors': validation_errors,
                    'guidance': "Please check your MT5 credentials in environment variables",
                    'connection_tested': False
                }

                log_mt5_operation(
                    self.logger,
                    "credential_validation_failed",
                    False,
                    validation_errors=validation_errors,
                    login_valid=str(self.login).isdigit(),
                    password_valid=bool(self.password and self.password.strip()),
                    server_valid=bool(self.server and self.server.strip())
                )

                return result

            # Test actual connection if requested
            if test_connection:
                terminal_status = await self.detect_mt5_terminal_status()

                if terminal_status['status'] != 'running':
                    return {
                        'valid': False,
                        'errors': [terminal_status['error']],
                        'guidance': terminal_status['guidance'],
                        'connection_tested': False,
                        'terminal_status': terminal_status
                    }

                # Try to connect with credentials
                test_connection = MT5Connection(9999)  # Temporary connection ID
                connection_success = await test_connection.connect(
                    self.login, self.password, self.server, self.path
                )
                await test_connection.disconnect()

                if not connection_success:
                    guidance = (
                        f"Connection failed with login {self.login} on server '{self.server}'. "
                        f"Please verify: 1) Account credentials are correct, "
                        f"2) Account is not expired/suspended, "
                        f"3) Server name matches your broker exactly, "
                        f"4) MetaTrader 5 terminal is logged in to the same account"
                    )

                    return {
                        'valid': False,
                        'errors': ['Authentication failed'],
                        'guidance': guidance,
                        'connection_tested': True,
                        'terminal_status': terminal_status
                    }

            result = {
                'valid': True,
                'errors': [],
                'guidance': "Credentials appear valid",
                'connection_tested': test_connection
            }

            log_mt5_operation(
                self.logger,
                "credential_validation_success",
                True,
                connection_tested=test_connection,
                account_number=self.login,
                server=self.server
            )

            return result

        except Exception as e:
            log_mt5_operation(
                self.logger,
                "credential_validation_error",
                False,
                error=str(e)
            )
            return {
                'valid': False,
                'errors': [f'Validation error: {e!s}'],
                'guidance': 'Credential validation failed due to system error',
                'connection_tested': False
            }

    async def handle_connection_timeout(self, operation: str, timeout_seconds: int) -> None:
        """
        Handle connection timeout with appropriate logging and recovery.
        
        Args:
            operation: Operation that timed out
            timeout_seconds: Timeout duration
        """
        log_mt5_operation(
            self.logger,
            "connection_timeout",
            False,
            operation_name=operation,
            timeout_seconds=timeout_seconds,
            pool_size=len(self.connections),
            active_connections=sum(1 for conn in self.connections.values() if conn.connected)
        )

        # Attempt to recover by checking terminal status
        terminal_status = await self.detect_mt5_terminal_status()

        if terminal_status['status'] != 'running':
            log_mt5_operation(
                self.logger,
                "timeout_recovery_terminal_down",
                False,
                terminal_status=terminal_status['status'],
                guidance=terminal_status['guidance']
            )
        else:
            # Terminal is running, might be a network/load issue
            log_mt5_operation(
                self.logger,
                "timeout_recovery_attempt",
                False,
                recovery_action="Attempting connection pool refresh",
                terminal_processes=terminal_status['processes_found']
            )

    async def graceful_degradation(self) -> dict[str, Any]:
        """
        Implement graceful degradation when MT5 is unavailable.
        
        Returns:
            Dictionary with degradation status and available operations
        """
        try:
            terminal_status = await self.detect_mt5_terminal_status()
            credential_status = await self.validate_credentials(test_connection=False)

            # Determine what operations are available
            available_operations = []
            degraded_operations = []
            unavailable_operations = []

            if terminal_status['status'] == 'running' and credential_status['valid']:
                available_operations = ['full_trading', 'account_info', 'symbol_specs', 'health_checks']
            elif terminal_status['status'] == 'running':
                available_operations = ['basic_connection_test']
                degraded_operations = ['account_info', 'symbol_specs']
                unavailable_operations = ['trading', 'position_management']
            else:
                degraded_operations = ['credential_validation', 'configuration_check']
                unavailable_operations = ['all_mt5_operations']

            degradation_status = {
                'mode': 'full' if len(unavailable_operations) == 0 else 'degraded' if len(available_operations) > 0 else 'offline',
                'available_operations': available_operations,
                'degraded_operations': degraded_operations,
                'unavailable_operations': unavailable_operations,
                'terminal_status': terminal_status,
                'credential_status': credential_status,
                'guidance': self._get_recovery_guidance(terminal_status, credential_status)
            }

            log_mt5_operation(
                self.logger,
                "graceful_degradation",
                True,
                degradation_mode=degradation_status['mode'],
                available_ops=len(available_operations),
                degraded_ops=len(degraded_operations),
                unavailable_ops=len(unavailable_operations)
            )

            return degradation_status

        except Exception as e:
            log_mt5_operation(
                self.logger,
                "degradation_assessment_error",
                False,
                error=str(e)
            )
            return {
                'mode': 'error',
                'available_operations': [],
                'degraded_operations': [],
                'unavailable_operations': ['all_operations'],
                'error': str(e),
                'guidance': 'System error during degradation assessment'
            }

    def _get_recovery_guidance(self, terminal_status: dict, credential_status: dict) -> str:
        """Get recovery guidance based on current status."""
        if terminal_status['status'] == 'not_running':
            return terminal_status['guidance']
        elif terminal_status['status'] == 'running_but_inaccessible':
            return (
                "MT5 is running but not accessible. Try: "
                "1) Enable 'Allow automated trading' in MT5 Tools->Options->Expert Advisors, "
                "2) Restart MT5 terminal, "
                "3) Check if MT5 is logged in to the correct account"
            )
        elif not credential_status['valid']:
            return (
                "Credential validation failed. Check: "
                "1) MT5_LOGIN, MT5_PASSWORD, MT5_SERVER environment variables, "
                "2) Account is not expired or suspended, "
                "3) Server name matches your broker exactly"
            )
        else:
            return "Run health check to identify specific issues"

    async def shutdown(self) -> None:
        """Shutdown connection manager and close all connections."""
        self._shutdown = True

        self.logger.info("Shutting down MT5 connection manager")

        for connection in self.connections.values():
            await connection.disconnect()

        self.connections.clear()

        # Clear the queue
        while not self.connection_queue.empty():
            try:
                self.connection_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self.logger.info("MT5 connection manager shutdown complete")


# Global connection manager instance (lazy initialization)
connection_manager = None


def get_connection_manager() -> MT5ConnectionManager:
    """Get or create the global connection manager instance."""
    global connection_manager
    if connection_manager is None:
        connection_manager = MT5ConnectionManager()
    return connection_manager