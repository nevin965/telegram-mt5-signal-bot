# Telegram Trading Signal EA Product Requirements Document (PRD)

## Goals and Background Context

### Goals
• Achieve 100% automated execution of French GOLD trading signals from Telegram groups within 2 seconds
• Enable 24/5 unattended trading operation across all market sessions without manual intervention  
• Implement intelligent context-aware signal correlation for updates like "BREAK EVEN" and "CLÔTUREZ"
• Automate stop-loss adjustments to entry +1 pip for proper risk management and prop firm compliance
• Maintain accurate position tracking through SQLite database that persists across system restarts
• Process text-based signals using gpt-5-mini for French language understanding and context interpretation
• Ensure zero missed signals due to system failures with automatic recovery mechanisms
• Keep operational costs under €50/month while maintaining reliable API service usage

### Background Context

This PRD addresses the critical execution gap faced by traders following French-language Telegram signal groups, where manual monitoring causes 30-60 second delays resulting in 5-20 pip slippage on volatile GOLD trades. The system leverages a hybrid approach combining regex pattern matching for standard signals and gpt-5-mini for contextual interpretation of French trading terminology and reply patterns. Unlike existing solutions like TSCopier that fail with French signals and contextual updates, this EA treats signal groups as conversations, maintaining message correlation to correctly match updates like "BREAK EVEN +30" to their parent positions even with multiple open trades.

### Change Log

| Date | Version | Description | Author |
|------|---------|-------------|---------|
| 2024-12-11 | 1.0 | Initial PRD creation based on Project Brief | John (PM) |

## Requirements

### Functional Requirements

**FR1:** The system shall monitor specified Telegram groups using a user account via Telethon/Pyrogram MTProto API (read-only access, no bot required)

**FR2:** The system shall read text messages directly from Telegram groups using user session authentication (phone number + code)

**FR3:** The system shall parse standard French trading signals using regex patterns (e.g., "JE BUY GOLD 3362")

**FR4:** The system shall interpret contextual updates using gpt-5-mini for messages like "BREAK EVEN", "CLÔTUREZ", and reply-based correlations

**FR5:** The system shall execute BUY/SELL orders on MT5 with specified stop-loss and take-profit levels via Python API

**FR6:** The system shall automatically adjust stop-loss to entry price +1 pip when "BREAK EVEN" messages are detected

**FR7:** The system shall maintain message-to-position correlation using SQLite database with signals, positions, position_updates, and message_correlations tables

**FR8:** The system shall process position modifications including close, partial close, and TP/SL adjustments from reply messages

**FR9:** The system shall log all signals, executions, errors, and correlations to files for debugging and audit purposes

**FR10:** The system shall automatically recover from Telegram or MT5 disconnections within 60 seconds

**FR11:** The system shall track and link Telegram message IDs to MT5 position tickets for accurate update correlation

**FR12:** The system shall handle simultaneous multiple GOLD positions without correlation conflicts

### Non-Functional Requirements

**NFR1:** Signal-to-execution latency shall not exceed 2 seconds from message receipt to MT5 order placement

**NFR2:** The system shall maintain 99% uptime during market hours (Sunday 22:00 - Friday 22:00 GMT)

**NFR3:** RAM usage shall not exceed 512MB under normal operation with 50+ messages per minute

**NFR4:** CPU usage shall remain under 10% on average during standard signal processing

**NFR5:** The system shall achieve 100% accuracy in correlating update messages to their parent positions

**NFR6:** API costs shall not exceed €50/month total for OpenAI services

**NFR7:** The system shall handle peak loads of 50+ messages per minute without degradation

**NFR8:** SQLite database operations shall complete within 100ms for inserts and queries

**NFR9:** The system shall implement human-like reading behavior to avoid detection (no aggressive polling, natural delays, read receipts handling)

**NFR10:** All credentials shall be stored securely using python-dotenv and keyring libraries

**NFR11:** The system shall provide console output for real-time monitoring of operations in CLI mode

**NFR12:** Error recovery mechanisms shall trigger within 5 seconds of failure detection

**NFR13:** The system shall use only user account authentication without requiring admin privileges or bot access to groups

## Technical Assumptions

### Repository Structure: **Monorepo**
Alle Komponenten in einem einzigen Repository für einfache Entwicklung und Deployment

### Service Architecture: **Monolith**
Single Python application mit async Pipeline-Architektur - kein Overengineering für MVP

### Testing Requirements: **Unit + Integration Tests**
- Unit tests für Parser, Signal-Logik, Correlation-Engine
- Integration tests für Telegram→Parser→MT5 Pipeline
- Mock-Tests für API Calls (OpenAI, MT5)

### Additional Technical Assumptions and Requests

• **Telegram Access:** Telethon mit User Session (Telefonnummer-Auth), KEIN Bot API, read-only Zugriff
• **Nachrichtenverarbeitung:** Direkte Text-Extraktion aus Telegram, KEINE OCR/Screenshots benötigt  
• **LLM Integration:** gpt-5-mini für französische Kontext-Interpretation
• **Datenbank:** SQLite von Anfang an für Persistenz (signals, positions, position_updates, message_correlations)
• **Async Architecture:** Python asyncio für gesamte Pipeline
• **Deployment:** Initial lokal auf Windows, später VPS-fähig
• **Message Correlation:** Via Telegram message_id und reply_to_message_id
• **Rate Limiting:** Human-like delays (1-3 Sekunden zwischen Reads) um Account-Ban zu vermeiden
• **Error Recovery:** Exponential backoff bei Verbindungsfehlern
• **Logging:** Strukturiertes Logging mit Python logging module + File rotation

## Epic List

**Epic 1: Foundation & Telegram Integration**
*Establish project infrastructure, Telegram user session connection, and basic message reading with health monitoring*

**Epic 2: Signal Processing Pipeline** 
*Implement French signal parsing with regex patterns and gpt-5-mini contextual interpretation*

**Epic 3: MT5 Trading Execution**
*Connect to MT5, execute trades from parsed signals, and implement position tracking with SQLite*

**Epic 4: Context-Aware Updates & Risk Management**
*Handle BREAK EVEN, CLÔTUREZ, and reply-based correlations with stop-loss automation*

## Epic 1: Foundation & Telegram Integration

**Goal:** Establish the foundational project infrastructure with Telegram user session authentication, implement real-time message reading from signal groups, and create a basic monitoring system to verify continuous operation. This epic delivers immediate value by proving we can reliably read signals without bot access.

### Story 1.1: Project Setup and Configuration Management
**As a** developer,  
**I want** a properly structured Python project with dependency management,  
**so that** the codebase is maintainable and deployable.

**Acceptance Criteria:**
1. Python 3.10+ project structure created with /telegram_client, /signal_parser, /mt5_executor, /models, /database modules
2. Requirements.txt includes telethon, python-dotenv, aiofiles, and core dependencies
3. .env.example template created with TELEGRAM_API_ID, TELEGRAM_API_HASH, PHONE_NUMBER placeholders
4. Git repository initialized with .gitignore excluding .env, *.session, and sensitive files
5. Basic logging configuration established with rotating file handler
6. README.md documents setup process and environment requirements

### Story 1.2: Telegram User Session Authentication
**As a** trader,  
**I want** to authenticate my Telegram user account,  
**so that** the system can read messages from my signal groups.

**Acceptance Criteria:**
1. Telethon client initializes with API credentials from environment variables
2. Phone number authentication flow completes with SMS/code verification
3. Session file (.session) persists authentication for future runs
4. Graceful handling of authentication errors with clear user prompts
5. Session validation on startup to confirm active connection

### Story 1.3: Signal Group Message Monitoring
**As a** trader,  
**I want** the system to continuously monitor my signal groups,  
**so that** no trading signals are missed.

**Acceptance Criteria:**
1. System connects to specified Telegram groups by username/ID from config
2. New messages are captured in real-time using Telethon event handlers
3. Message metadata extracted: sender, timestamp, message_id, reply_to_message_id, text content
4. Console output shows received messages with timestamp for monitoring
5. Implements 1-3 second human-like delays between operations to avoid detection
6. Automatic reconnection within 60 seconds if connection drops

### Story 1.4: Health Monitoring and Logging System
**As a** system operator,  
**I want** comprehensive logging and health checks,  
**so that** I can verify the system is running correctly.

**Acceptance Criteria:**
1. Health check runs every 60 seconds confirming Telegram connection
2. Structured logging captures all messages, errors, and system events
3. Log rotation prevents disk space issues (max 100MB per file, 5 file rotation)
4. Console dashboard shows: connection status, messages/minute, last signal time, uptime
5. Error alerts logged with ERROR level for connection failures or exceptions
6. Graceful shutdown handler saves state and closes connections properly

## Epic 2: Signal Processing Pipeline

**Goal:** Implement a robust signal parsing system that can handle both standard French trading signals using regex patterns and complex contextual messages using gpt-5-mini. This epic transforms raw Telegram messages into structured, actionable trading signals ready for execution.

### Story 2.1: Regex-Based Signal Parser for Standard Formats
**As a** trader,  
**I want** standard French trading signals to be parsed instantly,  
**so that** common signal formats are processed without AI overhead.

**Acceptance Criteria:**
1. Regex patterns match standard formats: "JE BUY GOLD 3362", "BUY GOLD @ 3362", "ACHETER OR 3362"
2. Parser extracts: action (BUY/SELL), instrument (GOLD/XAUUSD/OR), entry price, SL, TP when present
3. Handles variations: "JE VEND", "SELL", "SHORT", "VENDRE" for sell signals
4. Validates extracted values: prices must be realistic GOLD ranges (3000-4000), SL/TP logic verified
5. Returns structured signal object: {action, symbol, entry, sl, tp, original_message, confidence_score}
6. Logs all parse attempts with success/failure reasons for debugging

### Story 2.2: GPT-5-Mini Integration for Contextual Parsing
**As a** trader,  
**I want** complex French messages to be understood contextually,  
**so that** updates and non-standard signals are correctly interpreted.

**Acceptance Criteria:**
1. OpenAI client configured with gpt-5-mini model and API key from environment
2. Prompt engineering template specifically for French trading signals context
3. System sends messages that don't match regex patterns to gpt-5-mini
4. LLM response parsed into same structured format as regex parser
5. Rate limiting implemented to stay within API quotas (max 100 requests/minute)
6. Fallback handling when API is unavailable or returns errors
7. Response caching for identical messages to reduce API costs

### Story 2.3: Signal Validation and Deduplication
**As a** trader,  
**I want** signals to be validated and duplicates prevented,  
**so that** only legitimate, unique trades are executed.

**Acceptance Criteria:**
1. Validation checks: price within 5% of current market, SL not too close/far from entry
2. Duplicate detection using hash of (symbol, action, entry±2 pips) within 60-second window
3. Edit detection: if message_id exists with edit flag, update rather than duplicate
4. Signal confidence scoring: regex=0.95, gpt-5-mini=0.80, adjusted by validation results
5. Rejected signals logged with specific reason for analysis
6. Manual override list for trusted signal providers (always accept if from whitelist)

### Story 2.4: Signal Queue and Pipeline Management
**As a** system operator,  
**I want** signals to be processed in order with proper queuing,  
**so that** high message volumes don't cause missed signals.

**Acceptance Criteria:**
1. Async queue implementation using asyncio.Queue for signal pipeline
2. Separate queues: raw_messages → parsed_signals → validated_signals
3. Pipeline stages run concurrently: reading, parsing, validation
4. Queue monitoring: size, processing rate, average latency displayed
5. Overflow handling: alert if queue exceeds 100 messages (potential bottleneck)
6. Graceful degradation: if parser fails, message requeued with exponential backoff
7. Signal priority: "CLÔTUREZ" and "BREAK EVEN" get priority processing

## Epic 3: MT5 Trading Execution

**Goal:** Connect to MetaTrader 5, execute validated trading signals with proper position management, and establish SQLite database persistence for tracking all positions and their correlation to Telegram signals. This epic delivers the core trading functionality.

### Story 3.1: MT5 Connection and Authentication
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

### Story 3.2: SQLite Database Schema and Repository Layer
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

### Story 3.3: Order Execution Engine
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

### Story 3.4: Position Monitoring and Synchronization
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

## Epic 4: Context-Aware Updates & Risk Management

**Goal:** Implement intelligent message correlation to handle contextual updates like "BREAK EVEN" and "CLÔTUREZ", automate stop-loss adjustments to entry +1 pip for prop firm compliance, and ensure all position modifications are correctly linked to their parent signals. This epic completes the MVP with sophisticated risk management.

### Story 4.1: Message Reply Correlation Engine
**As a** trader,  
**I want** reply messages to be correctly linked to original signals,  
**so that** updates like "BREAK EVEN" affect the right position.

**Acceptance Criteria:**
1. Detects Telegram messages with reply_to_message_id field and retrieves parent message
2. Queries database to find position associated with parent message's telegram_message_id
3. Handles multi-level replies (reply to a reply) by traversing chain to original signal
4. Stores correlation in message_correlations table with relationship type
5. Processes orphaned updates (no reply_to) using time-based matching within 5-minute window
6. Prioritizes exact reply correlation over time-based matching (confidence scores)
7. Logs all correlation attempts with success/failure reasons for debugging

### Story 4.2: Break Even Automation with 1-Pip Adjustment
**As a** trader,  
**I want** stop-loss to automatically move to entry +1 pip on "BREAK EVEN" signals,  
**so that** trades are protected with proper prop firm compliance.

**Acceptance Criteria:**
1. Recognizes "BREAK EVEN" variations: "BE", "BREAK", "SL ON ENTRY", "SECURE", "SÉCURISER"
2. Identifies target position using reply correlation or context matching from Story 4.1
3. Calculates entry price +1 pip based on broker's pip specifications for GOLD
4. Sends MT5 position modify request to update stop-loss only (preserves take-profit)
5. Updates position_updates table with modification details and timestamp
6. Validates SL moved successfully and alerts if modification fails
7. Prevents duplicate BE updates on same position (idempotency check)

### Story 4.3: Close and Partial Close Processing
**As a** trader,  
**I want** "CLÔTUREZ" and partial close messages to execute immediately,  
**so that** profits are secured when signaled.

**Acceptance Criteria:**
1. Recognizes close signals: "CLÔTUREZ", "CLOSE", "FERMEZ", "TP HIT", "STOP"
2. Detects partial close patterns: "CLOSE 50%", "FERMEZ MOITIÉ", "PARTIAL TP"
3. Uses correlation engine to identify target position(s)
4. Executes MT5 close order for full or calculated partial volume
5. Updates positions table with close_time, close_price, final profit
6. Handles "CLOSE ALL GOLD" for multiple position closures
7. Confirms closure success and logs any failures with retry mechanism

### Story 4.4: Update Message Context Analysis with GPT-5-Mini
**As a** trader,  
**I want** complex update messages to be understood contextually,  
**so that** non-standard modifications are handled correctly.

**Acceptance Criteria:**
1. Sends ambiguous update messages to gpt-5-mini with conversation context
2. Prompt includes: current message, parent message, open positions list
3. LLM returns structured update intent: {action: "breakeven|close|modify", target_position, parameters}
4. Confidence threshold of 0.75 required for automatic execution
5. Low confidence updates logged for manual review without execution
6. Caches LLM interpretations for similar messages to reduce API calls
7. Falls back to rule-based parsing if API unavailable

### Story 4.5: Risk Management Dashboard and Alerts
**As a** trader,  
**I want** real-time visibility of risk management actions,  
**so that** I can verify the system is protecting my positions.

**Acceptance Criteria:**
1. Console dashboard shows: open positions, recent BE adjustments, pending updates
2. Alerts for critical events: BE failed, position not found, correlation uncertain
3. Daily summary: total BE adjustments, closes executed, positions protected
4. Risk metrics displayed: positions without SL, positions past BE point
5. Update history queryable: last 10 modifications per position
6. Emergency stop command: "STOP ALL" in console halts trading
7. Correlation success rate tracked and displayed (target >95%)

## Checklist Results Report

### Executive Summary
- **Overall PRD Completeness:** 92%
- **MVP Scope Appropriateness:** Just Right  
- **Readiness for Architecture Phase:** Ready
- **Critical Gaps:** UI/UX section appropriately skipped for CLI-only system

### Category Validation
All categories PASS except UI/UX (N/A for headless system) and Technical Guidance (PARTIAL - needs Telethon rate limit research)

### Key Strengths
- Clear problem definition with quantified impact (5-20 pip slippage)
- Well-scoped MVP focused on single asset (GOLD)
- Comprehensive epic structure with logical sequencing
- Strong correlation strategy for contextual updates

### Areas for Investigation
- Telethon rate limiting best practices to avoid account ban
- gpt-5-mini prompt optimization for French trading context
- SQLite performance validation at 50+ messages/minute
- Broker-specific pip calculations for GOLD

### Decision
**READY FOR ARCHITECT** - PRD is comprehensive and implementation-ready

## Next Steps

### UX Expert Prompt
*Not applicable - This is a headless CLI-only automation system without user interface requirements.*

### Architect Prompt
Please create the technical architecture for the Telegram Trading Signal EA based on the attached PRD. Focus on: (1) Async pipeline design using Python asyncio for Telegram→Parser→MT5 flow, (2) Telethon session management with human-like rate limiting to avoid detection, (3) SQLite schema design for signals, positions, and message correlations, (4) Queue architecture to handle 50+ messages/minute without signal loss, (5) Error recovery patterns with exponential backoff, and (6) Integration approach for gpt-5-mini contextual parsing. Prioritize reliability and account safety over speed. The architecture must support 24/5 operation with automatic recovery from disconnections.