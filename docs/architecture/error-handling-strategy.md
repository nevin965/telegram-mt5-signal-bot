# Error Handling Strategy

## General Approach

- **Error Model:** Exception hierarchy with specific error types for each component
- **Exception Hierarchy:** BaseEAException → ComponentException → SpecificError
- **Error Propagation:** Bubble up with context, handle at component boundaries

## Logging Standards

- **Library:** Python logging (built-in)
- **Format:** JSON structured logs: `{"timestamp": "ISO8601", "level": "ERROR", "component": "str", "message": "str", "context": {}}`
- **Levels:** DEBUG (dev only), INFO (operations), WARNING (degraded), ERROR (failures), CRITICAL (system down)
- **Required Context:**
  - Correlation ID: UUID per signal lifecycle
  - Service Context: Component name, method, line number
  - User Context: Telegram sender (hashed), signal group

## Error Handling Patterns

### External API Errors

- **Retry Policy:** Exponential backoff: 1s, 2s, 4s, 8s, then circuit break
- **Circuit Breaker:** Open after 5 consecutive failures, half-open after 30s
- **Timeout Configuration:** Telegram: 30s, OpenAI: 60s, MT5: 10s
- **Error Translation:** Map external errors to internal error codes for consistent handling

### Business Logic Errors

- **Custom Exceptions:** SignalParseError, PositionNotFoundError, InsufficientMarginError, CorrelationAmbiguousError
- **User-Facing Errors:** Not applicable (headless system) - all errors logged
- **Error Codes:** PARSE_001 through EXEC_999 for categorization

### Data Consistency

- **Transaction Strategy:** Atomic operations with rollback on failure
- **Compensation Logic:** Reverse partially completed operations (e.g., cancel order if DB save fails)
- **Idempotency:** Message deduplication by hash, position modification checks current state first
