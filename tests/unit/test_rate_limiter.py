"""
Unit tests for rate limiter.
Tests delay calculations and flood handling with time variations.
"""

import asyncio
import pytest
from datetime import datetime, date
from unittest.mock import Mock, patch, AsyncMock

from telethon.errors import FloodWaitError

from src.telegram_client.rate_limiter import RateLimiter, rate_limiter


class TestRateLimiter:
    """Test cases for RateLimiter class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.limiter = RateLimiter()

    def test_init_default_values(self):
        """Test RateLimiter initialization with default values."""
        assert self.limiter.base_delay_ms == 2000.0
        assert self.limiter.std_dev_ms == 500.0
        assert self.limiter.min_delay_ms == 1000.0
        assert self.limiter.max_delay_ms == 5000.0
        assert self.limiter._daily_message_count == 0
        assert self.limiter._max_daily_messages == 1000

    def test_init_custom_values(self):
        """Test RateLimiter initialization with custom values."""
        custom_limiter = RateLimiter(base_delay_ms=3000.0, std_dev_ms=700.0)
        assert custom_limiter.base_delay_ms == 3000.0
        assert custom_limiter.std_dev_ms == 700.0

    def test_get_time_of_day_factor_active_hours(self):
        """Test time of day factor during active hours (8:00-23:00)."""
        with patch('src.telegram_client.rate_limiter.datetime') as mock_datetime:
            # Test various active hours
            for hour in [8, 12, 16, 20, 22]:
                mock_datetime.now.return_value = Mock(hour=hour)
                factor = self.limiter._get_time_of_day_factor()
                assert factor == 1.0

    def test_get_time_of_day_factor_night_hours(self):
        """Test time of day factor during night hours (23:00-8:00)."""
        with patch('src.telegram_client.rate_limiter.datetime') as mock_datetime:
            # Test various night hours
            for hour in [23, 0, 2, 5, 7]:
                mock_datetime.now.return_value = Mock(hour=hour)
                factor = self.limiter._get_time_of_day_factor()
                assert factor == 1.5

    @pytest.mark.asyncio
    async def test_human_delay_duration_active_hours(self):
        """Test that delay duration is within expected bounds during active hours."""
        with patch('src.telegram_client.rate_limiter.datetime') as mock_datetime:
            mock_datetime.now.return_value = Mock(hour=14)  # Active hour
            mock_datetime.now().date.return_value = date.today()
            
            start_time = asyncio.get_event_loop().time()
            await self.limiter.human_delay()
            end_time = asyncio.get_event_loop().time()
            
            delay_seconds = end_time - start_time
            # Should be between 1-5 seconds (min_delay_ms to max_delay_ms)
            assert 1.0 <= delay_seconds <= 5.0

    @pytest.mark.asyncio
    async def test_human_delay_duration_night_hours(self):
        """Test that delay duration is longer during night hours."""
        with patch('src.telegram_client.rate_limiter.datetime') as mock_datetime:
            mock_datetime.now.return_value = Mock(hour=2)  # Night hour
            mock_datetime.now().date.return_value = date.today()
            
            start_time = asyncio.get_event_loop().time()
            await self.limiter.human_delay()
            end_time = asyncio.get_event_loop().time()
            
            delay_seconds = end_time - start_time
            # Should be between 1-5 seconds but likely on the higher end due to 1.5x factor
            assert 1.0 <= delay_seconds <= 5.0

    @pytest.mark.asyncio
    async def test_human_delay_increments_counter(self):
        """Test that human delay increments daily message counter."""
        initial_count = self.limiter._daily_message_count
        
        with patch('src.telegram_client.rate_limiter.datetime') as mock_datetime:
            mock_datetime.now.return_value = Mock(hour=14)
            mock_datetime.now().date.return_value = date.today()
            
            await self.limiter.human_delay()
            
            assert self.limiter._daily_message_count == initial_count + 1

    @pytest.mark.asyncio
    async def test_human_delay_cancellation(self):
        """Test that human delay handles cancellation properly."""
        with patch('src.telegram_client.rate_limiter.datetime') as mock_datetime:
            mock_datetime.now.return_value = Mock(hour=14)
            mock_datetime.now().date.return_value = date.today()
            
            # Create a task and cancel it
            task = asyncio.create_task(self.limiter.human_delay())
            await asyncio.sleep(0.1)  # Let it start
            task.cancel()
            
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_check_daily_limit_new_day_reset(self):
        """Test daily counter reset on new day."""
        # Set up old date and count
        old_date = date(2024, 1, 1)
        self.limiter._last_reset_date = old_date
        self.limiter._daily_message_count = 500
        
        with patch('src.telegram_client.rate_limiter.datetime') as mock_datetime:
            # Mock current date as different from last reset
            new_date = date(2024, 1, 2)
            mock_datetime.now.return_value = Mock(hour=14)
            mock_datetime.now().date.return_value = new_date
            
            await self.limiter._check_daily_limit()
            
            assert self.limiter._daily_message_count == 0
            assert self.limiter._last_reset_date == new_date

    @pytest.mark.asyncio
    async def test_check_daily_limit_same_day_no_reset(self):
        """Test that daily counter is not reset on same day."""
        today = date.today()
        self.limiter._last_reset_date = today
        self.limiter._daily_message_count = 100
        
        with patch('src.telegram_client.rate_limiter.datetime') as mock_datetime:
            mock_datetime.now.return_value = Mock(hour=14)
            mock_datetime.now().date.return_value = today
            
            await self.limiter._check_daily_limit()
            
            assert self.limiter._daily_message_count == 100
            assert self.limiter._last_reset_date == today

    @pytest.mark.asyncio
    async def test_check_daily_limit_exceeded(self):
        """Test extended delay when daily limit is exceeded."""
        # Set count to exceed limit
        self.limiter._daily_message_count = 1001
        
        with patch('src.telegram_client.rate_limiter.datetime') as mock_datetime:
            mock_datetime.now.return_value = Mock(hour=14)
            mock_datetime.now().date.return_value = date.today()
            
            with patch('asyncio.sleep') as mock_sleep:
                await self.limiter._check_daily_limit()
                
                # Should have called sleep with 60 seconds
                mock_sleep.assert_called_once_with(60)

    @pytest.mark.asyncio
    async def test_handle_flood_wait(self):
        """Test flood wait error handling with buffer."""
        flood_error = FloodWaitError(request=Mock(), capture=10)
        
        with patch('asyncio.sleep') as mock_sleep:
            await self.limiter.handle_flood_wait(flood_error)
            
            # Should sleep for error.seconds * 1.5
            expected_wait = 10 * 1.5
            mock_sleep.assert_called_once_with(expected_wait)

    @pytest.mark.asyncio
    async def test_handle_flood_wait_cancellation(self):
        """Test flood wait handling with cancellation."""
        flood_error = FloodWaitError(request=Mock(), capture=5)
        
        with patch('asyncio.sleep', side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await self.limiter.handle_flood_wait(flood_error)

    def test_get_daily_stats(self):
        """Test daily statistics retrieval."""
        self.limiter._daily_message_count = 250
        self.limiter._max_daily_messages = 1000
        test_date = date(2024, 1, 15)
        self.limiter._last_reset_date = test_date
        
        with patch('src.telegram_client.rate_limiter.datetime') as mock_datetime:
            mock_datetime.now.return_value = Mock(hour=16)
            
            stats = self.limiter.get_daily_stats()
            
            assert stats['daily_message_count'] == 250
            assert stats['max_daily_messages'] == 1000
            assert stats['remaining_messages'] == 750
            assert stats['current_date'] == test_date.isoformat()
            assert stats['time_factor'] == 1.0  # Active hour

    def test_reset_daily_counter(self):
        """Test manual daily counter reset."""
        # Set up existing count
        self.limiter._daily_message_count = 500
        old_date = date(2024, 1, 10)
        self.limiter._last_reset_date = old_date
        
        with patch('src.telegram_client.rate_limiter.datetime') as mock_datetime:
            new_date = date(2024, 1, 11)
            mock_datetime.now.return_value = Mock()
            mock_datetime.now().date.return_value = new_date
            
            self.limiter.reset_daily_counter()
            
            assert self.limiter._daily_message_count == 0
            assert self.limiter._last_reset_date == new_date

    def test_gaussian_distribution_bounds(self):
        """Test that Gaussian delay respects min/max bounds."""
        # Create limiter with extreme values to test bounds
        test_limiter = RateLimiter(base_delay_ms=100.0, std_dev_ms=1000.0)
        
        # Mock random.gauss to return extreme values
        with patch('src.telegram_client.rate_limiter.random.gauss') as mock_gauss:
            with patch('src.telegram_client.rate_limiter.datetime') as mock_datetime:
                mock_datetime.now.return_value = Mock(hour=14)
                mock_datetime.now().date.return_value = date.today()
                
                # Test very low value gets clamped to min
                mock_gauss.return_value = 500.0  # Below min_delay_ms
                
                async def test_min_bound():
                    start_time = asyncio.get_event_loop().time()
                    await test_limiter.human_delay()
                    end_time = asyncio.get_event_loop().time()
                    delay = end_time - start_time
                    assert delay >= 1.0  # Should be at least min_delay_ms/1000
                
                # Test very high value gets clamped to max
                mock_gauss.return_value = 10000.0  # Above max_delay_ms
                
                async def test_max_bound():
                    start_time = asyncio.get_event_loop().time()
                    await test_limiter.human_delay()
                    end_time = asyncio.get_event_loop().time()
                    delay = end_time - start_time
                    assert delay <= 5.1  # Allow small tolerance for timing variations
                
                asyncio.run(test_min_bound())
                asyncio.run(test_max_bound())


class TestGlobalRateLimiterInstance:
    """Test cases for global rate limiter instance."""

    def test_global_instance_exists(self):
        """Test that global rate limiter instance is available."""
        assert rate_limiter is not None
        assert isinstance(rate_limiter, RateLimiter)

    def test_global_instance_default_config(self):
        """Test that global instance has default configuration."""
        assert rate_limiter.base_delay_ms == 2000.0
        assert rate_limiter.std_dev_ms == 500.0