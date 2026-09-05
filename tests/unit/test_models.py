"""
Unit tests for SQLAlchemy models.

This module tests all database models including validation scenarios,
relationships, and custom methods.
"""

import pytest
import json
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError

from src.database.models import (
    Configuration, Signal, Position, PositionUpdate, MessageCorrelation,
    LLMCache, HealthMetrics, ParsedAction, ParserType, SignalStatus,
    PositionStatus, UpdateType, CorrelationType, HealthStatus
)


class TestConfiguration:
    """Test Configuration model."""
    
    def test_configuration_creation(self):
        """Test basic configuration creation."""
        config = Configuration(
            key="test_key",
            value="test_value",
            description="Test configuration"
        )
        assert config.key == "test_key"
        assert config.value == "test_value"
        assert config.description == "Test configuration"
        assert config.created_at is None  # Not set until saved
        assert config.updated_at is None
    
    def test_configuration_repr(self):
        """Test configuration string representation."""
        config = Configuration(key="test_key", value="test_value")
        assert repr(config) == "<Configuration(key='test_key', value='test_value')>"


class TestSignal:
    """Test Signal model."""
    
    def test_signal_creation(self):
        """Test basic signal creation."""
        signal = Signal(
            telegram_message_id=12345,
            telegram_chat_id=-100123456789,
            sender="test_user",
            timestamp=datetime.utcnow(),
            raw_text="BUY GOLD at 2000 SL 1995 TP 2010",
            parsed_action=ParsedAction.BUY,
            symbol="GOLD",
            entry_price=2000.0,
            stop_loss=1995.0,
            take_profit=2010.0,
            confidence_score=0.95,
            parser_type=ParserType.REGEX,
            status=SignalStatus.PENDING
        )
        
        assert signal.telegram_message_id == 12345
        assert signal.parsed_action == ParsedAction.BUY
        assert signal.symbol == "GOLD"
        assert signal.entry_price == 2000.0
        assert signal.confidence_score == 0.95
        assert signal.status == SignalStatus.PENDING
    
    def test_signal_to_dict(self):
        """Test signal dictionary conversion."""
        timestamp = datetime.utcnow()
        signal = Signal(
            telegram_message_id=12345,
            telegram_chat_id=-100123456789,
            sender="test_user",
            timestamp=timestamp,
            raw_text="BUY GOLD at 2000",
            parsed_action=ParsedAction.BUY,
            symbol="GOLD",
            entry_price=2000.0,
            parser_type=ParserType.REGEX,
            confidence_score=0.8
        )
        
        result = signal.to_dict()
        assert result['telegram_message_id'] == 12345
        assert result['parsed_action'] == 'BUY'
        assert result['symbol'] == 'GOLD'
        assert result['confidence_score'] == 0.8
        assert result['timestamp'] == timestamp.isoformat()
    
    def test_signal_validation_confidence_score(self):
        """Test confidence score validation."""
        # Valid confidence scores should work
        signal = Signal(
            telegram_message_id=12345,
            telegram_chat_id=-100123456789,
            sender="test_user",
            timestamp=datetime.utcnow(),
            raw_text="test",
            parsed_action=ParsedAction.BUY,
            symbol="GOLD",
            parser_type=ParserType.REGEX,
            confidence_score=0.5
        )
        assert signal.confidence_score == 0.5
        
        # Test boundary values
        signal.confidence_score = 0.0
        assert signal.confidence_score == 0.0
        
        signal.confidence_score = 1.0
        assert signal.confidence_score == 1.0
    
    def test_signal_repr(self):
        """Test signal string representation."""
        signal = Signal(
            id=1,
            parsed_action=ParsedAction.BUY,
            symbol="GOLD",
            status=SignalStatus.PENDING
        )
        expected = "<Signal(id=1, action=ParsedAction.BUY, symbol=GOLD, status=SignalStatus.PENDING)>"
        assert repr(signal) == expected


class TestPosition:
    """Test Position model."""
    
    def test_position_creation(self):
        """Test basic position creation."""
        position = Position(
            signal_id=1,
            mt5_ticket=123456,
            open_time=datetime.utcnow(),
            open_price=2000.0,
            volume=0.1,
            current_sl=1995.0,
            current_tp=2010.0,
            status=PositionStatus.OPEN
        )
        
        assert position.signal_id == 1
        assert position.mt5_ticket == 123456
        assert position.volume == 0.1
        assert position.status == PositionStatus.OPEN
    
    def test_position_is_open_property(self):
        """Test is_open property."""
        position = Position(signal_id=1, volume=0.1, status=PositionStatus.OPEN)
        assert position.is_open is True
        
        position.status = PositionStatus.CLOSED
        assert position.is_open is False
    
    def test_position_total_pnl_property(self):
        """Test total P&L calculation."""
        position = Position(
            signal_id=1,
            volume=0.1,
            profit=100.0,
            commission=-5.0,
            swap=-2.0
        )
        assert position.total_pnl == 93.0
    
    def test_position_to_dict(self):
        """Test position dictionary conversion."""
        open_time = datetime.utcnow()
        position = Position(
            id=1,
            signal_id=2,
            mt5_ticket=123456,
            open_time=open_time,
            volume=0.1,
            profit=50.0,
            commission=-2.0,
            swap=-1.0,
            status=PositionStatus.OPEN
        )
        
        result = position.to_dict()
        assert result['id'] == 1
        assert result['signal_id'] == 2
        assert result['mt5_ticket'] == 123456
        assert result['volume'] == 0.1
        assert result['total_pnl'] == 47.0
        assert result['status'] == 'OPEN'
        assert result['open_time'] == open_time.isoformat()
    
    def test_position_repr(self):
        """Test position string representation."""
        position = Position(
            id=1,
            mt5_ticket=123456,
            status=PositionStatus.OPEN,
            profit=100.0
        )
        expected = "<Position(id=1, mt5_ticket=123456, status=PositionStatus.OPEN, profit=100.0)>"
        assert repr(position) == expected


class TestPositionUpdate:
    """Test PositionUpdate model."""
    
    def test_position_update_creation(self):
        """Test basic position update creation."""
        update = PositionUpdate(
            position_id=1,
            update_type=UpdateType.SL_MODIFY,
            field_name="current_sl",
            old_value="1995.0",
            new_value="2000.0",
            telegram_message_id=12345,
            success=True
        )
        
        assert update.position_id == 1
        assert update.update_type == UpdateType.SL_MODIFY
        assert update.field_name == "current_sl"
        assert update.success is True
    
    def test_position_update_to_dict(self):
        """Test position update dictionary conversion."""
        timestamp = datetime.utcnow()
        update = PositionUpdate(
            id=1,
            position_id=2,
            update_type=UpdateType.TP_MODIFY,
            field_name="current_tp",
            old_value="2010.0",
            new_value="2015.0",
            success=True,
            timestamp=timestamp
        )
        
        result = update.to_dict()
        assert result['id'] == 1
        assert result['position_id'] == 2
        assert result['update_type'] == 'TP_MODIFY'
        assert result['field_name'] == 'current_tp'
        assert result['success'] is True
        assert result['timestamp'] == timestamp.isoformat()
    
    def test_position_update_repr(self):
        """Test position update string representation."""
        update = PositionUpdate(
            id=1,
            update_type=UpdateType.BREAK_EVEN,
            success=True
        )
        expected = "<PositionUpdate(id=1, type=UpdateType.BREAK_EVEN, success=True)>"
        assert repr(update) == expected


class TestMessageCorrelation:
    """Test MessageCorrelation model."""
    
    def test_message_correlation_creation(self):
        """Test basic message correlation creation."""
        correlation = MessageCorrelation(
            parent_message_id=12345,
            child_message_id=12346,
            correlation_type=CorrelationType.REPLY,
            correlation_confidence=0.95,
            position_id=1
        )
        
        assert correlation.parent_message_id == 12345
        assert correlation.child_message_id == 12346
        assert correlation.correlation_type == CorrelationType.REPLY
        assert correlation.correlation_confidence == 0.95
        assert correlation.position_id == 1
    
    def test_message_correlation_extra_data_property(self):
        """Test extra_data property getter/setter."""
        correlation = MessageCorrelation(
            parent_message_id=12345,
            child_message_id=12346,
            correlation_type=CorrelationType.REPLY
        )
        
        # Test empty extra_data
        assert correlation.extra_data_dict == {}
        
        # Test setting extra_data
        test_extra_data = {"reason": "stop_loss_hit", "confidence": 0.9}
        correlation.extra_data_dict = test_extra_data
        assert correlation.extra_data_dict == test_extra_data
        assert correlation.extra_data == json.dumps(test_extra_data)
        
        # Test getting extra_data
        correlation.extra_data = '{"test": "value"}'
        assert correlation.extra_data_dict == {"test": "value"}
        
        # Test invalid JSON
        correlation.extra_data = "invalid json"
        assert correlation.extra_data_dict == {}
    
    def test_message_correlation_to_dict(self):
        """Test message correlation dictionary conversion."""
        correlation_time = datetime.utcnow()
        extra_data = {"reason": "modification", "confidence": 0.8}
        
        correlation = MessageCorrelation(
            id=1,
            parent_message_id=12345,
            child_message_id=12346,
            correlation_type=CorrelationType.EDIT,
            correlation_confidence=0.9,
            correlation_time=correlation_time,
            position_id=2,
            extra_data=json.dumps(extra_data)
        )
        
        result = correlation.to_dict()
        assert result['id'] == 1
        assert result['parent_message_id'] == 12345
        assert result['child_message_id'] == 12346
        assert result['correlation_type'] == 'EDIT'
        assert result['correlation_confidence'] == 0.9
        assert result['position_id'] == 2
        assert result['extra_data'] == extra_data
        assert result['correlation_time'] == correlation_time.isoformat()
    
    def test_message_correlation_repr(self):
        """Test message correlation string representation."""
        correlation = MessageCorrelation(
            parent_message_id=12345,
            child_message_id=12346,
            correlation_type=CorrelationType.FOLLOWUP
        )
        expected = "<MessageCorrelation(parent=12345, child=12346, type=CorrelationType.FOLLOWUP)>"
        assert repr(correlation) == expected


class TestLLMCache:
    """Test LLMCache model."""
    
    def test_llm_cache_creation(self):
        """Test basic LLM cache creation."""
        cache = LLMCache(
            input_hash="abc123",
            prompt_type="signal_parser",
            raw_message="BUY GOLD",
            parsed_response='{"action": "BUY", "symbol": "GOLD"}',
            confidence_score=0.85,
            expires_at=datetime.utcnow() + timedelta(hours=24)
        )
        
        assert cache.input_hash == "abc123"
        assert cache.prompt_type == "signal_parser"
        assert cache.raw_message == "BUY GOLD"
        assert cache.confidence_score == 0.85
    
    def test_llm_cache_is_expired_property(self):
        """Test is_expired property."""
        # Future expiry - not expired
        future_cache = LLMCache(
            input_hash="abc123",
            prompt_type="test",
            raw_message="test",
            parsed_response="test",
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        assert future_cache.is_expired is False
        
        # Past expiry - expired
        past_cache = LLMCache(
            input_hash="def456",
            prompt_type="test",
            raw_message="test", 
            parsed_response="test",
            expires_at=datetime.utcnow() - timedelta(hours=1)
        )
        assert past_cache.is_expired is True
    
    def test_llm_cache_create_with_expiry(self):
        """Test create_with_expiry class method."""
        cache = LLMCache.create_with_expiry(
            input_hash="abc123",
            prompt_type="signal_parser",
            raw_message="BUY GOLD",
            parsed_response='{"action": "BUY"}',
            confidence_score=0.9,
            expiry_hours=12
        )
        
        assert cache.input_hash == "abc123"
        assert cache.confidence_score == 0.9
        # Check that expiry is approximately 12 hours from now
        expected_expiry = datetime.utcnow() + timedelta(hours=12)
        assert abs((cache.expires_at - expected_expiry).total_seconds()) < 60
    
    def test_llm_cache_to_dict(self):
        """Test LLM cache dictionary conversion."""
        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(hours=24)
        
        cache = LLMCache(
            id=1,
            input_hash="abc123",
            prompt_type="signal_parser",
            raw_message="BUY GOLD",
            parsed_response='{"action": "BUY"}',
            confidence_score=0.85,
            created_at=created_at,
            expires_at=expires_at
        )
        
        result = cache.to_dict()
        assert result['id'] == 1
        assert result['input_hash'] == "abc123"
        assert result['prompt_type'] == "signal_parser"
        assert result['confidence_score'] == 0.85
        assert result['created_at'] == created_at.isoformat()
        assert result['expires_at'] == expires_at.isoformat()
        assert result['is_expired'] == cache.is_expired
    
    def test_llm_cache_repr(self):
        """Test LLM cache string representation."""
        expires_at = datetime.utcnow() + timedelta(hours=24)
        cache = LLMCache(
            id=1,
            prompt_type="signal_parser",
            expires_at=expires_at
        )
        expected = f"<LLMCache(id=1, prompt_type=signal_parser, expires_at={expires_at})>"
        assert repr(cache) == expected


class TestHealthMetrics:
    """Test HealthMetrics model."""
    
    def test_health_metrics_creation(self):
        """Test basic health metrics creation."""
        metric = HealthMetrics(
            component="database",
            metric_name="connection_count",
            metric_value=5.0,
            status=HealthStatus.HEALTHY
        )
        
        assert metric.component == "database"
        assert metric.metric_name == "connection_count"
        assert metric.metric_value == 5.0
        assert metric.status == HealthStatus.HEALTHY
    
    def test_health_metrics_extra_data_property(self):
        """Test extra_data property getter/setter."""
        metric = HealthMetrics(
            component="test",
            metric_name="test_metric",
            metric_value=1.0,
            status=HealthStatus.HEALTHY
        )
        
        # Test empty extra_data
        assert metric.extra_data_dict == {}
        
        # Test setting extra_data
        test_extra_data = {"threshold": 10, "alert_level": "warning"}
        metric.extra_data_dict = test_extra_data
        assert metric.extra_data_dict == test_extra_data
        assert metric.extra_data == json.dumps(test_extra_data)
        
        # Test getting extra_data
        metric.extra_data = '{"test": "value"}'
        assert metric.extra_data_dict == {"test": "value"}
        
        # Test invalid JSON
        metric.extra_data = "invalid json"
        assert metric.extra_data_dict == {}
    
    def test_health_metrics_to_dict(self):
        """Test health metrics dictionary conversion."""
        timestamp = datetime.utcnow()
        extra_data = {"threshold": 100, "current": 85}
        
        metric = HealthMetrics(
            id=1,
            component="mt5_connection",
            metric_name="latency_ms",
            metric_value=85.0,
            status=HealthStatus.WARNING,
            timestamp=timestamp,
            extra_data=json.dumps(extra_data)
        )
        
        result = metric.to_dict()
        assert result['id'] == 1
        assert result['component'] == "mt5_connection"
        assert result['metric_name'] == "latency_ms"
        assert result['metric_value'] == 85.0
        assert result['status'] == 'WARNING'
        assert result['timestamp'] == timestamp.isoformat()
        assert result['extra_data'] == extra_data
    
    def test_health_metrics_repr(self):
        """Test health metrics string representation."""
        metric = HealthMetrics(
            component="telegram",
            metric_name="message_rate",
            status=HealthStatus.CRITICAL
        )
        expected = "<HealthMetrics(component=telegram, metric=message_rate, status=HealthStatus.CRITICAL)>"
        assert repr(metric) == expected