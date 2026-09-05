"""
Unit tests for correlation engine components.

Tests correlation engine functionality including reply chain traversal,
time-based matching, and database persistence with performance benchmarks.
"""

import asyncio
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.correlation_engine.correlator import (
    CorrelationEngine, TelegramMessage, CorrelationResult
)
from src.correlation_engine.reply_tracer import ReplyTracer, ReplyChainCache
from src.correlation_engine.time_matcher import TimeMatcher, TimeMatchCandidate
from src.database.models import (
    Signal, Position, MessageCorrelation, CorrelationType,
    SignalStatus, PositionStatus, ParsedAction, ParserType
)


class TestCorrelationEngine:
    """Test suite for CorrelationEngine main functionality."""
    
    @pytest_asyncio.fixture
    async def mock_db_manager(self):
        """Mock database manager."""
        mock_db = MagicMock()
        mock_db.get_session = AsyncMock()
        mock_db.get_transaction = AsyncMock()
        return mock_db
    
    @pytest_asyncio.fixture
    async def mock_telegram_client(self):
        """Mock telegram client."""
        mock_client = MagicMock()
        mock_client.client = MagicMock()
        return mock_client
    
    @pytest_asyncio.fixture
    async def correlation_engine(self, mock_db_manager, mock_telegram_client):
        """Create correlation engine with mocked dependencies."""
        with patch('src.correlation_engine.correlator.RepositoryFactory'):
            engine = CorrelationEngine(mock_db_manager, mock_telegram_client)
            
            # Mock repositories
            engine.signal_repo = AsyncMock()
            engine.position_repo = AsyncMock()
            engine.correlation_repo = AsyncMock()
            
            return engine
    
    @pytest.fixture
    def sample_message(self):
        """Sample Telegram message for testing."""
        return TelegramMessage(
            telegram_message_id=12345,
            telegram_chat_id=67890,
            sender="test_user",
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            raw_text="BREAK EVEN",
            reply_to_message_id=11111
        )
    
    @pytest.fixture
    def sample_position(self):
        """Sample position for testing."""
        signal = Signal(
            id=1,
            telegram_message_id=11111,
            telegram_chat_id=67890,
            sender="signal_provider",
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2),
            raw_text="BUY GOLD 1950 SL 1940 TP 1960",
            parsed_action=ParsedAction.BUY,
            symbol="GOLD",
            entry_price=1950.0,
            stop_loss=1940.0,
            take_profit=1960.0,
            confidence_score=0.95,
            parser_type=ParserType.REGEX,
            status=SignalStatus.EXECUTED
        )
        
        position = Position(
            id=1,
            signal_id=1,
            mt5_ticket=123456,
            open_time=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2),
            open_price=1950.0,
            volume=0.1,
            current_sl=1940.0,
            current_tp=1960.0,
            profit=50.0,
            status=PositionStatus.OPEN
        )
        
        # Set up relationship
        position.signal = signal
        return position
    
    @pytest.mark.asyncio
    async def test_correlate_message_with_reply_success(self, correlation_engine, sample_message, sample_position):
        """Test successful correlation with reply chain."""
        # Setup mocks
        correlation_engine.reply_tracer = AsyncMock()
        correlation_engine.reply_tracer.trace_reply_chain = AsyncMock(return_value=11111)
        correlation_engine.get_position_by_message_id = AsyncMock(return_value=sample_position)
        correlation_engine.correlation_repo.link_messages = AsyncMock(return_value=999)
        
        # Execute
        result = await correlation_engine.correlate_message(sample_message)
        
        # Assertions
        assert result == sample_position
        assert correlation_engine._successful_correlations == 1
        assert correlation_engine._reply_correlations == 1
        correlation_engine.reply_tracer.trace_reply_chain.assert_called_once()
        correlation_engine.correlation_repo.link_messages.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_correlate_message_with_time_based_fallback(self, correlation_engine, sample_message, sample_position):
        """Test fallback to time-based correlation."""
        # Remove reply_to to force time-based matching
        sample_message.reply_to_message_id = None
        
        # Setup mocks
        correlation_engine.time_matcher = AsyncMock()
        correlation_engine.time_matcher.find_matches = AsyncMock(return_value=[{
            'position': sample_position,
            'confidence': 0.8,
            'time_score': 0.9,
            'text_score': 0.7,
            'metadata': {}
        }])
        correlation_engine.correlation_repo.link_messages = AsyncMock(return_value=999)
        
        # Execute
        result = await correlation_engine.correlate_message(sample_message)
        
        # Assertions
        assert result == sample_position
        assert correlation_engine._time_based_correlations == 1
        correlation_engine.time_matcher.find_matches.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_correlate_message_no_match(self, correlation_engine, sample_message):
        """Test correlation with no matches found."""
        # Setup mocks for no matches
        correlation_engine.reply_tracer = AsyncMock()
        correlation_engine.reply_tracer.trace_reply_chain = AsyncMock(return_value=None)
        correlation_engine.time_matcher = AsyncMock()
        correlation_engine.time_matcher.find_matches = AsyncMock(return_value=[])
        
        # Execute
        result = await correlation_engine.correlate_message(sample_message)
        
        # Assertions
        assert result is None
        assert correlation_engine._successful_correlations == 0
    
    @pytest.mark.asyncio
    async def test_get_position_by_message_id(self, correlation_engine, sample_position):
        """Test position retrieval by message ID."""
        # Setup mocks
        correlation_engine.signal_repo.find_by_message_id = AsyncMock(return_value=sample_position.signal)
        correlation_engine.position_repo.get_positions_by_signal = AsyncMock(return_value=[sample_position])
        
        # Execute
        result = await correlation_engine.get_position_by_message_id(11111)
        
        # Assertions
        assert result == sample_position
        correlation_engine.signal_repo.find_by_message_id.assert_called_once_with(11111)
    
    def test_get_correlation_stats(self, correlation_engine):
        """Test correlation statistics retrieval."""
        # Set up some stats
        correlation_engine._correlation_attempts = 10
        correlation_engine._successful_correlations = 8
        correlation_engine._reply_correlations = 5
        correlation_engine._time_based_correlations = 3
        
        # Execute
        stats = correlation_engine.get_correlation_stats()
        
        # Assertions
        assert stats['total_attempts'] == 10
        assert stats['successful_correlations'] == 8
        assert stats['success_rate'] == 0.8
        assert stats['reply_correlations'] == 5
        assert stats['time_based_correlations'] == 3


class TestReplyTracer:
    """Test suite for ReplyTracer functionality."""
    
    @pytest.fixture
    def mock_telegram_client(self):
        """Mock Telegram client for testing."""
        mock_client = MagicMock()
        mock_client.client = AsyncMock()
        return mock_client
    
    @pytest.fixture
    def reply_tracer(self, mock_telegram_client):
        """Create reply tracer with mocked client."""
        return ReplyTracer(mock_telegram_client, max_depth=5)
    
    @pytest.mark.asyncio
    async def test_trace_reply_chain_single_level(self, reply_tracer):
        """Test tracing single-level reply chain."""
        # Mock message with no reply_to (root message)
        mock_message = MagicMock()
        mock_message.reply_to = None
        
        reply_tracer.telegram_client.client.get_messages = AsyncMock(return_value=[mock_message])
        
        # Execute
        result = await reply_tracer.trace_reply_chain(12345, 67890)
        
        # Assertions
        assert result == 12345  # Should return the same ID (root)
        assert reply_tracer._api_calls == 1
    
    @pytest.mark.asyncio
    async def test_trace_reply_chain_multi_level(self, reply_tracer):
        """Test tracing multi-level reply chain."""
        # Create chain: 12345 -> 11111 -> 10000 (root)
        mock_message_1 = MagicMock()
        mock_message_1.reply_to = MagicMock()
        mock_message_1.reply_to.reply_to_msg_id = 11111
        
        mock_message_2 = MagicMock()
        mock_message_2.reply_to = MagicMock()
        mock_message_2.reply_to.reply_to_msg_id = 10000
        
        mock_message_3 = MagicMock()  # Root message
        mock_message_3.reply_to = None
        
        # Configure client to return appropriate message for each call
        reply_tracer.telegram_client.client.get_messages = AsyncMock(
            side_effect=[[mock_message_1], [mock_message_2], [mock_message_3]]
        )
        
        # Execute
        result = await reply_tracer.trace_reply_chain(12345, 67890)
        
        # Assertions
        assert result == 10000  # Root message ID
        assert reply_tracer._api_calls == 3
        assert reply_tracer.telegram_client.client.get_messages.call_count == 3
    
    @pytest.mark.asyncio
    async def test_trace_reply_chain_with_cache(self, reply_tracer):
        """Test reply chain tracing with cache hit."""
        # Put result in cache
        reply_tracer.cache.put(67890, 12345, 10000)
        
        # Execute
        result = await reply_tracer.trace_reply_chain(12345, 67890)
        
        # Assertions
        assert result == 10000
        assert reply_tracer._cache_hits == 1
        assert reply_tracer._api_calls == 0  # No API calls due to cache hit
    
    @pytest.mark.asyncio
    async def test_trace_reply_chain_max_depth_protection(self, reply_tracer):
        """Test protection against infinite loops."""
        # Create circular reference: A -> B -> A
        mock_message = MagicMock()
        mock_message.reply_to = MagicMock()
        mock_message.reply_to.reply_to_msg_id = 12345  # Points back to itself
        
        reply_tracer.telegram_client.client.get_messages = AsyncMock(return_value=[mock_message])
        
        # Execute
        result = await reply_tracer.trace_reply_chain(12345, 67890)
        
        # Should break the loop and return the deepest message found or None on circular reference
        # In this case, it returns 12345 as it's the message we found (even if circular)
        assert result == 12345 or result is None  # Both are valid responses to circular refs
    
    def test_get_tracer_stats(self, reply_tracer):
        """Test tracer statistics."""
        reply_tracer._chain_requests = 5
        reply_tracer._cache_hits = 2
        reply_tracer._api_calls = 8
        reply_tracer._chain_depths = [1, 2, 1, 3, 2]
        
        stats = reply_tracer.get_tracer_stats()
        
        assert stats['chain_requests'] == 5
        assert stats['cache_hit_rate'] == 0.4
        assert stats['api_calls'] == 8
        assert stats['average_chain_depth'] == 1.8


class TestReplyChainCache:
    """Test suite for ReplyChainCache functionality."""
    
    @pytest.fixture
    def cache(self):
        """Create cache for testing."""
        return ReplyChainCache(max_entries=5, ttl_minutes=1)
    
    def test_cache_put_and_get(self, cache):
        """Test basic cache put and get operations."""
        cache.put(12345, 67890, 99999)
        result = cache.get(12345, 67890)
        assert result == 99999
    
    def test_cache_expiration(self, cache):
        """Test cache entry expiration."""
        # Use very short TTL
        cache.ttl_seconds = 0.1
        
        cache.put(12345, 67890, 99999)
        
        # Wait for expiration
        import time
        time.sleep(0.2)
        
        result = cache.get(12345, 67890)
        assert result is None
    
    def test_cache_eviction(self, cache):
        """Test cache eviction when full."""
        # Fill cache beyond capacity
        for i in range(10):
            cache.put(i, i, i)
        
        # Check that size is within limits
        assert len(cache._cache) <= cache.max_entries
    
    def test_cache_stats(self, cache):
        """Test cache statistics."""
        cache.put(1, 1, 1)
        cache.put(2, 2, 2)
        
        stats = cache.get_stats()
        assert stats['total_entries'] == 2
        assert stats['active_entries'] <= 2


class TestTimeMatcher:
    """Test suite for TimeMatcher functionality."""
    
    @pytest.fixture
    def mock_repos(self):
        """Mock repositories for time matcher."""
        signal_repo = AsyncMock()
        position_repo = AsyncMock()
        return signal_repo, position_repo
    
    @pytest.fixture
    def time_matcher(self, mock_repos):
        """Create time matcher with mocked repos."""
        signal_repo, position_repo = mock_repos
        return TimeMatcher(signal_repo, position_repo)
    
    @pytest.fixture
    def sample_message_for_matching(self):
        """Sample message for time matching."""
        return TelegramMessage(
            telegram_message_id=12345,
            telegram_chat_id=67890,
            sender="test_user",
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            raw_text="break even please",
            reply_to_message_id=None
        )
    
    @pytest.mark.asyncio
    async def test_find_matches_success(self, time_matcher, sample_message_for_matching):
        """Test successful time-based matching."""
        # Create mock signal and position
        mock_signal = Signal(
            id=1,
            telegram_message_id=11111,
            telegram_chat_id=67890,
            sender="provider",
            timestamp=sample_message_for_matching.timestamp - timedelta(minutes=2),
            raw_text="BUY GOLD 1950",
            parsed_action=ParsedAction.BUY,
            symbol="GOLD",
            confidence_score=0.9,
            parser_type=ParserType.REGEX,
            status=SignalStatus.EXECUTED
        )
        
        mock_position = Position(
            id=1,
            signal_id=1,
            open_time=mock_signal.timestamp,
            open_price=1950.0,
            volume=0.1,
            status=PositionStatus.OPEN
        )
        mock_position.signal = mock_signal
        
        # Setup repository mocks
        time_matcher.signal_repo.get_recent_signals = AsyncMock(return_value=[mock_signal])
        time_matcher.position_repo.get_positions_by_signal = AsyncMock(return_value=[mock_position])
        time_matcher.signal_repo.get_by_id = AsyncMock(return_value=mock_signal)
        
        # Execute
        matches = await time_matcher.find_matches(sample_message_for_matching)
        
        # Assertions
        assert len(matches) > 0
        assert matches[0]['position'] == mock_position
        assert matches[0]['confidence'] > 0.0
    
    @pytest.mark.asyncio
    async def test_find_matches_no_candidates(self, time_matcher, sample_message_for_matching):
        """Test time matching with no candidate positions."""
        # Setup empty results
        time_matcher.signal_repo.get_recent_signals = AsyncMock(return_value=[])
        
        # Execute
        matches = await time_matcher.find_matches(sample_message_for_matching)
        
        # Assertions
        assert len(matches) == 0
    
    def test_calculate_time_score(self, time_matcher):
        """Test time score calculation."""
        base_time = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # Same time should give high score
        score1 = time_matcher._calculate_time_score(base_time, base_time)
        assert score1 == 1.0
        
        # 1 minute difference should give good score
        score2 = time_matcher._calculate_time_score(
            base_time, base_time - timedelta(minutes=1)
        )
        assert score2 > 0.8
        
        # 5 minute difference should give minimum score
        score3 = time_matcher._calculate_time_score(
            base_time, base_time - timedelta(minutes=5)
        )
        assert score3 == 0.6
    
    def test_calculate_text_score(self, time_matcher):
        """Test text similarity scoring."""
        # High similarity
        score1 = time_matcher._calculate_text_score(
            "break even", "BUY GOLD entry price"
        )
        assert score1 > 0.5
        
        # Low similarity
        score2 = time_matcher._calculate_text_score(
            "unrelated text", "completely different content"
        )
        assert score2 >= 0.5  # Base score
        
        # Update pattern match
        score3 = time_matcher._calculate_text_score(
            "close position", "SELL GOLD"
        )
        assert score3 > 0.5
    
    def test_extract_symbols(self, time_matcher):
        """Test symbol extraction from text."""
        # Test GOLD detection
        symbols1 = time_matcher._extract_symbols("break even gold position")
        assert 'GOLD' in symbols1 or 'XAUUSD' in symbols1
        
        # Test EUR detection
        symbols2 = time_matcher._extract_symbols("close eur trade")
        assert 'EURUSD' in symbols2
        
        # Test no symbols
        symbols3 = time_matcher._extract_symbols("random text")
        assert len(symbols3) == 0


@pytest.mark.performance
class TestPerformanceBenchmarks:
    """Performance tests for correlation engine."""
    
    @pytest_asyncio.fixture
    async def performance_engine(self):
        """Create correlation engine for performance testing."""
        mock_db = MagicMock()
        mock_client = MagicMock()
        
        with patch('src.correlation_engine.correlator.RepositoryFactory'):
            engine = CorrelationEngine(mock_db, mock_client)
            engine.signal_repo = AsyncMock()
            engine.position_repo = AsyncMock()
            engine.correlation_repo = AsyncMock()
            return engine
    
    @pytest.mark.asyncio
    async def test_correlation_performance_benchmark(self, performance_engine):
        """Test correlation performance meets <50ms target."""
        # Create sample message
        message = TelegramMessage(
            telegram_message_id=12345,
            telegram_chat_id=67890,
            sender="test",
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            raw_text="test message",
            reply_to_message_id=None
        )
        
        # Mock for fast response
        performance_engine.time_matcher = AsyncMock()
        performance_engine.time_matcher.find_matches = AsyncMock(return_value=[])
        
        # Measure performance
        import time
        start_time = time.time()
        
        await performance_engine.correlate_message(message)
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Assert performance target
        assert duration_ms < 50, f"Correlation took {duration_ms:.1f}ms, exceeds 50ms target"
    
    @pytest.mark.asyncio
    async def test_concurrent_correlations(self, performance_engine):
        """Test concurrent correlation processing."""
        # Create multiple messages
        messages = [
            TelegramMessage(
                telegram_message_id=i,
                telegram_chat_id=67890,
                sender="test",
                timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
                raw_text=f"message {i}",
                reply_to_message_id=None
            )
            for i in range(10)
        ]
        
        # Mock for fast response
        performance_engine.time_matcher = AsyncMock()
        performance_engine.time_matcher.find_matches = AsyncMock(return_value=[])
        
        # Process concurrently
        import time
        start_time = time.time()
        
        tasks = [performance_engine.correlate_message(msg) for msg in messages]
        results = await asyncio.gather(*tasks)
        
        duration_ms = (time.time() - start_time) * 1000
        
        # All should complete successfully
        assert len(results) == 10
        
        # Average time per correlation should be reasonable
        avg_time_ms = duration_ms / 10
        assert avg_time_ms < 20, f"Average correlation time {avg_time_ms:.1f}ms too high"