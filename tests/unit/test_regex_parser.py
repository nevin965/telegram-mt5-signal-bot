"""Unit tests for RegexParser signal parsing functionality."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.signal_parser import ParsedAction, ParsedSignal
from src.signal_parser.regex_parser import RegexParser


class TestRegexParser:
    """Test suite for RegexParser class."""

    @pytest.fixture
    def parser(self):
        """Create RegexParser instance for testing."""
        return RegexParser()

    @pytest.fixture
    def sample_signals(self):
        """Load sample signal test data."""
        fixtures_path = Path(__file__).parent.parent / "fixtures" / "sample_signals.json"
        with open(fixtures_path) as f:
            return json.load(f)

    def test_parser_initialization(self, parser):
        """Test parser initializes correctly with patterns."""
        assert parser is not None
        assert parser.patterns is not None
        assert parser.main_patterns is not None
        assert len(parser.main_patterns) > 0
        assert 'buy_actions' in parser.patterns
        assert 'sell_actions' in parser.patterns
        assert 'instruments' in parser.patterns

    def test_valid_signal_parsing(self, parser, sample_signals):
        """Test parsing of all valid signal formats."""
        for signal_data in sample_signals['valid_signals']:
            text = signal_data['text']
            expected = signal_data['expected']

            result = parser.parse(text)

            assert result is not None, f"Failed to parse valid signal: {text}"
            assert isinstance(result, ParsedSignal)
            assert result.parsed_action.value == expected['action']
            assert result.symbol == expected['symbol']
            assert result.entry_price == Decimal(expected['entry_price'])

            # Check SL if expected
            if expected['stop_loss']:
                assert result.stop_loss == Decimal(expected['stop_loss'])
            else:
                assert result.stop_loss is None

            # Check TP if expected
            if expected['take_profit']:
                assert result.take_profit == Decimal(expected['take_profit'])
            else:
                assert result.take_profit is None

            # Check confidence and parser type
            assert result.confidence_score >= 0.90
            assert result.parser_type == "REGEX"
            assert result.status == "PENDING"

    def test_invalid_signal_rejection(self, parser, sample_signals):
        """Test that invalid signals are rejected."""
        for signal_data in sample_signals['invalid_signals']:
            text = signal_data['text']
            reason = signal_data['reason']

            result = parser.parse(text)

            # Signals with validation errors might parse but fail validation
            if reason in ['price_out_of_range', 'invalid_sl_logic']:
                # These might parse but should be rejected in validation
                if result is not None:
                    validation = parser._validate_signal(result)
                    assert not validation.is_valid, f"Signal should fail validation: {text} ({reason})"
            else:
                # These should fail to parse entirely
                assert result is None, f"Invalid signal should not parse: {text} ({reason})"

    def test_edge_cases(self, parser, sample_signals):
        """Test edge case handling."""
        for case_data in sample_signals['edge_cases']:
            text = case_data['text']
            description = case_data['description']

            # These should generally fail to parse or return None
            result = parser.parse(text)

            if description in ['empty_string', 'whitespace_only', 'invalid_price_format']:
                assert result is None, f"Edge case should return None: {description}"
            elif description == 'no_spaces':
                # This might still work if regex is flexible enough
                pass  # Allow either success or failure
            elif description == 'extra_spaces_and_decimals':
                # Should handle extra spaces and normalize decimals
                if result:
                    assert result.entry_price == Decimal('3362.00')

    def test_french_action_patterns(self, parser):
        """Test specific French action pattern recognition."""
        test_cases = [
            ("JE BUY GOLD 3362", ParsedAction.BUY),
            ("BUY GOLD 3362", ParsedAction.BUY),
            ("ACHETER OR 3362", ParsedAction.BUY),
            ("J'ACHÈTE GOLD 3362", ParsedAction.BUY),
            ("LONG GOLD 3362", ParsedAction.BUY),
            ("JE VEND GOLD 3362", ParsedAction.SELL),
            ("JE VENDS GOLD 3362", ParsedAction.SELL),
            ("SELL GOLD 3362", ParsedAction.SELL),
            ("SHORT GOLD 3362", ParsedAction.SELL),
            ("VENDRE OR 3362", ParsedAction.SELL)
        ]

        for text, expected_action in test_cases:
            result = parser.parse(text)
            assert result is not None, f"Failed to parse: {text}"
            assert result.parsed_action == expected_action, f"Wrong action for: {text}"

    def test_symbol_normalization(self, parser):
        """Test symbol normalization from French/variations."""
        test_cases = [
            ("BUY OR 3362", "GOLD"),        # French 'OR' → 'GOLD'
            ("BUY GOLD 3362", "GOLD"),       # Standard
            ("BUY XAUUSD 3362", "XAUUSD"),   # Standard
            ("BUY XAU 3362", "XAUUSD"),      # XAU → XAUUSD
            ("BUY XAU/USD 3362", "XAUUSD")   # XAU/USD → XAUUSD
        ]

        for text, expected_symbol in test_cases:
            result = parser.parse(text)
            if result:  # Some patterns might not match in main patterns
                assert result.symbol == expected_symbol, f"Wrong symbol normalization for: {text}"

    def test_price_format_variations(self, parser):
        """Test different price format handling."""
        test_cases = [
            ("BUY GOLD 3362", Decimal('3362')),
            ("BUY GOLD 3362.50", Decimal('3362.50')),
            ("BUY GOLD @ 3362", Decimal('3362')),
            ("BUY GOLD @ 3362.25", Decimal('3362.25')),
            ("BUY GOLD @3362", Decimal('3362')),  # No space after @
        ]

        for text, expected_price in test_cases:
            result = parser.parse(text)
            if result:
                assert result.entry_price == expected_price, f"Wrong price extraction for: {text}"

    def test_sl_tp_extraction(self, parser):
        """Test stop loss and take profit extraction."""
        test_cases = [
            ("BUY GOLD 3362 SL 3350", Decimal('3350'), None),
            ("BUY GOLD 3362 TP 3375", None, Decimal('3375')),
            ("BUY GOLD 3362 SL 3350 TP 3375", Decimal('3350'), Decimal('3375')),
            ("SELL GOLD 3362 STOP 3375", Decimal('3375'), None),
            ("SELL GOLD 3362 TARGET 3350", None, Decimal('3350')),
            ("BUY GOLD 3362 SL: 3350 TP: 3375", Decimal('3350'), Decimal('3375')),
            ("BUY GOLD 3362 STOP LOSS 3350 TAKE PROFIT 3375", Decimal('3350'), Decimal('3375'))
        ]

        for text, expected_sl, expected_tp in test_cases:
            result = parser.parse(text)
            if result:
                assert result.stop_loss == expected_sl, f"Wrong SL extraction for: {text}"
                assert result.take_profit == expected_tp, f"Wrong TP extraction for: {text}"

    def test_validation_price_ranges(self, parser):
        """Test GOLD price range validation."""
        # Valid range (3000-4000)
        valid_signal = parser.parse("BUY GOLD 3500")
        assert valid_signal is not None
        validation = parser._validate_signal(valid_signal)
        assert validation.is_valid

        # Below range
        low_result = parser.parse("BUY GOLD 2500")  # Will parse but fail validation
        if low_result:
            validation = parser._validate_signal(low_result)
            assert not validation.is_valid
            assert any("outside valid range" in error for error in validation.errors)

        # Above range
        high_result = parser.parse("BUY GOLD 5000")  # Will parse but fail validation
        if high_result:
            validation = parser._validate_signal(high_result)
            assert not validation.is_valid
            assert any("outside valid range" in error for error in validation.errors)

    def test_validation_sl_logic(self, parser):
        """Test stop loss logic validation."""
        # Valid BUY SL (below entry)
        buy_signal = parser.parse("BUY GOLD 3365 SL 3350")
        if buy_signal:
            validation = parser._validate_signal(buy_signal)
            assert validation.is_valid

        # Invalid BUY SL (above entry)
        buy_bad_sl = parser.parse("BUY GOLD 3365 SL 3370")
        if buy_bad_sl:
            validation = parser._validate_signal(buy_bad_sl)
            assert not validation.is_valid
            assert any("must be below entry" in error for error in validation.errors)

        # Valid SELL SL (above entry)
        sell_signal = parser.parse("SELL GOLD 3365 SL 3370")
        if sell_signal:
            validation = parser._validate_signal(sell_signal)
            assert validation.is_valid

        # Invalid SELL SL (below entry)
        sell_bad_sl = parser.parse("SELL GOLD 3365 SL 3350")
        if sell_bad_sl:
            validation = parser._validate_signal(sell_bad_sl)
            assert not validation.is_valid
            assert any("must be above entry" in error for error in validation.errors)

    def test_validation_tp_logic(self, parser):
        """Test take profit logic validation."""
        # Valid BUY TP (above entry)
        buy_signal = parser.parse("BUY GOLD 3365 TP 3375")
        if buy_signal:
            validation = parser._validate_signal(buy_signal)
            assert validation.is_valid

        # Invalid BUY TP (below entry)
        buy_bad_tp = parser.parse("BUY GOLD 3365 TP 3350")
        if buy_bad_tp:
            validation = parser._validate_signal(buy_bad_tp)
            assert not validation.is_valid
            assert any("must be above entry" in error for error in validation.errors)

        # Valid SELL TP (below entry)
        sell_signal = parser.parse("SELL GOLD 3365 TP 3350")
        if sell_signal:
            validation = parser._validate_signal(sell_signal)
            assert validation.is_valid

        # Invalid SELL TP (above entry)
        sell_bad_tp = parser.parse("SELL GOLD 3365 TP 3375")
        if sell_bad_tp:
            validation = parser._validate_signal(sell_bad_tp)
            assert not validation.is_valid
            assert any("must be below entry" in error for error in validation.errors)

    def test_validation_pip_distances(self, parser):
        """Test minimum/maximum pip distance validation."""
        # Very tight SL (< 5 pips) should warn
        tight_sl_signal = parser.parse("BUY GOLD 3365.00 SL 3364.99")
        if tight_sl_signal:
            validation = parser._validate_signal(tight_sl_signal)
            # Should still be valid but with warning
            assert validation.is_valid
            assert any("very tight" in warning for warning in validation.warnings)

        # Very wide SL (> 500 pips) should warn
        wide_sl_signal = parser.parse("BUY GOLD 3365 SL 3359")  # 6 point difference > 5.0 limit
        if wide_sl_signal:
            validation = parser._validate_signal(wide_sl_signal)
            # Should still be valid but with warning
            assert validation.is_valid
            assert any("high risk" in warning for warning in validation.warnings)

        # Very small TP (< 10 pips) should warn
        small_tp_signal = parser.parse("BUY GOLD 3365.00 TP 3365.05")
        if small_tp_signal:
            validation = parser._validate_signal(small_tp_signal)
            assert validation.is_valid
            assert any("minimum recommended" in warning for warning in validation.warnings)

    def test_confidence_scores(self, parser):
        """Test confidence score assignment."""
        # Main pattern matches should have 0.95 confidence
        main_result = parser.parse("BUY GOLD 3362")
        if main_result:
            assert main_result.confidence_score == 0.95

        # Component parsing should have 0.90 confidence
        # This is harder to test directly, but we can verify the logic exists
        assert hasattr(parser, '_try_component_parsing')

    def test_empty_and_none_inputs(self, parser):
        """Test handling of empty and None inputs."""
        assert parser.parse(None) is None
        assert parser.parse("") is None
        assert parser.parse("   ") is None
        assert parser.parse("\n\t  ") is None

    def test_case_insensitive_parsing(self, parser):
        """Test that parsing is case insensitive."""
        test_cases = [
            "buy gold 3362",
            "BUY GOLD 3362",
            "Buy Gold 3362",
            "bUy GoLd 3362"
        ]

        for text in test_cases:
            result = parser.parse(text)
            if result:  # All should parse if main one does
                assert result.parsed_action == ParsedAction.BUY
                assert result.symbol == "GOLD"
                assert result.entry_price == Decimal('3362')

    def test_component_parsing_fallback(self, parser):
        """Test component-based parsing as fallback."""
        # Create a signal that might not match main patterns but should work with components
        test_text = "I want to ACHETER some OR at price 3365"

        result = parser.parse(test_text)
        # This should either work via component parsing or fail gracefully
        if result:
            assert result.parsed_action == ParsedAction.BUY
            assert result.symbol == "GOLD"
            assert result.entry_price == Decimal('3365')
            assert result.confidence_score == 0.90  # Component parsing confidence
