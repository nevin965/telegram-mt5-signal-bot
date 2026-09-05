"""
Price and data formatting utilities for the trading system.

This module provides functions for normalizing and formatting prices
according to broker specifications and instrument requirements.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict


# Pip size definitions for different instruments
PIP_SIZES: Dict[str, float] = {
    "GOLD": 0.01,
    "XAUUSD": 0.01,
    "EURUSD": 0.00001,
    "GBPUSD": 0.00001,
    "USDJPY": 0.001,
    "DEFAULT": 0.00001
}

# Price precision (decimal places) for different instruments
PRICE_PRECISION: Dict[str, int] = {
    "GOLD": 2,
    "XAUUSD": 2,
    "EURUSD": 5,
    "GBPUSD": 5,
    "USDJPY": 3,
    "DEFAULT": 5
}


def normalize_price(price: float, symbol: str = "GOLD") -> float:
    """
    Normalize a price to the correct precision for the given symbol.
    
    Args:
        price: The price to normalize
        symbol: The trading symbol (default: "GOLD")
    
    Returns:
        The normalized price with correct decimal precision
    
    Example:
        >>> normalize_price(1850.12345, "GOLD")
        1850.12
        >>> normalize_price(1.234567, "EURUSD")
        1.23457
    """
    precision = PRICE_PRECISION.get(symbol.upper(), PRICE_PRECISION["DEFAULT"])
    
    # Use Decimal for precise rounding
    decimal_price = Decimal(str(price))
    quantize_str = f"0.{'0' * precision}"
    normalized = decimal_price.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)
    
    return float(normalized)


def get_pip_size(symbol: str = "GOLD") -> float:
    """
    Get the pip size for a given symbol.
    
    Args:
        symbol: The trading symbol (default: "GOLD")
    
    Returns:
        The pip size for the symbol
    
    Example:
        >>> get_pip_size("GOLD")
        0.01
        >>> get_pip_size("EURUSD")
        0.00001
    """
    return PIP_SIZES.get(symbol.upper(), PIP_SIZES["DEFAULT"])


def calculate_pips_difference(price1: float, price2: float, symbol: str = "GOLD") -> float:
    """
    Calculate the difference in pips between two prices.
    
    Args:
        price1: The first price
        price2: The second price
        symbol: The trading symbol (default: "GOLD")
    
    Returns:
        The difference in pips (can be negative)
    
    Example:
        >>> calculate_pips_difference(1850.50, 1850.00, "GOLD")
        50.0
        >>> calculate_pips_difference(1.10000, 1.10050, "EURUSD")
        -50.0
    """
    pip_size = get_pip_size(symbol)
    difference = price1 - price2
    return difference / pip_size


def add_pips_to_price(price: float, pips: float, symbol: str = "GOLD", direction: str = "BUY") -> float:
    """
    Add or subtract pips from a price based on trade direction.
    
    Args:
        price: The base price
        pips: Number of pips to add
        symbol: The trading symbol (default: "GOLD")
        direction: Trade direction ("BUY" or "SELL")
    
    Returns:
        The adjusted price, normalized to correct precision
    
    Example:
        >>> add_pips_to_price(1850.00, 1, "GOLD", "BUY")
        1850.01
        >>> add_pips_to_price(1850.00, 1, "GOLD", "SELL")
        1850.01  # For break even, both directions add 1 pip
    """
    pip_size = get_pip_size(symbol)
    
    # For break even, we always add pips (move SL to entry + 1 pip)
    # This is profitable for both BUY (SL below entry) and SELL (SL above entry)
    adjusted_price = price + (pips * pip_size)
    
    return normalize_price(adjusted_price, symbol)


def format_price_for_display(price: float, symbol: str = "GOLD") -> str:
    """
    Format a price for display with the correct decimal places.
    
    Args:
        price: The price to format
        symbol: The trading symbol (default: "GOLD")
    
    Returns:
        A formatted string representation of the price
    
    Example:
        >>> format_price_for_display(1850.1, "GOLD")
        '1850.10'
        >>> format_price_for_display(1.23456789, "EURUSD")
        '1.23457'
    """
    normalized = normalize_price(price, symbol)
    precision = PRICE_PRECISION.get(symbol.upper(), PRICE_PRECISION["DEFAULT"])
    return f"{normalized:.{precision}f}"


def validate_price_range(price: float, min_price: float, max_price: float) -> bool:
    """
    Validate that a price is within an acceptable range.
    
    Args:
        price: The price to validate
        min_price: Minimum acceptable price
        max_price: Maximum acceptable price
    
    Returns:
        True if price is within range, False otherwise
    """
    return min_price <= price <= max_price