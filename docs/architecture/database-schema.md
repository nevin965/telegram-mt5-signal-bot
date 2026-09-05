# Database Schema

## Database Performance Strategy

### SQLite Performance Benchmarks

- **Write Performance Target:** 100 signals/second with WAL mode
- **Connection Pool:** 5 writers, 10 readers via SQLAlchemy
- **Optimization Settings:**
  ```sql
  PRAGMA journal_mode = WAL;
  PRAGMA synchronous = NORMAL;
  PRAGMA cache_size = -64000;  -- 64MB cache
  PRAGMA temp_store = MEMORY;
  PRAGMA mmap_size = 268435456;  -- 256MB memory-mapped I/O
  ```

### Load Testing Requirements

- **Benchmark Script:** `scripts/benchmark_db.py`
- **Test Scenarios:**
  - Sustained 50 msg/min for 1 hour
  - Burst of 200 messages in 1 minute
  - Concurrent reads during writes
  
### PostgreSQL Migration Path

- **Trigger Point:** If SQLite latency >100ms sustained
- **Migration Strategy:** 
  1. PostgreSQL as write master
  2. SQLite as read cache
  3. Async replication via triggers
- **Configuration Ready:** `config/postgres_fallback.yaml`

```sql
-- SQLite database schema with WAL mode for better concurrency
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;
PRAGMA foreign_keys = ON;

-- Signals table: Raw and parsed trading signals from Telegram
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_message_id INTEGER NOT NULL,
    telegram_chat_id INTEGER NOT NULL,
    sender VARCHAR(255) NOT NULL,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_text TEXT NOT NULL,
    parsed_action VARCHAR(20) CHECK(parsed_action IN ('BUY', 'SELL', 'CLOSE', 'MODIFY', 'BE')),
    symbol VARCHAR(20),
    entry_price DECIMAL(10, 5),
    stop_loss DECIMAL(10, 5),
    take_profit DECIMAL(10, 5),
    confidence_score REAL CHECK(confidence_score >= 0 AND confidence_score <= 1),
    parser_type VARCHAR(10) CHECK(parser_type IN ('REGEX', 'LLM')),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' 
        CHECK(status IN ('PENDING', 'VALIDATED', 'EXECUTED', 'REJECTED')),
    rejection_reason TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for signal queries
CREATE UNIQUE INDEX idx_signals_telegram_msg ON signals(telegram_message_id, telegram_chat_id);
CREATE INDEX idx_signals_status ON signals(status);
CREATE INDEX idx_signals_timestamp ON signals(timestamp);
CREATE INDEX idx_signals_symbol ON signals(symbol);

-- Positions table: MT5 trading positions linked to signals
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER REFERENCES signals(id) ON DELETE CASCADE,
    mt5_ticket INTEGER NOT NULL UNIQUE,
    open_time DATETIME NOT NULL,
    close_time DATETIME,
    symbol VARCHAR(20) NOT NULL,
    volume DECIMAL(10, 2) NOT NULL,
    open_price DECIMAL(10, 5) NOT NULL,
    close_price DECIMAL(10, 5),
    current_sl DECIMAL(10, 5),
    current_tp DECIMAL(10, 5),
    profit DECIMAL(10, 2),
    commission DECIMAL(10, 2),
    swap DECIMAL(10, 2),
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' 
        CHECK(status IN ('OPEN', 'CLOSED', 'PARTIAL')),
    last_sync DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for position queries
CREATE INDEX idx_positions_signal ON positions(signal_id);
CREATE INDEX idx_positions_ticket ON positions(mt5_ticket);
CREATE INDEX idx_positions_status ON positions(status);
CREATE INDEX idx_positions_open_time ON positions(open_time);

-- Position updates audit table
CREATE TABLE position_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    update_type VARCHAR(20) NOT NULL 
        CHECK(update_type IN ('BE', 'TP_MODIFY', 'SL_MODIFY', 'PARTIAL_CLOSE', 'MANUAL_MODIFY')),
    field_name VARCHAR(20),
    old_value DECIMAL(10, 5),
    new_value DECIMAL(10, 5),
    telegram_message_id INTEGER,
    success BOOLEAN NOT NULL DEFAULT 1,
    error_message TEXT,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index for position update queries
CREATE INDEX idx_position_updates_position ON position_updates(position_id);
CREATE INDEX idx_position_updates_timestamp ON position_updates(timestamp);

-- Message correlations for tracking reply chains
CREATE TABLE message_correlations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_message_id INTEGER NOT NULL,
    child_message_id INTEGER NOT NULL,
    correlation_type VARCHAR(20) NOT NULL 
        CHECK(correlation_type IN ('REPLY', 'TIME_BASED', 'CONTEXT', 'MANUAL')),
    correlation_confidence REAL CHECK(correlation_confidence >= 0 AND correlation_confidence <= 1),
    position_id INTEGER REFERENCES positions(id) ON DELETE SET NULL,
    correlation_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata JSON,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for correlation queries
CREATE UNIQUE INDEX idx_correlations_messages ON message_correlations(parent_message_id, child_message_id);
CREATE INDEX idx_correlations_position ON message_correlations(position_id);
CREATE INDEX idx_correlations_child ON message_correlations(child_message_id);

-- LLM cache table to reduce API costs
CREATE TABLE llm_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_hash VARCHAR(64) NOT NULL UNIQUE,
    raw_text TEXT NOT NULL,
    llm_response JSON NOT NULL,
    confidence_score REAL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL
);

-- Index for cache lookups
CREATE INDEX idx_llm_cache_hash ON llm_cache(message_hash);
CREATE INDEX idx_llm_cache_expires ON llm_cache(expires_at);

-- System health metrics table
CREATE TABLE health_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK(status IN ('HEALTHY', 'DEGRADED', 'FAILED')),
    telegram_connected BOOLEAN,
    mt5_connected BOOLEAN,
    messages_per_minute INTEGER,
    queue_size INTEGER,
    cpu_percent REAL,
    memory_mb INTEGER,
    error_count INTEGER DEFAULT 0,
    last_signal_time DATETIME,
    last_execution_time DATETIME,
    avg_latency_ms INTEGER,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index for health queries
CREATE INDEX idx_health_timestamp ON health_metrics(timestamp);
CREATE INDEX idx_health_component ON health_metrics(component, timestamp);

-- Configuration table for runtime settings
CREATE TABLE configuration (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Insert default configuration
INSERT INTO configuration (key, value, description) VALUES
    ('lot_size', '0.01', 'Default lot size for trades'),
    ('max_positions', '5', 'Maximum concurrent positions'),
    ('sl_default_pips', '50', 'Default stop loss in pips if not specified'),
    ('tp_default_pips', '100', 'Default take profit in pips if not specified'),
    ('be_offset_pips', '1', 'Pips to add for break even (prop firm requirement)'),
    ('correlation_window_minutes', '5', 'Time window for correlation matching'),
    ('llm_cache_hours', '24', 'Hours to cache LLM responses'),
    ('human_delay_min_ms', '1000', 'Minimum human-like delay in milliseconds'),
    ('human_delay_max_ms', '3000', 'Maximum human-like delay in milliseconds');

-- Triggers for updated_at timestamps
CREATE TRIGGER update_signals_timestamp 
    AFTER UPDATE ON signals
    BEGIN
        UPDATE signals SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

CREATE TRIGGER update_positions_timestamp
    AFTER UPDATE ON positions
    BEGIN
        UPDATE positions SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;

-- View for active positions with signal details
CREATE VIEW active_positions_view AS
SELECT 
    p.*,
    s.telegram_message_id,
    s.raw_text as signal_text,
    s.sender as signal_sender,
    s.confidence_score as signal_confidence
FROM positions p
JOIN signals s ON p.signal_id = s.id
WHERE p.status = 'OPEN';

-- View for daily statistics
CREATE VIEW daily_stats AS
SELECT 
    DATE(timestamp) as date,
    COUNT(DISTINCT CASE WHEN status = 'EXECUTED' THEN id END) as signals_executed,
    COUNT(DISTINCT CASE WHEN status = 'REJECTED' THEN id END) as signals_rejected,
    AVG(confidence_score) as avg_confidence,
    COUNT(DISTINCT CASE WHEN parser_type = 'LLM' THEN id END) as llm_parses,
    COUNT(DISTINCT CASE WHEN parser_type = 'REGEX' THEN id END) as regex_parses
FROM signals
GROUP BY DATE(timestamp);
```
