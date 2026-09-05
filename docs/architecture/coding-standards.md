# Coding Standards

## Core Standards

- **Languages & Runtimes:** Python 3.12.7, asyncio for all I/O operations
- **Style & Linting:** black (line length 100), ruff with default rules
- **Test Organization:** `tests/unit/test_{module}.py`, `tests/integration/test_{feature}_flow.py`

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Classes | PascalCase | `SignalParser`, `TelegramClient` |
| Functions | snake_case | `parse_signal()`, `execute_trade()` |
| Constants | UPPER_SNAKE | `MAX_RETRIES`, `DEFAULT_SL_PIPS` |
| Private methods | Leading underscore | `_validate_price()` |
| Async functions | Prefix with snake_case | `async def process_message()` |

## Critical Rules

- **Never use print() for output - use logger:** All output must go through logging system for proper rotation and levels
- **All external API calls must use circuit breaker decorator:** Prevents cascade failures and respects rate limits
- **Database operations must use repository pattern:** Never direct SQLAlchemy queries outside repository class
- **All prices must be normalized to broker pip size:** Use `normalize_price()` utility before MT5 operations
- **Telegram operations must include human delays:** Use `rate_limiter.human_delay()` between all Telegram API calls
- **Never log sensitive data:** Hash telegram usernames, never log API keys or passwords
- **All async functions must handle cancellation:** Use `try/finally` to cleanup resources on task cancel
