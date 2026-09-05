# External APIs

## OpenAI API (gpt-5-mini)

- **Purpose:** Contextual interpretation of complex French trading messages that don't match regex patterns
- **Documentation:** https://platform.openai.com/docs/api-reference
- **Base URL(s):** https://api.openai.com/v1
- **Authentication:** Bearer token via API key from environment variable OPENAI_API_KEY
- **Rate Limits:** 100 requests/minute for gpt-5-mini tier (monitor for upgrades)

**Key Endpoints Used:**
- `POST /chat/completions` - Send French message with context for interpretation

**Integration Notes:** 
- Implement response caching for identical messages to reduce costs
- Use structured output format with JSON mode for consistent parsing
- Include system prompt specifically trained on French trading terminology
- Fallback to regex if API unavailable or rate limited
- Expected cost: ~€30-40/month at 50+ messages/minute with 20% LLM usage

## Telegram MTProto API

- **Purpose:** Real-time message reception from trading signal groups using user account
- **Documentation:** https://core.telegram.org/mtproto
- **Base URL(s):** Variable based on DC assignment (handled by Telethon)
- **Authentication:** Phone number + SMS code verification, session persisted
- **Rate Limits:** Unofficial - maintain 1-3 second delays between operations

**Key Endpoints Used:**
- MTProto layer 160+ via Telethon abstractions
- `messages.getHistory` - Retrieve message history on startup
- `messages.getMessages` - Fetch specific messages by ID
- Event handlers for real-time new message updates

**Integration Notes:**
- Must use user account (not bot) for group access without admin privileges
- Implement human-like delays: random 1-3 seconds between reads
- Handle DC migrations transparently via Telethon
- Store session file securely, never commit to repository
- Monitor for flood wait errors and implement exponential backoff
