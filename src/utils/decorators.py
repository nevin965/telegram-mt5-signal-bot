"""
Decorators for common patterns in the trading system.

This module provides decorators for circuit breaker, retry logic,
and other cross-cutting concerns.
"""

import asyncio
import functools
import logging
from typing import Any, Callable, Optional, TypeVar, Union
from datetime import datetime, timedelta

from src.utils.circuit_breaker import CircuitBreaker


# Type variable for generic decorator return type
F = TypeVar('F', bound=Callable[..., Any])

# Module logger
logger = logging.getLogger(__name__)


def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
    expected_exception: type = Exception
) -> Callable[[F], F]:
    """
    Decorator to apply circuit breaker pattern to a function.
    
    Args:
        failure_threshold: Number of failures before circuit opens
        recovery_timeout: Seconds to wait before attempting recovery
        expected_exception: Exception type to catch (default: Exception)
    
    Returns:
        Decorated function with circuit breaker protection
    
    Example:
        @circuit_breaker(failure_threshold=3, recovery_timeout=30)
        async def call_external_api():
            # API call that might fail
            pass
    """
    def decorator(func: F) -> F:
        # Create a circuit breaker instance for this function
        breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            expected_exception=expected_exception
        )
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            """Async wrapper for circuit breaker."""
            return await breaker.async_call(func, *args, **kwargs)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            """Sync wrapper for circuit breaker."""
            return breaker.call(func, *args, **kwargs)
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def retry_on_failure(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,)
) -> Callable[[F], F]:
    """
    Decorator to retry a function on failure with exponential backoff.
    
    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff: Backoff multiplier for exponential delay
        exceptions: Tuple of exceptions to catch and retry on
    
    Returns:
        Decorated function with retry logic
    
    Example:
        @retry_on_failure(max_attempts=3, delay=1.0, backoff=2.0)
        async def unstable_operation():
            # Operation that might fail transiently
            pass
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            """Async wrapper for retry logic."""
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_attempts} failed for {func.__name__}: {e}. "
                            f"Retrying in {current_delay:.1f}s..."
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"All {max_attempts} attempts failed for {func.__name__}: {e}"
                        )
            
            # Re-raise the last exception if all attempts failed
            if last_exception:
                raise last_exception
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            """Sync wrapper for retry logic."""
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_attempts} failed for {func.__name__}: {e}. "
                            f"Retrying in {current_delay:.1f}s..."
                        )
                        import time
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"All {max_attempts} attempts failed for {func.__name__}: {e}"
                        )
            
            # Re-raise the last exception if all attempts failed
            if last_exception:
                raise last_exception
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def log_execution_time(func: F) -> F:
    """
    Decorator to log the execution time of a function.
    
    Args:
        func: Function to measure
    
    Returns:
        Decorated function that logs execution time
    
    Example:
        @log_execution_time
        async def process_data():
            # Time-sensitive operation
            pass
    """
    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        """Async wrapper for execution time logging."""
        start_time = datetime.now()
        try:
            result = await func(*args, **kwargs)
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"{func.__name__} executed in {execution_time:.3f}s")
            return result
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.error(f"{func.__name__} failed after {execution_time:.3f}s: {e}")
            raise
    
    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        """Sync wrapper for execution time logging."""
        start_time = datetime.now()
        try:
            result = func(*args, **kwargs)
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"{func.__name__} executed in {execution_time:.3f}s")
            return result
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.error(f"{func.__name__} failed after {execution_time:.3f}s: {e}")
            raise
    
    # Return appropriate wrapper based on function type
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


def validate_not_none(**param_names):
    """
    Decorator to validate that specified parameters are not None.
    
    Args:
        **param_names: Parameter names to validate
    
    Returns:
        Decorated function with None validation
    
    Example:
        @validate_not_none(price='price', volume='volume')
        async def place_order(price, volume, symbol='GOLD'):
            # price and volume are guaranteed not to be None
            pass
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            """Async wrapper for parameter validation."""
            # Get function signature
            import inspect
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            
            # Validate specified parameters
            for param, name in param_names.items():
                if param in bound.arguments and bound.arguments[param] is None:
                    raise ValueError(f"Parameter '{name}' cannot be None in {func.__name__}")
            
            return await func(*args, **kwargs)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            """Sync wrapper for parameter validation."""
            # Get function signature
            import inspect
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            
            # Validate specified parameters
            for param, name in param_names.items():
                if param in bound.arguments and bound.arguments[param] is None:
                    raise ValueError(f"Parameter '{name}' cannot be None in {func.__name__}")
            
            return func(*args, **kwargs)
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator