"""
Unit tests for repository classes.

This module tests all repository CRUD operations and specialized queries
using in-memory SQLite for fast execution.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.exc import IntegrityError

from src.database.models import (
    Base, Signal, Position, PositionUpdate, MessageCorrelation, LLMCache,
    HealthMetrics, Configuration, ParsedAction, ParserType, SignalStatus,
    PositionStatus, UpdateType, CorrelationType, HealthStatus
)
from src.database.repository import (
    DatabaseManager, SignalRepository, PositionRepository, CorrelationRepository,
    ConfigurationRepository, LLMCacheRepository, HealthMetricsRepository,
    RepositoryFactory, DatabaseError, RepositoryError
)


@pytest.fixture
async def db_manager() -> AsyncGenerator[DatabaseManager, None]:
    """Create in-memory database manager for testing."""
    manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await manager.initialize()
    
    # Create tables
    async with manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield manager
    
    await manager.close()


@pytest.fixture
async def signal_repo(db_manager: DatabaseManager) -> SignalRepository:
    """Create signal repository fixture."""
    return SignalRepository(db_manager)


@pytest.fixture
async def position_repo(db_manager: DatabaseManager) -> PositionRepository:
    """Create position repository fixture."""
    return PositionRepository(db_manager)


@pytest.fixture
async def correlation_repo(db_manager: DatabaseManager) -> CorrelationRepository:
    """Create correlation repository fixture."""
    return CorrelationRepository(db_manager)


@pytest.fixture
async def config_repo(db_manager: DatabaseManager) -> ConfigurationRepository:
    """Create configuration repository fixture."""
    return ConfigurationRepository(db_manager)


@pytest.fixture
async def llm_cache_repo(db_manager: DatabaseManager) -> LLMCacheRepository:
    """Create LLM cache repository fixture."""
    return LLMCacheRepository(db_manager)


@pytest.fixture
async def health_metrics_repo(db_manager: DatabaseManager) -> HealthMetricsRepository:
    """Create health metrics repository fixture."""
    return HealthMetricsRepository(db_manager)


@pytest.fixture
async def sample_signal_data() -> dict:
    """Sample signal data for testing."""
    return {
        'telegram_message_id': 12345,
        'telegram_chat_id': -100123456789,
        'sender': 'test_user',
        'timestamp': datetime.utcnow(),
        'raw_text': 'BUY GOLD at 2000 SL 1995 TP 2010',
        'parsed_action': ParsedAction.BUY,
        'symbol': 'GOLD',
        'entry_price': 2000.0,
        'stop_loss': 1995.0,
        'take_profit': 2010.0,
        'confidence_score': 0.95,
        'parser_type': ParserType.REGEX,
        'status': SignalStatus.PENDING
    }


@pytest.mark.asyncio
class TestDatabaseManager:
    """Test DatabaseManager class."""
    
    async def test_database_manager_initialization(self):
        """Test database manager initialization."""
        manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
        await manager.initialize()
        
        assert manager.engine is not None
        assert manager.session_factory is not None
        
        # Test session creation
        async with manager.get_session() as session:
            assert isinstance(session, AsyncSession)
        
        await manager.close()
    
    async def test_database_manager_transaction(self):
        """Test transaction context manager."""
        manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
        await manager.initialize()
        
        async with manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # Test successful transaction
        async with manager.get_transaction() as session:
            config = Configuration(key="test", value="value")
            session.add(config)
            # Transaction should commit automatically
        
        # Verify data was saved
        async with manager.get_session() as session:
            result = await session.get(Configuration, 1)
            assert result is not None
            assert result.key == "test"
        
        await manager.close()
    
    async def test_database_manager_transaction_rollback(self):
        """Test transaction rollback on error."""
        manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
        await manager.initialize()
        
        async with manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # Test failed transaction
        try:
            async with manager.get_transaction() as session:
                config = Configuration(key="test", value="value")
                session.add(config)
                await session.flush()
                
                # Add duplicate key to force error
                config2 = Configuration(key="test", value="value2")
                session.add(config2)
                await session.flush()
        except IntegrityError:
            pass  # Expected error
        
        # Verify no data was saved due to rollback
        async with manager.get_session() as session:
            result = await session.get(Configuration, 1)
            assert result is None
        
        await manager.close()


class TestSignalRepository:
    """Test SignalRepository class."""
    
    async def test_create_signal(self, signal_repo: SignalRepository, sample_signal_data: dict):
        """Test signal creation."""
        signal = await signal_repo.create(**sample_signal_data)
        
        assert signal.id is not None
        assert signal.telegram_message_id == 12345
        assert signal.symbol == 'GOLD'
        assert signal.status == SignalStatus.PENDING
    
    async def test_save_signal(self, signal_repo: SignalRepository, sample_signal_data: dict):
        """Test save_signal method."""
        signal_id = await signal_repo.save_signal(sample_signal_data)
        
        assert signal_id > 0
        
        # Verify signal was saved
        signal = await signal_repo.get_by_id(signal_id)
        assert signal is not None
        assert signal.telegram_message_id == 12345
    
    async def test_find_by_message_id(self, signal_repo: SignalRepository, sample_signal_data: dict):
        """Test find_by_message_id method."""
        await signal_repo.create(**sample_signal_data)
        
        signal = await signal_repo.find_by_message_id(12345)
        assert signal is not None
        assert signal.telegram_message_id == 12345
        assert signal.symbol == 'GOLD'
        
        # Test non-existent message ID
        signal = await signal_repo.find_by_message_id(99999)
        assert signal is None
    
    async def test_get_recent_signals(self, signal_repo: SignalRepository):
        """Test get_recent_signals method."""
        now = datetime.utcnow()
        
        # Create signals at different times
        old_signal_data = {
            'telegram_message_id': 11111,
            'telegram_chat_id': -100123456789,
            'sender': 'test_user',
            'timestamp': now - timedelta(hours=2),  # 2 hours ago
            'raw_text': 'OLD BUY GOLD',
            'parsed_action': ParsedAction.BUY,
            'symbol': 'GOLD',
            'parser_type': ParserType.REGEX
        }
        
        recent_signal_data = {
            'telegram_message_id': 22222,
            'telegram_chat_id': -100123456789,
            'sender': 'test_user',
            'timestamp': now - timedelta(minutes=30),  # 30 minutes ago
            'raw_text': 'RECENT BUY GOLD',
            'parsed_action': ParsedAction.BUY,
            'symbol': 'GOLD',
            'parser_type': ParserType.REGEX
        }
        
        await signal_repo.create(**old_signal_data)
        await signal_repo.create(**recent_signal_data)
        
        # Get recent signals (last 60 minutes)
        recent_signals = await signal_repo.get_recent_signals(minutes=60)
        assert len(recent_signals) == 1
        assert recent_signals[0].telegram_message_id == 22222
        
        # Get all signals (last 180 minutes)
        all_signals = await signal_repo.get_recent_signals(minutes=180)
        assert len(all_signals) == 2
    
    async def test_get_signals_by_symbol(self, signal_repo: SignalRepository):
        """Test get_signals_by_symbol method."""
        # Create signals for different symbols
        gold_data = {
            'telegram_message_id': 11111,
            'telegram_chat_id': -100123456789,
            'sender': 'test_user',
            'timestamp': datetime.utcnow(),
            'raw_text': 'BUY GOLD',
            'parsed_action': ParsedAction.BUY,
            'symbol': 'GOLD',
            'parser_type': ParserType.REGEX
        }
        
        eurusd_data = {
            'telegram_message_id': 22222,
            'telegram_chat_id': -100123456789,
            'sender': 'test_user',
            'timestamp': datetime.utcnow(),
            'raw_text': 'BUY EURUSD',
            'parsed_action': ParsedAction.BUY,
            'symbol': 'EURUSD',
            'parser_type': ParserType.REGEX
        }
        
        await signal_repo.create(**gold_data)
        await signal_repo.create(**eurusd_data)
        
        # Get GOLD signals
        gold_signals = await signal_repo.get_signals_by_symbol('GOLD')
        assert len(gold_signals) == 1
        assert gold_signals[0].symbol == 'GOLD'
        
        # Get EURUSD signals
        eurusd_signals = await signal_repo.get_signals_by_symbol('EURUSD')
        assert len(eurusd_signals) == 1
        assert eurusd_signals[0].symbol == 'EURUSD'
        
        # Get non-existent symbol
        none_signals = await signal_repo.get_signals_by_symbol('GBPUSD')
        assert len(none_signals) == 0
    
    async def test_update_signal_status(self, signal_repo: SignalRepository, sample_signal_data: dict):
        """Test update_signal_status method."""
        signal = await signal_repo.create(**sample_signal_data)
        signal_id = signal.id
        
        # Update status to VALIDATED
        success = await signal_repo.update_signal_status(signal_id, SignalStatus.VALIDATED)
        assert success is True
        
        # Verify update
        updated_signal = await signal_repo.get_by_id(signal_id)
        assert updated_signal.status == SignalStatus.VALIDATED
        
        # Update status to REJECTED with reason
        success = await signal_repo.update_signal_status(
            signal_id, 
            SignalStatus.REJECTED, 
            rejection_reason="Invalid price format"
        )
        assert success is True
        
        # Verify update with rejection reason
        updated_signal = await signal_repo.get_by_id(signal_id)
        assert updated_signal.status == SignalStatus.REJECTED
        assert updated_signal.rejection_reason == "Invalid price format"
        
        # Test non-existent signal
        success = await signal_repo.update_signal_status(99999, SignalStatus.VALIDATED)
        assert success is False


class TestPositionRepository:
    """Test PositionRepository class."""
    
    async def test_create_position(self, position_repo: PositionRepository, signal_repo: SignalRepository, sample_signal_data: dict):
        """Test position creation."""
        # Create signal first
        signal = await signal_repo.create(**sample_signal_data)
        
        position_data = {
            'signal_id': signal.id,
            'mt5_ticket': 123456,
            'open_time': datetime.utcnow(),
            'open_price': 2000.0,
            'volume': 0.1,
            'status': PositionStatus.OPEN
        }
        
        position = await position_repo.create(**position_data)
        
        assert position.id is not None
        assert position.signal_id == signal.id
        assert position.mt5_ticket == 123456
        assert position.volume == 0.1
        assert position.status == PositionStatus.OPEN
    
    async def test_get_position_by_ticket(self, position_repo: PositionRepository, signal_repo: SignalRepository, sample_signal_data: dict):
        """Test get_position_by_ticket method."""
        # Create signal and position
        signal = await signal_repo.create(**sample_signal_data)
        position_data = {
            'signal_id': signal.id,
            'mt5_ticket': 123456,
            'volume': 0.1,
            'status': PositionStatus.OPEN
        }
        await position_repo.create(**position_data)
        
        # Test finding by ticket
        position = await position_repo.get_position_by_ticket(123456)
        assert position is not None
        assert position.mt5_ticket == 123456
        
        # Test non-existent ticket
        position = await position_repo.get_position_by_ticket(999999)
        assert position is None
    
    async def test_update_position_status(self, position_repo: PositionRepository, signal_repo: SignalRepository, sample_signal_data: dict):
        """Test update_position_status method."""
        # Create signal and position
        signal = await signal_repo.create(**sample_signal_data)
        position_data = {
            'signal_id': signal.id,
            'mt5_ticket': 123456,
            'volume': 0.1,
            'status': PositionStatus.OPEN
        }
        position = await position_repo.create(**position_data)
        
        # Update status
        success = await position_repo.update_position_status(position.id, PositionStatus.CLOSED)
        assert success is True
        
        # Verify update
        updated_position = await position_repo.get_by_id(position.id)
        assert updated_position.status == PositionStatus.CLOSED
        assert updated_position.last_sync is not None
        
        # Test non-existent position
        success = await position_repo.update_position_status(99999, PositionStatus.CLOSED)
        assert success is False
    
    async def test_get_open_positions(self, position_repo: PositionRepository, signal_repo: SignalRepository, sample_signal_data: dict):
        """Test get_open_positions method."""
        # Create signal
        signal = await signal_repo.create(**sample_signal_data)
        
        # Create open position
        open_position_data = {
            'signal_id': signal.id,
            'mt5_ticket': 123456,
            'volume': 0.1,
            'status': PositionStatus.OPEN
        }
        await position_repo.create(**open_position_data)
        
        # Create closed position
        closed_position_data = {
            'signal_id': signal.id,
            'mt5_ticket': 123457,
            'volume': 0.1,
            'status': PositionStatus.CLOSED
        }
        await position_repo.create(**closed_position_data)
        
        # Get open positions
        open_positions = await position_repo.get_open_positions()
        assert len(open_positions) == 1
        assert open_positions[0].status == PositionStatus.OPEN
        assert open_positions[0].mt5_ticket == 123456
    
    async def test_get_positions_needing_sync(self, position_repo: PositionRepository, signal_repo: SignalRepository, sample_signal_data: dict):
        """Test get_positions_needing_sync method."""
        # Create signal
        signal = await signal_repo.create(**sample_signal_data)
        
        # Create position with old sync time
        old_sync_time = datetime.utcnow() - timedelta(minutes=10)
        old_position_data = {
            'signal_id': signal.id,
            'mt5_ticket': 123456,
            'volume': 0.1,
            'status': PositionStatus.OPEN,
            'last_sync': old_sync_time
        }
        await position_repo.create(**old_position_data)
        
        # Create position with recent sync time
        recent_position_data = {
            'signal_id': signal.id,
            'mt5_ticket': 123457,
            'volume': 0.1,
            'status': PositionStatus.OPEN,
            'last_sync': datetime.utcnow()
        }
        await position_repo.create(**recent_position_data)
        
        # Get positions needing sync (older than 5 minutes)
        positions_needing_sync = await position_repo.get_positions_needing_sync(max_age_minutes=5)
        assert len(positions_needing_sync) == 1
        assert positions_needing_sync[0].mt5_ticket == 123456


class TestCorrelationRepository:
    """Test CorrelationRepository class."""
    
    async def test_link_messages(self, correlation_repo: CorrelationRepository):
        """Test link_messages method."""
        correlation_id = await correlation_repo.link_messages(
            parent_id=12345,
            child_id=12346,
            correlation_type=CorrelationType.REPLY,
            confidence=0.95
        )
        
        assert correlation_id > 0
        
        # Verify correlation was created
        correlation = await correlation_repo.get_by_id(correlation_id)
        assert correlation is not None
        assert correlation.parent_message_id == 12345
        assert correlation.child_message_id == 12346
        assert correlation.correlation_type == CorrelationType.REPLY
        assert correlation.correlation_confidence == 0.95
    
    async def test_find_correlations_by_parent(self, correlation_repo: CorrelationRepository):
        """Test find_correlations_by_parent method."""
        # Create correlations
        await correlation_repo.link_messages(12345, 12346, CorrelationType.REPLY)
        await correlation_repo.link_messages(12345, 12347, CorrelationType.FOLLOWUP)
        await correlation_repo.link_messages(11111, 11112, CorrelationType.REPLY)
        
        # Find correlations by parent
        correlations = await correlation_repo.find_correlations_by_parent(12345)
        assert len(correlations) == 2
        
        child_ids = [c.child_message_id for c in correlations]
        assert 12346 in child_ids
        assert 12347 in child_ids
        
        # Test non-existent parent
        correlations = await correlation_repo.find_correlations_by_parent(99999)
        assert len(correlations) == 0
    
    async def test_find_correlations_by_child(self, correlation_repo: CorrelationRepository):
        """Test find_correlations_by_child method."""
        # Create correlations
        await correlation_repo.link_messages(12345, 12346, CorrelationType.REPLY)
        await correlation_repo.link_messages(12347, 12346, CorrelationType.EDIT)
        await correlation_repo.link_messages(11111, 11112, CorrelationType.REPLY)
        
        # Find correlations by child
        correlations = await correlation_repo.find_correlations_by_child(12346)
        assert len(correlations) == 2
        
        parent_ids = [c.parent_message_id for c in correlations]
        assert 12345 in parent_ids
        assert 12347 in parent_ids


class TestConfigurationRepository:
    """Test ConfigurationRepository class."""
    
    async def test_set_and_get_config_value(self, config_repo: ConfigurationRepository):
        """Test set_config_value and get_config_value methods."""
        # Set new config value
        success = await config_repo.set_config_value(
            "test_key", 
            "test_value", 
            "Test configuration"
        )
        assert success is True
        
        # Get config value
        value = await config_repo.get_config_value("test_key")
        assert value == "test_value"
        
        # Get with default value for non-existent key
        value = await config_repo.get_config_value("missing_key", "default")
        assert value == "default"
        
        # Update existing config value
        success = await config_repo.set_config_value("test_key", "updated_value")
        assert success is True
        
        # Verify update
        value = await config_repo.get_config_value("test_key")
        assert value == "updated_value"
    
    async def test_get_all_config(self, config_repo: ConfigurationRepository):
        """Test get_all_config method."""
        # Set multiple config values
        await config_repo.set_config_value("key1", "value1")
        await config_repo.set_config_value("key2", "value2")
        await config_repo.set_config_value("key3", "value3")
        
        # Get all config
        all_config = await config_repo.get_all_config()
        assert len(all_config) == 3
        assert all_config["key1"] == "value1"
        assert all_config["key2"] == "value2"
        assert all_config["key3"] == "value3"


class TestLLMCacheRepository:
    """Test LLMCacheRepository class."""
    
    async def test_cache_and_get_response(self, llm_cache_repo: LLMCacheRepository):
        """Test cache_response and get_cached_response methods."""
        # Cache a response
        cache_id = await llm_cache_repo.cache_response(
            input_hash="abc123",
            prompt_type="signal_parser",
            raw_message="BUY GOLD",
            parsed_response='{"action": "BUY", "symbol": "GOLD"}',
            confidence_score=0.85,
            expiry_hours=24
        )
        
        assert cache_id > 0
        
        # Get cached response
        cached = await llm_cache_repo.get_cached_response("abc123")
        assert cached is not None
        assert cached.input_hash == "abc123"
        assert cached.prompt_type == "signal_parser"
        assert cached.confidence_score == 0.85
        assert not cached.is_expired
        
        # Test non-existent cache
        cached = await llm_cache_repo.get_cached_response("nonexistent")
        assert cached is None
    
    async def test_cache_expired_response(self, llm_cache_repo: LLMCacheRepository):
        """Test that expired cache entries are not returned."""
        # Cache a response with immediate expiry
        await llm_cache_repo.cache_response(
            input_hash="expired123",
            prompt_type="signal_parser",
            raw_message="BUY GOLD",
            parsed_response='{"action": "BUY"}',
            expiry_hours=-1  # Expired 1 hour ago
        )
        
        # Try to get expired cache
        cached = await llm_cache_repo.get_cached_response("expired123")
        assert cached is None  # Should not return expired cache
    
    async def test_cleanup_expired_cache(self, llm_cache_repo: LLMCacheRepository):
        """Test cleanup_expired_cache method."""
        # Create expired and valid cache entries
        await llm_cache_repo.cache_response(
            input_hash="expired1",
            prompt_type="test",
            raw_message="test",
            parsed_response="test",
            expiry_hours=-1
        )
        await llm_cache_repo.cache_response(
            input_hash="valid1",
            prompt_type="test",
            raw_message="test",
            parsed_response="test",
            expiry_hours=24
        )
        
        # Verify total count before cleanup
        total_count = await llm_cache_repo.count()
        assert total_count == 2
        
        # Cleanup expired entries
        cleaned_count = await llm_cache_repo.cleanup_expired_cache()
        assert cleaned_count == 1
        
        # Verify remaining count
        remaining_count = await llm_cache_repo.count()
        assert remaining_count == 1


class TestHealthMetricsRepository:
    """Test HealthMetricsRepository class."""
    
    async def test_record_metric(self, health_metrics_repo: HealthMetricsRepository):
        """Test record_metric method."""
        metadata = {"threshold": 100, "current": 85}
        
        metric_id = await health_metrics_repo.record_metric(
            component="database",
            metric_name="connection_count",
            metric_value=5.0,
            status=HealthStatus.HEALTHY,
            extra_data=metadata
        )
        
        assert metric_id > 0
        
        # Verify metric was saved
        metric = await health_metrics_repo.get_by_id(metric_id)
        assert metric is not None
        assert metric.component == "database"
        assert metric.metric_name == "connection_count"
        assert metric.metric_value == 5.0
        assert metric.status == HealthStatus.HEALTHY
        assert metric.extra_data_dict == metadata
    
    async def test_get_latest_metrics(self, health_metrics_repo: HealthMetricsRepository):
        """Test get_latest_metrics method."""
        # Record metrics for different components
        await health_metrics_repo.record_metric(
            "database", "connections", 5.0, HealthStatus.HEALTHY
        )
        await health_metrics_repo.record_metric(
            "telegram", "messages_per_minute", 10.0, HealthStatus.WARNING
        )
        await health_metrics_repo.record_metric(
            "mt5", "latency_ms", 50.0, HealthStatus.HEALTHY
        )
        
        # Get all latest metrics
        all_metrics = await health_metrics_repo.get_latest_metrics()
        assert len(all_metrics) == 3
        
        # Get metrics for specific component
        db_metrics = await health_metrics_repo.get_latest_metrics(component="database")
        assert len(db_metrics) == 1
        assert db_metrics[0].component == "database"


class TestRepositoryFactory:
    """Test RepositoryFactory class."""
    
    async def test_repository_factory(self, db_manager: DatabaseManager):
        """Test repository factory creates correct instances."""
        factory = RepositoryFactory(db_manager)
        
        # Test all repository getters
        signal_repo = factory.get_signal_repository()
        assert isinstance(signal_repo, SignalRepository)
        
        position_repo = factory.get_position_repository()
        assert isinstance(position_repo, PositionRepository)
        
        correlation_repo = factory.get_correlation_repository()
        assert isinstance(correlation_repo, CorrelationRepository)
        
        config_repo = factory.get_configuration_repository()
        assert isinstance(config_repo, ConfigurationRepository)
        
        llm_cache_repo = factory.get_llm_cache_repository()
        assert isinstance(llm_cache_repo, LLMCacheRepository)
        
        health_metrics_repo = factory.get_health_metrics_repository()
        assert isinstance(health_metrics_repo, HealthMetricsRepository)
        
        # Test that repeated calls return same instances
        assert factory.get_signal_repository() is signal_repo
        assert factory.get_position_repository() is position_repo