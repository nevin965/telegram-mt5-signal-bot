"""
Message correlation engine for linking Telegram replies to original signals.

This module provides the main correlation engine that processes incoming messages
and establishes relationships between parent signals and child update messages.
Follows coding standards: structured logging, async cancellation handling.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.database.models import CorrelationType, Position, Signal
from src.database.repository import (
    DatabaseManager,
    RepositoryFactory,
)

from .reply_tracer import ReplyTracer
from .time_matcher import TimeMatcher


@dataclass
class TelegramMessage:
    """Telegram message data structure for correlation processing."""
    telegram_message_id: int
    telegram_chat_id: int
    sender: str
    timestamp: datetime
    raw_text: str
    reply_to_message_id: int | None = None


@dataclass
class CorrelationResult:
    """Result of correlation attempt with metadata."""
    position: Position | None
    correlation_type: str
    confidence: float
    correlation_id: int | None = None
    metadata: dict[str, Any] | None = None


class CorrelationEngine:
    """
    Main correlation engine for message-to-position linking.
    
    Handles both exact reply correlation and time-based fallback matching
    with proper logging and performance monitoring.
    """

    def __init__(self, db_manager: DatabaseManager, telegram_client=None):
        """
        Initialize correlation engine with database and Telegram dependencies.
        
        Args:
            db_manager: Database manager for repository access
            telegram_client: Telegram client for retrieving parent messages
        """
        self.logger = logging.getLogger(__name__)
        self.db_manager = db_manager
        self.telegram_client = telegram_client

        # Initialize repositories through factory
        self.repo_factory = RepositoryFactory(db_manager)
        self.signal_repo = self.repo_factory.get_signal_repository()
        self.position_repo = self.repo_factory.get_position_repository()
        self.correlation_repo = self.repo_factory.get_correlation_repository()

        # Initialize correlation components
        self.reply_tracer = ReplyTracer(telegram_client) if telegram_client else None
        self.time_matcher = TimeMatcher(self.signal_repo, self.position_repo)

        # Correlation statistics for monitoring
        self._correlation_attempts = 0
        self._successful_correlations = 0
        self._reply_correlations = 0
        self._time_based_correlations = 0

    async def correlate_message(self, message: TelegramMessage) -> Position | None:
        """
        Main correlation interface - correlate message to position.
        
        Args:
            message: Telegram message to correlate
            
        Returns:
            Associated position if correlation found, None otherwise
        """
        correlation_id = f"corr_{message.telegram_message_id}_{datetime.now().timestamp()}"
        start_time = datetime.now()

        try:
            self._correlation_attempts += 1

            self.logger.info(
                f"Starting correlation for message {message.telegram_message_id}",
                extra={
                    'correlation_id': correlation_id,
                    'message_id': message.telegram_message_id,
                    'chat_id': message.telegram_chat_id,
                    'has_reply': message.reply_to_message_id is not None
                }
            )

            # Try exact reply correlation first (highest confidence)
            if message.reply_to_message_id and self.reply_tracer:
                result = await self._try_reply_correlation(message, correlation_id)
                if result and result.position:
                    self._successful_correlations += 1
                    self._reply_correlations += 1

                    duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                    self.logger.info(
                        f"Reply correlation successful in {duration_ms:.1f}ms",
                        extra={
                            'correlation_id': correlation_id,
                            'correlation_type': result.correlation_type,
                            'confidence': result.confidence,
                            'position_id': result.position.id,
                            'duration_ms': duration_ms
                        }
                    )
                    return result.position

            # Fallback to time-based correlation for orphaned messages
            result = await self._try_time_based_correlation(message, correlation_id)
            if result and result.position:
                self._successful_correlations += 1
                self._time_based_correlations += 1

                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                self.logger.info(
                    f"Time-based correlation successful in {duration_ms:.1f}ms",
                    extra={
                        'correlation_id': correlation_id,
                        'correlation_type': result.correlation_type,
                        'confidence': result.confidence,
                        'position_id': result.position.id,
                        'duration_ms': duration_ms
                    }
                )
                return result.position

            # No correlation found
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            self.logger.info(
                f"No correlation found for message {message.telegram_message_id} in {duration_ms:.1f}ms",
                extra={
                    'correlation_id': correlation_id,
                    'duration_ms': duration_ms,
                    'attempts': 'reply+time' if message.reply_to_message_id else 'time_only'
                }
            )
            return None

        except asyncio.CancelledError:
            self.logger.info(f"Correlation cancelled for message {message.telegram_message_id}")
            raise
        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            self.logger.error(
                f"Error correlating message {message.telegram_message_id}: {e}",
                extra={
                    'correlation_id': correlation_id,
                    'error': str(e),
                    'duration_ms': duration_ms
                }
            )
            return None

    async def _try_reply_correlation(self, message: TelegramMessage, correlation_id: str) -> CorrelationResult | None:
        """
        Attempt exact reply correlation using reply chain traversal.
        
        Args:
            message: Message with reply_to_message_id
            correlation_id: Unique correlation ID for logging
            
        Returns:
            CorrelationResult if successful, None otherwise
        """
        if not message.reply_to_message_id or not self.reply_tracer:
            return None

        try:
            # Trace reply chain to find root message
            root_message_id = await self.reply_tracer.trace_reply_chain(
                message.reply_to_message_id,
                message.telegram_chat_id
            )

            if not root_message_id:
                self.logger.debug(
                    "No root message found in reply chain",
                    extra={'correlation_id': correlation_id}
                )
                return None

            # Find position associated with root message
            position = await self.get_position_by_message_id(root_message_id)
            if not position:
                self.logger.debug(
                    f"No position found for root message {root_message_id}",
                    extra={'correlation_id': correlation_id}
                )
                return None

            # Store correlation in database
            correlation_db_id = await self.correlation_repo.link_messages(
                parent_id=root_message_id,
                child_id=message.telegram_message_id,
                correlation_type=CorrelationType.REPLY,
                confidence=1.0,
                position_id=position.id,
                extra_data={
                    'original_reply_to': message.reply_to_message_id,
                    'chain_length': 1 if root_message_id == message.reply_to_message_id else 2,
                    'correlation_method': 'reply_chain'
                }
            )

            return CorrelationResult(
                position=position,
                correlation_type="REPLY",
                confidence=1.0,
                correlation_id=correlation_db_id,
                metadata={
                    'root_message_id': root_message_id,
                    'chain_traversal': True
                }
            )

        except Exception as e:
            self.logger.error(
                f"Error in reply correlation: {e}",
                extra={'correlation_id': correlation_id}
            )
            return None

    async def _try_time_based_correlation(self, message: TelegramMessage, correlation_id: str) -> CorrelationResult | None:
        """
        Attempt time-based correlation for orphaned messages.
        
        Args:
            message: Message to correlate
            correlation_id: Unique correlation ID for logging
            
        Returns:
            CorrelationResult if successful, None otherwise
        """
        try:
            # Use time matcher to find candidate positions
            candidates = await self.time_matcher.find_matches(
                message=message,
                window_minutes=5
            )

            if not candidates:
                self.logger.debug(
                    "No time-based candidates found",
                    extra={'correlation_id': correlation_id}
                )
                return None

            # Select best candidate (highest confidence)
            best_candidate = max(candidates, key=lambda x: x['confidence'])

            if best_candidate['confidence'] < 0.75:
                self.logger.debug(
                    f"Best candidate confidence {best_candidate['confidence']:.2f} below threshold",
                    extra={'correlation_id': correlation_id}
                )
                return None

            position = best_candidate['position']

            # Store time-based correlation
            correlation_db_id = await self.correlation_repo.link_messages(
                parent_id=position.signal.telegram_message_id,
                child_id=message.telegram_message_id,
                correlation_type=CorrelationType.FOLLOWUP,
                confidence=best_candidate['confidence'],
                position_id=position.id,
                extra_data={
                    'time_window_minutes': 5,
                    'candidates_count': len(candidates),
                    'correlation_method': 'time_based',
                    'time_proximity_score': best_candidate.get('time_score', 0.0),
                    'text_similarity_score': best_candidate.get('text_score', 0.0)
                }
            )

            return CorrelationResult(
                position=position,
                correlation_type="TIME_BASED",
                confidence=best_candidate['confidence'],
                correlation_id=correlation_db_id,
                metadata={
                    'candidates_evaluated': len(candidates),
                    'time_based': True
                }
            )

        except Exception as e:
            self.logger.error(
                f"Error in time-based correlation: {e}",
                extra={'correlation_id': correlation_id}
            )
            return None

    async def get_position_by_message_id(self, telegram_message_id: int) -> Position | None:
        """
        Get position associated with Telegram message ID.
        
        Args:
            telegram_message_id: Telegram message ID to look up
            
        Returns:
            Position if found, None otherwise
        """
        try:
            # Find signal by message ID
            signal = await self.signal_repo.find_by_message_id(telegram_message_id)
            if not signal:
                return None

            # Get positions for this signal
            positions = await self.position_repo.get_positions_by_signal(signal.id)
            if not positions:
                return None

            # Return the most recent open position, or latest if none open
            open_positions = [p for p in positions if p.is_open]
            return open_positions[0] if open_positions else positions[0]

        except Exception as e:
            self.logger.error(f"Error getting position by message ID {telegram_message_id}: {e}")
            return None

    async def find_recent_positions_in_window(self, symbol: str, start_time: datetime, end_time: datetime) -> list[Position]:
        """
        Find recent positions within time window for time-based matching.
        
        Args:
            symbol: Trading symbol to filter by
            start_time: Window start time
            end_time: Window end time
            
        Returns:
            List of positions in time window
        """
        try:
            # Get recent signals within time window
            window_minutes = int((end_time - start_time).total_seconds() / 60)
            recent_signals = await self.signal_repo.get_recent_signals(
                minutes=window_minutes + 1  # Add buffer for timing
            )

            # Filter by symbol and time window
            filtered_signals = [
                signal for signal in recent_signals
                if signal.symbol == symbol
                and start_time <= signal.timestamp <= end_time
            ]

            # Get positions for filtered signals
            positions = []
            for signal in filtered_signals:
                signal_positions = await self.position_repo.get_positions_by_signal(signal.id)
                positions.extend(signal_positions)

            return positions

        except Exception as e:
            self.logger.error(f"Error finding positions in time window: {e}")
            return []

    async def get_signal_by_message_id(self, telegram_message_id: int) -> Signal | None:
        """
        Get signal by Telegram message ID.
        
        Args:
            telegram_message_id: Telegram message ID
            
        Returns:
            Signal if found, None otherwise
        """
        try:
            return await self.signal_repo.find_by_message_id(telegram_message_id)
        except Exception as e:
            self.logger.error(f"Error getting signal by message ID {telegram_message_id}: {e}")
            return None

    def get_correlation_stats(self) -> dict[str, Any]:
        """Get correlation statistics for monitoring."""
        success_rate = (
            self._successful_correlations / self._correlation_attempts
            if self._correlation_attempts > 0 else 0.0
        )

        return {
            'total_attempts': self._correlation_attempts,
            'successful_correlations': self._successful_correlations,
            'reply_correlations': self._reply_correlations,
            'time_based_correlations': self._time_based_correlations,
            'success_rate': round(success_rate, 3)
        }
