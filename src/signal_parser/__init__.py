"""Signal parser module for regex and LLM-based signal parsing."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class ParsedAction(Enum):
    """Supported trading actions."""
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"
    MODIFY = "MODIFY"


@dataclass
class ParsedSignal:
    """Structured signal object from parsing operations."""
    id: int | None = None
    telegram_message_id: int = 0
    telegram_chat_id: int = 0
    sender: str = ""  # Hashed for privacy
    timestamp: datetime | None = None
    raw_text: str = ""
    parsed_action: ParsedAction = ParsedAction.BUY
    symbol: str = ""  # GOLD/XAUUSD/OR normalized
    entry_price: Decimal = Decimal("0.0")
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    confidence_score: float = 0.0  # 0.95 for regex parser
    parser_type: str = "REGEX"
    status: str = "PENDING"

    def __post_init__(self) -> None:
        """Initialize timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class ValidationResult:
    """Result from signal validation operations."""
    is_valid: bool
    errors: list[str]
    warnings: list[str] | None = None

    def __post_init__(self) -> None:
        """Initialize warnings list if not provided."""
        if self.warnings is None:
            self.warnings = []
