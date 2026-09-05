# Security

## Input Validation

- **Validation Library:** Pydantic for data models
- **Validation Location:** At component boundaries before processing
- **Required Rules:**
  - All external inputs MUST be validated
  - Validation at API boundary before processing
  - Whitelist approach preferred over blacklist

## Authentication & Authorization

- **Auth Method:** Environment variables for credentials, keyring for sensitive data
- **Session Management:** Telethon session files with restricted permissions (600)
- **Required Patterns:**
  - Never commit credentials to repository
  - Rotate API keys monthly
  - Use separate accounts for dev/prod

## Secrets Management

- **Development:** .env file (never committed), python-dotenv
- **Production:** Environment variables injected via Docker
- **Code Requirements:**
  - NEVER hardcode secrets
  - Access via configuration service only
  - No secrets in logs or error messages

## API Security

- **Rate Limiting:** Respect all API rate limits, exponential backoff
- **CORS Policy:** N/A (no web interface)
- **Security Headers:** N/A (no HTTP endpoints)
- **HTTPS Enforcement:** All external APIs use HTTPS

## Data Protection

- **Encryption at Rest:** Filesystem encryption on VPS
- **Encryption in Transit:** TLS for all API communications
- **PII Handling:** Hash Telegram usernames, no storage of phone numbers
- **Logging Restrictions:** Never log: passwords, API keys, session tokens, full signal text with usernames

## Dependency Security

- **Scanning Tool:** pip-audit + safety
- **Update Policy:** Monthly security updates, quarterly feature updates
- **Approval Process:** Test all updates in staging for 24 hours

## Security Testing

- **SAST Tool:** Bandit for Python code scanning
- **DAST Tool:** N/A (no web interface)
- **Penetration Testing:** Annual review of Telegram session security
