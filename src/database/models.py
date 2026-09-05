"""
SQLAlchemy models for Telegram Signal EA database.

This module defines all database models using SQLAlchemy 2.0 async patterns.
All models follow the repository pattern and include proper relationships,
constraints, and validation.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List
import json
from enum import Enum

from sqlalchemy import (
    Integer, String, Float, Boolean, DateTime, Text, ForeignKey,
    CheckConstraint, UniqueConstraint, Index
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all database models."""
    pass


class ParsedAction(str, Enum):
    """Enumeration for signal parsed actions."""
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    MODIFY_SL = "MODIFY_SL"
    MODIFY_TP = "MODIFY_TP"


class ParserType(str, Enum):
    """Enumeration for parser types."""
    REGEX = "REGEX"
    LLM = "LLM"
    HYBRID = "HYBRID"


class SignalStatus(str, Enum):
    """Enumeration for signal status."""
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionStatus(str, Enum):
    """Enumeration for position status."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class UpdateType(str, Enum):
    """Enumeration for position update types."""
    SL_MODIFY = "SL_MODIFY"
    TP_MODIFY = "TP_MODIFY"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    FULL_CLOSE = "FULL_CLOSE"
    BREAK_EVEN = "BREAK_EVEN"
    LLM_ANALYSIS = "LLM_ANALYSIS"


class CorrelationType(str, Enum):
    """Enumeration for message correlation types."""
    REPLY = "REPLY"
    EDIT = "EDIT"
    FOLLOWUP = "FOLLOWUP"
    CANCEL = "CANCEL"


class HealthStatus(str, Enum):
    """Enumeration for health metric status."""
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class Configuration(Base):
    """Configuration table for runtime settings."""
    __tablename__ = "configuration"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<Configuration(key='{self.key}', value='{self.value}')>"


class Signal(Base):
    """Signal model for storing parsed trading signals."""
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_message_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    telegram_chat_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sender: Mapped[str] = mapped_column(String(100), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_action: Mapped[ParsedAction] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    entry_price: Mapped[Optional[float]] = mapped_column(Float)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float)
    take_profit: Mapped[Optional[float]] = mapped_column(Float)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    parser_type: Mapped[ParserType] = mapped_column(String(10), nullable=False)
    status: Mapped[SignalStatus] = mapped_column(String(20), default=SignalStatus.PENDING, index=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    positions: Mapped[List["Position"]] = relationship("Position", back_populates="signal", cascade="all, delete-orphan")

    # Constraints
    __table_args__ = (
        CheckConstraint('confidence_score >= 0.0 AND confidence_score <= 1.0', name='check_confidence_score'),
        Index('idx_signals_status_timestamp', 'status', 'timestamp'),
        Index('idx_signals_symbol_timestamp', 'symbol', 'timestamp'),
    )

    def __repr__(self) -> str:
        return f"<Signal(id={self.id}, action={self.parsed_action}, symbol={self.symbol}, status={self.status})>"

    def to_dict(self) -> dict:
        """Convert signal to dictionary representation."""
        return {
            'id': self.id,
            'telegram_message_id': self.telegram_message_id,
            'telegram_chat_id': self.telegram_chat_id,
            'sender': self.sender,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'raw_text': self.raw_text,
            'parsed_action': self.parsed_action.value if self.parsed_action else None,
            'symbol': self.symbol,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'confidence_score': self.confidence_score,
            'parser_type': self.parser_type.value if self.parser_type else None,
            'status': self.status.value if self.status else None,
            'rejection_reason': self.rejection_reason,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class Position(Base):
    """Position model for MT5 position tracking."""
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(Integer, ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, index=True)
    mt5_ticket: Mapped[Optional[int]] = mapped_column(Integer, unique=True, index=True)
    open_time: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    close_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    open_price: Mapped[Optional[float]] = mapped_column(Float)
    close_price: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    current_sl: Mapped[Optional[float]] = mapped_column(Float)
    current_tp: Mapped[Optional[float]] = mapped_column(Float)
    profit: Mapped[float] = mapped_column(Float, default=0.0)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    swap: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[PositionStatus] = mapped_column(String(20), default=PositionStatus.OPEN, index=True)
    last_sync: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    signal: Mapped["Signal"] = relationship("Signal", back_populates="positions")
    updates: Mapped[List["PositionUpdate"]] = relationship("PositionUpdate", back_populates="position", cascade="all, delete-orphan")
    correlations: Mapped[List["MessageCorrelation"]] = relationship("MessageCorrelation", back_populates="position")

    # Constraints
    __table_args__ = (
        CheckConstraint('volume > 0', name='check_volume_positive'),
        Index('idx_positions_status_open_time', 'status', 'open_time'),
    )

    def __repr__(self) -> str:
        return f"<Position(id={self.id}, mt5_ticket={self.mt5_ticket}, status={self.status}, profit={self.profit})>"

    @property
    def is_open(self) -> bool:
        """Check if position is currently open."""
        return self.status == PositionStatus.OPEN

    @property
    def total_pnl(self) -> float:
        """Calculate total P&L including commission and swap."""
        return self.profit + self.commission + self.swap

    def to_dict(self) -> dict:
        """Convert position to dictionary representation."""
        return {
            'id': self.id,
            'signal_id': self.signal_id,
            'mt5_ticket': self.mt5_ticket,
            'open_time': self.open_time.isoformat() if self.open_time else None,
            'close_time': self.close_time.isoformat() if self.close_time else None,
            'open_price': self.open_price,
            'close_price': self.close_price,
            'volume': self.volume,
            'current_sl': self.current_sl,
            'current_tp': self.current_tp,
            'profit': self.profit,
            'commission': self.commission,
            'swap': self.swap,
            'status': self.status.value if self.status else None,
            'total_pnl': self.total_pnl,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class PositionUpdate(Base):
    """Position update model for audit trail of position modifications."""
    __tablename__ = "position_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(Integer, ForeignKey("positions.id", ondelete="CASCADE"), nullable=False, index=True)
    update_type: Mapped[UpdateType] = mapped_column(String(20), nullable=False)
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)

    # Relationships
    position: Mapped["Position"] = relationship("Position", back_populates="updates")

    def __repr__(self) -> str:
        return f"<PositionUpdate(id={self.id}, type={self.update_type}, success={self.success})>"

    def to_dict(self) -> dict:
        """Convert position update to dictionary representation."""
        return {
            'id': self.id,
            'position_id': self.position_id,
            'update_type': self.update_type.value if self.update_type else None,
            'field_name': self.field_name,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'telegram_message_id': self.telegram_message_id,
            'success': self.success,
            'error_message': self.error_message,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }


class MessageCorrelation(Base):
    """Message correlation model for parent-child message linking."""
    __tablename__ = "message_correlations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    child_message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    correlation_type: Mapped[CorrelationType] = mapped_column(String(20), nullable=False)
    correlation_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    correlation_time: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    position_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("positions.id", ondelete="SET NULL"), index=True)
    extra_data: Mapped[Optional[str]] = mapped_column(Text)  # JSON string

    # Relationships
    position: Mapped[Optional["Position"]] = relationship("Position", back_populates="correlations")

    # Constraints
    __table_args__ = (
        CheckConstraint('correlation_confidence >= 0.0 AND correlation_confidence <= 1.0', name='check_correlation_confidence'),
        UniqueConstraint('parent_message_id', 'child_message_id', name='uq_message_correlation'),
        Index('idx_message_correlations_parent_child', 'parent_message_id', 'child_message_id'),
    )

    def __repr__(self) -> str:
        return f"<MessageCorrelation(parent={self.parent_message_id}, child={self.child_message_id}, type={self.correlation_type})>"

    @property
    def extra_data_dict(self) -> dict:
        """Parse extra_data JSON string to dictionary."""
        if not self.extra_data:
            return {}
        try:
            return json.loads(self.extra_data)
        except json.JSONDecodeError:
            return {}

    @extra_data_dict.setter
    def extra_data_dict(self, value: dict):
        """Set extra_data from dictionary."""
        self.extra_data = json.dumps(value) if value else None

    def to_dict(self) -> dict:
        """Convert message correlation to dictionary representation."""
        return {
            'id': self.id,
            'parent_message_id': self.parent_message_id,
            'child_message_id': self.child_message_id,
            'correlation_type': self.correlation_type.value if self.correlation_type else None,
            'correlation_confidence': self.correlation_confidence,
            'correlation_time': self.correlation_time.isoformat() if self.correlation_time else None,
            'position_id': self.position_id,
            'extra_data': self.extra_data_dict,
        }


class LLMCache(Base):
    """LLM cache model for response caching to reduce API costs."""
    __tablename__ = "llm_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    prompt_type: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_message: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_response: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<LLMCache(id={self.id}, prompt_type={self.prompt_type}, expires_at={self.expires_at})>"

    @property
    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        return datetime.now(timezone.utc).replace(tzinfo=None) > self.expires_at

    @classmethod
    def create_with_expiry(cls, input_hash: str, prompt_type: str, raw_message: str, 
                          parsed_response: str, confidence_score: Optional[float] = None,
                          expiry_hours: int = 24) -> "LLMCache":
        """Create cache entry with expiry time."""
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=expiry_hours)
        return cls(
            input_hash=input_hash,
            prompt_type=prompt_type,
            raw_message=raw_message,
            parsed_response=parsed_response,
            confidence_score=confidence_score,
            expires_at=expires_at
        )

    def to_dict(self) -> dict:
        """Convert LLM cache to dictionary representation."""
        return {
            'id': self.id,
            'input_hash': self.input_hash,
            'prompt_type': self.prompt_type,
            'raw_message': self.raw_message,
            'parsed_response': self.parsed_response,
            'confidence_score': self.confidence_score,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_expired': self.is_expired,
        }


class HealthMetrics(Base):
    """Health metrics model for system monitoring data."""
    __tablename__ = "health_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[HealthStatus] = mapped_column(String(20), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    extra_data: Mapped[Optional[str]] = mapped_column(Text)  # JSON string

    # Constraints
    __table_args__ = (
        Index('idx_health_metrics_component_timestamp', 'component', 'timestamp'),
    )

    def __repr__(self) -> str:
        return f"<HealthMetrics(component={self.component}, metric={self.metric_name}, status={self.status})>"

    @property
    def extra_data_dict(self) -> dict:
        """Parse extra_data JSON string to dictionary."""
        if not self.extra_data:
            return {}
        try:
            return json.loads(self.extra_data)
        except json.JSONDecodeError:
            return {}

    @extra_data_dict.setter
    def extra_data_dict(self, value: dict):
        """Set extra_data from dictionary."""
        self.extra_data = json.dumps(value) if value else None

    def to_dict(self) -> dict:
        """Convert health metrics to dictionary representation."""
        return {
            'id': self.id,
            'component': self.component,
            'metric_name': self.metric_name,
            'metric_value': self.metric_value,
            'status': self.status.value if self.status else None,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'extra_data': self.extra_data_dict,
        }