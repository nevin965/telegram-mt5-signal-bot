# Telegram Rate Limiting Strategy

## Human Behavior Simulation

- **Message Reading Delays:** Gaussian distribution with μ=2000ms, σ=500ms
- **Typing Indicators:** Random 5% chance to show "typing" before reading
- **Read Receipts:** Mark as read after 70% of delay period
- **Session Patterns:**
  - Active hours: 8:00-23:00 local time (higher activity)
  - Night hours: 23:00-8:00 (reduced activity, longer delays)
  - Weekend variation: 20% slower response times
  
## Anti-Detection Measures

- **Daily Limits:** Max 1000 messages/day per session
- **Burst Protection:** Max 10 messages/minute sustained
- **Error Handling:** On flood_wait error, pause for error.seconds * 1.5
- **Session Rotation:** If 3 flood errors in 1 hour, switch to backup session

## Implementation Pattern

```python
import random
import asyncio
from datetime import datetime

async def human_like_delay():
    base_delay = random.gauss(2000, 500)
    time_factor = get_time_of_day_factor()  # 0.5-1.5 based on hour
    final_delay = max(1000, min(5000, base_delay * time_factor))
    await asyncio.sleep(final_delay / 1000)

def get_time_of_day_factor():
    hour = datetime.now().hour
    if 8 <= hour < 23:  # Active hours
        return 1.0
    else:  # Night hours
        return 1.5
```

## MetaTrader 5 Server API

- **Purpose:** Execute trades, modify positions, and synchronize trading state
- **Documentation:** https://www.mql5.com/en/docs/python_metatrader5
- **Base URL(s):** Broker-specific server addresses (e.g., "MetaQuotes-Demo")
- **Authentication:** Login number + password + server name
- **Rate Limits:** No official limits but implement 100ms minimum between requests

**Key Endpoints Used:**
- `mt5.initialize()` - Connect to terminal
- `mt5.order_send()` - Execute market orders
- `mt5.positions_get()` - Retrieve open positions
- `mt5.position_modify()` - Update SL/TP levels
- `mt5.order_close()` - Close positions

**Integration Notes:**
- MT5 terminal must be running on same machine (Windows) or Wine (Linux)
- Connection drops frequently - implement automatic reconnection
- All prices must be normalized to broker's tick size for GOLD
- Symbol name varies by broker: GOLD vs XAUUSD vs GOLD.pro
- Implement connection pool for concurrent operations
- Cache symbol specifications on startup
