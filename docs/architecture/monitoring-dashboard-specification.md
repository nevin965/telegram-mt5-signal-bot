# Monitoring Dashboard Specification

## Rich Terminal Dashboard Layout

```
┌─────────────────── Signal EA Monitor v1.0 ───────────────────┐
│ Status: ● RUNNING  | Uptime: 5d 14h 23m | CPU: 12% | RAM: 823MB│
├──────────────────────────────────────────────────────────────┤
│ CONNECTIONS           │ SIGNALS              │ POSITIONS       │
│ Telegram: ● Connected │ Last: 2m ago         │ Open: 3         │
│ MT5: ● Connected      │ Today: 47            │ Today P/L: +$234│
│ OpenAI: ● Connected   │ Success: 98.2%       │ BE Applied: 12  │
├──────────────────────────────────────────────────────────────┤
│ QUEUES               │ PERFORMANCE                              │
│ Raw: 2               │ Parse Latency: 145ms                     │
│ Parsed: 0            │ Execution Latency: 892ms                 │
│ Priority: 1          │ Correlation Success: 96.4%               │
├──────────────────────────────────────────────────────────────┤
│ Recent Signals:                                                │
│ 14:23:15 [GOLD] BUY @ 2651.30 → Executed #5847291             │
│ 14:21:47 [GOLD] BREAK EVEN → Applied to #5847203              │
│ 14:19:33 [GOLD] CLOSE 50% → Partial close #5847156            │
└──────────────────────────────────────────────────────────────┘
```

## Implementation with Rich

```python