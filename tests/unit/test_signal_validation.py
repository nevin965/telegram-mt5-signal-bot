"""Unit tests for signal validation logic and ValidationResult."""

from datetime import datetime
from decimal import Decimal

import pytest

from src.signal_parser import ParsedAction, ParsedSignal, ValidationResult
from src.signal_parser.regex_parser import RegexParser


class TestSignalValidation:
    """Test suite for signal validation logic."""

    @pytest.fixture
    def parser(self):
        """Create RegexParser instance for validation testing."""
        return RegexParser()

    def create_test_signal(
        self,
        action: ParsedAction = ParsedAction.BUY,
        symbol: str = "GOLD",
        entry_price: Decimal = Decimal("3365"),
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None
    ) -> ParsedSignal:
        """Create test ParsedSignal with specified parameters."""
        return ParsedSignal(
            telegram_message_id=12345,
            telegram_chat_id=67890,
            sender="test_sender_hash",
            timestamp=datetime.now(),
            raw_text="TEST SIGNAL",
            parsed_action=action,
            symbol=symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence_score=0.95,
            parser_type="REGEX",
            status="PENDING"
        )

    def test_validation_result_structure(self):
        """Test ValidationResult dataclass structure."""
        # Valid result
        result = ValidationResult(is_valid=True, errors=[], warnings=[])
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []

        # Invalid result with errors
        result = ValidationResult(
            is_valid=False,
            errors=["Price out of range"],
            warnings=["High risk"]
        )
        assert result.is_valid is False
        assert len(result.errors) == 1
        assert len(result.warnings) == 1
        assert "Price out of range" in result.errors
        assert "High risk" in result.warnings

    def test_valid_gold_price_ranges(self, parser):
        """Test valid GOLD price range validation (3000-4000)."""
        valid_prices = [
            Decimal("3000.0"),   # Lower boundary
            Decimal("3365.5"),   # Middle
            Decimal("3999.99"),  # Near upper boundary
            Decimal("4000.0")    # Upper boundary
        ]

        for price in valid_prices:
            signal = self.create_test_signal(entry_price=price)
            validation = parser._validate_signal(signal)
            assert validation.is_valid, f"Price {price} should be valid"
            assert len(validation.errors) == 0, f"No errors expected for price {price}"

    def test_invalid_gold_price_ranges(self, parser):
        """Test invalid GOLD price range validation."""
        invalid_prices = [
            Decimal("2999.99"),  # Below range
            Decimal("2500.0"),   # Well below
            Decimal("4000.01"),  # Above range
            Decimal("5000.0")    # Well above
        ]

        for price in invalid_prices:
            signal = self.create_test_signal(entry_price=price)
            validation = parser._validate_signal(signal)
            assert not validation.is_valid, f"Price {price} should be invalid"
            assert len(validation.errors) > 0, f"Errors expected for price {price}"
            assert any("outside valid range" in error for error in validation.errors)

    def test_buy_stop_loss_validation(self, parser):
        """Test BUY order stop loss validation logic."""
        entry_price = Decimal("3365")

        # Valid BUY SL (below entry)
        valid_sl_prices = [
            Decimal("3360"),    # 5 points below
            Decimal("3350"),    # 15 points below
            Decimal("3300")     # 65 points below
        ]

        for sl in valid_sl_prices:
            signal = self.create_test_signal(
                action=ParsedAction.BUY,
                entry_price=entry_price,
                stop_loss=sl
            )
            validation = parser._validate_signal(signal)
            sl_errors = [e for e in validation.errors if "must be below entry" in e]
            assert len(sl_errors) == 0, f"BUY SL {sl} below entry {entry_price} should be valid"

        # Invalid BUY SL (above or equal to entry)
        invalid_sl_prices = [
            Decimal("3365"),    # Equal to entry
            Decimal("3370"),    # Above entry
            Decimal("3400")     # Well above entry
        ]

        for sl in invalid_sl_prices:
            signal = self.create_test_signal(
                action=ParsedAction.BUY,
                entry_price=entry_price,
                stop_loss=sl
            )
            validation = parser._validate_signal(signal)
            sl_errors = [e for e in validation.errors if "must be below entry" in e]
            assert len(sl_errors) > 0, f"BUY SL {sl} above entry {entry_price} should be invalid"

    def test_sell_stop_loss_validation(self, parser):
        """Test SELL order stop loss validation logic."""
        entry_price = Decimal("3365")

        # Valid SELL SL (above entry)
        valid_sl_prices = [
            Decimal("3370"),    # 5 points above
            Decimal("3380"),    # 15 points above
            Decimal("3430")     # 65 points above
        ]

        for sl in valid_sl_prices:
            signal = self.create_test_signal(
                action=ParsedAction.SELL,
                entry_price=entry_price,
                stop_loss=sl
            )
            validation = parser._validate_signal(signal)
            sl_errors = [e for e in validation.errors if "must be above entry" in e]
            assert len(sl_errors) == 0, f"SELL SL {sl} above entry {entry_price} should be valid"

        # Invalid SELL SL (below or equal to entry)
        invalid_sl_prices = [
            Decimal("3365"),    # Equal to entry
            Decimal("3360"),    # Below entry
            Decimal("3300")     # Well below entry
        ]

        for sl in invalid_sl_prices:
            signal = self.create_test_signal(
                action=ParsedAction.SELL,
                entry_price=entry_price,
                stop_loss=sl
            )
            validation = parser._validate_signal(signal)
            sl_errors = [e for e in validation.errors if "must be above entry" in e]
            assert len(sl_errors) > 0, f"SELL SL {sl} below entry {entry_price} should be invalid"

    def test_buy_take_profit_validation(self, parser):
        """Test BUY order take profit validation logic."""
        entry_price = Decimal("3365")

        # Valid BUY TP (above entry)
        valid_tp_prices = [
            Decimal("3370"),    # 5 points above
            Decimal("3380"),    # 15 points above
            Decimal("3430")     # 65 points above
        ]

        for tp in valid_tp_prices:
            signal = self.create_test_signal(
                action=ParsedAction.BUY,
                entry_price=entry_price,
                take_profit=tp
            )
            validation = parser._validate_signal(signal)
            tp_errors = [e for e in validation.errors if "must be above entry" in e]
            assert len(tp_errors) == 0, f"BUY TP {tp} above entry {entry_price} should be valid"

        # Invalid BUY TP (below or equal to entry)
        invalid_tp_prices = [
            Decimal("3365"),    # Equal to entry
            Decimal("3360"),    # Below entry
            Decimal("3300")     # Well below entry
        ]

        for tp in invalid_tp_prices:
            signal = self.create_test_signal(
                action=ParsedAction.BUY,
                entry_price=entry_price,
                take_profit=tp
            )
            validation = parser._validate_signal(signal)
            tp_errors = [e for e in validation.errors if "must be above entry" in e]
            assert len(tp_errors) > 0, f"BUY TP {tp} below entry {entry_price} should be invalid"

    def test_sell_take_profit_validation(self, parser):
        """Test SELL order take profit validation logic."""
        entry_price = Decimal("3365")

        # Valid SELL TP (below entry)
        valid_tp_prices = [
            Decimal("3360"),    # 5 points below
            Decimal("3350"),    # 15 points below
            Decimal("3300")     # 65 points below
        ]

        for tp in valid_tp_prices:
            signal = self.create_test_signal(
                action=ParsedAction.SELL,
                entry_price=entry_price,
                take_profit=tp
            )
            validation = parser._validate_signal(signal)
            tp_errors = [e for e in validation.errors if "must be below entry" in e]
            assert len(tp_errors) == 0, f"SELL TP {tp} below entry {entry_price} should be valid"

        # Invalid SELL TP (above or equal to entry)
        invalid_tp_prices = [
            Decimal("3365"),    # Equal to entry
            Decimal("3370"),    # Above entry
            Decimal("3400")     # Well above entry
        ]

        for tp in invalid_tp_prices:
            signal = self.create_test_signal(
                action=ParsedAction.SELL,
                entry_price=entry_price,
                take_profit=tp
            )
            validation = parser._validate_signal(signal)
            tp_errors = [e for e in validation.errors if "must be below entry" in e]
            assert len(tp_errors) > 0, f"SELL TP {tp} above entry {entry_price} should be invalid"

    def test_pip_distance_warnings(self, parser):
        """Test pip distance warning generation."""
        entry_price = Decimal("3365.00")

        # Very tight SL (< 5 pips = 0.05 for GOLD)
        tight_sl_signal = self.create_test_signal(
            action=ParsedAction.BUY,
            entry_price=entry_price,
            stop_loss=Decimal("3364.99")  # 0.01 difference
        )
        validation = parser._validate_signal(tight_sl_signal)
        assert validation.is_valid  # Should still be valid
        tight_warnings = [w for w in validation.warnings if "very tight" in w]
        assert len(tight_warnings) > 0, "Should warn about very tight SL"

        # Very wide SL (> 500 pips = 5.0 for GOLD)
        wide_sl_signal = self.create_test_signal(
            action=ParsedAction.BUY,
            entry_price=entry_price,
            stop_loss=Decimal("3358.00")  # 7.0 difference > 5.0 limit
        )
        validation = parser._validate_signal(wide_sl_signal)
        assert validation.is_valid  # Should still be valid
        risk_warnings = [w for w in validation.warnings if "high risk" in w]
        assert len(risk_warnings) > 0, "Should warn about high risk SL"

        # Very small TP (< 10 pips = 0.10 for GOLD)
        small_tp_signal = self.create_test_signal(
            action=ParsedAction.BUY,
            entry_price=entry_price,
            take_profit=Decimal("3365.05")  # 0.05 difference < 0.10 minimum
        )
        validation = parser._validate_signal(small_tp_signal)
        assert validation.is_valid  # Should still be valid
        min_warnings = [w for w in validation.warnings if "minimum recommended" in w]
        assert len(min_warnings) > 0, "Should warn about minimum TP distance"

    def test_no_sl_tp_validation(self, parser):
        """Test validation when SL/TP are not provided."""
        # Signal without SL or TP should be valid
        signal = self.create_test_signal(
            entry_price=Decimal("3365"),
            stop_loss=None,
            take_profit=None
        )
        validation = parser._validate_signal(signal)
        assert validation.is_valid
        assert len(validation.errors) == 0

    def test_combined_validation_scenarios(self, parser):
        """Test complex validation scenarios with multiple issues."""
        # Signal with multiple validation issues
        problematic_signal = self.create_test_signal(
            action=ParsedAction.BUY,
            entry_price=Decimal("2500"),        # Invalid price range
            stop_loss=Decimal("2510"),          # Invalid SL logic
            take_profit=Decimal("2490")         # Invalid TP logic
        )
        validation = parser._validate_signal(problematic_signal)
        assert not validation.is_valid
        assert len(validation.errors) >= 3  # Price range, SL logic, TP logic

        # Check specific error types
        range_errors = [e for e in validation.errors if "outside valid range" in e]
        sl_errors = [e for e in validation.errors if "must be below entry" in e]
        tp_errors = [e for e in validation.errors if "must be above entry" in e]

        assert len(range_errors) > 0, "Should have price range error"
        assert len(sl_errors) > 0, "Should have SL logic error"
        assert len(tp_errors) > 0, "Should have TP logic error"

    def test_xauusd_symbol_validation(self, parser):
        """Test validation works for XAUUSD symbol (same as GOLD)."""
        # XAUUSD should follow same rules as GOLD
        signal = self.create_test_signal(
            symbol="XAUUSD",
            entry_price=Decimal("3365"),
            stop_loss=Decimal("3350"),
            take_profit=Decimal("3380")
        )
        validation = parser._validate_signal(signal)
        assert validation.is_valid

        # Invalid XAUUSD price should fail
        invalid_signal = self.create_test_signal(
            symbol="XAUUSD",
            entry_price=Decimal("2500")  # Below valid range
        )
        validation = parser._validate_signal(invalid_signal)
        assert not validation.is_valid
        assert any("outside valid range" in error for error in validation.errors)

    def test_validation_edge_cases(self, parser):
        """Test validation edge cases and boundary conditions."""
        # Exactly at price boundaries
        boundary_signals = [
            (Decimal("3000.0"), True),    # Lower boundary - valid
            (Decimal("4000.0"), True),    # Upper boundary - valid
            (Decimal("2999.99"), False),  # Just below - invalid
            (Decimal("4000.01"), False)   # Just above - invalid
        ]

        for price, should_be_valid in boundary_signals:
            signal = self.create_test_signal(entry_price=price)
            validation = parser._validate_signal(signal)
            assert validation.is_valid == should_be_valid, f"Price {price} validation mismatch"

        # Exactly at pip distance boundaries
        entry = Decimal("3365.00")

        # Exactly 5 pips SL distance (0.05 for GOLD)
        exact_sl_signal = self.create_test_signal(
            action=ParsedAction.BUY,
            entry_price=entry,
            stop_loss=Decimal("3364.95")  # Exactly 0.05 difference
        )
        validation = parser._validate_signal(exact_sl_signal)
        # This is borderline - check that it doesn't crash and behavior is consistent
        assert validation.is_valid  # Should be valid

    def test_validation_with_decimal_precision(self, parser):
        """Test validation handles decimal precision correctly."""
        # High precision decimals
        precise_signal = self.create_test_signal(
            action=ParsedAction.BUY,
            entry_price=Decimal("3365.123456"),
            stop_loss=Decimal("3360.987654"),
            take_profit=Decimal("3370.555555")
        )
        validation = parser._validate_signal(precise_signal)
        assert validation.is_valid

        # Very small differences due to precision
        tiny_diff_signal = self.create_test_signal(
            action=ParsedAction.BUY,
            entry_price=Decimal("3365.000000"),
            stop_loss=Decimal("3364.999999")  # 0.000001 difference
        )
        validation = parser._validate_signal(tiny_diff_signal)
        # Should warn about very tight SL
        tight_warnings = [w for w in validation.warnings if "very tight" in w]
        assert len(tight_warnings) > 0
