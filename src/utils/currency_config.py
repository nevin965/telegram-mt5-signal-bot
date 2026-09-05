"""
Currency configuration for USD-based trading.

This module handles currency-specific configurations and validations
for USD trading accounts.
"""

import os
from decimal import Decimal
from typing import Any


class CurrencyConfig:
    """Configuration for USD-based trading operations."""

    def __init__(self):
        """Initialize currency configuration from environment."""
        # Base currency configuration
        self.base_currency = os.getenv('BASE_CURRENCY', 'USD')
        self.account_currency = os.getenv('MT5_ACCOUNT_CURRENCY', 'USD')
        
        # Validate USD configuration
        if self.account_currency != 'USD':
            raise ValueError(
                f"System is configured for USD trading but account currency is {self.account_currency}"
            )
        
        # USD-specific formatting
        self.currency_symbol = '$'
        self.decimal_places = 2  # USD uses 2 decimal places for money
        self.thousands_separator = ','
        self.decimal_separator = '.'
        
        # Trading parameters for USD accounts
        self.min_deposit = 100.0  # Minimum deposit in USD
        self.default_lot_size = float(os.getenv('DEFAULT_LOT_SIZE', '0.01'))
        
        # Risk management in USD
        self.default_risk_amount = 100.0  # Default risk per trade in USD
        self.max_risk_amount = 1000.0  # Maximum risk per trade in USD

    def format_money(self, amount: float) -> str:
        """
        Format money amount in USD format.
        
        Args:
            amount: Amount in USD
            
        Returns:
            Formatted string like $1,234.56
        """
        # Convert to Decimal for proper rounding
        decimal_amount = Decimal(str(amount)).quantize(Decimal('0.01'))
        
        # Format with thousands separator
        formatted = f"{decimal_amount:,.2f}"
        
        # Add currency symbol
        if amount >= 0:
            return f"{self.currency_symbol}{formatted}"
        else:
            # Negative amounts: -$1,234.56
            return f"-{self.currency_symbol}{formatted[1:]}"

    def validate_amount(self, amount: float) -> bool:
        """
        Validate if amount is valid for USD trading.
        
        Args:
            amount: Amount to validate
            
        Returns:
            True if valid, False otherwise
        """
        if amount < 0:
            return False
            
        # Check if amount has more than 2 decimal places (cents)
        decimal_str = str(amount)
        if '.' in decimal_str:
            decimal_part = decimal_str.split('.')[1]
            if len(decimal_part) > 2:
                return False
                
        return True

    def calculate_position_value(self, volume: float, price: float) -> float:
        """
        Calculate position value in USD.
        
        Args:
            volume: Position volume (lots)
            price: Current price
            
        Returns:
            Position value in USD
        """
        # For XAUUSD: 1 lot = 100 oz, so position value = volume * 100 * price
        # For forex: 1 lot = 100,000 units
        
        # This is simplified - actual calculation depends on symbol
        contract_size = 100  # For GOLD
        position_value = volume * contract_size * price
        
        return round(position_value, 2)

    def calculate_profit_loss(
        self,
        volume: float,
        entry_price: float,
        exit_price: float,
        is_buy: bool
    ) -> float:
        """
        Calculate profit/loss in USD.
        
        Args:
            volume: Position volume (lots)
            entry_price: Entry price
            exit_price: Exit price
            is_buy: True for buy positions, False for sell
            
        Returns:
            Profit/loss in USD
        """
        contract_size = 100  # For GOLD (100 oz per lot)
        
        if is_buy:
            price_difference = exit_price - entry_price
        else:
            price_difference = entry_price - exit_price
            
        # P/L = volume * contract_size * price_difference
        profit_loss = volume * contract_size * price_difference
        
        return round(profit_loss, 2)

    def calculate_lot_size_from_risk(
        self,
        risk_amount_usd: float,
        stop_loss_pips: float,
        pip_value_usd: float = 1.0
    ) -> float:
        """
        Calculate lot size based on USD risk amount.
        
        Args:
            risk_amount_usd: Risk amount in USD
            stop_loss_pips: Stop loss distance in pips
            pip_value_usd: Value of 1 pip in USD for 0.01 lot (default 1.0 for GOLD)
            
        Returns:
            Calculated lot size
        """
        if stop_loss_pips <= 0 or pip_value_usd <= 0:
            return self.default_lot_size
            
        # For GOLD: pip_value_usd is per 0.01 lot
        # Lot size = Risk Amount / (Stop Loss in Pips * Pip Value per 0.01 lot) * 0.01
        lot_size = (risk_amount_usd / (stop_loss_pips * pip_value_usd)) * 0.01
        
        # Round to valid lot step (0.01)
        lot_size = round(lot_size / 0.01) * 0.01
        
        # Ensure minimum lot size
        return max(lot_size, 0.01)

    def get_symbol_pip_value_usd(self, symbol: str, volume: float = 1.0) -> float:
        """
        Get pip value in USD for a symbol.
        
        Args:
            symbol: Trading symbol
            volume: Volume in lots
            
        Returns:
            Pip value in USD
        """
        # Pip values in USD for 1 standard lot
        pip_values = {
            'XAUUSD': 1.0,    # $1 per pip for 0.01 lot
            'GOLD': 1.0,      # $1 per pip for 0.01 lot  
            'EURUSD': 10.0,   # $10 per pip for 1 lot
            'GBPUSD': 10.0,   # $10 per pip for 1 lot
            'USDJPY': 9.0,    # ~$9 per pip for 1 lot (depends on rate)
            'USDCHF': 10.0,   # $10 per pip for 1 lot
            'AUDUSD': 10.0,   # $10 per pip for 1 lot
            'NZDUSD': 10.0,   # $10 per pip for 1 lot
            'USDCAD': 10.0,   # $10 per pip for 1 lot
        }
        
        symbol_upper = symbol.upper()
        
        # Get base pip value
        if symbol_upper in pip_values:
            base_pip_value = pip_values[symbol_upper]
        elif 'XAU' in symbol_upper or 'GOLD' in symbol_upper:
            base_pip_value = 1.0  # GOLD default
        elif 'USD' in symbol_upper:
            base_pip_value = 10.0  # Forex pairs with USD
        else:
            base_pip_value = 10.0  # Default for other pairs
            
        # Adjust for volume
        # For GOLD: 0.01 lot = $1 per pip, so 1 lot = $100 per pip
        if 'XAU' in symbol_upper or 'GOLD' in symbol_upper:
            return base_pip_value * (volume / 0.01)
        else:
            return base_pip_value * volume

    def get_config_summary(self) -> dict[str, Any]:
        """
        Get configuration summary.
        
        Returns:
            Dictionary with configuration details
        """
        return {
            'base_currency': self.base_currency,
            'account_currency': self.account_currency,
            'currency_symbol': self.currency_symbol,
            'decimal_places': self.decimal_places,
            'min_deposit': self.min_deposit,
            'default_lot_size': self.default_lot_size,
            'default_risk_amount': self.default_risk_amount,
            'max_risk_amount': self.max_risk_amount,
            'formatting': {
                'thousands_separator': self.thousands_separator,
                'decimal_separator': self.decimal_separator,
                'example': self.format_money(1234.56)
            }
        }


# Global currency configuration instance
currency_config = CurrencyConfig()