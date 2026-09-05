"""
MT5 position management with break even support.

This module provides position modification capabilities for MT5, specifically
supporting break even operations with proper error handling and circuit breaker protection.
Follows coding standards: circuit breaker decorator, structured logging, async cancellation.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

try:
    import MetaTrader5 as mt5
except ImportError:
    # For testing environments where MT5 is not available
    mt5 = None

from src.mt5_executor.connection import MT5ConnectionManager, get_connection_manager
from src.utils.decorators import circuit_breaker, log_execution_time, retry_on_failure
from src.utils.formatters import normalize_price


@dataclass
class MT5Result:
    """Result of MT5 operation with detailed status information."""
    success: bool
    ticket: int | None
    operation: str
    old_sl: float | None = None
    new_sl: float | None = None
    old_tp: float | None = None
    new_tp: float | None = None
    volume_closed: float | None = None
    close_price: float | None = None
    profit: float | None = None
    error_code: int | None = None
    error_message: str | None = None
    retcode: int | None = None
    execution_time_ms: float | None = None


class PositionManager:
    """
    MT5 position manager for break even and other position modifications.
    
    Provides secure position modification capabilities with proper error handling,
    circuit breaker protection, and comprehensive audit logging.
    """

    def __init__(self, connection_manager: MT5ConnectionManager | None = None):
        """
        Initialize position manager.
        
        Args:
            connection_manager: MT5 connection manager (uses global if None)
        """
        self.connection_manager = connection_manager or get_connection_manager()
        self.logger = logging.getLogger(__name__)

    @circuit_breaker(failure_threshold=3, recovery_timeout=30)
    @retry_on_failure(max_attempts=3, delay=1.0, backoff=2.0)
    @log_execution_time
    async def modify_stop_loss(
        self,
        ticket: int,
        new_sl: float,
        preserve_tp: bool = True
    ) -> MT5Result:
        """
        Modify stop-loss for a position while preserving take-profit.
        
        Args:
            ticket: MT5 position ticket number
            new_sl: New stop-loss price (normalized)
            preserve_tp: Whether to preserve existing take-profit (default: True)
            
        Returns:
            MT5Result with operation outcome and details
        """
        start_time = datetime.now()

        try:
            if mt5 is None:
                return MT5Result(
                    success=False,
                    ticket=ticket,
                    operation="modify_stop_loss",
                    error_message="MT5 module not available"
                )

            self.logger.info(
                f"Starting SL modification for ticket {ticket}",
                extra={
                    'ticket': ticket,
                    'new_sl': new_sl,
                    'preserve_tp': preserve_tp,
                    'operation': 'modify_stop_loss'
                }
            )

            # Get current position details
            async with self.connection_manager.get_connection() as connection:
                if not connection.connected:
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="modify_stop_loss",
                        error_message="MT5 connection not available"
                    )

                # Get position info
                position_info = mt5.positions_get(ticket=ticket)
                if not position_info or len(position_info) == 0:
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="modify_stop_loss",
                        error_message=f"Position {ticket} not found or already closed"
                    )

                position = position_info[0]
                old_sl = position.sl
                old_tp = position.tp if preserve_tp else None

                # Normalize new SL price
                normalized_sl = normalize_price(new_sl, position.symbol)

                # Security check: Validate SL is reasonable
                if normalized_sl <= 0 or normalized_sl > 10000:
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="modify_stop_loss",
                        error_message=f"Invalid SL price: {normalized_sl}"
                    )

                # Prepare modification request
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": position.symbol,
                    "position": ticket,
                    "sl": normalized_sl,
                    "tp": old_tp if preserve_tp else 0.0,
                    "magic": position.magic,
                    "comment": "Break Even SL Modification"
                }

                self.logger.debug(
                    f"Sending MT5 modification request for ticket {ticket}",
                    extra={
                        'request': {
                            'action': 'TRADE_ACTION_SLTP',
                            'symbol': position.symbol,
                            'position': ticket,
                            'sl': normalized_sl,
                            'tp': old_tp,
                            'magic': position.magic
                        },
                        'old_sl': old_sl,
                        'old_tp': old_tp
                    }
                )

                # Execute modification
                result = mt5.order_send(request)
                execution_time = (datetime.now() - start_time).total_seconds() * 1000

                if result is None:
                    error = mt5.last_error()
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="modify_stop_loss",
                        old_sl=old_sl,
                        new_sl=normalized_sl,
                        old_tp=old_tp,
                        error_code=error[0] if error else None,
                        error_message=f"MT5 order_send failed: {error[1] if error else 'Unknown error'}",
                        execution_time_ms=execution_time
                    )

                # Check result
                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    error_msg = self._get_retcode_description(result.retcode)

                    self.logger.error(
                        f"MT5 modification failed for ticket {ticket}",
                        extra={
                            'ticket': ticket,
                            'retcode': result.retcode,
                            'error_description': error_msg,
                            'execution_time_ms': execution_time
                        }
                    )

                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="modify_stop_loss",
                        old_sl=old_sl,
                        new_sl=normalized_sl,
                        old_tp=old_tp,
                        retcode=result.retcode,
                        error_message=error_msg,
                        execution_time_ms=execution_time
                    )

                # Success - log details
                self.logger.info(
                    f"SL modification successful for ticket {ticket}",
                    extra={
                        'ticket': ticket,
                        'old_sl': old_sl,
                        'new_sl': normalized_sl,
                        'tp_preserved': old_tp,
                        'retcode': result.retcode,
                        'execution_time_ms': execution_time
                    }
                )

                return MT5Result(
                    success=True,
                    ticket=ticket,
                    operation="modify_stop_loss",
                    old_sl=old_sl,
                    new_sl=normalized_sl,
                    old_tp=old_tp,
                    new_tp=old_tp,  # Preserved
                    retcode=result.retcode,
                    execution_time_ms=execution_time
                )

        except asyncio.CancelledError:
            self.logger.info(f"SL modification cancelled for ticket {ticket}")
            raise
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            self.logger.error(
                f"Exception during SL modification for ticket {ticket}: {e}",
                extra={
                    'ticket': ticket,
                    'new_sl': new_sl,
                    'error': str(e),
                    'execution_time_ms': execution_time
                }
            )

            return MT5Result(
                success=False,
                ticket=ticket,
                operation="modify_stop_loss",
                error_message=f"Exception: {e!s}",
                execution_time_ms=execution_time
            )

    @circuit_breaker(failure_threshold=3, recovery_timeout=30)
    async def validate_modification_success(
        self,
        ticket: int,
        expected_sl: float,
        timeout_seconds: int = 10
    ) -> bool:
        """
        Validate that stop-loss modification was applied successfully.
        
        Args:
            ticket: MT5 position ticket
            expected_sl: Expected new stop-loss value
            timeout_seconds: Maximum time to wait for update
            
        Returns:
            True if modification was applied successfully
        """
        try:
            if mt5 is None:
                self.logger.error("MT5 module not available for validation")
                return False

            async with self.connection_manager.get_connection() as connection:
                if not connection.connected:
                    self.logger.error("MT5 connection not available for validation")
                    return False

                # Wait for modification to be reflected (with timeout)
                start_time = datetime.now()
                expected_sl_normalized = normalize_price(expected_sl, "GOLD")

                while (datetime.now() - start_time).total_seconds() < timeout_seconds:
                    position_info = mt5.positions_get(ticket=ticket)

                    if not position_info or len(position_info) == 0:
                        self.logger.warning(f"Position {ticket} not found during validation")
                        return False

                    current_sl = position_info[0].sl
                    current_sl_normalized = normalize_price(current_sl, "GOLD")

                    # Check if SL matches expected value (allow small floating point differences)
                    if abs(current_sl_normalized - expected_sl_normalized) < 0.001:
                        self.logger.info(
                            f"SL modification validated successfully for ticket {ticket}",
                            extra={
                                'ticket': ticket,
                                'expected_sl': expected_sl_normalized,
                                'actual_sl': current_sl_normalized,
                                'validation_time_seconds': (datetime.now() - start_time).total_seconds()
                            }
                        )
                        return True

                    # Small delay before retry
                    await asyncio.sleep(0.5)

                # Timeout reached
                self.logger.error(
                    f"SL modification validation failed for ticket {ticket} - timeout",
                    extra={
                        'ticket': ticket,
                        'expected_sl': expected_sl_normalized,
                        'timeout_seconds': timeout_seconds
                    }
                )
                return False

        except Exception as e:
            self.logger.error(f"Error validating SL modification: {e}")
            return False

    async def get_position_details(self, ticket: int) -> dict[str, Any] | None:
        """
        Get current position details from MT5.
        
        Args:
            ticket: MT5 position ticket
            
        Returns:
            Dictionary with position details or None if not found
        """
        try:
            if mt5 is None:
                return None

            async with self.connection_manager.get_connection() as connection:
                if not connection.connected:
                    return None

                position_info = mt5.positions_get(ticket=ticket)
                if not position_info or len(position_info) == 0:
                    return None

                position = position_info[0]
                return {
                    'ticket': position.ticket,
                    'symbol': position.symbol,
                    'time': position.time,
                    'type': position.type,
                    'volume': position.volume,
                    'price_open': position.price_open,
                    'sl': position.sl,
                    'tp': position.tp,
                    'price_current': position.price_current,
                    'profit': position.profit,
                    'swap': position.swap,
                    'commission': position.commission,
                    'magic': position.magic,
                    'comment': position.comment
                }

        except Exception as e:
            self.logger.error(f"Error getting position details for ticket {ticket}: {e}")
            return None

    def _get_retcode_description(self, retcode: int) -> str:
        """
        Get human-readable description for MT5 return code.
        
        Args:
            retcode: MT5 return code
            
        Returns:
            Description of the return code
        """
        retcode_descriptions = {
            mt5.TRADE_RETCODE_REQUOTE: "Requote",
            mt5.TRADE_RETCODE_REJECT: "Request rejected",
            mt5.TRADE_RETCODE_CANCEL: "Request cancelled by trader",
            mt5.TRADE_RETCODE_PLACED: "Order placed",
            mt5.TRADE_RETCODE_DONE: "Request completed",
            mt5.TRADE_RETCODE_DONE_PARTIAL: "Request partially completed",
            mt5.TRADE_RETCODE_ERROR: "Request processing error",
            mt5.TRADE_RETCODE_TIMEOUT: "Request cancelled by timeout",
            mt5.TRADE_RETCODE_INVALID: "Invalid request",
            mt5.TRADE_RETCODE_INVALID_VOLUME: "Invalid volume in request",
            mt5.TRADE_RETCODE_INVALID_PRICE: "Invalid price in request",
            mt5.TRADE_RETCODE_INVALID_STOPS: "Invalid stops in request",
            mt5.TRADE_RETCODE_TRADE_DISABLED: "Trade is disabled",
            mt5.TRADE_RETCODE_MARKET_CLOSED: "Market is closed",
            mt5.TRADE_RETCODE_NO_MONEY: "Not enough money to complete request",
            mt5.TRADE_RETCODE_PRICE_CHANGED: "Price changed",
            mt5.TRADE_RETCODE_PRICE_OFF: "Off quotes",
            mt5.TRADE_RETCODE_INVALID_EXPIRATION: "Invalid request expiration",
            mt5.TRADE_RETCODE_ORDER_CHANGED: "Order state changed",
            mt5.TRADE_RETCODE_TOO_MANY_REQUESTS: "Too frequent requests",
            mt5.TRADE_RETCODE_NO_CHANGES: "No changes in request",
            mt5.TRADE_RETCODE_SERVER_DISABLES_AT: "Autotrading disabled by server",
            mt5.TRADE_RETCODE_CLIENT_DISABLES_AT: "Autotrading disabled by client",
            mt5.TRADE_RETCODE_LOCKED: "Request locked for processing",
            mt5.TRADE_RETCODE_FROZEN: "Order or position frozen",
            mt5.TRADE_RETCODE_INVALID_FILL: "Invalid order filling type",
            mt5.TRADE_RETCODE_CONNECTION: "No connection with trade server",
            mt5.TRADE_RETCODE_ONLY_REAL: "Operation allowed only for live accounts",
            mt5.TRADE_RETCODE_LIMIT_ORDERS: "Number of pending orders reached limit",
            mt5.TRADE_RETCODE_LIMIT_VOLUME: "Volume of orders and positions reached limit",
            mt5.TRADE_RETCODE_INVALID_ORDER: "Incorrect or prohibited order type",
            mt5.TRADE_RETCODE_POSITION_CLOSED: "Position with specified POSITION_IDENTIFIER already closed"
        }

        return retcode_descriptions.get(retcode, f"Unknown return code: {retcode}")

    async def rollback_modification(
        self,
        ticket: int,
        original_sl: float | None,
        original_tp: float | None
    ) -> MT5Result:
        """
        Rollback position modification to original values.
        
        Args:
            ticket: MT5 position ticket
            original_sl: Original stop-loss value
            original_tp: Original take-profit value
            
        Returns:
            MT5Result with rollback outcome
        """
        try:
            self.logger.warning(
                f"Attempting rollback for ticket {ticket}",
                extra={
                    'ticket': ticket,
                    'original_sl': original_sl,
                    'original_tp': original_tp
                }
            )

            if mt5 is None:
                return MT5Result(
                    success=False,
                    ticket=ticket,
                    operation="rollback_modification",
                    error_message="MT5 module not available for rollback"
                )

            async with self.connection_manager.get_connection() as connection:
                if not connection.connected:
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="rollback_modification",
                        error_message="MT5 connection not available for rollback"
                    )

                # Get current position
                position_info = mt5.positions_get(ticket=ticket)
                if not position_info or len(position_info) == 0:
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="rollback_modification",
                        error_message=f"Position {ticket} not found for rollback"
                    )

                position = position_info[0]

                # Prepare rollback request
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": position.symbol,
                    "position": ticket,
                    "sl": original_sl if original_sl else 0.0,
                    "tp": original_tp if original_tp else 0.0,
                    "magic": position.magic,
                    "comment": "Break Even Rollback"
                }

                # Execute rollback
                result = mt5.order_send(request)

                if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                    error_msg = self._get_retcode_description(result.retcode) if result else "Unknown error"
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="rollback_modification",
                        error_message=f"Rollback failed: {error_msg}",
                        retcode=result.retcode if result else None
                    )

                self.logger.info(f"Rollback successful for ticket {ticket}")
                return MT5Result(
                    success=True,
                    ticket=ticket,
                    operation="rollback_modification",
                    old_sl=position.sl,
                    new_sl=original_sl,
                    old_tp=position.tp,
                    new_tp=original_tp,
                    retcode=result.retcode
                )

        except Exception as e:
            self.logger.error(f"Exception during rollback for ticket {ticket}: {e}")
            return MT5Result(
                success=False,
                ticket=ticket,
                operation="rollback_modification",
                error_message=f"Rollback exception: {e!s}"
            )

    @circuit_breaker(failure_threshold=3, recovery_timeout=30)
    @retry_on_failure(max_attempts=3, delay=1.0, backoff=2.0)
    @log_execution_time
    async def close_position_full(self, ticket: int) -> MT5Result:
        """
        Close position completely using MT5 OrderSend function.
        
        Args:
            ticket: MT5 position ticket number
            
        Returns:
            MT5Result with close operation outcome and details
        """
        start_time = datetime.now()

        try:
            if mt5 is None:
                return MT5Result(
                    success=False,
                    ticket=ticket,
                    operation="close_position_full",
                    error_message="MT5 module not available"
                )

            self.logger.info(
                f"Starting full close for ticket {ticket}",
                extra={
                    'ticket': ticket,
                    'operation': 'close_position_full'
                }
            )

            # Get current position details
            async with self.connection_manager.get_connection() as connection:
                if not connection.connected:
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="close_position_full",
                        error_message="MT5 connection not available"
                    )

                # Get position info
                position_info = mt5.positions_get(ticket=ticket)
                if not position_info or len(position_info) == 0:
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="close_position_full",
                        error_message=f"Position {ticket} not found or already closed"
                    )

                position = position_info[0]

                # Determine opposite order type for closing
                if position.type == mt5.ORDER_TYPE_BUY:
                    order_type = mt5.ORDER_TYPE_SELL
                    price = mt5.symbol_info_tick(position.symbol).bid
                else:  # SELL position
                    order_type = mt5.ORDER_TYPE_BUY
                    price = mt5.symbol_info_tick(position.symbol).ask

                if price is None:
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="close_position_full",
                        error_message=f"Unable to get current price for {position.symbol}"
                    )

                # Prepare close request
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": position.symbol,
                    "volume": position.volume,
                    "type": order_type,
                    "position": ticket,
                    "price": price,
                    "magic": position.magic,
                    "comment": "Full Close",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }

                self.logger.debug(
                    f"Sending MT5 close request for ticket {ticket}",
                    extra={
                        'request': {
                            'action': 'TRADE_ACTION_DEAL',
                            'symbol': position.symbol,
                            'volume': position.volume,
                            'type': 'SELL' if order_type == mt5.ORDER_TYPE_SELL else 'BUY',
                            'position': ticket,
                            'price': price,
                            'magic': position.magic
                        },
                        'original_volume': position.volume
                    }
                )

                # Execute close
                result = mt5.order_send(request)
                execution_time = (datetime.now() - start_time).total_seconds() * 1000

                if result is None:
                    error = mt5.last_error()
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="close_position_full",
                        error_code=error[0] if error else None,
                        error_message=f"MT5 order_send failed: {error[1] if error else 'Unknown error'}",
                        execution_time_ms=execution_time
                    )

                # Check result
                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    error_msg = self._get_retcode_description(result.retcode)

                    self.logger.error(
                        f"MT5 close failed for ticket {ticket}",
                        extra={
                            'ticket': ticket,
                            'retcode': result.retcode,
                            'error_description': error_msg,
                            'execution_time_ms': execution_time
                        }
                    )

                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="close_position_full",
                        retcode=result.retcode,
                        error_message=error_msg,
                        execution_time_ms=execution_time
                    )

                # Success - log details
                self.logger.info(
                    f"Full close successful for ticket {ticket}",
                    extra={
                        'ticket': ticket,
                        'volume_closed': position.volume,
                        'close_price': price,
                        'retcode': result.retcode,
                        'execution_time_ms': execution_time
                    }
                )

                return MT5Result(
                    success=True,
                    ticket=ticket,
                    operation="close_position_full",
                    volume_closed=position.volume,
                    close_price=price,
                    profit=position.profit,
                    retcode=result.retcode,
                    execution_time_ms=execution_time
                )

        except asyncio.CancelledError:
            self.logger.info(f"Full close cancelled for ticket {ticket}")
            raise
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            self.logger.error(
                f"Exception during full close for ticket {ticket}: {e}",
                extra={
                    'ticket': ticket,
                    'error': str(e),
                    'execution_time_ms': execution_time
                }
            )

            return MT5Result(
                success=False,
                ticket=ticket,
                operation="close_position_full",
                error_message=f"Exception: {e!s}",
                execution_time_ms=execution_time
            )

    @circuit_breaker(failure_threshold=3, recovery_timeout=30)
    @retry_on_failure(max_attempts=3, delay=1.0, backoff=2.0)
    @log_execution_time
    async def close_position_partial(self, ticket: int, percentage: float) -> MT5Result:
        """
        Close position partially based on percentage.
        
        Args:
            ticket: MT5 position ticket number
            percentage: Percentage to close (0.0-1.0)
            
        Returns:
            MT5Result with partial close operation outcome and details
        """
        start_time = datetime.now()

        try:
            if mt5 is None:
                return MT5Result(
                    success=False,
                    ticket=ticket,
                    operation="close_position_partial",
                    error_message="MT5 module not available"
                )

            if not (0.0 < percentage < 1.0):
                return MT5Result(
                    success=False,
                    ticket=ticket,
                    operation="close_position_partial",
                    error_message=f"Invalid percentage: {percentage}. Must be between 0.0 and 1.0"
                )

            self.logger.info(
                f"Starting partial close for ticket {ticket} ({percentage:.1%})",
                extra={
                    'ticket': ticket,
                    'percentage': percentage,
                    'operation': 'close_position_partial'
                }
            )

            # Get current position details
            async with self.connection_manager.get_connection() as connection:
                if not connection.connected:
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="close_position_partial",
                        error_message="MT5 connection not available"
                    )

                # Get position info
                position_info = mt5.positions_get(ticket=ticket)
                if not position_info or len(position_info) == 0:
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="close_position_partial",
                        error_message=f"Position {ticket} not found or already closed"
                    )

                position = position_info[0]

                # Calculate close volume with proper lot normalization
                close_volume = self._calculate_partial_volume(position.volume, percentage, position.symbol)

                if close_volume <= 0:
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="close_position_partial",
                        error_message=f"Calculated close volume too small: {close_volume}"
                    )

                # Determine opposite order type for closing
                if position.type == mt5.ORDER_TYPE_BUY:
                    order_type = mt5.ORDER_TYPE_SELL
                    price = mt5.symbol_info_tick(position.symbol).bid
                else:  # SELL position
                    order_type = mt5.ORDER_TYPE_BUY
                    price = mt5.symbol_info_tick(position.symbol).ask

                if price is None:
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="close_position_partial",
                        error_message=f"Unable to get current price for {position.symbol}"
                    )

                # Prepare partial close request
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": position.symbol,
                    "volume": close_volume,
                    "type": order_type,
                    "position": ticket,
                    "price": price,
                    "magic": position.magic,
                    "comment": f"Partial Close {percentage:.1%}",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }

                self.logger.debug(
                    f"Sending MT5 partial close request for ticket {ticket}",
                    extra={
                        'request': {
                            'action': 'TRADE_ACTION_DEAL',
                            'symbol': position.symbol,
                            'volume': close_volume,
                            'type': 'SELL' if order_type == mt5.ORDER_TYPE_SELL else 'BUY',
                            'position': ticket,
                            'price': price,
                            'magic': position.magic
                        },
                        'original_volume': position.volume,
                        'percentage': percentage
                    }
                )

                # Execute partial close
                result = mt5.order_send(request)
                execution_time = (datetime.now() - start_time).total_seconds() * 1000

                if result is None:
                    error = mt5.last_error()
                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="close_position_partial",
                        error_code=error[0] if error else None,
                        error_message=f"MT5 order_send failed: {error[1] if error else 'Unknown error'}",
                        execution_time_ms=execution_time
                    )

                # Check result
                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    error_msg = self._get_retcode_description(result.retcode)

                    self.logger.error(
                        f"MT5 partial close failed for ticket {ticket}",
                        extra={
                            'ticket': ticket,
                            'percentage': percentage,
                            'close_volume': close_volume,
                            'retcode': result.retcode,
                            'error_description': error_msg,
                            'execution_time_ms': execution_time
                        }
                    )

                    return MT5Result(
                        success=False,
                        ticket=ticket,
                        operation="close_position_partial",
                        retcode=result.retcode,
                        error_message=error_msg,
                        execution_time_ms=execution_time
                    )

                # Calculate profit for closed portion (approximate)
                partial_profit = position.profit * percentage

                # Success - log details
                self.logger.info(
                    f"Partial close successful for ticket {ticket}",
                    extra={
                        'ticket': ticket,
                        'percentage': percentage,
                        'volume_closed': close_volume,
                        'original_volume': position.volume,
                        'close_price': price,
                        'partial_profit': partial_profit,
                        'retcode': result.retcode,
                        'execution_time_ms': execution_time
                    }
                )

                return MT5Result(
                    success=True,
                    ticket=ticket,
                    operation="close_position_partial",
                    volume_closed=close_volume,
                    close_price=price,
                    profit=partial_profit,
                    retcode=result.retcode,
                    execution_time_ms=execution_time
                )

        except asyncio.CancelledError:
            self.logger.info(f"Partial close cancelled for ticket {ticket}")
            raise
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            self.logger.error(
                f"Exception during partial close for ticket {ticket}: {e}",
                extra={
                    'ticket': ticket,
                    'percentage': percentage,
                    'error': str(e),
                    'execution_time_ms': execution_time
                }
            )

            return MT5Result(
                success=False,
                ticket=ticket,
                operation="close_position_partial",
                error_message=f"Exception: {e!s}",
                execution_time_ms=execution_time
            )

    def _calculate_partial_volume(self, current_volume: float, percentage: float, symbol: str) -> float:
        """
        Calculate partial close volume with proper lot normalization.
        
        Args:
            current_volume: Current position volume
            percentage: Percentage to close (0.0-1.0)
            symbol: Trading symbol for lot size validation
            
        Returns:
            Normalized volume for partial close
        """
        # Calculate raw close volume
        raw_close_volume = current_volume * percentage

        # Get symbol lot size information for normalization
        # Default to 0.01 for GOLD if symbol info unavailable
        min_volume = 0.01
        volume_step = 0.01

        if mt5 and symbol:
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info:
                min_volume = symbol_info.volume_min
                volume_step = symbol_info.volume_step

        # Normalize to valid lot size
        if raw_close_volume < min_volume:
            return 0.0  # Too small to close

        # Round down to nearest valid step
        normalized_volume = int(raw_close_volume / volume_step) * volume_step

        # Ensure we don't exceed current volume
        if normalized_volume > current_volume:
            normalized_volume = current_volume

        # Round to 2 decimal places for GOLD precision
        return round(normalized_volume, 2)
