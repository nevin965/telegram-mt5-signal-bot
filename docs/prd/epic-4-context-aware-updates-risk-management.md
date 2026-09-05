# Epic 4: Context-Aware Updates & Risk Management

**Goal:** Implement intelligent message correlation to handle contextual updates like "BREAK EVEN" and "CLÔTUREZ", automate stop-loss adjustments to entry +1 pip for prop firm compliance, and ensure all position modifications are correctly linked to their parent signals. This epic completes the MVP with sophisticated risk management.

## Story 4.1: Message Reply Correlation Engine
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

## Story 4.2: Break Even Automation with 1-Pip Adjustment
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

## Story 4.3: Close and Partial Close Processing
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

## Story 4.4: Update Message Context Analysis with GPT-5-Mini
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

## Story 4.5: Risk Management Dashboard and Alerts
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
