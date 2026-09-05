# Next Steps

## UX Expert Prompt
*Not applicable - This is a headless CLI-only automation system without user interface requirements.*

## Architect Prompt
Please create the technical architecture for the Telegram Trading Signal EA based on the attached PRD. Focus on: (1) Async pipeline design using Python asyncio for Telegram→Parser→MT5 flow, (2) Telethon session management with human-like rate limiting to avoid detection, (3) SQLite schema design for signals, positions, and message correlations, (4) Queue architecture to handle 50+ messages/minute without signal loss, (5) Error recovery patterns with exponential backoff, and (6) Integration approach for gpt-5-mini contextual parsing. Prioritize reliability and account safety over speed. The architecture must support 24/5 operation with automatic recovery from disconnections.