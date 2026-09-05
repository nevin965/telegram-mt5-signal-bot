-- SQLite Database Schema for Telegram Signal EA
-- Performance optimizations
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;  -- 64MB cache
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;  -- 256MB memory-mapped I/O
PRAGMA foreign_keys = ON;

-- Configuration table
CREATE TABLE IF NOT EXISTS configuration (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Signals table - Primary signal storage
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_message_id INTEGER NOT NULL UNIQUE,
    telegram_chat_id INTEGER NOT NULL,
    sender TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    raw_text TEXT NOT NULL,
    parsed_action TEXT NOT NULL CHECK (parsed_action IN ('BUY', 'SELL', 'CLOSE', 'PARTIAL_CLOSE', 'MODIFY_SL', 'MODIFY_TP')),
    symbol TEXT NOT NULL,
    entry_price REAL,
    stop_loss REAL,
    take_profit REAL,
    confidence_score REAL DEFAULT 0.0 CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    parser_type TEXT NOT NULL CHECK (parser_type IN ('REGEX', 'LLM', 'HYBRID')),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'VALIDATED', 'EXECUTED', 'REJECTED', 'EXPIRED')),
    rejection_reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Positions table - MT5 position tracking
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    mt5_ticket INTEGER UNIQUE,
    open_time DATETIME,
    close_time DATETIME,
    open_price REAL,
    close_price REAL,
    volume REAL NOT NULL,
    current_sl REAL,
    current_tp REAL,
    profit REAL DEFAULT 0.0,
    commission REAL DEFAULT 0.0,
    swap REAL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED', 'CANCELLED', 'EXPIRED')),
    last_sync DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (signal_id) REFERENCES signals (id) ON DELETE CASCADE
);

-- Position updates table - Audit trail for position modifications
CREATE TABLE IF NOT EXISTS position_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    update_type TEXT NOT NULL CHECK (update_type IN ('SL_MODIFY', 'TP_MODIFY', 'PARTIAL_CLOSE', 'FULL_CLOSE', 'BREAK_EVEN')),
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    telegram_message_id INTEGER,
    success BOOLEAN NOT NULL DEFAULT 0,
    error_message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (position_id) REFERENCES positions (id) ON DELETE CASCADE
);

-- Message correlations table - Parent-child message linking
CREATE TABLE IF NOT EXISTS message_correlations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_message_id INTEGER NOT NULL,
    child_message_id INTEGER NOT NULL,
    correlation_type TEXT NOT NULL CHECK (correlation_type IN ('REPLY', 'EDIT', 'FOLLOWUP', 'CANCEL')),
    correlation_confidence REAL DEFAULT 1.0 CHECK (correlation_confidence >= 0.0 AND correlation_confidence <= 1.0),
    correlation_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    position_id INTEGER,
    metadata TEXT, -- JSON for additional correlation data
    FOREIGN KEY (position_id) REFERENCES positions (id) ON DELETE SET NULL
);

-- LLM cache table - Response caching to reduce API costs
CREATE TABLE IF NOT EXISTS llm_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_hash TEXT NOT NULL UNIQUE,
    prompt_type TEXT NOT NULL,
    raw_message TEXT NOT NULL,
    parsed_response TEXT NOT NULL,
    confidence_score REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL
);

-- Health metrics table - System monitoring data
CREATE TABLE IF NOT EXISTS health_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('HEALTHY', 'WARNING', 'CRITICAL')),
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT -- JSON for additional metric data
);

-- Indexes for performance optimization
-- Signals table indexes
CREATE INDEX IF NOT EXISTS idx_signals_telegram_message_id ON signals (telegram_message_id);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals (status);
CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals (timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals (symbol);
CREATE INDEX IF NOT EXISTS idx_signals_chat_id ON signals (telegram_chat_id);

-- Positions table indexes
CREATE INDEX IF NOT EXISTS idx_positions_mt5_ticket ON positions (mt5_ticket);
CREATE INDEX IF NOT EXISTS idx_positions_signal_id ON positions (signal_id);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions (status);
CREATE INDEX IF NOT EXISTS idx_positions_open_time ON positions (open_time);

-- Position updates table indexes
CREATE INDEX IF NOT EXISTS idx_position_updates_position_id ON position_updates (position_id);
CREATE INDEX IF NOT EXISTS idx_position_updates_timestamp ON position_updates (timestamp);
CREATE INDEX IF NOT EXISTS idx_position_updates_telegram_message_id ON position_updates (telegram_message_id);

-- Message correlations table indexes
CREATE INDEX IF NOT EXISTS idx_message_correlations_parent ON message_correlations (parent_message_id);
CREATE INDEX IF NOT EXISTS idx_message_correlations_child ON message_correlations (child_message_id);
CREATE INDEX IF NOT EXISTS idx_message_correlations_position_id ON message_correlations (position_id);

-- LLM cache indexes
CREATE INDEX IF NOT EXISTS idx_llm_cache_input_hash ON llm_cache (input_hash);
CREATE INDEX IF NOT EXISTS idx_llm_cache_expires_at ON llm_cache (expires_at);

-- Health metrics indexes
CREATE INDEX IF NOT EXISTS idx_health_metrics_component ON health_metrics (component);
CREATE INDEX IF NOT EXISTS idx_health_metrics_timestamp ON health_metrics (timestamp);

-- Views for common queries
-- Active positions view
CREATE VIEW IF NOT EXISTS active_positions AS
SELECT 
    p.*,
    s.symbol,
    s.parsed_action,
    s.telegram_message_id
FROM positions p
JOIN signals s ON p.signal_id = s.id
WHERE p.status = 'OPEN';

-- Daily stats view
CREATE VIEW IF NOT EXISTS daily_stats AS
SELECT 
    DATE(p.close_time) as trade_date,
    COUNT(*) as total_trades,
    SUM(CASE WHEN p.profit > 0 THEN 1 ELSE 0 END) as winning_trades,
    SUM(CASE WHEN p.profit < 0 THEN 1 ELSE 0 END) as losing_trades,
    SUM(p.profit) as total_profit,
    AVG(p.profit) as avg_profit,
    MAX(p.profit) as max_profit,
    MIN(p.profit) as min_profit
FROM positions p
WHERE p.status = 'CLOSED' AND p.close_time IS NOT NULL
GROUP BY DATE(p.close_time)
ORDER BY trade_date DESC;

-- Insert default configuration values
INSERT OR IGNORE INTO configuration (key, value, description) VALUES
    ('max_concurrent_positions', '5', 'Maximum number of concurrent open positions'),
    ('default_risk_percent', '2.0', 'Default risk percentage per trade'),
    ('break_even_threshold', '10', 'Pips in profit to trigger break-even'),
    ('llm_cache_expiry_hours', '24', 'Hours before LLM cache entries expire'),
    ('position_sync_interval', '30', 'Seconds between position synchronization'),
    ('max_signal_age_minutes', '60', 'Maximum age of signals before expiry');

-- Trigger to update timestamps
CREATE TRIGGER IF NOT EXISTS update_signals_timestamp 
    AFTER UPDATE ON signals
    FOR EACH ROW
BEGIN
    UPDATE signals SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_positions_timestamp 
    AFTER UPDATE ON positions
    FOR EACH ROW
BEGIN
    UPDATE positions SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_configuration_timestamp 
    AFTER UPDATE ON configuration
    FOR EACH ROW
BEGIN
    UPDATE configuration SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Trigger to cleanup expired LLM cache entries
CREATE TRIGGER IF NOT EXISTS cleanup_expired_llm_cache
    AFTER INSERT ON llm_cache
    FOR EACH ROW
BEGIN
    DELETE FROM llm_cache WHERE expires_at < CURRENT_TIMESTAMP;
END;