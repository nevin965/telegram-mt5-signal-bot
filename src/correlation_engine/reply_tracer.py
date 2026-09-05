"""
Reply chain traversal for multi-level Telegram message correlation.

This module implements reply chain analysis to find the root message in
multi-level reply scenarios (reply to a reply). Includes caching and 
rate limiting for Telegram API calls.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from src.telegram_client.rate_limiter import RateLimiter
from src.utils.circuit_breaker import circuit_breaker


class ReplyChainCache:
    """
    Simple TTL cache for reply chains with memory management.
    
    Implements LRU-style eviction with TTL expiration to prevent
    memory bloat while caching frequently accessed chains.
    """

    def __init__(self, max_entries: int = 1000, ttl_minutes: int = 5):
        """
        Initialize cache with size and TTL limits.
        
        Args:
            max_entries: Maximum number of cached entries
            ttl_minutes: Time-to-live for cache entries in minutes
        """
        self.max_entries = max_entries
        self.ttl_seconds = ttl_minutes * 60
        self._cache: dict[str, dict[str, Any]] = {}
        self.logger = logging.getLogger(__name__)

    def _is_expired(self, entry: dict[str, Any]) -> bool:
        """Check if cache entry has expired."""
        return time.time() - entry['timestamp'] > self.ttl_seconds

    def _cleanup_expired(self):
        """Remove expired entries from cache."""
        expired_keys = [
            key for key, entry in self._cache.items()
            if self._is_expired(entry)
        ]
        for key in expired_keys:
            del self._cache[key]

    def _evict_oldest(self):
        """Evict oldest entries if cache is full."""
        if len(self._cache) >= self.max_entries:
            # Remove 20% of oldest entries
            entries_to_remove = max(1, len(self._cache) // 5)
            oldest_keys = sorted(
                self._cache.keys(),
                key=lambda k: self._cache[k]['timestamp']
            )[:entries_to_remove]

            for key in oldest_keys:
                del self._cache[key]

            self.logger.debug(f"Evicted {entries_to_remove} old cache entries")

    def get(self, chat_id: int, message_id: int) -> int | None:
        """
        Get cached root message ID for message.
        
        Args:
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            
        Returns:
            Root message ID if cached and valid, None otherwise
        """
        key = f"{chat_id}:{message_id}"
        entry = self._cache.get(key)

        if entry and not self._is_expired(entry):
            # Update access time for LRU behavior
            entry['last_accessed'] = time.time()
            return entry['root_message_id']

        # Remove expired entry
        if entry:
            del self._cache[key]

        return None

    def put(self, chat_id: int, message_id: int, root_message_id: int):
        """
        Cache root message ID for message.
        
        Args:
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            root_message_id: Root message ID to cache
        """
        # Periodic cleanup
        if len(self._cache) % 100 == 0:
            self._cleanup_expired()

        # Evict if needed
        if len(self._cache) >= self.max_entries:
            self._evict_oldest()

        key = f"{chat_id}:{message_id}"
        self._cache[key] = {
            'root_message_id': root_message_id,
            'timestamp': time.time(),
            'last_accessed': time.time()
        }

    def get_stats(self) -> dict[str, int]:
        """Get cache statistics for monitoring."""
        active_entries = sum(
            1 for entry in self._cache.values()
            if not self._is_expired(entry)
        )

        return {
            'total_entries': len(self._cache),
            'active_entries': active_entries,
            'expired_entries': len(self._cache) - active_entries
        }


class ReplyTracer:
    """
    Telegram reply chain traversal with caching and rate limiting.
    
    Handles multi-level reply scenarios by traversing the reply chain
    until finding the root message, with proper error handling and
    API rate limiting compliance.
    """

    def __init__(self, telegram_client, max_depth: int = 10):
        """
        Initialize reply tracer with Telegram client.
        
        Args:
            telegram_client: Telegram client for message retrieval
            max_depth: Maximum reply chain depth to prevent infinite loops
        """
        self.logger = logging.getLogger(__name__)
        self.telegram_client = telegram_client
        self.max_depth = max_depth

        # Initialize cache and rate limiter
        self.cache = ReplyChainCache(max_entries=1000, ttl_minutes=5)
        self.rate_limiter = RateLimiter(
            base_delay_ms=2000.0,
            std_dev_ms=500.0
        )

        # Statistics for monitoring
        self._chain_requests = 0
        self._cache_hits = 0
        self._api_calls = 0
        self._chain_depths = []

    async def trace_reply_chain(self, message_id: int, chat_id: int) -> int | None:
        """
        Trace reply chain to find root message ID.
        
        Args:
            message_id: Starting message ID
            chat_id: Telegram chat ID
            
        Returns:
            Root message ID if found, None on failure
        """
        trace_id = f"trace_{message_id}_{datetime.now().timestamp()}"

        try:
            self._chain_requests += 1

            self.logger.info(
                f"Starting reply chain trace for message {message_id}",
                extra={
                    'trace_id': trace_id,
                    'message_id': message_id,
                    'chat_id': chat_id
                }
            )

            # Check cache first
            cached_root = self.cache.get(chat_id, message_id)
            if cached_root:
                self._cache_hits += 1
                self.logger.debug(
                    f"Cache hit for message {message_id} -> root {cached_root}",
                    extra={'trace_id': trace_id}
                )
                return cached_root

            # Traverse chain with depth limiting
            root_id = await self._traverse_chain(message_id, chat_id, trace_id)

            if root_id:
                # Cache the result
                self.cache.put(chat_id, message_id, root_id)

                self.logger.info(
                    f"Reply chain traced successfully: {message_id} -> {root_id}",
                    extra={
                        'trace_id': trace_id,
                        'root_message_id': root_id,
                        'api_calls': self._api_calls - (self._chain_requests - 1)
                    }
                )

            return root_id

        except asyncio.CancelledError:
            self.logger.info(f"Reply chain trace cancelled for message {message_id}")
            raise
        except Exception as e:
            self.logger.error(
                f"Error tracing reply chain for message {message_id}: {e}",
                extra={'trace_id': trace_id}
            )
            return None

    @circuit_breaker(failure_threshold=5, recovery_timeout=30)
    async def _traverse_chain(self, message_id: int, chat_id: int, trace_id: str) -> int | None:
        """
        Recursively traverse reply chain to find root.
        
        Args:
            message_id: Current message ID
            chat_id: Telegram chat ID  
            trace_id: Trace ID for logging
            
        Returns:
            Root message ID if found
        """
        visited: set[int] = set()
        current_id = message_id
        depth = 0

        while current_id and depth < self.max_depth:
            # Prevent infinite loops
            if current_id in visited:
                self.logger.warning(
                    f"Circular reference detected in reply chain at message {current_id}",
                    extra={'trace_id': trace_id}
                )
                break

            visited.add(current_id)

            try:
                # Rate limit API calls
                await self.rate_limiter.human_delay()

                # Get message from Telegram
                message = await self._get_message_with_retry(chat_id, current_id, trace_id)
                if not message:
                    self.logger.debug(
                        f"Could not retrieve message {current_id}",
                        extra={'trace_id': trace_id}
                    )
                    break

                self._api_calls += 1

                # Check if this message has a reply_to
                if not hasattr(message, 'reply_to') or not message.reply_to:
                    # This is the root message
                    self._chain_depths.append(depth)
                    self.logger.debug(
                        f"Found root message {current_id} at depth {depth}",
                        extra={'trace_id': trace_id}
                    )
                    return current_id

                # Continue to parent message
                parent_id = message.reply_to.reply_to_msg_id
                self.logger.debug(
                    f"Following reply chain: {current_id} -> {parent_id}",
                    extra={'trace_id': trace_id}
                )

                current_id = parent_id
                depth += 1

            except Exception as e:
                self.logger.error(
                    f"Error retrieving message {current_id}: {e}",
                    extra={'trace_id': trace_id}
                )
                break

        if depth >= self.max_depth:
            self.logger.warning(
                f"Maximum chain depth {self.max_depth} reached for message {message_id}",
                extra={'trace_id': trace_id}
            )

        # Return the deepest message we found if no root
        return current_id if current_id != message_id else None

    async def _get_message_with_retry(self, chat_id: int, message_id: int,
                                    trace_id: str, max_retries: int = 3) -> Any | None:
        """
        Get message from Telegram with retry logic.
        
        Args:
            chat_id: Telegram chat ID
            message_id: Message ID to retrieve
            trace_id: Trace ID for logging
            max_retries: Maximum retry attempts
            
        Returns:
            Message object if successful, None otherwise
        """
        for attempt in range(max_retries + 1):
            try:
                if not self.telegram_client or not self.telegram_client.client:
                    self.logger.error("Telegram client not available")
                    return None

                # Use Telethon's get_messages method
                messages = await self.telegram_client.client.get_messages(
                    chat_id,
                    ids=[message_id]
                )

                if messages and len(messages) > 0:
                    return messages[0]
                else:
                    self.logger.debug(
                        f"Message {message_id} not found in chat {chat_id}",
                        extra={'trace_id': trace_id}
                    )
                    return None

            except Exception as e:
                if attempt < max_retries:
                    wait_time = 2 ** attempt  # Exponential backoff
                    self.logger.warning(
                        f"Attempt {attempt + 1} failed for message {message_id}, "
                        f"retrying in {wait_time}s: {e}",
                        extra={'trace_id': trace_id}
                    )
                    await asyncio.sleep(wait_time)
                else:
                    self.logger.error(
                        f"All {max_retries + 1} attempts failed for message {message_id}: {e}",
                        extra={'trace_id': trace_id}
                    )
                    return None

        return None

    def get_tracer_stats(self) -> dict[str, Any]:
        """Get reply tracer statistics for monitoring."""
        cache_stats = self.cache.get_stats()

        cache_hit_rate = (
            self._cache_hits / self._chain_requests
            if self._chain_requests > 0 else 0.0
        )

        avg_depth = (
            sum(self._chain_depths) / len(self._chain_depths)
            if self._chain_depths else 0.0
        )

        return {
            'chain_requests': self._chain_requests,
            'cache_hits': self._cache_hits,
            'cache_hit_rate': round(cache_hit_rate, 3),
            'api_calls': self._api_calls,
            'average_chain_depth': round(avg_depth, 1),
            'max_chain_depth': max(self._chain_depths) if self._chain_depths else 0,
            'cache_stats': cache_stats
        }

    async def cleanup_cache(self):
        """Clean up expired cache entries manually."""
        try:
            initial_size = len(self.cache._cache)
            self.cache._cleanup_expired()
            cleaned = initial_size - len(self.cache._cache)

            if cleaned > 0:
                self.logger.info(f"Cleaned up {cleaned} expired cache entries")
        except Exception as e:
            self.logger.error(f"Error during cache cleanup: {e}")
