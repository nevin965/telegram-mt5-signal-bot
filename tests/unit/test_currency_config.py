"""
Unit tests for USD currency configuration.
"""

import os
import pytest
from unittest.mock import patch

from src.utils.currency_config import CurrencyConfig


class TestCurrencyConfig:
    """Test USD currency configuration."""

    def test_usd_configuration_initialization(self):
        """Test that currency config initializes with USD settings."""
        with patch.dict(os.environ, {
            'BASE_CURRENCY': 'USD',
            'MT5_ACCOUNT_CURRENCY': 'USD',
            'DEFAULT_LOT_SIZE': '0.01'
        }):
            config = CurrencyConfig()
            
            assert config.base_currency == 'USD'
            assert config.account_currency == 'USD'
            assert config.currency_symbol == '$'
            assert config.decimal_places == 2
            assert config.default_lot_size == 0.01

    def test_non_usd_account_raises_error(self):
        """Test that non-USD account configuration raises error."""
        with patch.dict(os.environ, {
            'BASE_CURRENCY': 'USD',
            'MT5_ACCOUNT_CURRENCY': 'EUR'
        }):
            with pytest.raises(ValueError, match="System is configured for USD trading"):
                CurrencyConfig()

    def test_format_money_positive(self):
        """Test USD money formatting for positive amounts."""
        config = CurrencyConfig()
        
        assert config.format_money(1234.56) == "$1,234.56"
        assert config.format_money(0.01) == "$0.01"
        assert config.format_money(1000000.00) == "$1,000,000.00"
        assert config.format_money(99.999) == "$100.00"  # Rounding

    def test_format_money_negative(self):
        """Test USD money formatting for negative amounts."""
        config = CurrencyConfig()
        
        assert config.format_money(-1234.56) == "-$1,234.56"
        assert config.format_money(-0.01) == "-$0.01"

    def test_validate_amount(self):
        """Test amount validation for USD."""
        config = CurrencyConfig()
        
        # Valid amounts
        assert config.validate_amount(100.00) is True
        assert config.validate_amount(0.01) is True
        assert config.validate_amount(1234.56) is True
        
        # Invalid amounts
        assert config.validate_amount(-100.00) is False
        assert config.validate_amount(100.001) is False  # Too many decimals
        assert config.validate_amount(100.999) is False  # Too many decimals

    def test_calculate_position_value(self):
        """Test position value calculation in USD."""
        config = CurrencyConfig()
        
        # GOLD: 0.01 lot at $1950
        value = config.calculate_position_value(0.01, 1950.00)
        assert value == 1950.00  # 0.01 * 100 * 1950
        
        # GOLD: 1 lot at $1950
        value = config.calculate_position_value(1.0, 1950.00)
        assert value == 195000.00  # 1.0 * 100 * 1950

    def test_calculate_profit_loss_buy(self):
        """Test P/L calculation for buy positions."""
        config = CurrencyConfig()
        
        # Buy 0.01 lot GOLD at 1950, sell at 1960 (+10 pips)
        pl = config.calculate_profit_loss(0.01, 1950.00, 1960.00, is_buy=True)
        assert pl == 10.00  # 0.01 * 100 * (1960 - 1950)
        
        # Buy 0.01 lot GOLD at 1950, sell at 1940 (-10 pips)
        pl = config.calculate_profit_loss(0.01, 1950.00, 1940.00, is_buy=True)
        assert pl == -10.00  # 0.01 * 100 * (1940 - 1950)

    def test_calculate_profit_loss_sell(self):
        """Test P/L calculation for sell positions."""
        config = CurrencyConfig()
        
        # Sell 0.01 lot GOLD at 1950, buy back at 1940 (+10 pips profit)
        pl = config.calculate_profit_loss(0.01, 1950.00, 1940.00, is_buy=False)
        assert pl == 10.00  # 0.01 * 100 * (1950 - 1940)
        
        # Sell 0.01 lot GOLD at 1950, buy back at 1960 (-10 pips loss)
        pl = config.calculate_profit_loss(0.01, 1950.00, 1960.00, is_buy=False)
        assert pl == -10.00  # 0.01 * 100 * (1960 - 1950)

    def test_calculate_lot_size_from_risk(self):
        """Test lot size calculation from USD risk amount."""
        config = CurrencyConfig()
        
        # Risk $100 with 20 pip stop loss (pip value = $1 for 0.01 lot)
        lot_size = config.calculate_lot_size_from_risk(100.00, 20, 1.0)
        assert lot_size == 0.05  # 100 / (20 * 1) / 100
        
        # Risk $50 with 10 pip stop loss
        lot_size = config.calculate_lot_size_from_risk(50.00, 10, 1.0)
        assert lot_size == 0.05  # 50 / (10 * 1) / 100
        
        # Risk $200 with 50 pip stop loss
        lot_size = config.calculate_lot_size_from_risk(200.00, 50, 1.0)
        assert lot_size == 0.04  # 200 / (50 * 1) / 100

    def test_get_symbol_pip_value_usd(self):
        """Test pip value calculation in USD for different symbols."""
        config = CurrencyConfig()
        
        # GOLD: 0.01 lot = $1 per pip
        assert config.get_symbol_pip_value_usd('XAUUSD', 0.01) == 1.0
        assert config.get_symbol_pip_value_usd('GOLD', 0.01) == 1.0
        
        # GOLD: 0.1 lot = $10 per pip
        assert config.get_symbol_pip_value_usd('XAUUSD', 0.1) == 10.0
        
        # GOLD: 1 lot = $100 per pip
        assert config.get_symbol_pip_value_usd('XAUUSD', 1.0) == 100.0
        
        # Forex pairs: 1 lot = $10 per pip
        assert config.get_symbol_pip_value_usd('EURUSD', 1.0) == 10.0
        assert config.get_symbol_pip_value_usd('GBPUSD', 1.0) == 10.0
        
        # Forex pairs: 0.1 lot = $1 per pip
        assert config.get_symbol_pip_value_usd('EURUSD', 0.1) == 1.0

    def test_get_config_summary(self):
        """Test configuration summary generation."""
        config = CurrencyConfig()
        summary = config.get_config_summary()
        
        assert summary['base_currency'] == 'USD'
        assert summary['account_currency'] == 'USD'
        assert summary['currency_symbol'] == '$'
        assert summary['decimal_places'] == 2
        assert summary['min_deposit'] == 100.0
        assert summary['default_lot_size'] == 0.01
        assert summary['formatting']['example'] == '$1,234.56'