# Test Strategy and Standards

## Testing Philosophy

- **Approach:** Test-first for critical paths, test-after for utilities
- **Coverage Goals:** 80% overall, 95% for parser and correlation engine
- **Test Pyramid:** 60% unit, 30% integration, 10% end-to-end

## Test Types and Organization

### Unit Tests

- **Framework:** pytest 8.4.1
- **File Convention:** `test_{module_name}.py`
- **Location:** `tests/unit/`
- **Mocking Library:** unittest.mock + pytest-mock
- **Coverage Requirement:** 85% minimum

**AI Agent Requirements:**
- Generate tests for all public methods
- Cover edge cases and error conditions
- Follow AAA pattern (Arrange, Act, Assert)
- Mock all external dependencies

### Integration Tests

- **Scope:** Component interactions, database operations, queue flows
- **Location:** `tests/integration/`
- **Test Infrastructure:**
  - **Database:** In-memory SQLite for speed
  - **Telegram:** Mock Telethon client with replay fixtures
  - **MT5:** Mock MT5 module with position state machine
  - **OpenAI:** VCR.py for recording/replaying API calls

### End-to-End Tests

- **Framework:** pytest with asyncio
- **Scope:** Complete signal flow from Telegram to MT5 execution
- **Environment:** Docker compose with all services
- **Test Data:** Fixture files with real signal examples

## Test Data Management

- **Strategy:** Fixtures for deterministic tests, factories for dynamic data
- **Fixtures:** `tests/fixtures/` with JSON signal examples
- **Factories:** Factory pattern for creating test positions, signals
- **Cleanup:** Automatic cleanup after each test, no test pollution

## Continuous Testing

- **CI Integration:** GitHub Actions on every push: lint → unit → integration
- **Performance Tests:** Benchmark parsing speed, must handle 100 signals/second
- **Security Tests:** Bandit for security scanning, no hardcoded secrets check
