"""
LLM response caching system with TTL and automatic cleanup.
Reduces API costs by caching identical message parsing results.
"""

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
import aiosqlite

from config.logging_config import get_contextual_logger
from config.settings import settings


class LLMResponseCache:
    """
    Persistent cache for LLM parsing responses with TTL and automatic cleanup.
    
    Uses SQLite for persistence to survive application restarts while maintaining
    fast in-memory access for frequently accessed entries.
    """
    
    def __init__(self, db_path: Optional[Path] = None, ttl_hours: Optional[int] = None):
        """
        Initialize LLM response cache.
        
        Args:
            db_path: Path to SQLite database file, defaults to data/llm_cache.db
            ttl_hours: Cache TTL in hours, defaults to settings value
        """
        self.logger = get_contextual_logger(__name__)
        self.db_path = db_path or Path("data") / "llm_cache.db"
        self.ttl_hours = ttl_hours or settings.llm_cache_ttl_hours
        
        # Ensure data directory exists
        self.db_path.parent.mkdir(exist_ok=True)
        
        # In-memory cache for performance
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._memory_cache_timestamps: Dict[str, datetime] = {}
        self.max_memory_entries = 1000
        
        # Background cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        
        self.logger.info(
            f"LLM cache initialized with TTL={self.ttl_hours}h, db_path={self.db_path}"
        )

    async def initialize(self):
        """Initialize database and start background tasks."""
        await self._create_tables()
        await self._load_recent_to_memory()
        self._start_cleanup_task()

    async def _create_tables(self):
        """Create cache table if it doesn't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS llm_cache (
                    message_hash TEXT PRIMARY KEY,
                    normalized_text TEXT NOT NULL,
                    response_data TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    accessed_at TIMESTAMP NOT NULL,
                    access_count INTEGER DEFAULT 1
                )
            """)
            
            # Create index for efficient TTL queries
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_cache_created_at 
                ON llm_cache(created_at)
            """)
            
            await db.commit()
        
        self.logger.info("LLM cache database initialized")

    async def _load_recent_to_memory(self):
        """Load recent cache entries into memory for fast access."""
        cutoff_time = datetime.now() - timedelta(hours=1)  # Load last 1 hour
        
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT message_hash, response_data, created_at FROM llm_cache WHERE created_at > ? ORDER BY accessed_at DESC LIMIT ?",
                (cutoff_time.isoformat(), self.max_memory_entries)
            ) as cursor:
                loaded_count = 0
                async for row in cursor:
                    message_hash, response_data, created_at = row
                    self._memory_cache[message_hash] = json.loads(response_data)
                    self._memory_cache_timestamps[message_hash] = datetime.fromisoformat(created_at)
                    loaded_count += 1
        
        self.logger.info(f"Loaded {loaded_count} cache entries to memory")

    def _start_cleanup_task(self):
        """Start background task for cache cleanup."""
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self):
        """Periodic cleanup of expired entries."""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                await self.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Cache cleanup error: {e}")

    def _normalize_message_text(self, text: str) -> str:
        """
        Normalize message text for consistent caching.
        
        Args:
            text: Raw message text
            
        Returns:
            Normalized text for hashing
        """
        # Convert to lowercase and normalize whitespace
        normalized = ' '.join(text.lower().strip().split())
        
        # Remove common variations that don't affect parsing
        # (This could be expanded based on observed patterns)
        
        return normalized

    def _generate_cache_key(self, text: str) -> str:
        """
        Generate cache key from message text using SHA256.
        
        Args:
            text: Message text to hash
            
        Returns:
            SHA256 hash as hex string
        """
        normalized = self._normalize_message_text(text)
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    async def get(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Get cached response for message text.
        
        Args:
            text: Message text to look up
            
        Returns:
            Cached response data or None if not found/expired
        """
        cache_key = self._generate_cache_key(text)
        
        # Check memory cache first
        if cache_key in self._memory_cache:
            cached_time = self._memory_cache_timestamps[cache_key]
            if datetime.now() - cached_time < timedelta(hours=self.ttl_hours):
                await self._update_access_stats(cache_key)
                
                self.logger.debug(
                    "Cache hit (memory)",
                    extra_fields={
                        "cache_data": {
                            "cache_key": cache_key[:16],
                            "cached_ago_hours": (datetime.now() - cached_time).total_seconds() / 3600,
                            "source": "memory"
                        }
                    }
                )
                
                return self._memory_cache[cache_key]
            else:
                # Remove expired entry from memory
                del self._memory_cache[cache_key]
                del self._memory_cache_timestamps[cache_key]
        
        # Check database
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT response_data, created_at FROM llm_cache WHERE message_hash = ?",
                (cache_key,)
            ) as cursor:
                row = await cursor.fetchone()
                
                if row:
                    response_data, created_at = row
                    cached_time = datetime.fromisoformat(created_at)
                    
                    # Check if still valid
                    if datetime.now() - cached_time < timedelta(hours=self.ttl_hours):
                        # Load into memory cache
                        parsed_data = json.loads(response_data)
                        self._memory_cache[cache_key] = parsed_data
                        self._memory_cache_timestamps[cache_key] = cached_time
                        
                        # Update access stats
                        await self._update_access_stats(cache_key)
                        
                        self.logger.debug(
                            "Cache hit (database)",
                            extra_fields={
                                "cache_data": {
                                    "cache_key": cache_key[:16],
                                    "cached_ago_hours": (datetime.now() - cached_time).total_seconds() / 3600,
                                    "source": "database"
                                }
                            }
                        )
                        
                        return parsed_data
        
        # Cache miss
        self.logger.debug(
            "Cache miss",
            extra_fields={
                "cache_data": {
                    "cache_key": cache_key[:16],
                    "normalized_text_length": len(self._normalize_message_text(text))
                }
            }
        )
        
        return None

    async def set(self, text: str, response_data: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """
        Cache response data for message text.
        
        Args:
            text: Message text as cache key
            response_data: LLM response data to cache
            ttl: Optional TTL in seconds (overrides default TTL hours)
        """
        cache_key = self._generate_cache_key(text)
        normalized_text = self._normalize_message_text(text)
        current_time = datetime.now()
        
        # Store TTL info in response data for proper expiration
        if ttl:
            response_data['_cache_ttl_seconds'] = ttl
            response_data['_cache_expires_at'] = (current_time + timedelta(seconds=ttl)).isoformat()
        
        # Store in memory cache
        self._memory_cache[cache_key] = response_data
        self._memory_cache_timestamps[cache_key] = current_time
        
        # Evict oldest entries if memory cache is full
        if len(self._memory_cache) > self.max_memory_entries:
            oldest_key = min(self._memory_cache_timestamps, key=self._memory_cache_timestamps.get)
            del self._memory_cache[oldest_key]
            del self._memory_cache_timestamps[oldest_key]
        
        # Store in database
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO llm_cache 
                (message_hash, normalized_text, response_data, created_at, accessed_at, access_count)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (
                cache_key,
                normalized_text,
                json.dumps(response_data),
                current_time.isoformat(),
                current_time.isoformat()
            ))
            await db.commit()
        
        self.logger.debug(
            "Response cached",
            extra_fields={
                "cache_data": {
                    "cache_key": cache_key[:16],
                    "normalized_text_length": len(normalized_text),
                    "response_size_bytes": len(json.dumps(response_data))
                }
            }
        )

    async def _update_access_stats(self, cache_key: str) -> None:
        """Update access statistics for cache entry."""
        current_time = datetime.now()
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE llm_cache 
                SET accessed_at = ?, access_count = access_count + 1
                WHERE message_hash = ?
            """, (current_time.isoformat(), cache_key))
            await db.commit()

    async def cleanup_expired(self) -> int:
        """
        Remove expired entries from cache.
        
        Returns:
            Number of entries removed
        """
        cutoff_time = datetime.now() - timedelta(hours=self.ttl_hours)
        
        # Clean memory cache
        expired_keys = [
            key for key, timestamp in self._memory_cache_timestamps.items()
            if timestamp < cutoff_time
        ]
        
        for key in expired_keys:
            del self._memory_cache[key]
            del self._memory_cache_timestamps[key]
        
        # Clean database
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM llm_cache WHERE created_at < ?",
                (cutoff_time.isoformat(),)
            )
            deleted_count = cursor.rowcount
            await db.commit()
        
        if deleted_count > 0 or len(expired_keys) > 0:
            self.logger.info(
                f"Cache cleanup removed {deleted_count} database entries, {len(expired_keys)} memory entries"
            )
        
        return deleted_count

    async def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache metrics
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Total entries
            cursor = await db.execute("SELECT COUNT(*) FROM llm_cache")
            total_entries = (await cursor.fetchone())[0]
            
            # Valid entries (non-expired)
            cutoff_time = datetime.now() - timedelta(hours=self.ttl_hours)
            cursor = await db.execute(
                "SELECT COUNT(*) FROM llm_cache WHERE created_at > ?",
                (cutoff_time.isoformat(),)
            )
            valid_entries = (await cursor.fetchone())[0]
            
            # Top accessed entries
            cursor = await db.execute(
                "SELECT access_count FROM llm_cache ORDER BY access_count DESC LIMIT 10"
            )
            top_access_counts = [row[0] for row in await cursor.fetchall()]
        
        return {
            "total_entries": total_entries,
            "valid_entries": valid_entries,
            "expired_entries": total_entries - valid_entries,
            "memory_cache_size": len(self._memory_cache),
            "max_memory_entries": self.max_memory_entries,
            "ttl_hours": self.ttl_hours,
            "top_access_counts": top_access_counts,
            "cache_hit_potential": f"{(valid_entries / max(1, total_entries)) * 100:.1f}%"
        }

    async def clear(self) -> None:
        """Clear all cache entries."""
        # Clear memory cache
        self._memory_cache.clear()
        self._memory_cache_timestamps.clear()
        
        # Clear database
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM llm_cache")
            await db.commit()
        
        self.logger.info("Cache cleared")

    async def cleanup(self):
        """Clean up cache resources."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("Cache cleanup completed")


# Global cache instance
llm_cache = LLMResponseCache()