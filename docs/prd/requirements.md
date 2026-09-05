# Requirements

## Functional Requirements

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

## Non-Functional Requirements

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
