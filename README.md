# Telegram-to-MT5 Signal Bot

Automated Telegram signal parser and MetaTrader 5 trade execution engine with context-aware risk management, built for real-time gold/forex signal channels.

## ⚠️ Disclaimer

This project automates the execution of trading signals on a live or demo trading account. Trading forex, gold, and other leveraged instruments carries a high risk of financial loss. This software is provided for educational purposes only, comes with **no warranty**, and the author accepts no responsibility for any trading losses incurred while using it. Always test on a demo account first.

## Overview

This system monitors Telegram channels for trading signals (primarily GOLD/XAUUSD), parses them using a combination of regex pattern matching and LLM validation, correlates related messages over time (entries, exits, modifications), and executes and manages the resulting trades on MetaTrader 5 automatically.

## Features

- **Signal Processing** — real-time Telegram message monitoring with dual-stage parsing (regex + LLM fallback)
- **Context Correlation** — links related messages (entries, exits, SL/TP modifications) across time, even when they arrive as separate messages
- **MT5 Integration** — automated trade execution with live position management
- **Risk Management** — break-even automation, SL/TP modifications, position sizing by account risk %
- **Monitoring** — health checks, metrics collection, and a console dashboard

## Tech Stack

Python 3.12 · Telethon (Telegram) · MetaTrader5 Python API · OpenAI API (signal validation) · SQLite (aiosqlite) · pytest

## Requirements

- Python 3.12.7 or higher
- MetaTrader5 terminal (Windows, or Wine on Linux/macOS)
- A Telegram API ID/hash ([my.telegram.org](https://my.telegram.org))
- An OpenAI API key (used for LLM-assisted signal parsing)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/telegram-mt5-signal-bot.git
cd telegram-mt5-signal-bot
```

### 2. Create a virtual environment

```bash
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
# then edit .env with your own credentials
```

Required environment variables:

| Variable | Description |
|---|---|
| `TELEGRAM_API_ID` | Your Telegram API ID |
| `TELEGRAM_API_HASH` | Your Telegram API hash |
| `PHONE_NUMBER` | Your phone number, with country code |
| `OPENAI_API_KEY` | Your OpenAI API key |
| `MT5_LOGIN` | MetaTrader 5 account login |
| `MT5_PASSWORD` | MetaTrader 5 account password |
| `MT5_SERVER` | MetaTrader 5 broker server name |

**Never commit your `.env` file.** It's already excluded via `.gitignore` — keep it that way.

### 5. Set up the Telegram session

```bash
python scripts/setup_session.py
```

This prompts for phone verification and creates a local session file (also gitignored).

### 6. Test the MT5 connection

```bash
python scripts/test_mt5_connection.py
```

## Usage

```bash
python main.py
# or, via the CLI:
python cli.py start
python cli.py status
python cli.py stop
```

## Project Structure

```
telegram-mt5-signal-bot/
├── src/
│   ├── telegram_client/    # Telegram integration
│   ├── signal_parser/      # Signal parsing logic (regex + LLM)
│   ├── mt5_executor/       # MT5 trade execution
│   ├── correlation_engine/ # Cross-message correlation
│   ├── risk_manager/       # Position sizing & risk rules
│   └── database/           # Data persistence
├── config/                 # App & LLM configuration
├── tests/                  # Unit + integration test suite
├── scripts/                 # Setup & maintenance utilities
├── docs/                   # Architecture & product docs
├── main.py                 # Application entry point
└── cli.py                  # CLI interface
```

## Development

```bash
# Run all tests
pytest

# Unit tests only
pytest tests/unit/

# With coverage
pytest --cov=src

# Format & lint
black src/ tests/
ruff check src/ tests/
mypy src/
```

## Configuration Notes

- Logs are written to `logs/app.log`, `logs/error.log`, and `logs/trades.log` (rotating, gitignored).
- Key trading parameters (`DEFAULT_RISK_PERCENT`, `DEFAULT_SL_PIPS`, `DEFAULT_TP_PIPS`, `BREAK_EVEN_TRIGGER_PIPS`) are set in `.env`.
- Rate limits for Telegram and the LLM provider are also configurable in `.env`.

## Security

- `.env`, `*.session` files, and the local database are all gitignored — never commit them.
- Credentials are read exclusively from environment variables at runtime.
- Telegram sessions are encrypted by Telethon.

## License

Released under the [MIT License](LICENSE).
