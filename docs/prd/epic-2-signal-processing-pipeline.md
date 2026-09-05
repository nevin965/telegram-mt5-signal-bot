# Epic 2: Signal Processing Pipeline

**Goal:** Implement a robust signal parsing system that can handle both standard French trading signals using regex patterns and complex contextual messages using gpt-5-mini. This epic transforms raw Telegram messages into structured, actionable trading signals ready for execution.

## Story 2.1: Regex-Based Signal Parser for Standard Formats
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

## Story 2.2: GPT-5-Mini Integration for Contextual Parsing
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

## Story 2.3: Signal Validation and Deduplication
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

## Story 2.4: Signal Queue and Pipeline Management
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
