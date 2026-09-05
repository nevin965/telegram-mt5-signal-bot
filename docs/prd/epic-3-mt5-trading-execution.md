# Epic 3: MT5 Trading Execution

**Goal:** Connect to MetaTrader 5, execute validated trading signals with proper position management, and establish SQLite database persistence for tracking all positions and their correlation to Telegram signals. This epic delivers the core trading functionality.

## Story 3.1: MT5 Connection and Authentication
**As a** trader,  
**I want** the system to connect to my MT5 account,  
**so that** automated trading can be executed.

**Acceptance Criteria:**
1. MetaTrader5 Python package connects using login credentials from environment variables
2. Connection validates account type, balance, and trading permissions on startup
3. Verifies GOLD/XAUUSD symbol is available and gets symbol specifications (pip size, min lot)
4. Implements connection pool with automatic reconnection on disconnect
5. Terminal info logged: broker, account number, leverage, balance, margin
6. Graceful error handling for invalid credentials or terminal not running

## Story 3.2: SQLite Database Schema and Repository Layer
**As a** system operator,  
**I want** persistent storage of signals and positions,  
**so that** the system can recover from restarts and track history.

**Acceptance Criteria:**
1. SQLite database created with schema: signals, positions, position_updates, message_correlations tables
2. Signals table: id, telegram_message_id, sender, timestamp, raw_text, parsed_action, symbol, entry, sl, tp, status
3. Positions table: id, signal_id, mt5_ticket, open_time, close_time, open_price, close_price, profit, status
4. Message_correlations table: parent_message_id, child_message_id, correlation_type, correlation_time
5. Async repository pattern using aiosqlite for all database operations
6. Database migrations setup for future schema changes
7. Indexes on frequently queried fields: telegram_message_id, mt5_ticket, status

## Story 3.3: Order Execution Engine
**As a** trader,  
**I want** validated signals to be executed as MT5 orders,  
**so that** trades are placed automatically within 2 seconds.

**Acceptance Criteria:**
1. Converts parsed signals to MT5 order requests with proper lot sizing from config
2. Executes market orders for BUY/SELL with slippage tolerance (max 5 pips)
3. Sets stop-loss and take-profit according to signal or default values if missing
4. Stores successful trades in positions table with MT5 ticket number
5. Links position to original signal via signal_id foreign key
6. Handles execution errors: insufficient margin, market closed, invalid stops
7. Execution latency tracked and logged (target <2 seconds signal to execution)

## Story 3.4: Position Monitoring and Synchronization
**As a** trader,  
**I want** open positions to be tracked and synchronized,  
**so that** the system knows current trading state at all times.

**Acceptance Criteria:**
1. Polls MT5 every 5 seconds for open positions and updates database
2. Detects positions closed manually and updates database status
3. Reconciles database positions with MT5 positions on startup
4. Handles partial closes and updates position size in database
5. Tracks position modifications: SL/TP changes logged to position_updates table
6. Alerts on position discrepancies between database and MT5
7. Maintains position registry in memory for fast correlation lookups
