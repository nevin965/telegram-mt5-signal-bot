"""
Position modification and price calculation utilities for break even processing.

This module provides utilities for calculating break even prices and validating
position modifications according to broker constraints and risk management rules.
Follows coding standards: structured logging, proper error handling.
"""

import logging
from dataclasses import dataclass
from typing import Any

from src.database.models import Position
from src.utils.formatters import (
    add_pips_to_price,
    calculate_pips_difference,
    normalize_price,
    validate_price_range,
)


@dataclass
class BreakEvenCalculation:
    """Result of break even price calculation."""
    entry_price: float
    new_sl: float
    old_sl: float | None
    pip_adjustment: float
    symbol: str
    valid: bool
    error_message: str | None = None


@dataclass
class PositionValidation:
    """Result of position validation for break even."""
    valid: bool
    position_id: int
    mt5_ticket: int | None
    error_message: str | None = None
    warnings: list | None = None


class PositionModifier:
    """
    Position modification utility for break even processing.

    Handles price calculations, validation, and broker constraint checking
    for stop-loss modifications in break even scenarios.
    """

    def __init__(self):
        """Initialize position modifier."""
        self.logger = logging.getLogger(__name__)

    def calculate_break_even_price(self, entry_price: float, side: str) -> float:
        """
        Calculate break even price for both BUY and SELL positions.

        For break even, we always move SL to entry + 1 pip:
        - BUY positions: SL moves from below entry to entry + 1 pip (secures profit)
        - SELL positions: SL moves to entry + 1 pip above entry (secures profit)

        Args:
            entry_price: Original entry price of the position
            side: Position direction ("BUY" or "SELL")

        Returns:
            New stop-loss price (entry + 1 pip) normalized to GOLD precision

        Example:
            >>> modifier = PositionModifier()
            >>> modifier.calculate_break_even_price(1850.00, "BUY")
            1850.01
            >>> modifier.calculate_break_even_price(1850.00, "SELL")
            1850.01  # Same for SELL - SL above entry secures profit
        """
        if not entry_price or entry_price <= 0:
            raise ValueError(f"Invalid entry price: {entry_price}")

        if side not in ["BUY", "SELL"]:
            raise ValueError(f"Invalid position side: {side}")

        # For break even, always add 1 pip to entry price regardless of direction
        # This creates profitable SL for both BUY (SL above entry) and SELL (SL above entry)
        new_sl = add_pips_to_price(
            price=entry_price,
            pips=1,
            symbol="GOLD",
            direction=side  # Direction doesn't affect calculation for BE
        )

        self.logger.debug(
            f"Break even price calculated: {entry_price} -> {new_sl}",
            extra={
                'entry_price': entry_price,
                'new_sl': new_sl,
                'side': side,
                'pip_adjustment': 1,
                'symbol': 'GOLD'
            }
        )

        return new_sl

    def validate_break_even_calculation(
        self,
        position: Position,
        new_sl: float
    ) -> BreakEvenCalculation:
        """
        Validate break even calculation for a position.

        Args:
            position: Position to validate
            new_sl: Calculated new stop-loss price

        Returns:
            BreakEvenCalculation with validation results
        """
        try:
            if not position.open_price:
                return BreakEvenCalculation(
                    entry_price=0.0,
                    new_sl=new_sl,
                    old_sl=position.current_sl,
                    pip_adjustment=1,
                    symbol="GOLD",
                    valid=False,
                    error_message="Position entry price not available"
                )

            # Calculate pip adjustment from entry
            pip_difference = calculate_pips_difference(
                price1=new_sl,
                price2=position.open_price,
                symbol="GOLD"
            )

            # Validate pip adjustment is exactly +1
            if abs(pip_difference - 1.0) > 0.001:  # Allow small FP errors
                return BreakEvenCalculation(
                    entry_price=position.open_price,
                    new_sl=new_sl,
                    old_sl=position.current_sl,
                    pip_adjustment=pip_difference,
                    symbol="GOLD",
                    valid=False,
                    error_message=f"Invalid pip adjustment: {pip_difference:.3f} (expected: 1.0)"
                )

            # Validate price is normalized correctly
            normalized_sl = normalize_price(new_sl, "GOLD")
            if abs(new_sl - normalized_sl) > 0.001:
                return BreakEvenCalculation(
                    entry_price=position.open_price,
                    new_sl=normalized_sl,
                    old_sl=position.current_sl,
                    pip_adjustment=pip_difference,
                    symbol="GOLD",
                    valid=False,
                    error_message=f"Price normalization error: {new_sl} != {normalized_sl}"
                )

            # Validation passed
            return BreakEvenCalculation(
                entry_price=position.open_price,
                new_sl=normalized_sl,
                old_sl=position.current_sl,
                pip_adjustment=pip_difference,
                symbol="GOLD",
                valid=True
            )

        except Exception as e:
            self.logger.error(f"Error validating break even calculation: {e}")
            return BreakEvenCalculation(
                entry_price=position.open_price or 0.0,
                new_sl=new_sl,
                old_sl=position.current_sl,
                pip_adjustment=0.0,
                symbol="GOLD",
                valid=False,
                error_message=f"Validation error: {e!s}"
            )

    def validate_position_for_break_even(self, position: Position) -> PositionValidation:
        """
        Validate position eligibility for break even modification.

        Checks:
        - Position is open and has MT5 ticket
        - Entry price is available
        - Current SL exists and is not already at break even
        - Position has not expired or been closed

        Args:
            position: Position to validate

        Returns:
            PositionValidation with eligibility results
        """
        warnings = []

        try:
            # Check position is open
            if not position.is_open:
                return PositionValidation(
                    valid=False,
                    position_id=position.id,
                    mt5_ticket=position.mt5_ticket,
                    error_message=(
                        f"Position {position.id} not open: {position.status}"
                    )
                )

            # Check MT5 ticket exists
            if not position.mt5_ticket:
                return PositionValidation(
                    valid=False,
                    position_id=position.id,
                    mt5_ticket=None,
                    error_message=f"Position {position.id} has no MT5 ticket"
                )

            # Check entry price exists
            if not position.open_price:
                return PositionValidation(
                    valid=False,
                    position_id=position.id,
                    mt5_ticket=position.mt5_ticket,
                    error_message=f"Position {position.id} missing entry price"
                )

            # Check if SL is already at break even (entry + 1 pip)
            if position.current_sl:
                expected_be_sl = self.calculate_break_even_price(
                    position.open_price,
                    "BUY"  # Side doesn't matter for calculation
                )

                current_sl_normalized = normalize_price(position.current_sl, "GOLD")

                if abs(current_sl_normalized - expected_be_sl) < 0.001:
                    return PositionValidation(
                        valid=False,
                        position_id=position.id,
                        mt5_ticket=position.mt5_ticket,
                        error_message=f"Position {position.id} SL already at break even level"
                    )

            # Warning checks (don't invalidate but worth noting)
            if not position.current_sl:
                warnings.append("Position has no current stop-loss set")

            if position.profit < 0:
                warnings.append(f"Position currently in loss: {position.profit}")

            # All validations passed
            self.logger.debug(
                f"Position {position.id} validated for break even",
                extra={
                    'position_id': position.id,
                    'mt5_ticket': position.mt5_ticket,
                    'entry_price': position.open_price,
                    'current_sl': position.current_sl,
                    'current_profit': position.profit,
                    'warnings_count': len(warnings)
                }
            )

            return PositionValidation(
                valid=True,
                position_id=position.id,
                mt5_ticket=position.mt5_ticket,
                warnings=warnings if warnings else None
            )

        except Exception as e:
            self.logger.error(f"Error validating position for break even: {e}")
            return PositionValidation(
                valid=False,
                position_id=position.id,
                mt5_ticket=position.mt5_ticket,
                error_message=f"Validation error: {e!s}"
            )

    def validate_broker_constraints(
        self,
        position: Position,
        new_sl: float,
        current_market_price: float | None = None
    ) -> dict[str, Any]:
        """
        Validate broker-specific constraints for stop-loss modification.

        Args:
            position: Position being modified
            new_sl: Proposed new stop-loss price
            current_market_price: Current market price (optional)

        Returns:
            Dictionary with constraint validation results
        """
        constraints = {
            'valid': True,
            'violations': [],
            'warnings': []
        }

        try:
            # Minimum SL distance from current price (if available)
            if current_market_price:
                min_sl_distance_pips = 10  # Typical GOLD minimum
                current_distance_pips = abs(calculate_pips_difference(
                    new_sl, current_market_price, "GOLD"
                ))

                if current_distance_pips < min_sl_distance_pips:
                    constraints['violations'].append(
                        f"SL too close to market: {current_distance_pips:.1f} pips "
                        f"(minimum: {min_sl_distance_pips})"
                    )
                    constraints['valid'] = False

            # Price range validation (reasonable bounds for GOLD)
            gold_min_price = 1000.0  # Reasonable minimum for GOLD
            gold_max_price = 3000.0  # Reasonable maximum for GOLD

            if not validate_price_range(new_sl, gold_min_price, gold_max_price):
                constraints['violations'].append(
                    f"SL price {new_sl} outside reasonable range "
                    f"({gold_min_price}-{gold_max_price})"
                )
                constraints['valid'] = False

            # Position size considerations (larger positions may have stricter rules)
            if position.volume > 10.0:  # Large position warning
                constraints['warnings'].append(
                    f"Large position volume: {position.volume} lots"
                )

            return constraints

        except Exception as e:
            self.logger.error(f"Error validating broker constraints: {e}")
            return {
                'valid': False,
                'violations': [f"Constraint validation error: {e!s}"],
                'warnings': []
            }

    def get_modification_summary(
        self,
        position: Position,
        old_sl: float | None,
        new_sl: float
    ) -> dict[str, Any]:
        """
        Generate summary of break even modification for logging and audit.

        Args:
            position: Position being modified
            old_sl: Previous stop-loss value
            new_sl: New stop-loss value

        Returns:
            Dictionary with modification summary
        """
        try:
            summary = {
                'position_id': position.id,
                'mt5_ticket': position.mt5_ticket,
                'modification_type': 'BREAK_EVEN',
                'entry_price': position.open_price,
                'old_sl': old_sl,
                'new_sl': new_sl,
                'sl_change_pips': None,
                'profit_secured': None,
                'symbol': 'GOLD',
                'timestamp': position.updated_at
            }

            # Calculate SL change in pips
            if old_sl and position.open_price:
                old_distance = calculate_pips_difference(
                    old_sl, position.open_price, "GOLD"
                )
                new_distance = calculate_pips_difference(
                    new_sl, position.open_price, "GOLD"
                )
                summary['sl_change_pips'] = new_distance - old_distance

            # Calculate profit secured (if position currently profitable)
            if position.profit > 0:
                summary['profit_secured'] = position.profit

            return summary

        except Exception as e:
            self.logger.error(f"Error generating modification summary: {e}")
            return {
                'position_id': position.id,
                'error': str(e)
            }
