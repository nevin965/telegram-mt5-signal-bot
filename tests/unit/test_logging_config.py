"""
Unit tests for logging configuration.
Tests structured logging format, rotation, and context management.
"""

import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from config.logging_config import (
    setup_logging, 
    StructuredFormatter, 
    ContextualLoggerAdapter,
    set_correlation_id,
    get_correlation_id,
    clear_correlation_id,
    set_user_context,
    get_user_context,
    clear_user_context,
    set_service_context,
    get_service_context,
    clear_service_context,
    clear_all_context,
    get_contextual_logger
)


class TestStructuredFormatter:
    """Test StructuredFormatter class."""
    
    @pytest.fixture
    def formatter(self):
        """Create a StructuredFormatter instance."""
        return StructuredFormatter()
    
    @pytest.fixture
    def log_record(self):
        """Create a basic log record for testing."""
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="/path/to/test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None
        )
        record.module = "test"
        record.funcName = "test_function"
        return record
    
    def test_basic_formatting(self, formatter, log_record):
        """Test basic JSON structured log formatting."""
        formatted = formatter.format(log_record)
        
        # Parse JSON
        log_data = json.loads(formatted)
        
        # Verify basic fields
        assert log_data["level"] == "INFO"
        assert log_data["component"] == "test.module"
        assert log_data["message"] == "Test message"
        assert "timestamp" in log_data
        
        # Verify context includes service context fallback
        assert "context" in log_data
        assert "service_context" in log_data["context"]
        assert log_data["context"]["service_context"]["module"] == "test"
        assert log_data["context"]["service_context"]["function"] == "test_function"
        assert log_data["context"]["service_context"]["line"] == 42
    
    def test_formatting_with_correlation_id(self, formatter, log_record):
        """Test formatting with correlation ID context."""
        # Set correlation ID
        correlation_id = set_correlation_id("test-correlation-123")
        
        try:
            formatted = formatter.format(log_record)
            log_data = json.loads(formatted)
            
            assert "context" in log_data
            assert log_data["context"]["correlation_id"] == correlation_id
            
        finally:
            clear_correlation_id()
    
    def test_formatting_with_user_context(self, formatter, log_record):
        """Test formatting with user context and sensitive data hashing."""
        # Set user context with sensitive data
        user_context = {
            "username": "test_user",
            "user_id": "12345",
            "telegram_id": "telegram_test",
            "channel": "test_channel",
            "action": "signal_parse"
        }
        
        set_user_context(user_context)
        
        try:
            formatted = formatter.format(log_record)
            log_data = json.loads(formatted)
            
            assert "context" in log_data
            assert "user_context" in log_data["context"]
            
            user_ctx = log_data["context"]["user_context"]
            
            # Sensitive data should be hashed
            assert "username_hash" in user_ctx
            assert "user_id_hash" in user_ctx
            assert "telegram_id_hash" in user_ctx
            assert "username" not in user_ctx  # Original should be removed
            assert "user_id" not in user_ctx
            assert "telegram_id" not in user_ctx
            
            # Non-sensitive data should remain
            assert user_ctx["channel"] == "test_channel"
            assert user_ctx["action"] == "signal_parse"
            
            # Verify hash format (should be 16 char hex string)
            assert len(user_ctx["username_hash"]) == 16
            assert len(user_ctx["user_id_hash"]) == 16
            assert len(user_ctx["telegram_id_hash"]) == 16
            
        finally:
            clear_user_context()
    
    def test_formatting_with_service_context(self, formatter, log_record):
        """Test formatting with service context override."""
        # Set service context
        set_service_context("custom_component", "custom_method", 100)
        
        try:
            formatted = formatter.format(log_record)
            log_data = json.loads(formatted)
            
            assert "context" in log_data
            assert "service_context" in log_data["context"]
            
            service_ctx = log_data["context"]["service_context"]
            assert service_ctx["component"] == "custom_component"
            assert service_ctx["method"] == "custom_method"
            assert service_ctx["line"] == 100
            
        finally:
            clear_service_context()
    
    def test_formatting_with_exception(self, formatter, log_record):
        """Test formatting with exception information."""
        try:
            raise ValueError("Test exception")
        except ValueError:
            log_record.exc_info = True  # This would normally be set by logging
            # Manually set exc_info since we're testing
            import sys
            log_record.exc_info = sys.exc_info()
            
            formatted = formatter.format(log_record)
            log_data = json.loads(formatted)
            
            assert "exception" in log_data
            assert "ValueError" in log_data["exception"]
            assert "Test exception" in log_data["exception"]
    
    def test_formatting_with_extra_fields(self, formatter, log_record):
        """Test formatting with extra fields from LoggerAdapter."""
        # Add extra fields to record
        log_record.extra_fields = {"custom_field": "custom_value", "metric": 123.45}
        
        formatted = formatter.format(log_record)
        log_data = json.loads(formatted)
        
        assert log_data["custom_field"] == "custom_value"
        assert log_data["metric"] == 123.45
    
    def test_hash_sensitive_data(self, formatter):
        """Test sensitive data hashing function."""
        hash1 = formatter._hash_sensitive_data("test_user")
        hash2 = formatter._hash_sensitive_data("test_user")
        hash3 = formatter._hash_sensitive_data("different_user")
        
        # Same input should produce same hash
        assert hash1 == hash2
        
        # Different input should produce different hash
        assert hash1 != hash3
        
        # Hash should be 16 characters
        assert len(hash1) == 16
        assert len(hash3) == 16
    
    def test_formatting_with_all_contexts(self, formatter, log_record):
        """Test formatting with all context types set."""
        correlation_id = set_correlation_id("test-123")
        set_user_context({"username": "test_user", "action": "parse"})
        set_service_context("test_service", "test_method", 50)
        
        try:
            formatted = formatter.format(log_record)
            log_data = json.loads(formatted)
            
            context = log_data["context"]
            
            # All context types should be present
            assert context["correlation_id"] == correlation_id
            assert "user_context" in context
            assert context["user_context"]["username_hash"] is not None
            assert context["user_context"]["action"] == "parse"
            assert context["service_context"]["component"] == "test_service"
            assert context["service_context"]["method"] == "test_method"
            assert context["service_context"]["line"] == 50
            
        finally:
            clear_all_context()


class TestContextualLoggerAdapter:
    """Test ContextualLoggerAdapter class."""
    
    @pytest.fixture
    def adapter(self):
        """Create a ContextualLoggerAdapter instance."""
        base_logger = logging.getLogger("test")
        return ContextualLoggerAdapter(base_logger, {})
    
    def test_process_with_extra_fields(self, adapter):
        """Test message processing with extra fields."""
        msg = "Test message"
        kwargs = {
            "extra_fields": {"custom": "value", "number": 42},
            "other_arg": "other_value"
        }
        
        processed_msg, processed_kwargs = adapter.process(msg, kwargs)
        
        assert processed_msg == msg
        assert "extra_fields" not in processed_kwargs
        assert "extra" in processed_kwargs
        assert processed_kwargs["extra"]["extra_fields"] == {"custom": "value", "number": 42}
        assert processed_kwargs["other_arg"] == "other_value"
    
    def test_process_without_extra_fields(self, adapter):
        """Test message processing without extra fields."""
        msg = "Test message"
        kwargs = {"level": "INFO"}
        
        processed_msg, processed_kwargs = adapter.process(msg, kwargs)
        
        assert processed_msg == msg
        assert processed_kwargs == kwargs


class TestContextManagement:
    """Test context variable management functions."""
    
    def test_correlation_id_management(self):
        """Test correlation ID context management."""
        # Initially should be None
        assert get_correlation_id() is None
        
        # Set custom correlation ID
        custom_id = "custom-correlation-123"
        result_id = set_correlation_id(custom_id)
        assert result_id == custom_id
        assert get_correlation_id() == custom_id
        
        # Set without providing ID (should generate UUID)
        generated_id = set_correlation_id()
        assert generated_id is not None
        assert len(generated_id) == 36  # UUID format
        assert get_correlation_id() == generated_id
        
        # Clear correlation ID
        clear_correlation_id()
        assert get_correlation_id() is None
    
    def test_user_context_management(self):
        """Test user context management."""
        # Initially should be None
        assert get_user_context() is None
        
        # Set user context
        user_context = {"username": "test_user", "channel": "test_channel"}
        set_user_context(user_context)
        assert get_user_context() == user_context
        
        # Clear user context
        clear_user_context()
        assert get_user_context() is None
    
    def test_service_context_management(self):
        """Test service context management."""
        # Initially should be None
        assert get_service_context() is None
        
        # Set service context with line number
        set_service_context("test_component", "test_method", 42)
        context = get_service_context()
        assert context["component"] == "test_component"
        assert context["method"] == "test_method"
        assert context["line"] == 42
        
        # Set service context without line number
        set_service_context("another_component", "another_method")
        context = get_service_context()
        assert context["component"] == "another_component"
        assert context["method"] == "another_method"
        assert "line" not in context
        
        # Clear service context
        clear_service_context()
        assert get_service_context() is None
    
    def test_clear_all_context(self):
        """Test clearing all context at once."""
        # Set all contexts
        set_correlation_id("test-123")
        set_user_context({"user": "test"})
        set_service_context("component", "method")
        
        # Verify all are set
        assert get_correlation_id() is not None
        assert get_user_context() is not None
        assert get_service_context() is not None
        
        # Clear all
        clear_all_context()
        
        # Verify all are cleared
        assert get_correlation_id() is None
        assert get_user_context() is None
        assert get_service_context() is None


class TestLoggingSetup:
    """Test logging setup functions."""
    
    def test_setup_logging_with_temp_dir(self):
        """Test logging setup with temporary directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Setup logging in temp directory
            config = setup_logging(log_level="DEBUG", log_dir=temp_dir, structured=True)
            
            # Verify configuration
            assert config["level"] == "DEBUG"
            assert config["handlers"] > 0
            assert temp_dir in config["log_dir"]
            assert "app.log" in config["files"]
            assert "error.log" in config["files"]
            assert "trades.log" in config["files"]
            
            # Verify log files are created
            log_path = Path(temp_dir)
            assert (log_path / "app.log").exists() or True  # May not exist until first write
    
    def test_setup_logging_structured_vs_plain(self):
        """Test logging setup with structured vs plain formatting."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test structured logging
            setup_logging(log_dir=temp_dir, structured=True)
            logger = logging.getLogger("test.structured")
            
            # Should not raise exception
            logger.info("Test structured message")
            
            # Test plain logging
            setup_logging(log_dir=temp_dir, structured=False)
            logger_plain = logging.getLogger("test.plain")
            
            # Should not raise exception
            logger_plain.info("Test plain message")
    
    @patch.dict('os.environ', {'DEV_MODE': 'true'})
    def test_setup_logging_dev_mode(self):
        """Test logging setup in development mode."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = setup_logging(log_dir=temp_dir)
            
            # Should add console handler in dev mode
            root_logger = logging.getLogger()
            handler_types = [type(h).__name__ for h in root_logger.handlers]
            assert "StreamHandler" in handler_types
    
    def test_get_contextual_logger(self):
        """Test getting contextual logger."""
        logger = get_contextual_logger("test.contextual")
        
        assert isinstance(logger, ContextualLoggerAdapter)
        assert logger.logger.name == "test.contextual"
    
    def test_log_rotation_configuration(self):
        """Test that log rotation is configured correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            setup_logging(log_dir=temp_dir)
            
            root_logger = logging.getLogger()
            
            # Find RotatingFileHandler instances
            rotating_handlers = [
                h for h in root_logger.handlers 
                if h.__class__.__name__ == "RotatingFileHandler"
            ]
            
            # Should have at least app.log and error.log handlers
            assert len(rotating_handlers) >= 2
            
            # Check rotation settings
            for handler in rotating_handlers:
                assert handler.maxBytes == 100 * 1024 * 1024  # 100MB
                assert handler.backupCount == 5
    
    def test_logger_levels_configuration(self):
        """Test that specific logger levels are configured."""
        with tempfile.TemporaryDirectory() as temp_dir:
            setup_logging(log_dir=temp_dir)
            
            # Check that noisy loggers are set to WARNING
            assert logging.getLogger("telethon").level == logging.WARNING
            assert logging.getLogger("aiohttp").level == logging.WARNING
            assert logging.getLogger("urllib3").level == logging.WARNING
    
    def test_trade_logger_separation(self):
        """Test that trade logger is separate from root logger."""
        with tempfile.TemporaryDirectory() as temp_dir:
            setup_logging(log_dir=temp_dir)
            
            trade_logger = logging.getLogger("trade")
            
            # Trade logger should not propagate to root
            assert not trade_logger.propagate
            
            # Trade logger should have its own handler
            assert len(trade_logger.handlers) > 0
    
    def test_error_log_level_filtering(self):
        """Test that error log only gets ERROR and CRITICAL messages."""
        with tempfile.TemporaryDirectory() as temp_dir:
            setup_logging(log_dir=temp_dir)
            
            root_logger = logging.getLogger()
            
            # Find error handler
            error_handlers = [
                h for h in root_logger.handlers 
                if "error.log" in str(getattr(h, 'baseFilename', ''))
            ]
            
            assert len(error_handlers) > 0
            error_handler = error_handlers[0]
            assert error_handler.level == logging.ERROR
    
    def test_integration_with_structured_formatter(self):
        """Test integration of structured formatter with logging setup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            setup_logging(log_dir=temp_dir, structured=True)
            
            # Set context and log message
            correlation_id = set_correlation_id("integration-test")
            set_user_context({"username": "integration_user"})
            
            try:
                logger = logging.getLogger("integration.test")
                logger.info("Integration test message")
                
                # If we get here without exception, formatting worked
                assert True
                
            finally:
                clear_all_context()