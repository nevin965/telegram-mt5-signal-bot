"""
Async repository pattern implementation for database operations.

This module provides the repository pattern for all database access using
aiosqlite and SQLAlchemy 2.0 async patterns. All database operations
must go through repository classes to maintain consistency and proper
transaction management.
"""

import logging
from abc import ABC
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import (
    Any,
    Generic,
    TypeVar,
)

from sqlalchemy import and_, asc, delete, desc, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from .models import (
    Base,
    Configuration,
    CorrelationType,
    HealthMetrics,
    HealthStatus,
    LLMCache,
    MessageCorrelation,
    Position,
    PositionStatus,
    PositionUpdate,
    Signal,
    SignalStatus,
    UpdateType,
)

logger = logging.getLogger(__name__)

ModelType = TypeVar('ModelType', bound=Base)


class DatabaseError(Exception):
    """Base exception for database operations."""
    pass


class RepositoryError(DatabaseError):
    """Exception for repository-specific errors."""
    pass


class DatabaseManager:
    """Database connection and session management."""

    def __init__(self, database_url: str):
        """
        Initialize database manager.
        
        Args:
            database_url: SQLite database URL (e.g., 'sqlite+aiosqlite:///data/signal_ea.db')
        """
        self.database_url = database_url
        self.engine = None
        self.session_factory = None

    async def initialize(self):
        """Initialize database engine and session factory."""
        try:
            # Configure SQLite for performance
            self.engine = create_async_engine(
                self.database_url,
                echo=False,  # Set to True for SQL debugging
                pool_pre_ping=True,
                pool_recycle=3600,  # Recycle connections after 1 hour
                connect_args={
                    "check_same_thread": False,
                    "timeout": 30,
                }
            )

            # Configure session factory
            self.session_factory = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=True,
                autocommit=False
            )

            # Apply SQLite optimizations
            await self._apply_sqlite_optimizations()

            # Create tables if they don't exist
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            logger.info("Database initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise DatabaseError(f"Database initialization failed: {e}")

    async def _apply_sqlite_optimizations(self):
        """Apply SQLite performance optimizations."""
        optimizations = [
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA cache_size = -64000",  # 64MB cache
            "PRAGMA temp_store = MEMORY",
            "PRAGMA mmap_size = 268435456",  # 256MB memory-mapped I/O
            "PRAGMA foreign_keys = ON"
        ]

        async with self.engine.connect() as conn:
            for optimization in optimizations:
                await conn.execute(text(optimization))

        logger.info("SQLite optimizations applied")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get async database session with proper cleanup."""
        if not self.session_factory:
            raise DatabaseError("Database not initialized")

        session = self.session_factory()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    @asynccontextmanager
    async def get_transaction(self) -> AsyncGenerator[AsyncSession, None]:
        """Get async database session with automatic transaction management."""
        async with self.get_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def close(self):
        """Close database connection."""
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connection closed")


class BaseRepository(Generic[ModelType], ABC):
    """Base repository class with common CRUD operations."""

    def __init__(self, db_manager: DatabaseManager, model_class: type[ModelType]):
        """
        Initialize repository.
        
        Args:
            db_manager: Database manager instance
            model_class: SQLAlchemy model class
        """
        self.db_manager = db_manager
        self.model_class = model_class

    async def create(self, **kwargs) -> ModelType:
        """Create new record."""
        try:
            instance = self.model_class(**kwargs)
            async with self.db_manager.get_transaction() as session:
                session.add(instance)
                await session.flush()
                await session.refresh(instance)
                return instance
        except IntegrityError as e:
            logger.error(f"Integrity error creating {self.model_class.__name__}: {e}")
            raise RepositoryError(f"Failed to create {self.model_class.__name__}: {e}")
        except SQLAlchemyError as e:
            logger.error(f"Database error creating {self.model_class.__name__}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def get_by_id(self, record_id: int) -> ModelType | None:
        """Get record by ID."""
        try:
            async with self.db_manager.get_session() as session:
                result = await session.get(self.model_class, record_id)
                return result
        except SQLAlchemyError as e:
            logger.error(f"Database error getting {self.model_class.__name__} by ID {record_id}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def update(self, record_id: int, **kwargs) -> ModelType | None:
        """Update record by ID."""
        try:
            async with self.db_manager.get_transaction() as session:
                result = await session.get(self.model_class, record_id)
                if result:
                    for key, value in kwargs.items():
                        if hasattr(result, key):
                            setattr(result, key, value)
                    await session.flush()
                    await session.refresh(result)
                return result
        except SQLAlchemyError as e:
            logger.error(f"Database error updating {self.model_class.__name__} {record_id}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def delete(self, record_id: int) -> bool:
        """Delete record by ID."""
        try:
            async with self.db_manager.get_transaction() as session:
                result = await session.get(self.model_class, record_id)
                if result:
                    await session.delete(result)
                    return True
                return False
        except SQLAlchemyError as e:
            logger.error(f"Database error deleting {self.model_class.__name__} {record_id}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def get_all(self, limit: int | None = None, offset: int = 0) -> list[ModelType]:
        """Get all records with optional pagination."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = select(self.model_class).offset(offset)
                if limit:
                    stmt = stmt.limit(limit)
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting all {self.model_class.__name__}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def count(self) -> int:
        """Get total count of records."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = select(func.count()).select_from(self.model_class)
                result = await session.execute(stmt)
                return result.scalar() or 0
        except SQLAlchemyError as e:
            logger.error(f"Database error counting {self.model_class.__name__}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def exists(self, **filters) -> bool:
        """Check if record exists with given filters."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = select(self.model_class).filter_by(**filters).limit(1)
                result = await session.execute(stmt)
                return result.first() is not None
        except SQLAlchemyError as e:
            logger.error(f"Database error checking existence for {self.model_class.__name__}: {e}")
            raise RepositoryError(f"Database error: {e}")


class SignalRepository(BaseRepository[Signal]):
    """Repository for signal operations."""

    def __init__(self, db_manager: DatabaseManager):
        super().__init__(db_manager, Signal)

    async def save_signal(self, signal_data: dict[str, Any]) -> int:
        """
        Persist parsed signal with validation.
        
        Args:
            signal_data: Dictionary containing signal data
            
        Returns:
            Signal ID
        """
        try:
            signal = await self.create(**signal_data)
            logger.info(f"Saved signal {signal.id} for message {signal.telegram_message_id}")
            return signal.id
        except Exception as e:
            logger.error(f"Failed to save signal: {e}")
            raise

    async def find_by_message_id(self, message_id: int) -> Signal | None:
        """Find signal by Telegram message ID."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = select(Signal).where(Signal.telegram_message_id == message_id)
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Database error finding signal by message ID {message_id}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def get_recent_signals(self, minutes: int = 60, status: SignalStatus | None = None) -> list[Signal]:
        """
        Get signals from recent time window for correlation.
        
        Args:
            minutes: Time window in minutes
            status: Optional status filter
            
        Returns:
            List of recent signals
        """
        try:
            cutoff_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=minutes)
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(Signal)
                    .where(Signal.timestamp >= cutoff_time)
                    .order_by(desc(Signal.timestamp))
                )
                if status:
                    stmt = stmt.where(Signal.status == status)

                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting recent signals: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def get_signals_by_symbol(self, symbol: str, limit: int = 50) -> list[Signal]:
        """Get signals by symbol with limit."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(Signal)
                    .where(Signal.symbol == symbol)
                    .order_by(desc(Signal.timestamp))
                    .limit(limit)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting signals for symbol {symbol}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def update_signal_status(self, signal_id: int, status: SignalStatus,
                                 rejection_reason: str | None = None) -> bool:
        """Update signal status with optional rejection reason."""
        try:
            update_data = {"status": status}
            if rejection_reason:
                update_data["rejection_reason"] = rejection_reason

            result = await self.update(signal_id, **update_data)
            if result:
                logger.info(f"Updated signal {signal_id} status to {status}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to update signal status: {e}")
            raise

    async def get_signals_with_positions(self) -> list[Signal]:
        """Get signals with their associated positions."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(Signal)
                    .options(selectinload(Signal.positions))
                    .order_by(desc(Signal.timestamp))
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting signals with positions: {e}")
            raise RepositoryError(f"Database error: {e}")


class PositionRepository(BaseRepository[Position]):
    """Repository for position operations."""

    def __init__(self, db_manager: DatabaseManager):
        super().__init__(db_manager, Position)

    async def get_position_by_ticket(self, ticket: int) -> Position | None:
        """Query position by MT5 ticket."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = select(Position).where(Position.mt5_ticket == ticket)
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Database error finding position by ticket {ticket}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def update_position_status(self, position_id: int, status: PositionStatus) -> bool:
        """Status changes with timestamp."""
        try:
            result = await self.update(position_id, status=status, last_sync=datetime.now(UTC).replace(tzinfo=None))
            if result:
                logger.info(f"Updated position {position_id} status to {status}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to update position status: {e}")
            raise

    async def get_open_positions(self) -> list[Position]:
        """Get all open positions."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(Position)
                    .where(Position.status == PositionStatus.OPEN)
                    .options(selectinload(Position.signal))
                    .order_by(desc(Position.open_time))
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting open positions: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def get_positions_by_signal(self, signal_id: int) -> list[Position]:
        """Get all positions for a specific signal."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(Position)
                    .where(Position.signal_id == signal_id)
                    .order_by(desc(Position.created_at))
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting positions for signal {signal_id}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def update_position_mt5_data(self, position_id: int, mt5_data: dict[str, Any]) -> bool:
        """Update position with MT5 sync data."""
        try:
            mt5_data['last_sync'] = datetime.now(UTC).replace(tzinfo=None)
            result = await self.update(position_id, **mt5_data)
            return result is not None
        except Exception as e:
            logger.error(f"Failed to update position MT5 data: {e}")
            raise

    async def get_positions_needing_sync(self, max_age_minutes: int = 5) -> list[Position]:
        """Get positions that need MT5 synchronization."""
        try:
            cutoff_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=max_age_minutes)
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(Position)
                    .where(
                        and_(
                            Position.status == PositionStatus.OPEN,
                            Position.last_sync < cutoff_time
                        )
                    )
                    .order_by(asc(Position.last_sync))
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting positions needing sync: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def update_position_closed(
        self,
        position_id: int,
        close_price: float,
        profit: float,
        close_time: datetime
    ) -> bool:
        """
        Update position record for full closure.
        
        Args:
            position_id: Position database ID
            close_price: Actual close price from MT5
            profit: Final profit/loss calculation
            close_time: Position close timestamp
            
        Returns:
            True if update successful, False otherwise
        """
        try:
            close_data = {
                'close_time': close_time,
                'close_price': close_price,
                'profit': profit,
                'status': PositionStatus.CLOSED,
                'last_sync': datetime.now(UTC).replace(tzinfo=None),
                'volume': 0.0  # Position fully closed
            }

            result = await self.update(position_id, **close_data)
            if result:
                logger.info(
                    f"Updated position {position_id} as CLOSED",
                    extra={
                        'position_id': position_id,
                        'close_price': close_price,
                        'profit': profit,
                        'close_time': close_time
                    }
                )
                return True
            return False

        except Exception as e:
            logger.error(f"Failed to update position {position_id} as closed: {e}")
            raise

    async def update_position_partial_close(
        self,
        position_id: int,
        close_price: float,
        profit_realized: float,
        volume_remaining: float,
        close_time: datetime
    ) -> bool:
        """
        Update position record for partial closure.
        
        Args:
            position_id: Position database ID
            close_price: Close price for partial closure
            profit_realized: Profit from the closed portion
            volume_remaining: Remaining volume after partial close
            close_time: Partial close timestamp
            
        Returns:
            True if update successful, False otherwise
        """
        try:
            # For partial closes, we keep the position open but update volume
            partial_data = {
                'volume': volume_remaining,
                'profit': profit_realized,  # Cumulative profit
                'last_sync': datetime.now(UTC).replace(tzinfo=None)
            }

            result = await self.update(position_id, **partial_data)
            if result:
                logger.info(
                    f"Updated position {position_id} for partial close",
                    extra={
                        'position_id': position_id,
                        'close_price': close_price,
                        'profit_realized': profit_realized,
                        'volume_remaining': volume_remaining,
                        'close_time': close_time
                    }
                )
                return True
            return False

        except Exception as e:
            logger.error(f"Failed to update position {position_id} for partial close: {e}")
            raise

    async def get_positions_without_sl(self) -> int:
        """Get count of open positions without stop-loss protection."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(func.count())
                    .select_from(Position)
                    .where(
                        and_(
                            Position.status == PositionStatus.OPEN,
                            Position.current_sl.is_(None)
                        )
                    )
                )
                result = await session.execute(stmt)
                return result.scalar() or 0
        except SQLAlchemyError as e:
            logger.error(f"Database error getting positions without SL: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def get_positions_past_be_point(self) -> int:
        """Get count of positions past break-even point eligibility."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(func.count())
                    .select_from(Position)
                    .where(
                        and_(
                            Position.status == PositionStatus.OPEN,
                            Position.profit > 0
                        )
                    )
                )
                result = await session.execute(stmt)
                return result.scalar() or 0
        except SQLAlchemyError as e:
            logger.error(f"Database error getting positions past BE point: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def get_daily_pnl(self, date: datetime | None = None) -> float:
        """Get daily P/L for specified date (default: today)."""
        try:
            if date is None:
                date = datetime.now(UTC)
            
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
            end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)
            
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(func.sum(Position.profit))
                    .where(
                        and_(
                            Position.close_time >= start_of_day,
                            Position.close_time <= end_of_day,
                            Position.status == PositionStatus.CLOSED
                        )
                    )
                )
                result = await session.execute(stmt)
                return result.scalar() or 0.0
        except SQLAlchemyError as e:
            logger.error(f"Database error getting daily P/L: {e}")
            raise RepositoryError(f"Database error: {e}")


class CorrelationRepository(BaseRepository[MessageCorrelation]):
    """Repository for message correlation operations."""

    def __init__(self, db_manager: DatabaseManager):
        super().__init__(db_manager, MessageCorrelation)

    async def link_messages(self, parent_id: int, child_id: int,
                           correlation_type: CorrelationType,
                           confidence: float = 1.0,
                           position_id: int | None = None,
                           extra_data: dict[str, Any] | None = None) -> int:
        """Link parent-child messages for correlation."""
        try:
            correlation_data = {
                'parent_message_id': parent_id,
                'child_message_id': child_id,
                'correlation_type': correlation_type,
                'correlation_confidence': confidence,
                'position_id': position_id,
            }

            if extra_data:
                import json
                correlation_data['extra_data'] = json.dumps(extra_data)

            correlation = await self.create(**correlation_data)
            logger.info(f"Linked messages {parent_id} -> {child_id} with type {correlation_type}")
            return correlation.id
        except Exception as e:
            logger.error(f"Failed to link messages: {e}")
            raise

    async def find_correlations_by_parent(self, parent_id: int) -> list[MessageCorrelation]:
        """Find all correlations where message is parent."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(MessageCorrelation)
                    .where(MessageCorrelation.parent_message_id == parent_id)
                    .order_by(desc(MessageCorrelation.correlation_time))
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error finding correlations by parent {parent_id}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def find_correlations_by_child(self, child_id: int) -> list[MessageCorrelation]:
        """Find all correlations where message is child."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(MessageCorrelation)
                    .where(MessageCorrelation.child_message_id == child_id)
                    .order_by(desc(MessageCorrelation.correlation_time))
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error finding correlations by child {child_id}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def get_correlation_chain(self, message_id: int) -> list[MessageCorrelation]:
        """Get complete correlation chain for a message."""
        try:
            correlations = []
            # Get where message is parent
            parent_correlations = await self.find_correlations_by_parent(message_id)
            correlations.extend(parent_correlations)

            # Get where message is child
            child_correlations = await self.find_correlations_by_child(message_id)
            correlations.extend(child_correlations)

            return correlations
        except Exception as e:
            logger.error(f"Failed to get correlation chain for message {message_id}: {e}")
            raise

    async def store_correlation(self, parent_id: int, child_id: int,
                               correlation_type: str, confidence: float,
                               position_id: int | None = None,
                               metadata: dict[str, Any] | None = None) -> int:
        """
        Store correlation between parent and child messages.
        
        Args:
            parent_id: Parent message ID
            child_id: Child message ID
            correlation_type: Type of correlation (REPLY, TIME_BASED, etc.)
            confidence: Confidence score (0.0-1.0)
            position_id: Associated position ID
            metadata: Additional correlation metadata
            
        Returns:
            Created MessageCorrelation object
        """
        try:
            # Convert string to enum if needed
            if isinstance(correlation_type, str):
                correlation_type_enum = CorrelationType[correlation_type]
            else:
                correlation_type_enum = correlation_type

            return await self.link_messages(
                parent_id=parent_id,
                child_id=child_id,
                correlation_type=correlation_type_enum,
                confidence=confidence,
                position_id=position_id,
                extra_data=metadata
            )
        except Exception as e:
            logger.error(f"Failed to store correlation: {e}")
            raise

    async def get_correlation_by_child_message(self, child_message_id: int) -> MessageCorrelation | None:
        """
        Get correlation by child message ID.
        
        Args:
            child_message_id: Child message ID
            
        Returns:
            MessageCorrelation if found, None otherwise
        """
        try:
            correlations = await self.find_correlations_by_child(child_message_id)
            return correlations[0] if correlations else None
        except Exception as e:
            logger.error(f"Failed to get correlation by child message {child_message_id}: {e}")
            return None

    async def get_correlations_by_position(self, position_id: int) -> list[MessageCorrelation]:
        """
        Get all correlations associated with a position.
        
        Args:
            position_id: Position ID
            
        Returns:
            List of MessageCorrelation objects
        """
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(MessageCorrelation)
                    .where(MessageCorrelation.position_id == position_id)
                    .order_by(desc(MessageCorrelation.correlation_time))
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error finding correlations by position {position_id}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def correlation_exists(self, parent_id: int, child_id: int) -> bool:
        """
        Check if correlation exists between parent and child messages.
        
        Args:
            parent_id: Parent message ID
            child_id: Child message ID
            
        Returns:
            True if correlation exists, False otherwise
        """
        try:
            async with self.db_manager.get_session() as session:
                stmt = select(MessageCorrelation).where(
                    and_(
                        MessageCorrelation.parent_message_id == parent_id,
                        MessageCorrelation.child_message_id == child_id
                    )
                ).limit(1)
                result = await session.execute(stmt)
                return result.first() is not None
        except SQLAlchemyError as e:
            logger.error(f"Database error checking correlation existence: {e}")
            return False

    async def get_correlation_success_rate(self, confidence_threshold: float = 0.8) -> float:
        """Get correlation success rate based on confidence threshold."""
        try:
            async with self.db_manager.get_session() as session:
                # Total correlations
                total_stmt = select(func.count()).select_from(MessageCorrelation)
                total_result = await session.execute(total_stmt)
                total_count = total_result.scalar() or 0
                
                if total_count == 0:
                    return 100.0  # Assume success if no data
                
                # Successful correlations (above threshold)
                success_stmt = (
                    select(func.count())
                    .select_from(MessageCorrelation)
                    .where(MessageCorrelation.correlation_confidence >= confidence_threshold)
                )
                success_result = await session.execute(success_stmt)
                success_count = success_result.scalar() or 0
                
                return (success_count / total_count) * 100.0
        except SQLAlchemyError as e:
            logger.error(f"Database error getting correlation success rate: {e}")
            raise RepositoryError(f"Database error: {e}")


class ConfigurationRepository(BaseRepository[Configuration]):
    """Repository for configuration operations."""

    def __init__(self, db_manager: DatabaseManager):
        super().__init__(db_manager, Configuration)

    async def get_config_value(self, key: str, default_value: str | None = None) -> str | None:
        """Get configuration value by key."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = select(Configuration).where(Configuration.key == key)
                result = await session.execute(stmt)
                config = result.scalar_one_or_none()
                return config.value if config else default_value
        except SQLAlchemyError as e:
            logger.error(f"Database error getting config value for {key}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def set_config_value(self, key: str, value: str, description: str | None = None) -> bool:
        """Set configuration value."""
        try:
            async with self.db_manager.get_transaction() as session:
                stmt = select(Configuration).where(Configuration.key == key)
                result = await session.execute(stmt)
                config = result.scalar_one_or_none()

                if config:
                    config.value = value
                    config.updated_at = datetime.now(UTC).replace(tzinfo=None)
                    if description:
                        config.description = description
                else:
                    config = Configuration(key=key, value=value, description=description)
                    session.add(config)

                await session.flush()
                logger.info(f"Set config {key} = {value}")
                return True
        except SQLAlchemyError as e:
            logger.error(f"Database error setting config value for {key}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def get_all_config(self) -> dict[str, str]:
        """Get all configuration as dictionary."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = select(Configuration)
                result = await session.execute(stmt)
                configs = result.scalars().all()
                return {config.key: config.value for config in configs}
        except SQLAlchemyError as e:
            logger.error(f"Database error getting all config: {e}")
            raise RepositoryError(f"Database error: {e}")


class LLMCacheRepository(BaseRepository[LLMCache]):
    """Repository for LLM cache operations."""

    def __init__(self, db_manager: DatabaseManager):
        super().__init__(db_manager, LLMCache)

    async def get_cached_response(self, input_hash: str) -> LLMCache | None:
        """Get cached LLM response if not expired."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(LLMCache)
                    .where(
                        and_(
                            LLMCache.input_hash == input_hash,
                            LLMCache.expires_at > datetime.now(UTC).replace(tzinfo=None)
                        )
                    )
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Database error getting cached response: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def cache_response(self, input_hash: str, prompt_type: str,
                           raw_message: str, parsed_response: str,
                           confidence_score: float | None = None,
                           expiry_hours: int = 24) -> int:
        """Cache LLM response with expiry."""
        try:
            cache_entry = LLMCache.create_with_expiry(
                input_hash=input_hash,
                prompt_type=prompt_type,
                raw_message=raw_message,
                parsed_response=parsed_response,
                confidence_score=confidence_score,
                expiry_hours=expiry_hours
            )

            async with self.db_manager.get_transaction() as session:
                session.add(cache_entry)
                await session.flush()
                await session.refresh(cache_entry)
                return cache_entry.id
        except SQLAlchemyError as e:
            logger.error(f"Database error caching LLM response: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def cleanup_expired_cache(self) -> int:
        """Clean up expired cache entries."""
        try:
            async with self.db_manager.get_transaction() as session:
                stmt = delete(LLMCache).where(LLMCache.expires_at < datetime.now(UTC).replace(tzinfo=None))
                result = await session.execute(stmt)
                count = result.rowcount or 0
                logger.info(f"Cleaned up {count} expired cache entries")
                return count
        except SQLAlchemyError as e:
            logger.error(f"Database error cleaning up cache: {e}")
            raise RepositoryError(f"Database error: {e}")


class PositionUpdateRepository(BaseRepository[PositionUpdate]):
    """Repository for position update operations."""

    def __init__(self, db_manager: DatabaseManager):
        super().__init__(db_manager, PositionUpdate)

    async def create_update(self, position_update: PositionUpdate) -> int:
        """Create a new position update record."""
        try:
            update = await self.create(
                position_id=position_update.position_id,
                update_type=position_update.update_type,
                field_name=position_update.field_name,
                old_value=position_update.old_value,
                new_value=position_update.new_value,
                telegram_message_id=position_update.telegram_message_id,
                success=position_update.success,
                error_message=position_update.error_message,
                timestamp=position_update.timestamp
            )
            logger.info(f"Created position update {update.id} for position {position_update.position_id}")
            return update.id
        except Exception as e:
            logger.error(f"Failed to create position update: {e}")
            raise

    async def get_updates_by_position(
        self,
        position_id: int,
        update_type: UpdateType | None = None
    ) -> list[PositionUpdate]:
        """Get all updates for a specific position, optionally filtered by type."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(PositionUpdate)
                    .where(PositionUpdate.position_id == position_id)
                    .order_by(desc(PositionUpdate.timestamp))
                )
                if update_type:
                    stmt = stmt.where(PositionUpdate.update_type == update_type)

                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting updates for position {position_id}: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def check_existing_be_update(self, position_id: int) -> bool:
        """Check if successful break even update exists for position (idempotency check)."""
        try:
            updates = await self.get_updates_by_position(
                position_id=position_id,
                update_type=UpdateType.BREAK_EVEN
            )

            # Check if any successful break even updates exist
            successful_updates = [u for u in updates if u.success]
            return len(successful_updates) > 0

        except Exception as e:
            logger.error(f"Error checking existing break even update: {e}")
            # On error, assume no existing update to avoid blocking new requests
            return False

    async def record_be_update(
        self,
        position_id: int,
        old_sl: float | None,
        new_sl: float,
        telegram_message_id: int,
        success: bool,
        error_msg: str | None = None
    ) -> int:
        """Record break even update for audit trail."""
        try:
            update_record = PositionUpdate(
                position_id=position_id,
                update_type=UpdateType.BREAK_EVEN,
                field_name="stop_loss",
                old_value=str(old_sl) if old_sl is not None else None,
                new_value=str(new_sl),
                telegram_message_id=telegram_message_id,
                success=success,
                error_message=error_msg,
                timestamp=datetime.now(UTC).replace(tzinfo=None)
            )

            return await self.create_update(update_record)

        except Exception as e:
            logger.error(f"Error recording break even update: {e}")
            raise

    async def get_position_be_history(self, position_id: int) -> list[PositionUpdate]:
        """Get break even update history for a position."""
        try:
            return await self.get_updates_by_position(
                position_id=position_id,
                update_type=UpdateType.BREAK_EVEN
            )
        except Exception as e:
            logger.error(f"Error retrieving break even history: {e}")
            return []

    async def update_success_status(
        self,
        update_id: int,
        success: bool,
        error_message: str | None = None
    ) -> bool:
        """Update success status of an existing position update."""
        try:
            update_data = {"success": success}
            if error_message:
                update_data["error_message"] = error_message

            result = await self.update(update_id, **update_data)
            if result:
                logger.info(f"Updated position update {update_id} success status to {success}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to update position update success status: {e}")
            raise

    async def record_close_attempt(
        self,
        position_id: int,
        close_type: str,
        volume_closed: float,
        success: bool,
        error_msg: str | None = None
    ) -> int:
        """
        Record close attempt audit trail.
        
        Args:
            position_id: Position database ID
            close_type: Type of close ("FULL_CLOSE" or "PARTIAL_CLOSE")
            volume_closed: Volume that was closed
            success: Whether the close operation succeeded
            error_msg: Error message if operation failed
            
        Returns:
            Position update record ID
        """
        try:
            update_type = UpdateType.FULL_CLOSE if close_type == "FULL_CLOSE" else UpdateType.PARTIAL_CLOSE

            update = await self.create(
                position_id=position_id,
                update_type=update_type,
                field_name="volume" if close_type == "PARTIAL_CLOSE" else "status",
                old_value=str(volume_closed) if close_type == "PARTIAL_CLOSE" else "OPEN",
                new_value="0.0" if close_type == "FULL_CLOSE" else str(volume_closed),
                success=success,
                error_message=error_msg,
                timestamp=datetime.now(UTC).replace(tzinfo=None)
            )

            logger.info(
                f"Recorded {close_type} attempt for position {position_id}",
                extra={
                    'position_id': position_id,
                    'close_type': close_type,
                    'volume_closed': volume_closed,
                    'success': success,
                    'update_id': update.id
                }
            )

            return update.id

        except Exception as e:
            logger.error(f"Failed to record close attempt: {e}")
            raise

    async def get_daily_be_count(self, date: datetime | None = None) -> int:
        """Get count of break-even adjustments applied for a specific date."""
        try:
            if date is None:
                date = datetime.now(UTC)
            
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
            end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)
            
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(func.count())
                    .select_from(PositionUpdate)
                    .where(
                        and_(
                            PositionUpdate.update_type == UpdateType.BREAK_EVEN,
                            PositionUpdate.success == True,
                            PositionUpdate.timestamp >= start_of_day,
                            PositionUpdate.timestamp <= end_of_day
                        )
                    )
                )
                result = await session.execute(stmt)
                return result.scalar() or 0
        except SQLAlchemyError as e:
            logger.error(f"Database error getting daily BE count: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def get_daily_close_count(self, date: datetime | None = None) -> int:
        """Get count of positions closed (full and partial) for a specific date."""
        try:
            if date is None:
                date = datetime.now(UTC)
            
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
            end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)
            
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(func.count())
                    .select_from(PositionUpdate)
                    .where(
                        and_(
                            PositionUpdate.update_type.in_([UpdateType.FULL_CLOSE, UpdateType.PARTIAL_CLOSE]),
                            PositionUpdate.success == True,
                            PositionUpdate.timestamp >= start_of_day,
                            PositionUpdate.timestamp <= end_of_day
                        )
                    )
                )
                result = await session.execute(stmt)
                return result.scalar() or 0
        except SQLAlchemyError as e:
            logger.error(f"Database error getting daily close count: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def get_recent_be_updates(self, limit: int = 10) -> list[PositionUpdate]:
        """Get recent break-even adjustments with timestamps."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(PositionUpdate)
                    .where(PositionUpdate.update_type == UpdateType.BREAK_EVEN)
                    .order_by(desc(PositionUpdate.timestamp))
                    .limit(limit)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting recent BE updates: {e}")
            raise RepositoryError(f"Database error: {e}")

    async def get_position_update_history(self, position_id: int, limit: int = 10) -> list[PositionUpdate]:
        """Get last N modifications for a specific position."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(PositionUpdate)
                    .where(PositionUpdate.position_id == position_id)
                    .order_by(desc(PositionUpdate.timestamp))
                    .limit(limit)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting position update history: {e}")
            raise RepositoryError(f"Database error: {e}")


class HealthMetricsRepository(BaseRepository[HealthMetrics]):
    """Repository for health metrics operations."""

    def __init__(self, db_manager: DatabaseManager):
        super().__init__(db_manager, HealthMetrics)

    async def record_metric(self, component: str, metric_name: str,
                          metric_value: float, status: HealthStatus,
                          extra_data: dict[str, Any] | None = None) -> int:
        """Record health metric."""
        try:
            metric_data = {
                'component': component,
                'metric_name': metric_name,
                'metric_value': metric_value,
                'status': status,
            }

            if extra_data:
                import json
                metric_data['extra_data'] = json.dumps(extra_data)

            metric = await self.create(**metric_data)
            return metric.id
        except Exception as e:
            logger.error(f"Failed to record health metric: {e}")
            raise

    async def get_latest_metrics(self, component: str | None = None) -> list[HealthMetrics]:
        """Get latest health metrics, optionally filtered by component."""
        try:
            async with self.db_manager.get_session() as session:
                stmt = (
                    select(HealthMetrics)
                    .order_by(desc(HealthMetrics.timestamp))
                    .limit(100)
                )
                if component:
                    stmt = stmt.where(HealthMetrics.component == component)

                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Database error getting health metrics: {e}")
            raise RepositoryError(f"Database error: {e}")


# Repository factory for easy access
class RepositoryFactory:
    """Factory for creating repository instances."""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self._repositories = {}

    def get_signal_repository(self) -> SignalRepository:
        """Get signal repository instance."""
        if 'signal' not in self._repositories:
            self._repositories['signal'] = SignalRepository(self.db_manager)
        return self._repositories['signal']

    def get_position_repository(self) -> PositionRepository:
        """Get position repository instance."""
        if 'position' not in self._repositories:
            self._repositories['position'] = PositionRepository(self.db_manager)
        return self._repositories['position']

    def get_correlation_repository(self) -> CorrelationRepository:
        """Get correlation repository instance."""
        if 'correlation' not in self._repositories:
            self._repositories['correlation'] = CorrelationRepository(self.db_manager)
        return self._repositories['correlation']

    def get_configuration_repository(self) -> ConfigurationRepository:
        """Get configuration repository instance."""
        if 'config' not in self._repositories:
            self._repositories['config'] = ConfigurationRepository(self.db_manager)
        return self._repositories['config']

    def get_llm_cache_repository(self) -> LLMCacheRepository:
        """Get LLM cache repository instance."""
        if 'llm_cache' not in self._repositories:
            self._repositories['llm_cache'] = LLMCacheRepository(self.db_manager)
        return self._repositories['llm_cache']

    def get_position_update_repository(self) -> PositionUpdateRepository:
        """Get position update repository instance."""
        if 'position_update' not in self._repositories:
            self._repositories['position_update'] = PositionUpdateRepository(self.db_manager)
        return self._repositories['position_update']

    def get_health_metrics_repository(self) -> HealthMetricsRepository:
        """Get health metrics repository instance."""
        if 'health_metrics' not in self._repositories:
            self._repositories['health_metrics'] = HealthMetricsRepository(self.db_manager)
        return self._repositories['health_metrics']
