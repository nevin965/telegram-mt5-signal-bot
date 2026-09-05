# Source Tree

```plaintext
telegram-signal-ea/
├── .env.example                    # Environment variables template
├── .gitignore                      # Git ignore file
├── README.md                       # Project documentation
├── requirements.txt                # Python dependencies
├── setup.py                        # Package setup file
├── pyproject.toml                  # Modern Python project config
├── pytest.ini                      # Pytest configuration
├── .ruff.toml                      # Ruff linter configuration
├── mypy.ini                        # Type checking configuration
│
├── config/                         # Configuration files
│   ├── __init__.py
│   ├── settings.py                 # Settings management with pydantic
│   ├── logging_config.py           # Logging configuration
│   └── prompts/                    # LLM prompt templates
│       ├── signal_parser.txt       # gpt-5-mini parsing prompt
│       └── context_analyzer.txt    # Context correlation prompt
│
├── src/                            # Main source code
│   ├── __init__.py
│   │
│   ├── telegram_client/            # Telegram integration module
│   │   ├── __init__.py
│   │   ├── client.py               # Telethon client wrapper
│   │   ├── session_manager.py      # Session authentication
│   │   ├── message_handler.py      # Event handlers
│   │   └── rate_limiter.py         # Human-like delays
│   │
│   ├── signal_parser/              # Signal parsing module
│   │   ├── __init__.py
│   │   ├── parser.py               # Main parser orchestrator
│   │   ├── regex_parser.py         # Regex pattern matching
│   │   ├── llm_parser.py           # gpt-5-mini integration
│   │   ├── validator.py            # Signal validation
│   │   └── patterns.py             # French signal patterns
│   │
│   ├── mt5_executor/               # MT5 trading module
│   │   ├── __init__.py
│   │   ├── executor.py             # Order execution
│   │   ├── connection.py           # MT5 connection manager
│   │   ├── position_manager.py     # Position operations
│   │   └── symbol_specs.py         # GOLD specifications
│   │
│   ├── correlation_engine/         # Message correlation module
│   │   ├── __init__.py
│   │   ├── correlator.py           # Main correlation logic
│   │   ├── reply_tracer.py         # Reply chain analysis
│   │   └── time_matcher.py         # Time-based matching
│   │
│   ├── risk_manager/               # Risk management module
│   │   ├── __init__.py
│   │   ├── break_even.py           # BE automation
│   │   ├── position_modifier.py    # SL/TP modifications
│   │   └── risk_rules.py           # Risk validation
│   │
│   ├── database/                   # Database layer
│   │   ├── __init__.py
│   │   ├── models.py               # SQLAlchemy models
│   │   ├── repository.py           # Repository pattern
│   │   ├── migrations/             # Alembic migrations
│   │   │   ├── alembic.ini
│   │   │   ├── env.py
│   │   │   └── versions/
│   │   └── cache.py                # LLM response cache
│   │
│   ├── queue_manager/              # Queue management module
│   │   ├── __init__.py
│   │   ├── message_queue.py        # Async queue implementation
│   │   └── priority_queue.py       # Priority message handling
│   │
│   ├── monitoring/                 # Health and monitoring
│   │   ├── __init__.py
│   │   ├── health_checker.py       # Component health checks
│   │   ├── metrics_collector.py    # System metrics
│   │   ├── console_dashboard.py    # Rich console UI
│   │   └── alert_manager.py        # Error alerting
│   │
│   └── utils/                      # Utility functions
│       ├── __init__.py
│       ├── async_helpers.py        # Async utilities
│       ├── decorators.py           # Retry, circuit breaker
│       ├── formatters.py           # Price formatting
│       └── constants.py            # System constants
│
├── main.py                         # Application entry point
├── cli.py                          # CLI commands (start, stop, status)
│
├── tests/                          # Test suite
│   ├── __init__.py
│   ├── conftest.py                 # Pytest fixtures
│   │
│   ├── unit/                       # Unit tests
│   │   ├── test_regex_parser.py
│   │   ├── test_signal_validator.py
│   │   ├── test_correlator.py
│   │   ├── test_break_even.py
│   │   └── test_repository.py
│   │
│   ├── integration/                # Integration tests
│   │   ├── test_telegram_flow.py
│   │   ├── test_parsing_pipeline.py
│   │   ├── test_mt5_execution.py
│   │   └── test_correlation_flow.py
│   │
│   └── fixtures/                   # Test data
│       ├── sample_signals.json
│       ├── mock_positions.json
│       └── telegram_messages.txt
│
├── scripts/                        # Utility scripts
│   ├── setup_session.py            # Initialize Telegram session
│   ├── test_mt5_connection.py      # Verify MT5 connectivity
│   ├── migrate_database.py         # Run migrations
│   └── export_stats.py             # Export trading statistics
│
├── logs/                           # Log files (gitignored)
│   ├── app.log
│   ├── error.log
│   └── trades.log
│
├── data/                           # Data directory (gitignored)
│   ├── signal_ea.db                # SQLite database
│   └── telegram.session            # Telethon session file
│
└── docs/                           # Documentation
    ├── architecture.md             # This document
    ├── prd.md                      # Product requirements
    ├── deployment.md               # Deployment guide
    └── api_examples.md             # External API examples
```
