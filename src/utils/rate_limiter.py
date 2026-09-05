"""
Rate limiting utilities for API requests with queuing and exponential backoff.
Follows coding standards: structured logging, async patterns.
"""

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass

from config.logging_config import get_contextual_logger


@dataclass
class RateLimitConfig:
    """Rate limiting configuration parameters."""
    requests_per_minute: int = 100
    burst_limit: int = 10
    backoff_base: float = 1.0
    backoff_max: float = 60.0
    queue_max_size: int = 50


class APIRateLimiter:
    """
    Rate limiter with request queuing and exponential backoff for API calls.
    
    Implements a sliding window rate limiter with burst handling and request queuing
    for smooth traffic distribution to respect API quotas.
    """
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        """
        Initialize rate limiter with configuration.
        
        Args:
            config: Rate limiting configuration, defaults to standard limits
        """
        self.config = config or RateLimitConfig()
        self.logger = get_contextual_logger(__name__)
        
        # Sliding window tracking
        self._request_times: deque = deque()
        self._request_lock = asyncio.Lock()
        
        # Request queue for throttling
        self._request_queue: asyncio.Queue = asyncio.Queue(maxsize=self.config.queue_max_size)
        self._queue_processor_task: Optional[asyncio.Task] = None
        
        # Exponential backoff state
        self._consecutive_failures = 0
        self._last_failure_time: Optional[datetime] = None
        
        # Metrics
        self._total_requests = 0
        self._total_queued = 0
        self._total_rejected = 0
        
        self.logger.info(
            "Rate limiter initialized",
            extra_fields={
                "rate_limiter_config": {
                    "requests_per_minute": self.config.requests_per_minute,
                    "burst_limit": self.config.burst_limit,
                    "queue_max_size": self.config.queue_max_size
                }
            }
        )

    async def acquire(self, priority: int = 0) -> bool:
        """
        Acquire permission to make an API request.
        
        Args:
            priority: Request priority (higher = more priority), default 0
            
        Returns:
            True if permission granted, False if rejected due to queue limits
        """
        async with self._request_lock:
            current_time = datetime.now()
            
            # Clean old requests from sliding window (older than 1 minute)
            cutoff_time = current_time - timedelta(minutes=1)
            while self._request_times and self._request_times[0] < cutoff_time:
                self._request_times.popleft()
            
            # Check if we can make request immediately (within burst limit)
            recent_requests = len([t for t in self._request_times if t > current_time - timedelta(seconds=10)])
            
            if recent_requests < self.config.burst_limit and len(self._request_times) < self.config.requests_per_minute:
                # Can proceed immediately
                self._request_times.append(current_time)
                self._total_requests += 1
                
                self.logger.debug(
                    "Rate limit check passed - immediate execution",
                    extra_fields={
                        "api_metrics": {
                            "requests_this_minute": len(self._request_times),
                            "rate_limit_remaining": self.config.requests_per_minute - len(self._request_times),
                            "burst_requests_recent": recent_requests,
                            "queue_size": self._request_queue.qsize()
                        }
                    }
                )
                return True
            
            # Need to queue the request
            try:
                await self._request_queue.put((current_time, priority), block=False)
                self._total_queued += 1
                
                self.logger.info(
                    "Request queued due to rate limiting",
                    extra_fields={
                        "api_metrics": {
                            "requests_this_minute": len(self._request_times),
                            "rate_limit_remaining": self.config.requests_per_minute - len(self._request_times),
                            "queue_size": self._request_queue.qsize(),
                            "priority": priority
                        }
                    }
                )
                
                # Start queue processor if not running
                if not self._queue_processor_task or self._queue_processor_task.done():
                    self._queue_processor_task = asyncio.create_task(self._process_queue())
                
                return True
                
            except asyncio.QueueFull:
                self._total_rejected += 1
                self.logger.warning(
                    "Request rejected - rate limit queue full",
                    extra_fields={
                        "api_metrics": {
                            "requests_this_minute": len(self._request_times),
                            "queue_size": self._request_queue.qsize(),
                            "total_rejected": self._total_rejected
                        }
                    }
                )
                return False

    async def _process_queue(self):
        """Process queued requests with proper timing."""
        while True:
            try:
                # Wait for queued request
                queued_time, priority = await asyncio.wait_for(
                    self._request_queue.get(),
                    timeout=30.0  # Process queue for 30 seconds after last request
                )
                
                # Calculate when we can process this request
                async with self._request_lock:
                    current_time = datetime.now()
                    
                    # Clean old requests
                    cutoff_time = current_time - timedelta(minutes=1)
                    while self._request_times and self._request_times[0] < cutoff_time:
                        self._request_times.popleft()
                    
                    # Check if we need to wait
                    if len(self._request_times) >= self.config.requests_per_minute:
                        # Wait until oldest request is more than 1 minute old
                        wait_until = self._request_times[0] + timedelta(minutes=1)
                        wait_seconds = (wait_until - current_time).total_seconds()
                        
                        if wait_seconds > 0:
                            self.logger.debug(f"Queue processor waiting {wait_seconds:.1f}s for rate limit")
                            await asyncio.sleep(wait_seconds)
                            current_time = datetime.now()
                    
                    # Add request to tracking
                    self._request_times.append(current_time)
                    self._total_requests += 1
                    
                    self.logger.debug(
                        "Queued request processed",
                        extra_fields={
                            "api_metrics": {
                                "queue_wait_seconds": (current_time - queued_time).total_seconds(),
                                "requests_this_minute": len(self._request_times),
                                "queue_size": self._request_queue.qsize(),
                                "priority": priority
                            }
                        }
                    )
                
            except asyncio.TimeoutError:
                # No requests in queue for 30 seconds, exit processor
                self.logger.debug("Queue processor stopping - no requests")
                break
            except Exception as e:
                self.logger.error(f"Error in queue processor: {e}")
                await asyncio.sleep(1)  # Brief pause before retrying

    def calculate_backoff_delay(self) -> float:
        """
        Calculate exponential backoff delay based on consecutive failures.
        
        Returns:
            Delay in seconds before next retry attempt
        """
        if self._consecutive_failures == 0:
            return 0.0
        
        # Exponential backoff: base^failures seconds
        delay = min(
            self.config.backoff_base * (2 ** (self._consecutive_failures - 1)),
            self.config.backoff_max
        )
        
        return delay

    def record_success(self):
        """Record successful API call (resets backoff)."""
        if self._consecutive_failures > 0:
            self.logger.info(
                f"API call succeeded after {self._consecutive_failures} failures - resetting backoff"
            )
        self._consecutive_failures = 0
        self._last_failure_time = None

    def record_failure(self):
        """Record failed API call (increases backoff)."""
        self._consecutive_failures += 1
        self._last_failure_time = datetime.now()
        
        backoff_delay = self.calculate_backoff_delay()
        
        self.logger.warning(
            f"API call failed ({self._consecutive_failures} consecutive failures)",
            extra_fields={
                "api_metrics": {
                    "consecutive_failures": self._consecutive_failures,
                    "backoff_delay_seconds": backoff_delay,
                    "next_retry_after": (datetime.now() + timedelta(seconds=backoff_delay)).isoformat()
                }
            }
        )

    async def wait_for_backoff(self):
        """Wait for exponential backoff delay if needed."""
        delay = self.calculate_backoff_delay()
        if delay > 0:
            self.logger.info(f"Waiting {delay:.1f}s for exponential backoff")
            await asyncio.sleep(delay)

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current rate limiter metrics.
        
        Returns:
            Dictionary with current metrics and state
        """
        current_time = datetime.now()
        
        # Count requests in last minute
        cutoff_time = current_time - timedelta(minutes=1)
        recent_requests = len([t for t in self._request_times if t > cutoff_time])
        
        return {
            "requests_this_minute": recent_requests,
            "rate_limit_remaining": max(0, self.config.requests_per_minute - recent_requests),
            "queue_size": self._request_queue.qsize(),
            "consecutive_failures": self._consecutive_failures,
            "backoff_delay_seconds": self.calculate_backoff_delay(),
            "total_requests": self._total_requests,
            "total_queued": self._total_queued,
            "total_rejected": self._total_rejected,
            "queue_processor_running": bool(
                self._queue_processor_task and not self._queue_processor_task.done()
            )
        }

    async def cleanup(self):
        """Clean up background tasks."""
        if self._queue_processor_task and not self._queue_processor_task.done():
            self._queue_processor_task.cancel()
            try:
                await self._queue_processor_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("Rate limiter cleaned up")


# Global rate limiter instance for LLM API calls
llm_rate_limiter = APIRateLimiter(
    RateLimitConfig(
        requests_per_minute=100,  # From settings
        burst_limit=10,
        queue_max_size=50
    )
)