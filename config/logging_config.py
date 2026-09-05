"""
Logging configuration with rotating file handlers and structured JSON logging.
Follows coding standards: never use print(), all output through logging system.
"""

import hashlib
import json
import logging
import logging.handlers
import os
import uuid
from contextvars import ContextVar
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, Optional


# Context variables for tracking correlation IDs and user context
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)
user_context_var: ContextVar[Optional[Dict[str, Any]]] = ContextVar('user_context', default=None)
service_context_var: ContextVar[Optional[Dict[str, Any]]] = ContextVar('service_context', default=None)


class StructuredFormatter(logging.Formatter):
    """
    JSON structured logging formatter with correlation IDs and context.
    Follows the logging requirements from architecture specs.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured JSON."""
        # Build base log entry
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
        }
        
        # Add context information
        context = {}
        
        # Add correlation ID if available
        correlation_id = correlation_id_var.get()
        if correlation_id:
            context["correlation_id"] = correlation_id
            
        # Add service context (component, method, line number)
        service_context = service_context_var.get()
        if service_context:
            context["service_context"] = service_context
        else:
            # Fallback to extracting from log record
            context["service_context"] = {
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno
            }
        
        # Add user context with hashed sensitive data
        user_context = user_context_var.get()
        if user_context:
            # Hash sensitive information like usernames
            sanitized_user_context = {}
            for key, value in user_context.items():
                if key in ['username', 'user_id', 'telegram_id']:
                    # Hash sensitive identifiers
                    if value:
                        sanitized_user_context[f"{key}_hash"] = self._hash_sensitive_data(str(value))
                else:
                    sanitized_user_context[key] = value
            context["user_context"] = sanitized_user_context
        
        # Add context to log entry if not empty
        if context:
            log_entry["context"] = context
            
        # Add exception information if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
            
        # Add extra fields from LoggerAdapter or manual addition
        if hasattr(record, 'extra_fields'):
            log_entry.update(record.extra_fields)
        
        return json.dumps(log_entry, default=str)
    
    def _hash_sensitive_data(self, data: str) -> str:
        """Hash sensitive data using SHA256."""
        return hashlib.sha256(data.encode('utf-8')).hexdigest()[:16]  # First 16 chars for readability


class ContextualLoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that adds contextual information to log records.
    """
    
    def process(self, msg: Any, kwargs: Dict[str, Any]) -> tuple[Any, Dict[str, Any]]:
        """Process log message and add contextual information."""
        # Add extra fields if provided
        if 'extra_fields' in kwargs:
            extra = kwargs.setdefault('extra', {})
            extra['extra_fields'] = kwargs.pop('extra_fields')
            
        return msg, kwargs


def setup_logging(log_level: str = "INFO", log_dir: str = "logs", structured: bool = True) -> dict[str, Any]:
    """
    Setup application logging with rotating file handlers and structured JSON logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Directory for log files
        structured: Whether to use structured JSON logging (default True)

    Returns:
        Dictionary with logger configuration
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Clear any existing handlers
    root_logger.handlers.clear()

    # Create formatters based on structured logging preference
    if structured:
        # JSON structured formatter for production
        json_formatter = StructuredFormatter()
        file_formatter = json_formatter
    else:
        # Human-readable formatter for development
        file_formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Simple console formatter
    simple_formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
    )

    # Application log (rotating, 100MB max, keep 5 files as per AC 3)
    app_handler = logging.handlers.RotatingFileHandler(
        filename=log_path / "app.log",
        maxBytes=100 * 1024 * 1024,  # 100MB as per AC 3
        backupCount=5,  # 5 file rotation as per AC 3
        encoding="utf-8",
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(file_formatter)
    root_logger.addHandler(app_handler)

    # Error log (rotating, 100MB max, keep 5 files as per AC 3)
    error_handler = logging.handlers.RotatingFileHandler(
        filename=log_path / "error.log",
        maxBytes=100 * 1024 * 1024,  # 100MB as per AC 3
        backupCount=5,  # 5 file rotation as per AC 3
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    root_logger.addHandler(error_handler)

    # Trading log (for trade executions and positions)
    trade_handler = logging.handlers.RotatingFileHandler(
        filename=log_path / "trades.log",
        maxBytes=100 * 1024 * 1024,  # 100MB consistent with other logs
        backupCount=5,  # 5 file rotation consistent with other logs
        encoding="utf-8",
    )
    trade_handler.setLevel(logging.INFO)
    trade_handler.setFormatter(file_formatter)

    # Create trade logger
    trade_logger = logging.getLogger("trade")
    trade_logger.addHandler(trade_handler)
    trade_logger.propagate = False  # Don't duplicate to root logger

    # Console handler for development
    if os.getenv("DEV_MODE", "false").lower() == "true":
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(simple_formatter)
        root_logger.addHandler(console_handler)

    # Configure specific logger levels
    logging.getLogger("telethon").setLevel(logging.WARNING)  # Reduce telethon noise
    logging.getLogger("aiohttp").setLevel(logging.WARNING)  # Reduce aiohttp noise
    logging.getLogger("urllib3").setLevel(logging.WARNING)  # Reduce urllib3 noise

    return {
        "level": log_level,
        "handlers": len(root_logger.handlers),
        "log_dir": str(log_path.absolute()),
        "files": ["app.log", "error.log", "trades.log"],
    }


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the specified name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def get_trade_logger() -> logging.Logger:
    """
    Get the specialized trade logger for trade executions.

    Returns:
        Trade logger instance
    """
    return logging.getLogger("trade")


def get_contextual_logger(name: str) -> ContextualLoggerAdapter:
    """
    Get a contextual logger adapter that supports extra fields.
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        ContextualLoggerAdapter instance
    """
    base_logger = logging.getLogger(name)
    return ContextualLoggerAdapter(base_logger, {})


# Correlation ID and context management functions

def set_correlation_id(correlation_id: Optional[str] = None) -> str:
    """
    Set correlation ID for current context.
    
    Args:
        correlation_id: Correlation ID to set (generates new UUID if None)
    
    Returns:
        The correlation ID that was set
    """
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    
    correlation_id_var.set(correlation_id)
    return correlation_id


def get_correlation_id() -> Optional[str]:
    """Get current correlation ID from context."""
    return correlation_id_var.get()


def clear_correlation_id() -> None:
    """Clear correlation ID from context."""
    correlation_id_var.set(None)


def set_user_context(user_context: Dict[str, Any]) -> None:
    """
    Set user context for current logging context.
    
    Args:
        user_context: User context information (will be sanitized automatically)
    """
    user_context_var.set(user_context)


def get_user_context() -> Optional[Dict[str, Any]]:
    """Get current user context from context."""
    return user_context_var.get()


def clear_user_context() -> None:
    """Clear user context from context."""
    user_context_var.set(None)


def set_service_context(component: str, method: str, line: Optional[int] = None) -> None:
    """
    Set service context for current logging context.
    
    Args:
        component: Component or module name
        method: Method or function name
        line: Line number (optional)
    """
    context = {
        "component": component,
        "method": method
    }
    if line:
        context["line"] = line
        
    service_context_var.set(context)


def get_service_context() -> Optional[Dict[str, Any]]:
    """Get current service context from context."""
    return service_context_var.get()


def clear_service_context() -> None:
    """Clear service context from context."""
    service_context_var.set(None)


def clear_all_context() -> None:
    """Clear all logging context variables."""
    clear_correlation_id()
    clear_user_context()
    clear_service_context()
