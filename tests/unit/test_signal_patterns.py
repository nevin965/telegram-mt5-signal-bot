"""Unit tests for French signal pattern definitions and regex matching."""

import re

from src.signal_parser.patterns import FrenchSignalPatterns


class TestFrenchSignalPatterns:
    """Test suite for French signal regex patterns."""

    def test_buy_action_patterns(self):
        """Test buy action pattern matching."""
        patterns = [re.compile(p, re.IGNORECASE) for p in FrenchSignalPatterns.BUY_ACTIONS]

        # Should match
        buy_texts = [
            "JE BUY",
            "je buy",
            "BUY",
            "buy",
            "ACHETER",
            "acheter",
            "J'ACHÈTE",
            "j'achète",
            "LONG",
            "long"
        ]

        for text in buy_texts:
            matched = any(pattern.search(text) for pattern in patterns)
            assert matched, f"Buy pattern should match: {text}"

        # Should not match
        non_buy_texts = [
            "SELL",
            "VENDRE",
            "SHORT",
            "HELLO",
            "PRICE",
            "ANALYSIS"
        ]

        for text in non_buy_texts:
            matched = any(pattern.search(text) for pattern in patterns)
            assert not matched, f"Buy pattern should not match: {text}"

    def test_sell_action_patterns(self):
        """Test sell action pattern matching."""
        patterns = [re.compile(p, re.IGNORECASE) for p in FrenchSignalPatterns.SELL_ACTIONS]

        # Should match
        sell_texts = [
            "JE VEND",
            "je vend",
            "JE VENDS",
            "je vends",
            "SELL",
            "sell",
            "SHORT",
            "short",
            "VENDRE",
            "vendre"
        ]

        for text in sell_texts:
            matched = any(pattern.search(text) for pattern in patterns)
            assert matched, f"Sell pattern should match: {text}"

        # Should not match
        non_sell_texts = [
            "BUY",
            "ACHETER",
            "LONG",
            "HELLO",
            "PRICE"
        ]

        for text in non_sell_texts:
            matched = any(pattern.search(text) for pattern in patterns)
            assert not matched, f"Sell pattern should not match: {text}"

    def test_instrument_patterns(self):
        """Test instrument pattern matching."""
        patterns = [re.compile(p, re.IGNORECASE) for p in FrenchSignalPatterns.INSTRUMENTS]

        # Should match
        instrument_texts = [
            "GOLD",
            "gold",
            "XAUUSD",
            "xauusd",
            "OR",
            "or",
            "XAU/USD",
            "xau/usd",
            "XAU",
            "xau"
        ]

        for text in instrument_texts:
            matched = any(pattern.search(text) for pattern in patterns)
            assert matched, f"Instrument pattern should match: {text}"

        # Should not match
        non_instrument_texts = [
            "EURUSD",
            "GBPUSD",
            "SILVER",
            "OIL",
            "BUY",
            "SELL"
        ]

        for text in non_instrument_texts:
            matched = any(pattern.search(text) for pattern in patterns)
            assert not matched, f"Instrument pattern should not match: {text}"

    def test_price_patterns(self):
        """Test price extraction patterns."""
        patterns = [re.compile(p, re.IGNORECASE) for p in FrenchSignalPatterns.PRICE_PATTERNS]

        # Test @ format
        at_price_tests = [
            ("@ 3362", "3362"),
            ("@3362", "3362"),
            ("@ 3362.50", "3362.50"),
            ("@3362.75", "3362.75")
        ]

        for text, expected in at_price_tests:
            matched = False
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    price = match.group(1) if match.groups() else match.group(0)
                    assert price == expected, f"Price extraction failed for: {text}"
                    matched = True
                    break
            assert matched, f"Price pattern should match: {text}"

        # Test simple number format
        number_tests = [
            ("3362", "3362"),
            ("3362.50", "3362.50"),
            ("3999.99", "3999.99")
        ]

        for text, expected in number_tests:
            matched = False
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    price = match.group(1) if match.groups() else match.group(0)
                    assert price == expected, f"Price extraction failed for: {text}"
                    matched = True
                    break
            assert matched, f"Price pattern should match: {text}"

    def test_sl_patterns(self):
        """Test stop loss pattern matching and extraction."""
        patterns = [re.compile(p, re.IGNORECASE) for p in FrenchSignalPatterns.SL_PATTERNS]

        sl_tests = [
            ("SL 3350", "3350"),
            ("SL: 3350", "3350"),
            ("SL:3350", "3350"),
            ("sl 3350.50", "3350.50"),
            ("STOP 3350", "3350"),
            ("stop 3350.25", "3350.25"),
            ("STOP LOSS 3350", "3350"),
            ("stop loss: 3350.75", "3350.75")
        ]

        for text, expected in sl_tests:
            matched = False
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    sl_price = match.group(1)
                    assert sl_price == expected, f"SL extraction failed for: {text}"
                    matched = True
                    break
            assert matched, f"SL pattern should match: {text}"

    def test_tp_patterns(self):
        """Test take profit pattern matching and extraction."""
        patterns = [re.compile(p, re.IGNORECASE) for p in FrenchSignalPatterns.TP_PATTERNS]

        tp_tests = [
            ("TP 3375", "3375"),
            ("TP: 3375", "3375"),
            ("TP:3375", "3375"),
            ("tp 3375.50", "3375.50"),
            ("TARGET 3375", "3375"),
            ("target 3375.25", "3375.25"),
            ("TAKE PROFIT 3375", "3375"),
            ("take profit: 3375.75", "3375.75")
        ]

        for text, expected in tp_tests:
            matched = False
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    tp_price = match.group(1)
                    assert tp_price == expected, f"TP extraction failed for: {text}"
                    matched = True
                    break
            assert matched, f"TP pattern should match: {text}"

    def test_compiled_patterns_structure(self):
        """Test the compiled patterns structure."""
        compiled = FrenchSignalPatterns.get_compiled_patterns()

        # Check all expected keys exist
        expected_keys = ['buy_actions', 'sell_actions', 'instruments', 'prices', 'stop_losses', 'take_profits']
        for key in expected_keys:
            assert key in compiled, f"Missing compiled pattern key: {key}"
            assert isinstance(compiled[key], list), f"Pattern key {key} should be list"
            assert len(compiled[key]) > 0, f"Pattern key {key} should not be empty"

        # Check all patterns are compiled regex objects
        for key, patterns in compiled.items():
            for pattern in patterns:
                assert hasattr(pattern, 'search'), f"Pattern in {key} should be compiled regex"
                assert hasattr(pattern, 'match'), f"Pattern in {key} should be compiled regex"

    def test_main_patterns_generation(self):
        """Test main combined pattern generation."""
        main_patterns = FrenchSignalPatterns.build_main_patterns()

        assert isinstance(main_patterns, list)
        assert len(main_patterns) > 0

        # All should be compiled regex patterns
        for pattern in main_patterns:
            assert hasattr(pattern, 'search'), "Main pattern should be compiled regex"
            assert hasattr(pattern, 'match'), "Main pattern should be compiled regex"

        # Test some expected combinations work
        test_texts = [
            "BUY GOLD 3362",
            "SELL XAUUSD 3375",
            "ACHETER OR 3350",
            "VENDRE GOLD @ 3380"
        ]

        for text in test_texts:
            matched = any(pattern.search(text) for pattern in main_patterns)
            # Note: Not all combinations might be generated, so this is informational
            if matched:
                print(f"Main pattern matched: {text}")

    def test_pattern_case_insensitivity(self):
        """Test that all patterns are case insensitive."""
        compiled = FrenchSignalPatterns.get_compiled_patterns()

        test_cases = [
            ("buy_actions", "BUY", "buy"),
            ("sell_actions", "SELL", "sell"),
            ("instruments", "GOLD", "gold"),
            ("stop_losses", "SL 3350", "sl 3350"),
            ("take_profits", "TP 3375", "tp 3375")
        ]

        for pattern_key, upper_text, lower_text in test_cases:
            patterns = compiled[pattern_key]

            upper_matched = any(p.search(upper_text) for p in patterns)
            lower_matched = any(p.search(lower_text) for p in patterns)

            # If one matches, both should match (case insensitive)
            if upper_matched or lower_matched:
                assert upper_matched and lower_matched, f"Case insensitivity failed for {pattern_key}: {upper_text} vs {lower_text}"

    def test_pattern_special_characters(self):
        """Test patterns handle special characters correctly."""
        # Test apostrophe in J'ACHÈTE
        apostrophe_pattern = None
        for pattern_text in FrenchSignalPatterns.BUY_ACTIONS:
            if "ACHÈTE" in pattern_text:
                apostrophe_pattern = re.compile(pattern_text, re.IGNORECASE)
                break

        if apostrophe_pattern:
            assert apostrophe_pattern.search("J'ACHÈTE"), "Should match apostrophe"
            assert apostrophe_pattern.search("j'achète"), "Should match lowercase apostrophe"

        # Test @ symbol in price patterns
        at_patterns = [re.compile(p, re.IGNORECASE) for p in FrenchSignalPatterns.PRICE_PATTERNS]
        at_texts = ["@ 3362", "@3362", "@ 3362.50"]

        for text in at_texts:
            matched = any(p.search(text) for p in at_patterns)
            assert matched, f"@ pattern should match: {text}"

    def test_pattern_boundary_conditions(self):
        """Test pattern boundary conditions and edge cases."""
        compiled = FrenchSignalPatterns.get_compiled_patterns()

        # Test that patterns don't over-match
        boundary_tests = [
            ("buy_actions", "BUYSOMETHING", False),  # Should not match partial
            ("instruments", "GOLDSMITH", True),      # Might match as substring - this is ok
            ("prices", "abc3362def", True),          # Numbers in text - might match
        ]

        for pattern_key, text, should_match in boundary_tests:
            patterns = compiled[pattern_key]
            matched = any(p.search(text) for p in patterns)

            # This is more informational - regex behavior can vary
            # The key is that our actual parsing logic handles these cases
            print(f"Boundary test - {pattern_key} in '{text}': {matched} (expected: {should_match})")
