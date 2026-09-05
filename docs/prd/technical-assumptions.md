# Technical Assumptions

## Repository Structure: **Monorepo**
Alle Komponenten in einem einzigen Repository für einfache Entwicklung und Deployment

## Service Architecture: **Monolith**
Single Python application mit async Pipeline-Architektur - kein Overengineering für MVP

## Testing Requirements: **Unit + Integration Tests**
- Unit tests für Parser, Signal-Logik, Correlation-Engine
- Integration tests für Telegram→Parser→MT5 Pipeline
- Mock-Tests für API Calls (OpenAI, MT5)

## Additional Technical Assumptions and Requests

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
