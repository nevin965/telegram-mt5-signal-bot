# Tech Stack

## Cloud Infrastructure

- **Provider:** Local/On-Premise initially, VPS-ready
- **Key Services:** N/A for MVP (self-hosted)
- **Deployment Regions:** Europe (when moving to VPS)

## Technology Stack Table

| Category | Technology | Version | Purpose | Rationale |
|----------|-----------|---------|---------|-----------|
| **Language** | Python | 3.12.7 | Primary development language | LTS version, stable, excellent asyncio support |
| **Async Runtime** | asyncio | Built-in | Concurrent I/O operations | Native Python async, no additional dependencies |
| **Telegram Client** | Telethon | 1.40.0 | MTProto client library | User session support, mature, well-documented |
| **Trading Platform** | MetaTrader5 | 5.0.5200 | MT5 Python integration | Official package, stable API |
| **Database** | SQLite | 3.45.0 | Persistent storage | Simple, file-based, sufficient for MVP load |
| **Async DB** | aiosqlite | 0.20.0 | Async SQLite operations | Non-blocking database access |
| **ORM/Query Builder** | SQLAlchemy | 2.0.43 | Database abstraction | Latest 2.0 series, async support, migration management |
| **LLM Integration** | openai | 1.99.1 | gpt-5-mini API client | Official SDK, very active development |
| **Configuration** | python-dotenv | 1.0.1 | Environment management | Simple, secure credential handling |
| **Logging** | Python logging | Built-in | Application logging | Standard, rotating file handlers included |
| **Testing** | pytest | 8.4.1 | Unit/integration testing | Powerful fixtures, async support |
| **Test Doubles** | pytest-asyncio | 0.25.0 | Async test support | Seamless async testing |
| **Mocking** | unittest.mock | Built-in | Test doubles | Standard library, no deps |
| **Type Checking** | mypy | 1.13.0 | Static type analysis | Catch errors early, better IDE support |
| **Code Formatting** | black | 24.10.0 | Code style enforcement | Consistent formatting |
| **Linting** | ruff | 0.8.4 | Fast Python linter | Replaces flake8/pylint, much faster |
| **Task Queue** | asyncio.Queue | Built-in | In-memory message queuing | Simple, sufficient for MVP |
| **Scheduling** | APScheduler | 3.10.4 | Periodic tasks | Position sync, health checks |
| **JSON Parsing** | orjson | 3.10.12 | Fast JSON operations | 3x faster than standard json |
| **Datetime** | pendulum | 3.0.0 | Timezone-aware dates | Better timezone handling for global markets |
| **HTTP Client** | aiohttp | 3.11.11 | Async HTTP for webhooks | If needed for monitoring endpoints |
| **Process Manager** | supervisor | 4.2.5 | Process monitoring | Auto-restart on crashes (Linux/VPS) |
