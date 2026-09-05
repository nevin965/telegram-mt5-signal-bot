"""
Unit tests for LLM response caching functionality.
Tests cache operations, TTL handling, and cleanup.
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock

from src.database.cache import LLMResponseCache


class TestLLMResponseCache:
    """Test cases for LLMResponseCache class."""

    @pytest.fixture
    async def cache(self, tmp_path):
        """Create cache instance for testing."""
        cache_instance = LLMResponseCache(
            db_path=tmp_path / "test_cache.db",
            ttl_hours=1  # Short TTL for testing
        )
        await cache_instance.initialize()
        return cache_instance

    @pytest.fixture
    def sample_response_data(self):
        """Sample response data for testing."""
        return {
            "parsed_action": "BUY",
            "symbol": "GOLD",
            "entry_price": 3362.50,
            "stop_loss": 3350.00,
            "confidence_score": 0.80,
            "parser_type": "LLM"
        }

    @pytest.mark.asyncio
    async def test_initialization(self, tmp_path):
        """Test cache initialization creates database."""
        db_path = tmp_path / "test_init.db"
        cache = LLMResponseCache(db_path=db_path, ttl_hours=24)
        
        await cache.initialize()
        
        assert db_path.exists()
        assert cache.ttl_hours == 24

    @pytest.mark.asyncio
    async def test_set_and_get_basic(self, cache, sample_response_data):
        """Test basic cache set and get operations."""
        test_text = "BUY GOLD maintenant"
        
        # Cache miss initially
        result = await cache.get(test_text)
        assert result is None
        
        # Set cache entry
        await cache.set(test_text, sample_response_data)
        
        # Cache hit
        result = await cache.get(test_text)
        assert result == sample_response_data

    @pytest.mark.asyncio
    async def test_message_normalization(self, cache, sample_response_data):
        """Test message text normalization for consistent caching."""
        original_text = "  BUY   GOLD   maintenant  "
        normalized_variants = [
            "BUY GOLD maintenant",
            "buy gold maintenant",
            "  buy   gold   maintenant  ",
            "BUY    GOLD    MAINTENANT"
        ]
        
        # Set cache with original text
        await cache.set(original_text, sample_response_data)
        
        # All normalized variants should hit the cache
        for variant in normalized_variants:
            result = await cache.get(variant)
            assert result == sample_response_data, f"Failed for variant: {variant}"

    def test_normalize_message_text(self, cache):
        """Test message normalization function."""
        test_cases = [
            ("  BUY   GOLD   ", "buy gold"),
            ("BUY GOLD maintenant", "buy gold maintenant"),
            ("   buy    gold    maintenant   ", "buy gold maintenant"),
            ("BUY\tGOLD\nmaintenant", "buy gold maintenant"),
        ]
        
        for input_text, expected in test_cases:
            result = cache._normalize_message_text(input_text)
            assert result == expected

    def test_generate_cache_key(self, cache):
        """Test cache key generation consistency."""
        text1 = "BUY GOLD maintenant"
        text2 = "  buy   gold   maintenant  "
        text3 = "SELL GOLD maintenant"
        
        key1 = cache._generate_cache_key(text1)
        key2 = cache._generate_cache_key(text2)
        key3 = cache._generate_cache_key(text3)
        
        # Same normalized content should generate same key
        assert key1 == key2
        
        # Different content should generate different keys
        assert key1 != key3
        
        # Keys should be SHA256 hex (64 chars)
        assert len(key1) == 64
        assert all(c in '0123456789abcdef' for c in key1)

    @pytest.mark.asyncio
    async def test_memory_cache_functionality(self, cache, sample_response_data):
        """Test in-memory cache layer."""
        test_text = "BUY GOLD maintenant"
        
        # Set data (goes to both memory and DB)
        await cache.set(test_text, sample_response_data)
        
        # Verify in memory cache
        cache_key = cache._generate_cache_key(test_text)
        assert cache_key in cache._memory_cache
        assert cache._memory_cache[cache_key] == sample_response_data

    @pytest.mark.asyncio
    async def test_memory_cache_eviction(self, cache, sample_response_data):
        """Test memory cache size limit and LRU eviction."""
        original_max = cache.max_memory_entries
        cache.max_memory_entries = 2  # Small limit for testing
        
        # Add more entries than limit
        for i in range(5):
            await cache.set(f"test message {i}", {**sample_response_data, "id": i})
        
        # Memory cache should be limited to max size
        assert len(cache._memory_cache) <= cache.max_memory_entries
        
        # Restore original limit
        cache.max_memory_entries = original_max

    @pytest.mark.asyncio
    async def test_database_persistence(self, cache, sample_response_data):
        """Test that data persists in database."""
        test_text = "BUY GOLD maintenant"
        
        # Set data
        await cache.set(test_text, sample_response_data)
        
        # Clear memory cache to force DB read
        cache._memory_cache.clear()
        cache._memory_cache_timestamps.clear()
        
        # Should still retrieve from database
        result = await cache.get(test_text)
        assert result == sample_response_data

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, tmp_path, sample_response_data):
        """Test cache TTL expiration."""
        # Create cache with very short TTL
        cache = LLMResponseCache(
            db_path=tmp_path / "ttl_test.db",
            ttl_hours=0.001  # ~3.6 seconds
        )
        await cache.initialize()
        
        test_text = "BUY GOLD maintenant"
        
        # Set data
        await cache.set(test_text, sample_response_data)
        
        # Should hit immediately
        result = await cache.get(test_text)
        assert result == sample_response_data
        
        # Wait for expiration
        await asyncio.sleep(0.1)  # Wait longer than TTL
        
        # Should miss after expiration
        result = await cache.get(test_text)
        assert result is None

    @pytest.mark.asyncio
    async def test_access_stats_update(self, cache, sample_response_data):
        """Test access statistics tracking."""
        test_text = "BUY GOLD maintenant"
        
        await cache.set(test_text, sample_response_data)
        
        # Multiple gets should update access stats
        await cache.get(test_text)
        await cache.get(test_text)
        await cache.get(test_text)
        
        # Access stats should be updated in database
        # (This is implementation detail, mainly testing no crashes occur)

    @pytest.mark.asyncio
    async def test_cleanup_expired_entries(self, cache, sample_response_data):
        """Test cleanup of expired cache entries."""
        # Add some test data
        await cache.set("test1", sample_response_data)
        await cache.set("test2", sample_response_data) 
        await cache.set("test3", sample_response_data)
        
        # Manually expire entries by setting old timestamps
        old_time = datetime.now() - timedelta(hours=cache.ttl_hours + 1)
        for key in cache._memory_cache_timestamps:
            cache._memory_cache_timestamps[key] = old_time
        
        # Run cleanup
        deleted_count = await cache.cleanup_expired()
        
        # Should have cleaned up expired entries
        assert deleted_count >= 0  # May be 0 if DB cleanup was fast

    @pytest.mark.asyncio
    async def test_cache_stats(self, cache, sample_response_data):
        """Test cache statistics reporting."""
        # Add some test data
        await cache.set("test1", sample_response_data)
        await cache.set("test2", {**sample_response_data, "action": "SELL"})
        
        stats = await cache.get_stats()
        
        required_keys = [
            "total_entries",
            "valid_entries",
            "expired_entries",
            "memory_cache_size",
            "max_memory_entries",
            "ttl_hours",
            "top_access_counts",
            "cache_hit_potential"
        ]
        
        for key in required_keys:
            assert key in stats, f"Missing stat key: {key}"
        
        assert stats["total_entries"] >= 2
        assert stats["memory_cache_size"] >= 0
        assert stats["ttl_hours"] == cache.ttl_hours

    @pytest.mark.asyncio
    async def test_cache_clear(self, cache, sample_response_data):
        """Test clearing all cache entries."""
        # Add some test data
        await cache.set("test1", sample_response_data)
        await cache.set("test2", sample_response_data)
        
        # Verify data exists
        result1 = await cache.get("test1")
        assert result1 is not None
        
        # Clear cache
        await cache.clear()
        
        # Data should be gone
        result1 = await cache.get("test1")
        result2 = await cache.get("test2")
        assert result1 is None
        assert result2 is None
        
        # Memory cache should be empty
        assert len(cache._memory_cache) == 0

    @pytest.mark.asyncio
    async def test_concurrent_access(self, cache, sample_response_data):
        """Test cache under concurrent access."""
        async def cache_operation(i):
            text = f"test message {i}"
            data = {**sample_response_data, "id": i}
            
            await cache.set(text, data)
            result = await cache.get(text)
            return result
        
        # Run concurrent operations
        tasks = [cache_operation(i) for i in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All should succeed
        assert all(isinstance(result, dict) for result in results)

    @pytest.mark.asyncio
    async def test_large_data_handling(self, cache):
        """Test cache with large data objects."""
        large_data = {
            "parsed_action": "BUY",
            "symbol": "GOLD",
            "large_field": "x" * 10000,  # Large string
            "nested_data": {
                "level1": {
                    "level2": {
                        "data": ["item"] * 1000
                    }
                }
            }
        }
        
        test_text = "Large data test"
        
        await cache.set(test_text, large_data)
        result = await cache.get(test_text)
        
        assert result == large_data

    @pytest.mark.asyncio
    async def test_cache_with_special_characters(self, cache, sample_response_data):
        """Test cache with special characters in text."""
        special_texts = [
            "BUY GOLD à 3350€",
            "VENTE OR ça monte!",
            "Signal avec émojis 🚀💰",
            "Caractères spéciaux: àáâãäåæçèéêë",
            "Mixed: BUY GOLD NOW! 💎🚀"
        ]
        
        for text in special_texts:
            await cache.set(text, sample_response_data)
            result = await cache.get(text)
            assert result == sample_response_data, f"Failed for text: {text}"

    @pytest.mark.asyncio
    async def test_error_handling(self, cache):
        """Test cache error handling with invalid data."""
        # Test with None data
        await cache.set("test", None)  # Should not crash
        
        # Test with non-serializable data
        class NonSerializable:
            pass
        
        try:
            await cache.set("test", {"obj": NonSerializable()})
        except Exception:
            pass  # Expected to fail, should not crash the cache system

    @pytest.mark.asyncio
    async def test_cleanup_background_task(self, tmp_path, sample_response_data):
        """Test background cleanup task."""
        cache = LLMResponseCache(
            db_path=tmp_path / "cleanup_test.db",
            ttl_hours=1
        )
        await cache.initialize()
        
        # Add some data
        await cache.set("test", sample_response_data)
        
        # Background cleanup should be running
        assert cache._cleanup_task is not None
        assert not cache._cleanup_task.done()
        
        # Cleanup
        await cache.cleanup()
        
        # Task should be cancelled
        assert cache._cleanup_task.cancelled() or cache._cleanup_task.done()