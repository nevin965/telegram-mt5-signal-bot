"""
Regex-based signal parser for standard trading formats.
"""

import decimal
import hashlib
import re
from datetime import datetime
from decimal import Decimal

from config.logging_config import (
    get_contextual_logger,
    set_correlation_id,
    set_service_context,
)

from . import ParsedAction, ParsedSignal, ValidationResult
from .patterns import FrenchSignalPatterns


class RegexParser:
    """Fast regex-based parser for standard trading signal formats."""

    def __init__(self) -> None:
        """Initialize regex parser with compiled patterns."""
        self.logger = get_contextual_logger(__name__)
        self.patterns = FrenchSignalPatterns.get_compiled_patterns()
        self.main_patterns = FrenchSignalPatterns.build_main_patterns()

    # Compiled once - matches "TP1 HIT", "TP 1 HIT", "Target 1 Done",
    # "Take Profit 2 Hit", "First Target Done", etc. across the provider
    # formats we've seen. Requires an explicit hit/done/reached/secured
    # keyword right after TP/TARGET/TAKE PROFIT, so it does NOT match the
    # original signal itself (which just states "TP: 4082" with no such
    # keyword), and does NOT match unrelated text like "Protected Stop
    # Loss Hit" or "Running Profit 50 pips" (no TP/TARGET keyword present).
    _TP_HIT_PATTERNS = [
        re.compile(r'\bTP\s*\d*\s*(?:HIT|REACHED|DONE|SECURED)\b', re.IGNORECASE),
        re.compile(r'\b(?:TARGET|TAKE\s*PROFIT)\s*\d*\s*(?:HIT|REACHED|DONE|SECURED)\b', re.IGNORECASE),
        re.compile(r'\bFIRST\s+TARGET\s+(?:HIT|DONE)\b', re.IGNORECASE),
    ]

    def is_tp_hit_notification(self, text: str) -> bool:
        """
        Return True if this message is a follow-up "a target was hit"
        notification (in any of the phrasings providers use) rather than a
        new trade signal. Used to detect when a still-pending order's
        target has already been reached by the market without the entry
        ever being filled - meaning the pending order is now stale.

        Note: intentionally conservative. Loose celebratory phrasing that
        doesn't include an actual hit/done/reached keyword (e.g. "TP 1
        KAWKAW 🔥") is NOT matched, since acting on ambiguous chatter risks
        wrongly cancelling a still-valid pending order. Better to miss a
        few of those than false-positive on real ones.
        """
        if not text or not text.strip():
            return False
        cleaned = self._remove_emojis(text)
        return any(p.search(cleaned) for p in self._TP_HIT_PATTERNS)

    def _remove_emojis(self, text: str) -> str:
        """
        Remove emojis and special Unicode characters from text.
        Includes premium Telegram emojis and all supplementary Unicode.
        """
        emoji_pattern = re.compile(
            "["
            u"\U0001F600-\U0001F64F"  # emoticons
            u"\U0001F300-\U0001F5FF"  # symbols & pictographs
            u"\U0001F680-\U0001F6FF"  # transport & map symbols
            u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
            u"\U00002500-\U00002BEF"  # chinese char
            u"\U00002702-\U000027B0"
            u"\U000024C2-\U0001F251"
            u"\U0001f926-\U0001f937"
            u"\U00010000-\U0010FFFF"  # Premium emojis and supplementary characters
            u"\u2640-\u2642"
            u"\u2600-\u2B55"
            u"\u200d"
            u"\u23cf"
            u"\u23e9"
            u"\u231a"
            u"\ufe0f"
            u"\u3030"
            "]+",
            flags=re.UNICODE
        )
        return emoji_pattern.sub(r'', text)

    # -----------------------------------------------------------------
    #  FLEXIBLE EXTRACTION METHODS (case‑insensitive, multiple forms)
    # -----------------------------------------------------------------
    def _extract_stop_loss_flexible(self, text: str) -> Decimal | None:
        """
        Extract SL from text supporting:
        SL, STOP LOSS, STOPLOSS (case‑insensitive)
        Returns Decimal or None.
        """
        cleaned = self._remove_emojis(text)
        cleaned = re.sub(r'\*+', '', cleaned)
        cleaned = re.sub(r'_{2,}', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        pattern = re.compile(r'(?:SL|STOP\s*LOSS)\s*[:=\-–—@]?\s*(\d+\.?\d*)', re.IGNORECASE)
        match = pattern.search(cleaned)
        if match:
            try:
                return Decimal(match.group(1))
            except:
                pass
        return None

    def _extract_take_profit_flexible(self, text: str) -> Decimal | None:
        """
        Extract the first TP from text supporting:
        TP, TP1, TP2, ..., TAKE PROFIT, TARGET (case‑insensitive)
        Returns Decimal or None.
        """
        cleaned = self._remove_emojis(text)
        cleaned = re.sub(r'\*+', '', cleaned)
        cleaned = re.sub(r'_{2,}', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        # Three candidate patterns, tried in priority order:
        #  1. TP / TP1 / TP2 (label glued directly to "TP", e.g. no space) - unambiguous
        #  2. "TARGET 1 :" / "TAKE PROFIT 2 -" (label is a separate word, so a
        #     separator is REQUIRED afterwards - otherwise "Target 4060" would
        #     misread "4060" itself as the label, since \d* is greedy)
        #  3. "TARGET :" / "TARGET -" / "TAKE PROFIT 4060" (no numbered label at all)
        candidates = [
            re.compile(r'TP\d*\s*[:=\-–—@]?\s*(\d+\.?\d*)', re.IGNORECASE),
            re.compile(r'(?:TAKE\s*PROFIT|TARGET)\s+\d{1,2}\s*[:=\-–—@]\s*(\d+\.?\d*)', re.IGNORECASE),
            re.compile(r'(?:TAKE\s*PROFIT|TARGET)\s*[:=\-–—@]?\s*(\d+\.?\d*)', re.IGNORECASE),
        ]
        best_match = None
        for pattern in candidates:
            m = pattern.search(cleaned)
            # Strict "<" means earlier candidates win ties, so the more specific
            # (label-aware) patterns are preferred over the generic fallback
            # when they match at the same position.
            if m and (best_match is None or m.start() < best_match.start()):
                best_match = m
        if best_match:
            try:
                return Decimal(best_match.group(1))
            except:
                pass
        return None

    # -----------------------------------------------------------------
    #  STRICT COMPONENT VALIDATION (uses flexible patterns)
    # -----------------------------------------------------------------
    def _has_required_components(self, text: str) -> bool:
        """
        Check if the text contains all required trading signal components:
        - Action (BUY/SELL)
        - Stop Loss (SL, STOP LOSS, STOPLOSS)
        - Take Profit (TP, TP1, TP2, TAKE PROFIT, TARGET)
        """
        cleaned = self._remove_emojis(text)
        cleaned = re.sub(r'\*+', '', cleaned)
        cleaned = re.sub(r'_{2,}', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        cleaned_upper = cleaned.upper()

        has_action = re.search(r'\b(BUY|SELL)\b', cleaned_upper) is not None
        has_sl = re.search(r'\b(SL|STOP\s*LOSS)\b', cleaned_upper) is not None
        has_tp = (
            re.search(r'\bTP\d*\b', cleaned_upper) is not None or
            re.search(r'TAKE\s*PROFIT', cleaned_upper) is not None or
            re.search(r'TARGET', cleaned_upper) is not None
        )

        self.logger.info(f"🔍 Component check - Action: {has_action}, SL: {has_sl}, TP: {has_tp}")
        return has_action and has_sl and has_tp

    def _expand_shorthand_bound(self, first: Decimal, second_text: str) -> Decimal:
        """
        Ranges are often written in shorthand, e.g. '4070-73' meaning
        4070 to 4073, or '4090/95' meaning 4090 to 4095 - only the digits
        that differ from the first number are given.

        If the second number has fewer integer digits than the first AND
        has no decimal point of its own, treat it as shorthand: splice it
        onto the first number's leading digits. Otherwise it's a fully
        independent price (e.g. '4070.65 - 4072.29' or '3330-3334') and
        is used as-is.
        """
        second_text = second_text.strip()
        if '.' in second_text:
            return Decimal(second_text)
        first_int_str = str(int(first))
        if len(second_text) < len(first_int_str):
            spliced = first_int_str[:-len(second_text)] + second_text
            return Decimal(spliced)
        return Decimal(second_text)

    def _resolve_directional_entry(self, entry1_text: str, entry2_text: str, action: ParsedAction) -> Decimal:
        """
        Resolve a two-sided entry range/zone to a single conservative entry
        price: BUY takes the lower bound, SELL takes the upper bound (the
        worst realistic fill within the zone). Handles shorthand second
        numbers via _expand_shorthand_bound.
        """
        e1 = Decimal(entry1_text.strip())
        e2 = self._expand_shorthand_bound(e1, entry2_text)
        return min(e1, e2) if action == ParsedAction.BUY else max(e1, e2)

    # -----------------------------------------------------------------
    #  IN ZONE PARSER (uses flexible extraction)
    # -----------------------------------------------------------------
    def _parse_in_zone_format(self, text: str) -> ParsedSignal | None:
        try:
            cleaned = self._remove_emojis(text)
            cleaned = re.sub(r'\*+', '', cleaned)
            cleaned = re.sub(r'_{2,}', '', cleaned)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()

            self.logger.info(f"🔍 IN ZONE cleaned: {cleaned}")

            if "IN ZONE" not in cleaned.upper():
                return None

            action_match = re.search(r'\b(BUY|SELL)\b', cleaned, re.IGNORECASE)
            if not action_match:
                return None
            action = ParsedAction.BUY if action_match.group(1).upper() == 'BUY' else ParsedAction.SELL

            symbol_match = re.search(r'\b(GOLD|XAUUSD)\b', cleaned, re.IGNORECASE)
            if not symbol_match:
                return None
            symbol = self._normalize_symbol(symbol_match.group(1))

            entry_match = re.search(r'(\d+\.?\d*)\s*[-–—/]\s*(\d+\.?\d*)', cleaned)
            if not entry_match:
                return None
            entry_price = self._resolve_directional_entry(entry_match.group(1), entry_match.group(2), action)

            stop_loss = self._extract_stop_loss_flexible(cleaned)
            take_profit = self._extract_take_profit_flexible(cleaned)

            self.logger.info(
                f"📊 IN ZONE parser: {action.value} {symbol} @ {entry_price}, SL: {stop_loss}, TP: {take_profit}"
            )

            signal = ParsedSignal(
                telegram_message_id=0,
                telegram_chat_id=0,
                sender="",
                timestamp=datetime.now(),
                raw_text=text,
                parsed_action=action,
                symbol=symbol,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence_score=0.95,
                parser_type="REGEX_IN_ZONE",
                status="PENDING"
            )

            validation = self._validate_signal(signal)
            if validation.is_valid:
                return signal
            else:
                self.logger.warning(f"IN ZONE validation failed: {validation.errors}")
                return None

        except Exception as e:
            self.logger.error(f"Error in IN ZONE parser: {e}")
            return None

    # -----------------------------------------------------------------
    #  ENTRY ZONE PARSER (uses flexible extraction)
    # -----------------------------------------------------------------
    def _parse_entry_zone_format(self, text: str) -> ParsedSignal | None:
        try:
            cleaned = self._remove_emojis(text)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()

            action_symbol_match = re.search(r'\b(BUY|SELL)\s+(XAUUSD|GOLD|BTCUSD|EURUSD|GBPUSD|USDJPY)\b', cleaned, re.IGNORECASE)
            if not action_symbol_match:
                return None
            action_text = action_symbol_match.group(1).upper()
            symbol_text = action_symbol_match.group(2).upper()
            action = ParsedAction.BUY if action_text == 'BUY' else ParsedAction.SELL
            symbol = self._normalize_symbol(symbol_text)

            entry_match = re.search(r'(?:Entry\s+Zone|ENTRY\s+ZONE)\s*[:=]?\s*(\d+\.?\d*)\s*[-–—/]\s*(\d+\.?\d*)', cleaned, re.IGNORECASE)
            if not entry_match:
                entry_match = re.search(r'(\d+\.?\d*)\s*[-–—/]\s*(\d+\.?\d*)', cleaned, re.IGNORECASE)
                if not entry_match:
                    return None
            entry_price = self._resolve_directional_entry(entry_match.group(1), entry_match.group(2), action)

            stop_loss = self._extract_stop_loss_flexible(cleaned)
            take_profit = self._extract_take_profit_flexible(cleaned)

            self.logger.info(
                f"📊 Entry Zone parser: {action.value} {symbol} @ {entry_price}, SL: {stop_loss}, TP: {take_profit}"
            )

            signal = ParsedSignal(
                telegram_message_id=0,
                telegram_chat_id=0,
                sender="",
                timestamp=datetime.now(),
                raw_text=text,
                parsed_action=action,
                symbol=symbol,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence_score=0.95,
                parser_type="REGEX_ENTRY_ZONE",
                status="PENDING"
            )

            validation = self._validate_signal(signal)
            if validation.is_valid:
                return signal
            else:
                self.logger.warning(f"Entry Zone validation failed: {validation.errors}")
                return None

        except Exception as e:
            self.logger.error(f"Error in Entry Zone parser: {e}")
            return None

    # -----------------------------------------------------------------
    #  SCALPING PARSER (keeps its own TP extraction for superscripts)
    # -----------------------------------------------------------------
    def _parse_scalping_format(self, text: str) -> ParsedSignal | None:
        try:
            cleaned = self._remove_emojis(text)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()

            self.logger.info(f"🔍 Scalping parser running on: {cleaned[:100]}...")

            symbols = r'XAUUSD|GOLD|XAU/USD|BTCUSD|BTC/USD|EURUSD|GBPUSD|USDJPY|AUDUSD|USDCAD|NZDUSD'
            symbol_match = re.search(r'(' + symbols + r')', cleaned, re.IGNORECASE)
            if not symbol_match:
                return None
            symbol = self._normalize_symbol(symbol_match.group(1))

            action_match = re.search(r'(BUY|SELL)', cleaned, re.IGNORECASE)
            if not action_match:
                return None
            action = ParsedAction.BUY if action_match.group(1).upper() == 'BUY' else ParsedAction.SELL

            entry_match = re.search(r'(BUY|SELL)\s+(\d+\.?\d*)', cleaned, re.IGNORECASE)
            if not entry_match:
                return None
            try:
                entry_price = Decimal(entry_match.group(2))
            except:
                return None

            stop_loss = self._extract_stop_loss_flexible(cleaned)

            # TP pattern: handles superscripts as before
            tp_pattern = re.compile(r'(?:TP|ΤΡ)\s*[\^¹²³⁴⁵⁶⁷⁸⁹⁰]*\s*(\d+\.?\d*)', re.IGNORECASE)
            tp_matches = tp_pattern.findall(cleaned)
            tp_numbers = []
            for m in tp_matches:
                try:
                    tp_numbers.append(Decimal(m))
                except:
                    continue
            self.logger.info(f"🔍 Scalping parser found TPs: {tp_numbers}")

            if len(tp_numbers) < 4:
                tp_index = 0
            else:
                tp_index = 3  # 4th TP

            take_profit = tp_numbers[tp_index] if tp_numbers else None

            self.logger.info(
                f"📊 Scalping format parsed: {action.value} {symbol} @ {entry_price}, SL: {stop_loss}, TP (4th): {take_profit}"
            )

            signal = ParsedSignal(
                telegram_message_id=0,
                telegram_chat_id=0,
                sender="",
                timestamp=datetime.now(),
                raw_text=text,
                parsed_action=action,
                symbol=symbol,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence_score=0.95,
                parser_type="REGEX_SCALPING",
                status="PENDING"
            )

            validation = self._validate_signal(signal)
            if validation.is_valid:
                return signal
            else:
                self.logger.warning(f"Scalping format validation failed: {validation.errors}")
                return None

        except Exception as e:
            self.logger.error(f"Error in scalping format parser: {e}")
            return None

    # -----------------------------------------------------------------
    #  GOLD PARSER (uses flexible extraction)
    # -----------------------------------------------------------------
    def _parse_gold_format(self, text: str) -> ParsedSignal | None:
        try:
            cleaned = self._remove_emojis(text)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()

            symbol_match = re.search(r'\b(GOLD|XAUUSD)\b', cleaned, re.IGNORECASE)
            if not symbol_match:
                return None
            symbol = self._normalize_symbol(symbol_match.group(1))

            action_match = re.search(r'\b(BUY|SELL)\b', cleaned, re.IGNORECASE)
            if not action_match:
                return None
            action = ParsedAction.BUY if action_match.group(1).upper() == 'BUY' else ParsedAction.SELL

            range_match = re.search(r'@\s*(\d+\.?\d*)\s*[-–—/]\s*(\d+\.?\d*)', cleaned, re.IGNORECASE)
            if range_match:
                entry_price = self._resolve_directional_entry(range_match.group(1), range_match.group(2), action)
            else:
                entry_match = re.search(r'@\s*(\d+\.?\d*)', cleaned, re.IGNORECASE)
                if not entry_match:
                    entry_match = re.search(r'(BUY|SELL)\s+(\d+\.?\d*)', cleaned, re.IGNORECASE)
                    if entry_match:
                        entry_price = Decimal(entry_match.group(2))
                    else:
                        return None
                else:
                    entry_price = Decimal(entry_match.group(1))

            stop_loss = self._extract_stop_loss_flexible(cleaned)
            take_profit = self._extract_take_profit_flexible(cleaned)

            self.logger.info(
                f"📊 Dedicated GOLD parser: {action.value} {symbol} @ {entry_price}, SL: {stop_loss}, TP: {take_profit}"
            )

            signal = ParsedSignal(
                telegram_message_id=0,
                telegram_chat_id=0,
                sender="",
                timestamp=datetime.now(),
                raw_text=text,
                parsed_action=action,
                symbol=symbol,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence_score=0.95,
                parser_type="REGEX_GOLD",
                status="PENDING"
            )

            validation = self._validate_signal(signal)
            if validation.is_valid:
                return signal
            else:
                self.logger.warning(f"GOLD parser validation failed: {validation.errors}")
                return None

        except Exception as e:
            self.logger.error(f"Error in GOLD parser: {e}")
            return None

    # -----------------------------------------------------------------
    #  MAIN PARSE
    # -----------------------------------------------------------------
    def parse(self, text: str) -> ParsedSignal | None:
        """
        Public entry point. Delegates to _parse_raw() for the actual format
        detection, then applies one final safety gate: never hand back a
        signal that's missing SL or TP, even if some parser technically
        "succeeded". A trade with no stop loss is unacceptable regardless
        of which code path produced it.
        """
        signal = self._parse_raw(text)
        if signal is None:
            return None
        if signal.stop_loss is None or signal.take_profit is None:
            self.logger.error(
                f"⚠️ REJECTING signal: parsed but missing SL and/or TP "
                f"(SL={signal.stop_loss}, TP={signal.take_profit}) - refusing to place an "
                f"unprotected trade. Raw text: {text[:200]!r}"
            )
            return None
        return signal

    def _parse_raw(self, text: str) -> ParsedSignal | None:
        if not text or not text.strip():
            return None

        # Strict validation first
        if not self._has_required_components(text):
            self.logger.info("❌ Message missing required components (action, SL, TP) – ignoring")
            return None

        # Try dedicated parsers
        for parser in [
            self._parse_in_zone_format,
            self._parse_entry_zone_format,
            self._parse_scalping_format,
            self._parse_gold_format,
        ]:
            signal = parser(text)
            if signal:
                return signal

        # Fallback to main regex patterns
        text = self._remove_emojis(text)
        set_service_context("RegexParser", "parse")
        correlation_id = set_correlation_id()
        cleaned_text = text.strip().upper()

        self.logger.info(
            "Signal parse attempt started",
            extra_fields={
                "signal_data": {
                    "raw_text_hash": self._hash_text(text),
                    "text_length": len(text),
                    "parser": "REGEX"
                }
            }
        )

        for pattern in self.main_patterns:
            match = pattern.search(cleaned_text)
            if match:
                try:
                    signal = self._extract_signal_from_match(match, text, correlation_id)
                    if signal:
                        validation = self._validate_signal(signal)
                        if validation.is_valid:
                            self.logger.info(
                                "Signal parsed successfully",
                                extra_fields={
                                    "signal_data": {
                                        "action": signal.parsed_action.value,
                                        "symbol": signal.symbol,
                                        "entry": str(signal.entry_price),
                                        "confidence": signal.confidence_score,
                                        "parser": "REGEX",
                                        "raw_text_hash": self._hash_text(text)
                                    }
                                }
                            )
                            return signal
                        else:
                            self.logger.warning(
                                "Signal validation failed",
                                extra_fields={
                                    "signal_data": {
                                        "validation_errors": validation.errors,
                                        "parser": "REGEX",
                                        "raw_text_hash": self._hash_text(text)
                                    }
                                }
                            )
                except Exception as e:
                    self.logger.error(
                        f"Error extracting signal from regex match: {e}",
                        extra_fields={
                            "signal_data": {
                                "parser": "REGEX",
                                "raw_text_hash": self._hash_text(text),
                                "error": str(e)
                            }
                        }
                    )

        # Fallback to component parsing
        fallback_signal = self._try_component_parsing(cleaned_text, text, correlation_id)
        if fallback_signal:
            return fallback_signal

        self.logger.info(
            "Parse failed - no patterns matched",
            extra_fields={
                "signal_data": {
                    "parser": "REGEX",
                    "raw_text_hash": self._hash_text(text),
                    "patterns_attempted": len(self.main_patterns) + 1
                }
            }
        )

        return None

    # -----------------------------------------------------------------
    #  EXTRACT FROM MATCH (unchanged)
    # -----------------------------------------------------------------
    def _extract_signal_from_match(self, match: re.Match, original_text: str, _correlation_id: str) -> ParsedSignal | None:
        """
        Extract ParsedSignal from regex match.
        """
        try:
            groups = match.groups()
            if len(groups) < 3:
                return None

            # GOLD FORMAT WITH TP1, TP2, TP3, SL
            if len(groups) == 7:
                if groups[0].upper() in ['BUY', 'SELL'] and groups[1].upper() in ['GOLD', 'XAUUSD']:
                    action_text = groups[0].strip()
                    symbol_text = groups[1].strip()
                    entry_text = groups[2].strip()
                    tp1_text = groups[3].strip()
                    tp2_text = groups[4].strip()
                    tp3_text = groups[5].strip()
                    sl_text = groups[6].strip()

                    parsed_action = self._parse_action(action_text)
                    if not parsed_action:
                        return None

                    normalized_symbol = self._normalize_symbol(symbol_text)

                    try:
                        entry_price = Decimal(entry_text)
                    except:
                        return None

                    try:
                        stop_loss = Decimal(sl_text) if sl_text else None
                    except:
                        stop_loss = None

                    try:
                        take_profit = Decimal(tp1_text) if tp1_text else None
                    except:
                        take_profit = None

                    self.logger.info(
                        f"📊 Parsed GOLD-TP1/TP2/TP3 format: {action_text} {normalized_symbol} @ {entry_price}, SL: {sl_text}, TP1: {tp1_text}, TP2: {tp2_text}, TP3: {tp3_text}"
                    )

                    signal = ParsedSignal(
                        telegram_message_id=0,
                        telegram_chat_id=0,
                        sender="",
                        timestamp=datetime.now(),
                        raw_text=original_text,
                        parsed_action=parsed_action,
                        symbol=normalized_symbol,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        confidence_score=0.95,
                        parser_type="REGEX",
                        status="PENDING"
                    )
                    return signal

            # 11-group format
            if len(groups) == 11:
                action_text = groups[0].strip()
                symbol_text = groups[1].strip()
                entry_text = groups[2].strip()
                tp1_text = groups[3].strip() if groups[3] else groups[4].strip() if groups[4] else None
                tp2_text = groups[5].strip() if groups[5] else groups[6].strip() if groups[6] else None
                tp3_text = groups[7].strip() if groups[7] else groups[8].strip() if groups[8] else None
                sl_text = groups[9].strip() if groups[9] else groups[10].strip() if groups[10] else None

                parsed_action = self._parse_action(action_text)
                if not parsed_action:
                    return None

                normalized_symbol = self._normalize_symbol(symbol_text)

                try:
                    entry_price = Decimal(entry_text)
                except:
                    return None

                try:
                    stop_loss = Decimal(sl_text) if sl_text else None
                except:
                    stop_loss = None

                try:
                    take_profit = Decimal(tp1_text) if tp1_text else None
                except:
                    take_profit = None

                self.logger.info(
                    f"📊 Parsed GOLD-TP1/TP2/TP3 (11-group) format: {action_text} {normalized_symbol} @ {entry_price}, SL: {sl_text}, TP1: {tp1_text}, TP2: {tp2_text}, TP3: {tp3_text}"
                )

                signal = ParsedSignal(
                    telegram_message_id=0,
                    telegram_chat_id=0,
                    sender="",
                    timestamp=datetime.now(),
                    raw_text=original_text,
                    parsed_action=parsed_action,
                    symbol=normalized_symbol,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence_score=0.95,
                    parser_type="REGEX",
                    status="PENDING"
                )
                return signal

            # SYMBOL-FIRST: Sl@, Tp1@, Tp2@
            if len(groups) == 6 and "sl@" in original_text.lower() and "tp1@" in original_text.lower():
                symbol_text = groups[0].strip()
                action_text = groups[1].strip()
                entry_text = groups[2].strip()
                sl_text = groups[3].strip()
                tp1_text = groups[4].strip()
                tp2_text = groups[5].strip()

                parsed_action = self._parse_action(action_text)
                if not parsed_action:
                    return None

                normalized_symbol = self._normalize_symbol(symbol_text)

                try:
                    entry_price = Decimal(entry_text)
                except:
                    return None

                try:
                    stop_loss = Decimal(sl_text)
                except:
                    stop_loss = None

                try:
                    take_profit = Decimal(tp1_text)
                except:
                    take_profit = None

                self.logger.info(
                    f"📊 Parsed Sl@Tp1@Tp2 (symbol-first) format: {action_text} {normalized_symbol} @ {entry_price}, SL: {sl_text}, TP1: {tp1_text}, TP2: {tp2_text}"
                )

                signal = ParsedSignal(
                    telegram_message_id=0,
                    telegram_chat_id=0,
                    sender="",
                    timestamp=datetime.now(),
                    raw_text=original_text,
                    parsed_action=parsed_action,
                    symbol=normalized_symbol,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence_score=0.95,
                    parser_type="REGEX",
                    status="PENDING"
                )
                return signal

            # ACTION-FIRST: Sl@, Tp1@, Tp2@
            if len(groups) == 6:
                action_text = groups[0].strip()
                symbol_text = groups[1].strip()
                entry_text = groups[2].strip()
                sl_text = groups[3].strip()
                tp1_text = groups[4].strip()
                tp2_text = groups[5].strip()

                parsed_action = self._parse_action(action_text)
                if not parsed_action:
                    return None

                normalized_symbol = self._normalize_symbol(symbol_text)

                try:
                    entry_price = Decimal(entry_text)
                except:
                    return None

                try:
                    stop_loss = Decimal(sl_text)
                except:
                    stop_loss = None

                try:
                    take_profit = Decimal(tp1_text)
                except:
                    take_profit = None

                self.logger.info(
                    f"📊 Parsed Sl@Tp1@Tp2 (action-first) format: {action_text} {normalized_symbol} @ {entry_price}, SL: {sl_text}, TP1: {tp1_text}, TP2: {tp2_text}"
                )

                signal = ParsedSignal(
                    telegram_message_id=0,
                    telegram_chat_id=0,
                    sender="",
                    timestamp=datetime.now(),
                    raw_text=original_text,
                    parsed_action=parsed_action,
                    symbol=normalized_symbol,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence_score=0.95,
                    parser_type="REGEX",
                    status="PENDING"
                )
                return signal

            # 7-group format (symbol, action, entry1, entry2, tp1, tp2, sl)
            if len(groups) == 7:
                symbol_text = groups[0].strip()
                action_text = groups[1].strip()
                entry_price_text = groups[2].strip()
                entry_price_high = groups[3]
                tp1_text = groups[4].strip()
                tp2_text = groups[5].strip()
                sl_text = groups[6].strip()

                parsed_action = self._parse_action(action_text)
                if not parsed_action:
                    return None

                normalized_symbol = self._normalize_symbol(symbol_text)

                try:
                    entry_price = Decimal(entry_price_text)
                except:
                    return None

                try:
                    stop_loss = Decimal(sl_text)
                except:
                    stop_loss = None

                try:
                    take_profit = Decimal(tp1_text)
                except:
                    take_profit = None

                self.logger.info(
                    f"📊 Parsed 7-group format: {action_text} {normalized_symbol} @ {entry_price}, SL: {sl_text}, TP1: {tp1_text}, TP2: {tp2_text}"
                )

                signal = ParsedSignal(
                    telegram_message_id=0,
                    telegram_chat_id=0,
                    sender="",
                    timestamp=datetime.now(),
                    raw_text=original_text,
                    parsed_action=parsed_action,
                    symbol=normalized_symbol,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence_score=0.95,
                    parser_type="REGEX",
                    status="PENDING"
                )
                return signal

            # 3-5 group formats
            action_text = groups[0].strip()
            parsed_action = self._parse_action(action_text)

            if parsed_action:
                symbol_text = groups[1].strip()
                normalized_symbol = self._normalize_symbol(symbol_text)
                price_text = groups[2].strip()
            else:
                symbol_text = groups[0].strip()
                normalized_symbol = self._normalize_symbol(symbol_text)
                action_text = groups[1].strip()
                parsed_action = self._parse_action(action_text)
                if not parsed_action:
                    return None
                price_text = groups[2].strip()

            try:
                entry_price = Decimal(price_text)
            except:
                return None

            # Use flexible extraction for SL and TP as fallback
            stop_loss = self._extract_stop_loss_flexible(original_text)
            take_profit = self._extract_take_profit_flexible(original_text)

            signal = ParsedSignal(
                telegram_message_id=0,
                telegram_chat_id=0,
                sender="",
                timestamp=datetime.now(),
                raw_text=original_text,
                parsed_action=parsed_action,
                symbol=normalized_symbol,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence_score=0.95,
                parser_type="REGEX",
                status="PENDING"
            )

            return signal

        except Exception as e:
            self.logger.error(f"Error extracting signal from match: {e}")
            return None

    def _try_component_parsing(self, cleaned_text: str, original_text: str, _correlation_id: str) -> ParsedSignal | None:
        """Try parsing by extracting components individually."""
        try:
            action = None
            for pattern in self.patterns['buy_actions']:
                if pattern.search(cleaned_text):
                    action = ParsedAction.BUY
                    break

            if not action:
                for pattern in self.patterns['sell_actions']:
                    if pattern.search(cleaned_text):
                        action = ParsedAction.SELL
                        break

            if not action:
                return None

            symbol = None
            for pattern in self.patterns['instruments']:
                match = pattern.search(cleaned_text)
                if match:
                    symbol = self._normalize_symbol(match.group(0))
                    break

            if not symbol:
                return None

            entry_price = None
            for pattern in self.patterns['prices']:
                match = pattern.search(cleaned_text)
                if match:
                    try:
                        entry_price = Decimal(match.group(1) if match.groups() else match.group(0))
                        break
                    except (ValueError, TypeError, decimal.InvalidOperation):
                        continue

            if not entry_price:
                return None

            # Use flexible extraction
            stop_loss = self._extract_stop_loss_flexible(original_text)
            take_profit = self._extract_take_profit_flexible(original_text)

            signal = ParsedSignal(
                telegram_message_id=0,
                telegram_chat_id=0,
                sender="",
                timestamp=datetime.now(),
                raw_text=original_text,
                parsed_action=action,
                symbol=symbol,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence_score=0.90,
                parser_type="REGEX",
                status="PENDING"
            )

            validation = self._validate_signal(signal)
            if validation.is_valid:
                self.logger.info(
                    "Signal parsed via component extraction",
                    extra_fields={
                        "signal_data": {
                            "action": signal.parsed_action.value,
                            "symbol": signal.symbol,
                            "entry": str(signal.entry_price),
                            "confidence": signal.confidence_score,
                            "parser": "REGEX_COMPONENT",
                            "raw_text_hash": self._hash_text(original_text)
                        }
                    }
                )
                return signal
            else:
                self.logger.warning(
                    "Component-parsed signal validation failed",
                    extra_fields={
                        "signal_data": {
                            "validation_errors": validation.errors,
                            "parser": "REGEX_COMPONENT",
                            "raw_text_hash": self._hash_text(original_text)
                        }
                    }
                )

        except Exception as e:
            self.logger.error(f"Error in component parsing: {e}")

        return None

    def _parse_action(self, action_text: str) -> ParsedAction | None:
        action_upper = action_text.upper()
        for pattern in FrenchSignalPatterns.BUY_ACTIONS:
            if re.search(pattern, action_upper, re.IGNORECASE):
                return ParsedAction.BUY
        for pattern in FrenchSignalPatterns.SELL_ACTIONS:
            if re.search(pattern, action_upper, re.IGNORECASE):
                return ParsedAction.SELL
        return None

    def _normalize_symbol(self, symbol_text: str) -> str:
        symbol_upper = symbol_text.upper()
        if symbol_upper in ['OR']:
            return 'GOLD'
        elif symbol_upper in ['XAU/USD', 'XAU', 'XAUUSDM']:
            return 'XAUUSD'
        elif symbol_upper in ['BTC/USD', 'BTC', 'BTCUSDM']:
            return 'BTCUSD'
        elif symbol_upper in ['GOLD', 'XAUUSD', 'BTCUSD']:
            return symbol_upper
        return symbol_text.upper()

    def _extract_stop_loss(self, text: str) -> Decimal | None:
        # kept for backward compatibility, but use flexible version
        return self._extract_stop_loss_flexible(text)

    def _extract_take_profit(self, text: str) -> Decimal | None:
        # kept for backward compatibility, but use flexible version
        return self._extract_take_profit_flexible(text)

    def _validate_signal(self, signal: ParsedSignal) -> ValidationResult:
        errors = []
        warnings = []

        if signal.stop_loss:
            if signal.parsed_action == ParsedAction.BUY:
                if signal.stop_loss >= signal.entry_price:
                    errors.append("SL for BUY order must be below entry price")
                elif signal.entry_price - signal.stop_loss > Decimal('5.0'):
                    warnings.append("SL distance > 500 pips, high risk")
                elif signal.entry_price - signal.stop_loss < Decimal('0.05'):
                    warnings.append("SL distance < 5 pips, very tight")
            elif signal.parsed_action == ParsedAction.SELL:
                if signal.stop_loss <= signal.entry_price:
                    errors.append("SL for SELL order must be above entry price")
                elif signal.stop_loss - signal.entry_price > Decimal('5.0'):
                    warnings.append("SL distance > 500 pips, high risk")
                elif signal.stop_loss - signal.entry_price < Decimal('0.05'):
                    warnings.append("SL distance < 5 pips, very tight")

        if signal.take_profit:
            if signal.parsed_action == ParsedAction.BUY:
                if signal.take_profit <= signal.entry_price:
                    errors.append("TP for BUY order must be above entry price")
                elif signal.take_profit - signal.entry_price < Decimal('0.10'):
                    warnings.append("TP distance < 10 pips, minimum recommended")
            elif signal.parsed_action == ParsedAction.SELL:
                if signal.take_profit >= signal.entry_price:
                    errors.append("TP for SELL order must be below entry price")
                elif signal.entry_price - signal.take_profit < Decimal('0.10'):
                    warnings.append("TP distance < 10 pips, minimum recommended")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]