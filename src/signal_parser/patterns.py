"""
Trading signal patterns for regex-based parsing.
"""

import re


class FrenchSignalPatterns:
    """Pattern definitions for trading signal formats."""

    # Action patterns
    BUY_ACTIONS = [
        r'BUY',
        r'ACHAT',
        r'LONG',
        r'BULL',
        r'BUY\s+LIMIT',
        r'BUY\s+STOP',
    ]

    SELL_ACTIONS = [
        r'SELL',
        r'VENTE',
        r'SHORT',
        r'BEAR',
        r'SELL\s+LIMIT',
        r'SELL\s+STOP',
    ]

    # Instrument patterns
    INSTRUMENTS = [
        r'XAUUSDm',
        r'XAUUSD',
        r'GOLD',
        r'XAU/USD',
        r'BTCUSDm',
        r'BTCUSD',
        r'BTC/USD',
        r'BTC',
        r'BITCOIN',
        r'EURUSD',
        r'GBPUSD',
        r'USDJPY',
        r'AUDUSD',
        r'USDCAD',
        r'NZDUSD',
    ]

    # Price patterns
    PRICE_PATTERNS = [
        r'(\d+\.?\d*)',
    ]

    # SL/TP patterns
    STOP_LOSS_PATTERNS = [
        r'SL\s*[:=]?\s*(\d+\.?\d*)',
        r'STOP\s*LOSS\s*[:=]?\s*(\d+\.?\d*)',
        r'STOP\s*[:=]?\s*(\d+\.?\d*)',
        r'Stoploss\s*[-:]\s*(\d+\.?\d*)',
    ]

    TAKE_PROFIT_PATTERNS = [
        r'TP\s*[:=]?\s*(\d+\.?\d*)',
        r'TAKE\s*PROFIT\s*[:=]?\s*(\d+\.?\d*)',
        r'TARGET\s*[:=]?\s*(\d+\.?\d*)',
        r'Take\s+Profit\s*[-:]\s*(\d+\.?\d*)',
    ]

    @classmethod
    def get_compiled_patterns(cls):
        """Get compiled patterns for all categories."""
        return {
            'buy_actions': [re.compile(p, re.IGNORECASE) for p in cls.BUY_ACTIONS],
            'sell_actions': [re.compile(p, re.IGNORECASE) for p in cls.SELL_ACTIONS],
            'instruments': [re.compile(p, re.IGNORECASE) for p in cls.INSTRUMENTS],
            'prices': [re.compile(p, re.IGNORECASE) for p in cls.PRICE_PATTERNS],
            'stop_losses': [re.compile(p, re.IGNORECASE) for p in cls.STOP_LOSS_PATTERNS],
            'take_profits': [re.compile(p, re.IGNORECASE) for p in cls.TAKE_PROFIT_PATTERNS],
        }

    @classmethod
    def build_main_patterns(cls):
        """
        Build combined patterns for direct signal extraction.
        """
        symbols = '|'.join([
            'XAUUSDm', 'XAUUSD', 'GOLD', 'XAU/USD',
            'BTCUSDm', 'BTCUSD', 'BTC/USD', 'BTC', 'BITCOIN',
            'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'NZDUSD'
        ])

        patterns = [
            # ✅ GOLD FORMAT WITH TP1, TP2, TP3, SL - MUST BE FIRST!
            # Example: "SELL GOLD @ 3991.49 TP1: 3989.49 TP2: 3987.49 TP3: 3985.49 SL: 3996.49"
            re.compile(
                r'(BUY|SELL)\s+(GOLD|XAUUSD)\s*@?\s*(\d+\.?\d*)\s+TP1:?\s*(\d+\.?\d*)\s+TP2:?\s*(\d+\.?\d*)\s+TP3:?\s*(\d+\.?\d*)\s+SL:?\s*(\d+\.?\d*)',
                re.IGNORECASE
            ),

            # ✅ NEW: GOLD BUY IN ZONE format with range entry
            # Example: "GOLD BUY IN ZONE 4007 - 4002 SL : 3998 TP1 : 4012 TP2 : 4017"
            re.compile(
                r'(BUY|SELL)\s+(GOLD|XAUUSD)\s+IN\s+ZONE\s+(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s+(?:SL|STOP)\s*:?\s*(\d+\.?\d*)\s+(?:TP1|TAKE\s+PROFIT\s*1)\s*:?\s*(\d+\.?\d*)\s+(?:TP2|TAKE\s+PROFIT\s*2)\s*:?\s*(\d+\.?\d*)',
                re.IGNORECASE
            ),

            # Standard format: BUY XAUUSD 3330 SL 3326 TP 3340
            re.compile(
                r'(BUY|SELL|LONG|SHORT)\s+(' + symbols + r')\s+(\d+\.?\d*)\s+(?:SL|STOP)\s+(\d+\.?\d*)\s+(?:TP|TAKE)\s+(\d+\.?\d*)',
                re.IGNORECASE
            ),
            
            # Format with entry range: BUY XAUUSD 3330-3334 SL 3326 TP 3340
            re.compile(
                r'(BUY|SELL|LONG|SHORT)\s+(' + symbols + r')\s+(\d+\.?\d*)[-\s]?(\d+\.?\d*)?\s+(?:SL|STOP)\s+(\d+\.?\d*)\s+(?:TP|TAKE)\s+(\d+\.?\d*)',
                re.IGNORECASE
            ),
            
            # Format: XAUUSD BUY 3330 SL 3326 TP 3340
            re.compile(
                r'(' + symbols + r')\s+(BUY|SELL|LONG|SHORT)\s+(\d+\.?\d*)\s+(?:SL|STOP)\s+(\d+\.?\d*)\s+(?:TP|TAKE)\s+(\d+\.?\d*)',
                re.IGNORECASE
            ),
            
            # Universal format with TP1, TP2, SL
            re.compile(
                r'(' + symbols + r')\s+(BUY|SELL)\s+(?:NOW\s+)?(?:INSTANT\s+)?@?(\d+\.?\d*)[-\s]?(\d+\.?\d*)?\s+(?:Take\s+Profit\s*1|TP1)\s*[-:]\s*(\d+\.?\d*)\s+(?:Take\s+Profit\s*2|TP2)\s*[-:]\s*(\d+\.?\d*)\s+(?:Stoploss|SL)\s*[-:]\s*(\d+\.?\d*)',
                re.IGNORECASE
            ),
            
            # Alternative format: "BUY GOLD 3991.5 TP1 3997 TP2 4000 SL 3982"
            re.compile(
                r'(BUY|SELL)\s+(' + symbols + r')\s+@?(\d+\.?\d*)[-\s]?(\d+\.?\d*)?\s+(?:Take\s+Profit\s*1|TP1)\s*[-:]\s*(\d+\.?\d*)\s+(?:Take\s+Profit\s*2|TP2)\s*[-:]\s*(\d+\.?\d*)\s+(?:Stoploss|SL)\s*[-:]\s*(\d+\.?\d*)',
                re.IGNORECASE
            ),

            # SUPER FLEXIBLE: Ignore ANY text before BUY/SELL
            re.compile(
                r'.*?(BUY|SELL)\s+(?:Limit|Stop|Market)?\s*(' + symbols + r')\s*@?\s*(\d+\.?\d*)\s*(?:\([^)]*\))?\s*(?:TP\s*#?\s*1|TP1)\s*[:=]\s*(\d+\.?\d*)\s*(?:TP\s*#?\s*2|TP2)\s*[:=]\s*(\d+\.?\d*)\s*(?:-+\s*)?(?:SL|Stoploss)\s*[:=]\s*(\d+\.?\d*)\s*(?:\([^)]*\))?',
                re.IGNORECASE
            ),
            
            # SUPER FLEXIBLE: Same but with optional colons
            re.compile(
                r'.*?(BUY|SELL)\s+(?:Limit|Stop|Market)?\s*(' + symbols + r')\s*@?\s*(\d+\.?\d*)\s*(?:\([^)]*\))?\s*(?:TP\s*#?\s*1|TP1)\s*(?:[:=]\s*)?(\d+\.?\d*)\s*(?:TP\s*#?\s*2|TP2)\s*(?:[:=]\s*)?(\d+\.?\d*)\s*(?:-+\s*)?(?:SL|Stoploss)\s*(?:[:=]\s*)?(\d+\.?\d*)\s*(?:\([^)]*\))?',
                re.IGNORECASE
            ),
            
            # Format with "__" separator
            re.compile(
                r'.*?(BUY|SELL)\s+(?:Limit|Stop|Market)?\s*(' + symbols + r')\s*@?\s*(\d+\.?\d*)\s*(?:\([^)]*\))?\s*(?:TP\s*#?\s*1|TP1)\s*[:=]\s*(\d+\.?\d*)\s*(?:TP\s*#?\s*2|TP2)\s*[:=]\s*(\d+\.?\d*)\s*(?:_{2,}\s*)?(?:SL|Stoploss)\s*[:=]\s*(\d+\.?\d*)\s*(?:\([^)]*\))?',
                re.IGNORECASE
            ),

            # Action-first format: "Sell XAUUSD now@4062 Sl@4080 Tp1@4047 Tp2@4015"
            re.compile(
                r'.*?(BUY|SELL)\s*(' + symbols + r')\s*(?:now\s*)?@?(\d+\.?\d*)\s*(?:Sl@|SL\s*@?)\s*(\d+\.?\d*)\s*(?:Tp1@|TP1\s*@?)\s*(\d+\.?\d*)\s*(?:Tp2@|TP2\s*@?)\s*(\d+\.?\d*)',
                re.IGNORECASE
            ),

            # Symbol-first format: "XAUUSD Sell now@4062 Sl@4080 Tp1@4047 Tp2@4015"
            re.compile(
                r'.*?(' + symbols + r')\s+(BUY|SELL)\s*(?:now\s*)?@?(\d+\.?\d*)\s*(?:Sl@|SL\s*@?)\s*(\d+\.?\d*)\s*(?:Tp1@|TP1\s*@?)\s*(\d+\.?\d*)\s*(?:Tp2@|TP2\s*@?)\s*(\d+\.?\d*)',
                re.IGNORECASE
            ),
        ]

        return patterns