# Data Models

## Signal Model

**Purpose:** Represents raw trading signals extracted from Telegram messages

**Key Attributes:**
- id: Integer (Primary Key) - Unique identifier
- telegram_message_id: Integer - Original Telegram message ID for correlation
- telegram_chat_id: Integer - Source chat/group ID
- sender: String - Username/ID of signal sender
- timestamp: DateTime - When message was received
- raw_text: Text - Original message content
- parsed_action: Enum(BUY/SELL/CLOSE/MODIFY) - Interpreted trading action
- symbol: String - Trading instrument (GOLD/XAUUSD/OR)
- entry_price: Decimal - Entry price for trade
- stop_loss: Decimal (nullable) - Stop loss level
- take_profit: Decimal (nullable) - Take profit level
- confidence_score: Float - Parser confidence (0.0-1.0)
- parser_type: Enum(REGEX/LLM) - Which parser succeeded
- status: Enum(PENDING/VALIDATED/EXECUTED/REJECTED) - Processing status

**Relationships:**
- Has one Position (when executed)
- Has many MessageCorrelations (for updates)

## Position Model

**Purpose:** Tracks active and historical MT5 trading positions

**Key Attributes:**
- id: Integer (Primary Key) - Unique identifier
- signal_id: Integer (Foreign Key) - Link to originating signal
- mt5_ticket: Integer - MT5 position ticket number
- open_time: DateTime - Position open timestamp
- close_time: DateTime (nullable) - Position close timestamp
- open_price: Decimal - Actual execution price
- close_price: Decimal (nullable) - Close price if closed
- volume: Decimal - Position size/lots
- current_sl: Decimal - Current stop loss (can be modified)
- current_tp: Decimal - Current take profit (can be modified)
- profit: Decimal (nullable) - Realized P&L when closed
- status: Enum(OPEN/CLOSED/PARTIAL) - Position status
- last_sync: DateTime - Last MT5 synchronization

**Relationships:**
- Belongs to one Signal
- Has many PositionUpdates
- Has many MessageCorrelations

## PositionUpdate Model

**Purpose:** Audit trail of all position modifications

**Key Attributes:**
- id: Integer (Primary Key) - Unique identifier
- position_id: Integer (Foreign Key) - Parent position
- update_type: Enum(BE/TP_MODIFY/SL_MODIFY/PARTIAL_CLOSE) - Type of update
- old_value: Decimal - Previous value (SL/TP/Volume)
- new_value: Decimal - New value after update
- telegram_message_id: Integer (nullable) - Triggering message if applicable
- timestamp: DateTime - When update occurred
- success: Boolean - Whether MT5 update succeeded
- error_message: Text (nullable) - Error details if failed

**Relationships:**
- Belongs to one Position
- May reference MessageCorrelation

## MessageCorrelation Model

**Purpose:** Links Telegram reply chains for contextual updates

**Key Attributes:**
- id: Integer (Primary Key) - Unique identifier
- parent_message_id: Integer - Original signal message ID
- child_message_id: Integer - Update/reply message ID
- correlation_type: Enum(REPLY/TIME_BASED/CONTEXT) - How correlation was determined
- correlation_confidence: Float - Confidence score (0.0-1.0)
- correlation_time: DateTime - When correlation was established
- position_id: Integer (nullable, Foreign Key) - Linked position if found

**Relationships:**
- May belong to one Position
- Links two Signals (parent-child)
