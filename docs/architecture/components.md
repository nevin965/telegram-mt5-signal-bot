# Components

## Telegram Client Component

**Responsibility:** Manages Telethon user session, connects to Telegram groups, receives messages with human-like behavior patterns to avoid detection

**Key Interfaces:**
- `connect_session(phone: str, api_id: int, api_hash: str)` - Initialize user session
- `subscribe_to_groups(group_ids: List[str])` - Monitor specified groups
- `on_new_message` - Event emitter for incoming messages
- `get_message_context(message_id: int)` - Retrieve parent/reply chain

**Dependencies:** None (entry point component)

**Technology Stack:** Telethon 1.40.0, asyncio event handlers, session persistence via .session files

---

## Message Queue Manager

**Responsibility:** Buffers incoming messages, manages processing pipeline queues, handles overflow and prioritization

**Key Interfaces:**
- `enqueue_raw_message(message: TelegramMessage)` - Add to raw queue
- `get_next_for_parsing()` - Retrieve for processing
- `prioritize_message(message_id: int)` - Move to priority queue
- `get_queue_stats()` - Monitor queue health

**Dependencies:** Telegram Client (producer)

**Technology Stack:** asyncio.Queue (3 queues: raw, parsed, validated), priority queue for BREAK EVEN/CLOSE messages

---

## Signal Parser Component

**Responsibility:** Transforms raw French text into structured trading signals using hybrid regex/LLM approach

**Key Interfaces:**
- `parse_signal(text: str) -> ParsedSignal` - Main parsing interface
- `try_regex_parse(text: str) -> Optional[ParsedSignal]` - Fast path
- `try_llm_parse(text: str, context: str) -> ParsedSignal` - Fallback
- `validate_signal(signal: ParsedSignal) -> ValidationResult` - Sanity checks

**Dependencies:** Message Queue Manager (consumer), OpenAI Client (for LLM)

**Technology Stack:** Python re module for regex, openai SDK 1.99.1 for gpt-5-mini, caching layer for duplicate LLM calls

---

## Correlation Engine

**Responsibility:** Links update messages (BREAK EVEN, CLOSE) to their parent positions using reply chains and time-based matching

**Key Interfaces:**
- `correlate_message(message: TelegramMessage) -> Optional[Position]` - Find target position
- `trace_reply_chain(message_id: int) -> Optional[int]` - Follow replies to original
- `time_based_match(text: str, window_minutes: int) -> List[Position]` - Fallback correlation
- `store_correlation(parent_id: int, child_id: int, type: str)` - Persist correlation

**Dependencies:** Signal Parser, Database Repository, Telegram Client (for reply chains)

**Technology Stack:** SQLAlchemy 2.0.43 for queries, asyncio for concurrent correlation attempts

---

## MT5 Executor Component

**Responsibility:** Executes validated signals on MetaTrader 5, manages order lifecycle, handles errors and retries

**Key Interfaces:**
- `connect_mt5(login: str, password: str, server: str)` - Initialize connection
- `execute_market_order(signal: ValidatedSignal) -> MT5Result` - Place trade
- `modify_position(ticket: int, sl: float, tp: float) -> MT5Result` - Update position
- `close_position(ticket: int, volume: float) -> MT5Result` - Close trade

**Dependencies:** Signal Parser (validated signals), Position Monitor (sync)

**Technology Stack:** MetaTrader5 5.0.5200 package, connection pooling, exponential backoff for retries

---

## Position Monitor

**Responsibility:** Synchronizes MT5 positions with database, detects manual changes, maintains position registry

**Key Interfaces:**
- `sync_positions()` - Poll MT5 and update database
- `get_open_positions() -> List[Position]` - Current positions
- `detect_discrepancies() -> List[Discrepancy]` - Find mismatches
- `register_position(signal_id: int, ticket: int)` - Link signal to position

**Dependencies:** MT5 Executor, Database Repository

**Technology Stack:** APScheduler 3.10.4 for periodic sync, in-memory position cache for fast lookups

---

## Risk Manager

**Responsibility:** Implements break-even automation, processes position modifications, enforces risk rules

**Key Interfaces:**
- `process_break_even(position: Position)` - Move SL to entry +1 pip
- `calculate_break_even_price(entry: float, symbol: str) -> float` - Broker-specific calculation
- `validate_modification(position: Position, new_sl: float, new_tp: float) -> bool` - Risk checks
- `emergency_close_all()` - Panic button

**Dependencies:** Correlation Engine (for update signals), MT5 Executor (for modifications)

**Technology Stack:** Custom risk logic, broker pip specifications, idempotency checks

---

## Database Repository

**Responsibility:** Provides async data access layer, manages transactions, handles migrations

**Key Interfaces:**
- `save_signal(signal: Signal) -> int` - Persist parsed signal
- `get_position_by_ticket(ticket: int) -> Optional[Position]` - Query position
- `update_position_status(position_id: int, status: str)` - Status changes
- `get_recent_signals(minutes: int) -> List[Signal]` - Time-window queries

**Dependencies:** All components use this for persistence

**Technology Stack:** SQLAlchemy 2.0.43 with async support, aiosqlite 0.20.0, Alembic for migrations

---

## Health Monitor

**Responsibility:** Monitors system health, logs metrics, provides console dashboard, alerts on failures

**Key Interfaces:**
- `check_telegram_connection() -> HealthStatus` - Verify Telegram connected
- `check_mt5_connection() -> HealthStatus` - Verify MT5 connected
- `get_system_metrics() -> SystemMetrics` - CPU, RAM, queue sizes
- `alert_on_failure(component: str, error: str)` - Error notifications

**Dependencies:** All components register health checks

**Technology Stack:** Python logging with RotatingFileHandler, rich library for console UI, system metrics via psutil
