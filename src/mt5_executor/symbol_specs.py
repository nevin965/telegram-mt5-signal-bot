"""
Symbol specifications and validation for GOLD/XAUUSD trading.
Handles symbol normalization, specification caching, and validation.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

try:
    import MetaTrader5 as mt5
except ImportError:
    # For testing environments where MT5 is not available
    mt5 = None

from src.utils.circuit_breaker import circuit_breaker


class SymbolSpec(NamedTuple):
    """Symbol specification structure."""
    symbol: str
    description: str
    currency_base: str
    currency_profit: str
    currency_margin: str
    digits: int
    point: float
    tick_size: float
    tick_value: float
    volume_min: float
    volume_max: float
    volume_step: float
    spread: int
    trade_mode: int
    trade_allowed: bool
    trade_stops_level: int
    trade_freeze_level: int
    margin_initial: float
    margin_maintenance: float
    session_deals: int
    session_buy_orders: int
    session_sell_orders: int
    time: int


class MarketHours(NamedTuple):
    """Market session hours."""
    symbol: str
    session_name: str
    start_time: str
    end_time: str
    is_active: bool


class SymbolValidator:
    """
    Validates and manages symbol specifications for MT5 trading.
    Handles symbol normalization and caching for GOLD/XAUUSD.
    """

    def __init__(self, connection_manager):
        """
        Initialize symbol validator.
        
        Args:
            connection_manager: MT5ConnectionManager instance
        """
        self.connection_manager = connection_manager
        self.logger = logging.getLogger(__name__)

        # Symbol name mappings for different brokers
        self.symbol_mappings = {
    		'GOLD': ['XAUUSD', 'GOLD', 'XAU/USD', 'XAUUSD.', 'XAUUSD#', 'XAUUSDm'],  # ✅ added XAUUSDm
    		'XAUUSD': ['XAUUSD', 'GOLD', 'XAU/USD', 'XAUUSD.', 'XAUUSD#', 'XAUUSDm'],
    		'XAU': ['XAUUSD', 'GOLD', 'XAU/USD', 'XAUUSD.', 'XAUUSD#', 'XAUUSDm'],
    		'BTCUSD': ['BTCUSD', 'BITCOIN', 'BTC/USD', 'BTC', 'BTCUSD.', 'BTCUSDm'],  # ✅ added BTCUSDm
    		'BTC': ['BTCUSD', 'BITCOIN', 'BTC/USD', 'BTC', 'BTCUSD.', 'BTCUSDm'],
	}

        # Cached symbol specifications
        self.cache: dict[str, dict[str, Any]] = {}
        self.cache_expiry: dict[str, datetime] = {}
        self.cache_duration = timedelta(minutes=30)  # Refresh every 30 minutes

    def normalize_symbol_name(self, symbol: str) -> list[str]:
        """
        Normalize symbol name to possible broker variations.
        
        Args:
            symbol: Input symbol name (GOLD, XAUUSD, etc.)
            
        Returns:
            List of possible symbol names to try
        """
        symbol_upper = symbol.upper().strip()

        # Remove common suffixes and prefixes
        cleaned_symbol = symbol_upper.replace('/', '').replace('.', '').replace('#', '')

        if cleaned_symbol in self.symbol_mappings:
            return self.symbol_mappings[cleaned_symbol]

        # If not in mappings, return the original with common variations
        return [
            symbol_upper,
            symbol_upper + '.',
            symbol_upper + '#',
            symbol_upper.replace('/', ''),
            'XAU/USD' if 'XAU' in symbol_upper else symbol_upper,
            'XAUUSD' if 'GOLD' in symbol_upper else symbol_upper
        ]

    @circuit_breaker(failure_threshold=3, recovery_timeout=30)
    async def get_symbol_info(self, symbol: str) -> SymbolSpec | None:
        """
        Get symbol information from MT5 with circuit breaker protection.
        
        Args:
            symbol: Symbol name to query
            
        Returns:
            SymbolSpec if found, None otherwise
        """
        async with self.connection_manager.get_connection() as connection:
            if mt5 is None or not connection.connected:
                return None

            try:
                info = mt5.symbol_info(symbol)
                if info is None:
                    return None

                return SymbolSpec(
                    symbol=info.name,
                    description=info.description,
                    currency_base=info.currency_base,
                    currency_profit=info.currency_profit,
                    currency_margin=info.currency_margin,
                    digits=info.digits,
                    point=info.point,
                    tick_size=info.trade_tick_size,
                    tick_value=info.trade_tick_value,
                    volume_min=info.volume_min,
                    volume_max=info.volume_max,
                    volume_step=info.volume_step,
                    spread=info.spread,
                    trade_mode=info.trade_mode,
                    trade_allowed=bool(info.visible),
                    trade_stops_level=info.trade_stops_level,
                    trade_freeze_level=info.trade_freeze_level,
                    margin_initial=info.margin_initial,
                    margin_maintenance=info.margin_maintenance,
                    session_deals=info.session_deals,
                    session_buy_orders=info.session_buy_orders,
                    session_sell_orders=info.session_sell_orders,
                    time=info.time
                )

            except Exception as e:
                self.logger.error(f"Failed to get symbol info for {symbol}: {e}")
                raise

    async def find_symbol(self, symbol: str) -> SymbolSpec | None:
        """
        Find symbol by trying different broker variations.
        
        Args:
            symbol: Symbol name to find
            
        Returns:
            SymbolSpec if found, None otherwise
        """
        possible_names = self.normalize_symbol_name(symbol)

        for symbol_name in possible_names:
            try:
                spec = await self.get_symbol_info(symbol_name)
                if spec:
                    self.logger.info(f"Found symbol '{symbol}' as '{symbol_name}' on broker")
                    return spec
            except Exception as e:
                self.logger.debug(f"Symbol '{symbol_name}' not found: {e}")
                continue

        self.logger.warning(f"Symbol '{symbol}' not found with any variation: {possible_names}")
        return None

    async def validate_symbol(self, symbol: str) -> dict[str, Any]:
        """
        Validate symbol and return comprehensive information.
        
        Args:
            symbol: Symbol to validate
            
        Returns:
            Dictionary with validation results and specifications
        """
        # Check cache first
        cache_key = symbol.upper()
        if (cache_key in self.cache and
            cache_key in self.cache_expiry and
            datetime.now(UTC) < self.cache_expiry[cache_key]):

            self.logger.debug(f"Returning cached symbol spec for {symbol}")
            return self.cache[cache_key]

        try:
            # Find symbol specification
            spec = await self.find_symbol(symbol)

            if spec is None:
                result = {
                    'valid': False,
                    'symbol': symbol,
                    'error': f'Symbol {symbol} not found on broker',
                    'possible_names': self.normalize_symbol_name(symbol),
                    'specifications': None,
                    'trading_info': None,
                    'market_hours': None
                }
            else:
                # Get current tick for spread info
                tick_info = await self._get_current_tick(spec.symbol)
                current_spread = tick_info.get('spread', 0) if tick_info else spec.spread

                # Calculate pip information
                pip_info = self._calculate_pip_info(spec)

                # Get market hours
                market_hours = await self._get_market_hours(spec.symbol)

                # Validate trading conditions
                trading_validation = self._validate_trading_conditions(spec)

                result = {
                    'valid': True,
                    'symbol': spec.symbol,
                    'original_symbol': symbol,
                    'error': None,
                    'specifications': {
                        'description': spec.description,
                        'currency_base': spec.currency_base,
                        'currency_profit': spec.currency_profit,
                        'digits': spec.digits,
                        'point': spec.point,
                        'tick_size': spec.tick_size,
                        'tick_value': spec.tick_value,
                        'pip_size': pip_info['pip_size'],
                        'pip_value': pip_info['pip_value'],
                        'spread_points': current_spread,
                        'spread_pips': current_spread * pip_info['pip_size'],
                    },
                    'trading_info': {
                        'min_volume': spec.volume_min,
                        'max_volume': spec.volume_max,
                        'volume_step': spec.volume_step,
                        'stops_level': spec.trade_stops_level,
                        'freeze_level': spec.trade_freeze_level,
                        'trade_allowed': spec.trade_allowed and trading_validation['allowed'],
                        'margin_initial': spec.margin_initial,
                        'margin_maintenance': spec.margin_maintenance,
                        'validation_errors': trading_validation['errors']
                    },
                    'market_hours': market_hours,
                    'cached_at': datetime.now(UTC).isoformat()
                }

                self.logger.info(
                    f"Symbol validation successful for {symbol} -> {spec.symbol}: "
                    f"pip_size={pip_info['pip_size']}, min_lot={spec.volume_min}, "
                    f"spread={current_spread} points"
                )

            # Cache the result
            self.cache[cache_key] = result
            self.cache_expiry[cache_key] = datetime.now(UTC) + self.cache_duration

            return result

        except Exception as e:
            self.logger.error(f"Symbol validation failed for {symbol}: {e}")
            error_result = {
                'valid': False,
                'symbol': symbol,
                'error': f'Validation error: {e!s}',
                'possible_names': self.normalize_symbol_name(symbol),
                'specifications': None,
                'trading_info': None,
                'market_hours': None
            }

            # Cache error for short time to avoid repeated failures
            self.cache[cache_key] = error_result
            self.cache_expiry[cache_key] = datetime.now(UTC) + timedelta(minutes=5)

            return error_result

    def _calculate_pip_info(self, spec: SymbolSpec) -> dict[str, float]:
        """
        Calculate pip size and value for the symbol.
        
        Args:
            spec: Symbol specification
            
        Returns:
            Dictionary with pip information
        """
        # For GOLD/XAUUSD, pip is usually 0.01 (1 cent)
        # For most forex pairs, pip is 0.0001
        if spec.digits == 5 or spec.digits == 3:
            # 5-digit or 3-digit broker (fractional pips)
            pip_size = spec.point * 10
        else:
            # Standard 4-digit or 2-digit pricing
            pip_size = spec.point

        # For GOLD, pip size is typically 0.01
        if 'XAU' in spec.symbol or 'GOLD' in spec.symbol:
            pip_size = 0.01

        # Calculate pip value (how much 1 pip movement is worth)
        # For XAUUSD, 1 pip = 0.01 * tick_value / tick_size
        try:
            pip_value = (pip_size / spec.tick_size) * spec.tick_value
        except ZeroDivisionError:
            pip_value = spec.tick_value

        return {
            'pip_size': pip_size,
            'pip_value': pip_value,
            'point': spec.point,
            'digits': spec.digits
        }

    def _validate_trading_conditions(self, spec: SymbolSpec) -> dict[str, Any]:
        """
        Validate if symbol can be traded.
        
        Args:
            spec: Symbol specification
            
        Returns:
            Dictionary with validation results
        """
        errors = []

        if not spec.trade_allowed:
            errors.append("Trading not allowed for this symbol")

        if spec.volume_min <= 0:
            errors.append("Invalid minimum volume")

        if spec.volume_max <= spec.volume_min:
            errors.append("Invalid volume range")

        if spec.trade_mode == 0:  # TRADE_DISABLED
            errors.append("Trading disabled by broker")

        return {
            'allowed': len(errors) == 0,
            'errors': errors
        }

    async def _get_current_tick(self, symbol: str) -> dict[str, Any] | None:
        """
        Get current tick information for symbol.
        
        Args:
            symbol: Symbol name
            
        Returns:
            Tick information dictionary or None
        """
        try:
            async with self.connection_manager.get_connection() as connection:
                if mt5 is None or not connection.connected:
                    return None

                tick = mt5.symbol_info_tick(symbol)
                if tick is None:
                    return None

                return {
                    'bid': tick.bid,
                    'ask': tick.ask,
                    'spread': tick.ask - tick.bid,
                    'time': tick.time,
                    'volume': tick.volume,
                    'last': tick.last
                }

        except Exception as e:
            self.logger.debug(f"Failed to get current tick for {symbol}: {e}")
            return None

    async def _get_market_hours(self, symbol: str) -> list[MarketHours]:
        """
        Get market hours for symbol.
        
        Args:
            symbol: Symbol name
            
        Returns:
            List of market session hours
        """
        try:
            # For GOLD/XAUUSD, trading hours are typically:
            # Monday 00:01 - Friday 23:59 (with daily break 23:59-00:01)
            # This is a simplified implementation
            return [
                MarketHours(
                    symbol=symbol,
                    session_name="Main Session",
                    start_time="00:01",
                    end_time="23:59",
                    is_active=True  # Simplified - should check actual broker sessions
                )
            ]

        except Exception as e:
            self.logger.debug(f"Failed to get market hours for {symbol}: {e}")
            return []

    async def refresh_cache(self) -> None:
        """Refresh all cached symbol specifications."""
        self.logger.info("Refreshing symbol specification cache")

        # Clear expired entries
        current_time = datetime.now(UTC)
        expired_keys = [
            key for key, expiry in self.cache_expiry.items()
            if current_time >= expiry
        ]

        for key in expired_keys:
            del self.cache[key]
            del self.cache_expiry[key]

        self.logger.info(f"Cleared {len(expired_keys)} expired cache entries")

    def get_cache_status(self) -> dict[str, Any]:
        """
        Get current cache status.
        
        Returns:
            Dictionary with cache information
        """
        current_time = datetime.now(UTC)

        return {
            'total_entries': len(self.cache),
            'expired_entries': sum(1 for exp in self.cache_expiry.values() if current_time >= exp),
            'cache_duration_minutes': self.cache_duration.total_seconds() / 60,
            'cached_symbols': list(self.cache.keys()),
            'last_refresh': current_time.isoformat()
        }


# Global symbol validator instance (will be initialized with connection manager)
symbol_validator = None


def initialize_symbol_validator(connection_manager):
    """Initialize global symbol validator instance."""
    global symbol_validator
    symbol_validator = SymbolValidator(connection_manager)
    return symbol_validator
