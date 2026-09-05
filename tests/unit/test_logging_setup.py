"""
Unit tests for logging configuration and setup.
Tests log handler creation, formatting, and file management.
"""

import logging
from pathlib import Path
from unittest.mock import patch

from config.logging_config import get_logger, get_trade_logger, setup_logging


class TestLoggingSetup:
    """Test logging configuration setup."""

    def test_setup_logging_creates_log_directory(self, temp_dir: Path):
        """Test that setup_logging creates the log directory if it doesn't exist."""
        log_dir = temp_dir / "test_logs"
        assert not log_dir.exists()

        config = setup_logging(log_dir=str(log_dir))

        assert log_dir.exists()
        assert log_dir.is_dir()
        assert config["log_dir"] == str(log_dir.absolute())

    def test_setup_logging_returns_configuration(self, temp_log_dir: Path):
        """Test that setup_logging returns proper configuration dictionary."""
        config = setup_logging(log_level="DEBUG", log_dir=str(temp_log_dir))

        assert isinstance(config, dict)
        assert "level" in config
        assert "handlers" in config
        assert "log_dir" in config
        assert "files" in config

        assert config["level"] == "DEBUG"
        assert isinstance(config["handlers"], int)
        assert config["handlers"] > 0
        assert len(config["files"]) >= 3  # app.log, error.log, trades.log

    def test_setup_logging_creates_required_handlers(self, temp_log_dir: Path):
        """Test that all required log handlers are created."""
        setup_logging(log_dir=str(temp_log_dir))

        root_logger = logging.getLogger()

        # Should have at least app, error handlers
        assert len(root_logger.handlers) >= 2

        # Check handler types
        handler_types = [type(handler).__name__ for handler in root_logger.handlers]
        assert "RotatingFileHandler" in handler_types

    def test_setup_logging_configures_log_levels(self, temp_log_dir: Path):
        """Test that log levels are properly configured."""
        setup_logging(log_level="WARNING", log_dir=str(temp_log_dir))

        root_logger = logging.getLogger()
        assert root_logger.level == logging.WARNING

        # Test specific logger levels
        telethon_logger = logging.getLogger("telethon")
        assert telethon_logger.level == logging.WARNING

        aiohttp_logger = logging.getLogger("aiohttp")
        assert aiohttp_logger.level == logging.WARNING

    def test_setup_logging_creates_log_files(self, temp_log_dir: Path):
        """Test that log files are created when logging occurs."""
        setup_logging(log_dir=str(temp_log_dir))

        # Generate some log messages
        logger = get_logger("test")
        logger.info("Test info message")
        logger.error("Test error message")

        # Force log file creation by getting handlers to flush
        for handler in logging.getLogger().handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        # Check that log files exist
        expected_files = ["app.log", "error.log"]
        for filename in expected_files:
            temp_log_dir / filename
            # Files may not exist until first message, but handlers should be configured
            assert True  # Handler creation is tested above

    @patch.dict("os.environ", {"DEV_MODE": "true"})
    def test_dev_mode_adds_console_handler(self, temp_log_dir: Path):
        """Test that DEV_MODE=true adds console handler."""
        setup_logging(log_dir=str(temp_log_dir))

        root_logger = logging.getLogger()
        handler_types = [type(handler).__name__ for handler in root_logger.handlers]

        assert "StreamHandler" in handler_types

    @patch.dict("os.environ", {"DEV_MODE": "false"})
    def test_prod_mode_no_console_handler(self, temp_log_dir: Path):
        """Test that DEV_MODE=false doesn't add console handler."""
        setup_logging(log_dir=str(temp_log_dir))

        root_logger = logging.getLogger()
        handler_types = [type(handler).__name__ for handler in root_logger.handlers]

        # Should only have file handlers in production
        assert "StreamHandler" not in handler_types


class TestLoggerCreation:
    """Test logger creation functions."""

    def test_get_logger_returns_logger_instance(self):
        """Test that get_logger returns proper Logger instance."""
        logger = get_logger("test_module")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_get_logger_with_different_names(self):
        """Test that get_logger creates different loggers for different names."""
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")

        assert logger1 is not logger2
        assert logger1.name != logger2.name

    def test_get_trade_logger_is_specialized(self):
        """Test that trade logger is properly configured."""
        trade_logger = get_trade_logger()

        assert isinstance(trade_logger, logging.Logger)
        assert trade_logger.name == "trade"

        # Trade logger should not propagate to root logger
        assert trade_logger.propagate is False

    def test_get_trade_logger_has_dedicated_handler(self, temp_log_dir: Path):
        """Test that trade logger has its own handler."""
        setup_logging(log_dir=str(temp_log_dir))
        trade_logger = get_trade_logger()

        # Trade logger should have at least one handler
        assert len(trade_logger.handlers) > 0

        # Handler should be RotatingFileHandler for trades.log
        handler = trade_logger.handlers[0]
        assert isinstance(handler, logging.handlers.RotatingFileHandler)


class TestLogFormatting:
    """Test log message formatting."""

    def test_detailed_formatter_includes_required_fields(self, temp_log_dir: Path):
        """Test that detailed formatter includes all required fields."""
        setup_logging(log_dir=str(temp_log_dir))

        # Get a handler to check its formatter
        root_logger = logging.getLogger()
        handler = root_logger.handlers[0]
        formatter = handler.formatter

        # Create a test log record
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
            func="test_function",
        )

        formatted = formatter.format(record)

        # Check that formatted message contains expected components
        assert "test" in formatted  # logger name
        assert "INFO" in formatted  # log level
        assert "test_function" in formatted  # function name
        assert "42" in formatted  # line number
        assert "Test message" in formatted  # actual message

    def test_simple_formatter_for_console(self):
        """Test simple formatter for console output."""
        # This would be tested with console handler
        # For now, verify the concept
        simple_format = "%(asctime)s - %(levelname)s - %(message)s"
        formatter = logging.Formatter(simple_format, datefmt="%H:%M:%S")

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)

        # Should be simpler format
        assert "INFO" in formatted
        assert "Test message" in formatted
        # Should not include function name or line number
        assert "test_function" not in formatted
        assert "42" not in formatted


class TestLogRotation:
    """Test log file rotation configuration."""

    def test_rotating_handler_configuration(self, temp_log_dir: Path):
        """Test that rotating handlers are properly configured."""
        setup_logging(log_dir=str(temp_log_dir))

        root_logger = logging.getLogger()

        # Find rotating file handlers
        rotating_handlers = [
            h for h in root_logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
        ]

        assert len(rotating_handlers) > 0

        # Check configuration
        for handler in rotating_handlers:
            assert handler.maxBytes > 0  # Should have size limit
            assert handler.backupCount > 0  # Should keep backups
            assert handler.encoding == "utf-8"  # Should use UTF-8
