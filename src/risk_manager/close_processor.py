"""
Close signal processor for detecting and handling position closure requests.

This module implements close signal detection with French pattern recognition,
partial close percentage extraction, and structured close instruction generation.
Follows coding standards: structured logging, async cancellation handling.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.correlation_engine.correlator import CorrelationEngine, TelegramMessage
from src.database.models import Position
from src.database.repository import RepositoryFactory
from src.mt5_executor.position_manager import PositionManager
from src.utils.decorators import circuit_breaker, log_execution_time


class CloseAction(str, Enum):
    """Enumeration for close action types."""
    FULL_CLOSE = "FULL_CLOSE"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    CLOSE_ALL = "CLOSE_ALL"


@dataclass
class CloseInstruction:
    """Structured close instruction with action details."""
    action: CloseAction
    percentage: float | None = None  # 0.0-1.0 for partial closes
    symbol_filter: str | None = None  # Symbol filter for CLOSE_ALL
    confidence: float = 0.0  # Signal detection confidence score


class CloseProcessor:
    """
    Close signal processor for immediate position closure execution.

    Handles close signal detection with French pattern recognition,
    volume calculations for partial closes, and MT5 execution with
    proper error handling and audit trail.
    """

    def __init__(
        self,
        correlation_engine: CorrelationEngine,
        position_manager: PositionManager,
        repo_factory: RepositoryFactory
    ):
        """
        Initialize close processor with dependencies.

        Args:
            correlation_engine: For correlating close messages to positions
            position_manager: For executing MT5 close operations
            repo_factory: For database operations
        """
        self.logger = logging.getLogger(__name__)
        self.correlation_engine = correlation_engine
        self.position_manager = position_manager
        self.repo_factory = repo_factory

        # Get repositories
        self.position_repo = repo_factory.get_position_repository()

        # Close signal patterns (French and English)
        self._full_close_patterns = [
            r'\b(?:clôturez|fermez|fermer|tp\s+hit|exit|clôture)\b',
            r'\b(?:fermer\s+la\s+position|clôture\s+position)\b',
            r'\bclose\b(?!\s+(?:all|\d+%|moitié|half))',  # CLOSE but not followed by ALL or percentage
            r'^stop$|^stop\s+(?:hit|activé|triggered)',  # STOP only as standalone or with specific keywords
        ]

        self._partial_close_patterns = [
            r'\b(?:close|fermez|fermer)\s+(\d+)%',
            r'\b(\d+)%\s+(?:close|fermez)',
            r'\b(?:partial\s+tp)\s+(\d+)%',
            r'\b(?:close|fermez)\s+(?:la\s+)?moitié\b',
            r'\b(?:partial\s+tp|fermez\s+moitié)\b',
            r'\b(?:close|fermez)\s+(?:la\s+)?half\b'
        ]

        self._close_all_patterns = [
            r'\b(?:close\s+all|fermez\s+tout)\s+(?:positions?\s*)?(?:on\s+)?(\w+)\b',
            r'\b(?:close\s+all|fermez\s+tout)\s+(\w+)\s+(?:positions?)\b',
            r'\b(?:close\s+all|fermez\s+tout)(?:\s+positions?)?\b'
        ]

        # Percentage mapping for text-based percentages
        self._percentage_mapping = {
            'moitié': 0.5,
            'half': 0.5,
            'tout': 1.0,
            'all': 1.0
        }

    @log_execution_time
    async def detect_close_signal(self, text: str) -> CloseInstruction | None:
        """
        Detect close signal from message text with French pattern recognition.

        Args:
            text: Message text to analyze

        Returns:
            CloseInstruction if close signal detected, None otherwise
        """
        try:
            text_lower = text.lower().strip()

            self.logger.debug(
                f"Analyzing text for close signals: '{text_lower[:100]}...'",
                extra={'text_length': len(text)}
            )

            # Check for CLOSE ALL patterns first (highest priority)
            close_all_result = self._detect_close_all(text_lower)
            if close_all_result:
                self.logger.info(
                    f"Detected CLOSE ALL signal with symbol filter: {close_all_result.symbol_filter}",
                    extra={
                        'action': close_all_result.action,
                        'symbol_filter': close_all_result.symbol_filter,
                        'confidence': close_all_result.confidence
                    }
                )
                return close_all_result

            # Check for partial close patterns
            partial_result = self._detect_partial_close(text_lower)
            if partial_result:
                self.logger.info(
                    f"Detected PARTIAL CLOSE signal: {partial_result.percentage:.1%}",
                    extra={
                        'action': partial_result.action,
                        'percentage': partial_result.percentage,
                        'confidence': partial_result.confidence
                    }
                )
                return partial_result

            # Check for full close patterns
            full_result = self._detect_full_close(text_lower)
            if full_result:
                self.logger.info(
                    "Detected FULL CLOSE signal",
                    extra={
                        'action': full_result.action,
                        'confidence': full_result.confidence
                    }
                )
                return full_result

            # No close signal detected
            self.logger.debug("No close signal patterns matched")
            return None

        except Exception as e:
            self.logger.error(f"Error detecting close signal: {e}")
            return None

    def _detect_close_all(self, text: str) -> CloseInstruction | None:
        """Detect close all patterns with symbol filtering."""
        for pattern in self._close_all_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                symbol_filter = None
                if match.lastindex and match.lastindex >= 1:
                    symbol_filter = match.group(1).upper()
                    # Normalize common symbol names
                    if symbol_filter in ['GOLD', 'XAU', 'XAUUSD']:
                        symbol_filter = 'GOLD'
                    elif symbol_filter == 'EUR':
                        symbol_filter = 'EUR'  # Keep EUR as is for the test case
                    elif symbol_filter == 'EURUSD':
                        symbol_filter = 'EURUSD'

                return CloseInstruction(
                    action=CloseAction.CLOSE_ALL,
                    symbol_filter=symbol_filter,
                    confidence=0.95  # High confidence for explicit patterns
                )
        return None

    def _detect_partial_close(self, text: str) -> CloseInstruction | None:
        """Detect partial close patterns and extract percentage."""
        # Check percentage patterns first
        for pattern in self._partial_close_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Check if we captured a numeric percentage
                for group_num in range(1, match.lastindex + 1 if match.lastindex else 1):
                    group_val = match.group(group_num)
                    if group_val and group_val.isdigit():
                        percentage = float(group_val) / 100.0
                        if 0.0 < percentage < 1.0:  # Valid partial percentage
                            return CloseInstruction(
                                action=CloseAction.PARTIAL_CLOSE,
                                percentage=percentage,
                                confidence=0.9
                            )

                # Text-based percentage (e.g., "moitié", "half")
                for word, pct in self._percentage_mapping.items():
                    if word in text and pct < 1.0:  # Only partial percentages
                        return CloseInstruction(
                            action=CloseAction.PARTIAL_CLOSE,
                            percentage=pct,
                            confidence=0.85
                        )
        return None

    def _detect_full_close(self, text: str) -> CloseInstruction | None:
        """Detect full close patterns."""
        for pattern in self._full_close_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return CloseInstruction(
                    action=CloseAction.FULL_CLOSE,
                    confidence=0.8  # Standard confidence for full close
                )
        return None

    @circuit_breaker(failure_threshold=3, recovery_timeout=30)
    @log_execution_time
    async def process_close_signal(self, message: TelegramMessage) -> dict:
        """
        Main close processing interface - process close signal from message.

        Args:
            message: Telegram message containing close signal

        Returns:
            Dictionary with processing results and status
        """
        processing_id = f"close_{message.telegram_message_id}_{datetime.now().timestamp()}"
        start_time = datetime.now()

        try:
            self.logger.info(
                f"Starting close signal processing for message {message.telegram_message_id}",
                extra={
                    'processing_id': processing_id,
                    'message_id': message.telegram_message_id,
                    'chat_id': message.telegram_chat_id,
                    'sender': message.sender
                }
            )

            # Detect close instruction
            close_instruction = await self.detect_close_signal(message.raw_text)
            if not close_instruction:
                return {
                    'success': False,
                    'processing_id': processing_id,
                    'error': 'No close signal detected',
                    'execution_time_ms': (datetime.now() - start_time).total_seconds() * 1000
                }

            # Process based on close action type
            if close_instruction.action == CloseAction.CLOSE_ALL:
                result = await self._process_close_all_command(
                    close_instruction.symbol_filter,
                    processing_id
                )
            else:
                # Single position close (full or partial)
                target_position = await self.correlation_engine.correlate_message(message)
                if not target_position:
                    return {
                        'success': False,
                        'processing_id': processing_id,
                        'error': 'Could not correlate message to position',
                        'execution_time_ms': (datetime.now() - start_time).total_seconds() * 1000
                    }

                if close_instruction.action == CloseAction.FULL_CLOSE:
                    result = await self._execute_full_close(target_position, processing_id)
                else:  # PARTIAL_CLOSE
                    if close_instruction.percentage is None:
                        return {
                            'success': False,
                            'processing_id': processing_id,
                            'error': 'No percentage specified for partial close',
                            'execution_time_ms': (datetime.now() - start_time).total_seconds() * 1000
                        }
                    result = await self._execute_partial_close(
                        target_position,
                        close_instruction.percentage,
                        processing_id
                    )

            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            result['execution_time_ms'] = execution_time

            self.logger.info(
                f"Close processing completed in {execution_time:.1f}ms",
                extra={
                    'processing_id': processing_id,
                    'success': result['success'],
                    'action': close_instruction.action,
                    'execution_time_ms': execution_time
                }
            )

            return result

        except asyncio.CancelledError:
            self.logger.info(f"Close processing cancelled for message {message.telegram_message_id}")
            raise
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            self.logger.error(
                f"Error processing close signal: {e}",
                extra={
                    'processing_id': processing_id,
                    'error': str(e),
                    'execution_time_ms': execution_time
                }
            )
            return {
                'success': False,
                'processing_id': processing_id,
                'error': f"Processing exception: {e}",
                'execution_time_ms': execution_time
            }

    async def _process_close_all_command(self, symbol: str | None, processing_id: str) -> dict:
        """
        Process close all command for multiple positions.

        Args:
            symbol: Symbol filter (e.g., 'GOLD') or None for all symbols
            processing_id: Unique processing identifier

        Returns:
            Dictionary with batch closure results
        """
        try:
            # Find all open positions matching symbol filter
            all_positions = await self.position_repo.get_open_positions()

            if symbol:
                # Filter by symbol through signal relationship
                target_positions = [
                    position for position in all_positions
                    if position.signal and position.signal.symbol == symbol
                ]
            else:
                target_positions = all_positions

            if not target_positions:
                return {
                    'success': True,
                    'processing_id': processing_id,
                    'message': f'No open positions found for symbol filter: {symbol}',
                    'positions_closed': 0,
                    'failures': []
                }

            self.logger.info(
                f"Found {len(target_positions)} positions to close",
                extra={
                    'processing_id': processing_id,
                    'symbol_filter': symbol,
                    'position_count': len(target_positions)
                }
            )

            # Execute concurrent closures using asyncio.gather
            close_tasks = []
            for position in target_positions:
                task = self._execute_full_close(position, processing_id)
                close_tasks.append(task)

            # Execute all closes concurrently with error isolation
            results = await asyncio.gather(*close_tasks, return_exceptions=True)

            # Analyze results
            successful_closes = 0
            failures = []

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    failures.append({
                        'position_id': target_positions[i].id,
                        'ticket': target_positions[i].mt5_ticket,
                        'error': str(result)
                    })
                elif isinstance(result, dict) and result.get('success', False):
                    successful_closes += 1
                elif isinstance(result, dict):
                    failures.append({
                        'position_id': target_positions[i].id,
                        'ticket': target_positions[i].mt5_ticket,
                        'error': result.get('error', 'Unknown error')
                    })
                else:
                    failures.append({
                        'position_id': target_positions[i].id,
                        'ticket': target_positions[i].mt5_ticket,
                        'error': f'Unexpected result type: {type(result)}'
                    })

            success_rate = successful_closes / len(target_positions) if target_positions else 1.0

            return {
                'success': success_rate >= 0.8,  # Consider successful if 80%+ positions closed
                'processing_id': processing_id,
                'positions_closed': successful_closes,
                'total_positions': len(target_positions),
                'success_rate': success_rate,
                'failures': failures
            }

        except Exception as e:
            self.logger.error(f"Error in close all processing: {e}")
            return {
                'success': False,
                'processing_id': processing_id,
                'error': f"Close all exception: {e}",
                'positions_closed': 0,
                'failures': []
            }

    async def _execute_full_close(self, position: Position, processing_id: str) -> dict:
        """Execute full position close."""
        try:
            if not position.mt5_ticket:
                return {
                    'success': False,
                    'processing_id': processing_id,
                    'error': f'Position {position.id} has no MT5 ticket'
                }

            # Execute MT5 close
            close_result = await self.position_manager.close_position_full(position.mt5_ticket)

            if close_result.success:
                # Update database position record
                await self._update_position_closed(
                    position,
                    close_result.close_price or 0.0,
                    close_result.profit or 0.0,
                    close_result.volume_closed or 0.0,
                    processing_id
                )

                return {
                    'success': True,
                    'processing_id': processing_id,
                    'position_id': position.id,
                    'ticket': position.mt5_ticket,
                    'volume_closed': close_result.volume_closed,
                    'close_price': close_result.close_price,
                    'profit': close_result.profit
                }
            else:
                return {
                    'success': False,
                    'processing_id': processing_id,
                    'position_id': position.id,
                    'ticket': position.mt5_ticket,
                    'error': close_result.error_message
                }

        except Exception as e:
            self.logger.error(f"Error executing full close: {e}")
            return {
                'success': False,
                'processing_id': processing_id,
                'error': f"Full close exception: {e}"
            }

    async def _execute_partial_close(
        self,
        position: Position,
        percentage: float,
        processing_id: str
    ) -> dict:
        """Execute partial position close."""
        try:
            if not position.mt5_ticket:
                return {
                    'success': False,
                    'processing_id': processing_id,
                    'error': f'Position {position.id} has no MT5 ticket'
                }

            # Execute MT5 partial close
            close_result = await self.position_manager.close_position_partial(
                position.mt5_ticket,
                percentage
            )

            if close_result.success:
                # Update database position record for partial close
                await self._update_position_partial_close(
                    position,
                    close_result.close_price or 0.0,
                    close_result.profit or 0.0,
                    close_result.volume_closed or 0.0,
                    percentage,
                    processing_id
                )

                return {
                    'success': True,
                    'processing_id': processing_id,
                    'position_id': position.id,
                    'ticket': position.mt5_ticket,
                    'percentage': percentage,
                    'volume_closed': close_result.volume_closed,
                    'close_price': close_result.close_price,
                    'profit': close_result.profit
                }
            else:
                return {
                    'success': False,
                    'processing_id': processing_id,
                    'position_id': position.id,
                    'ticket': position.mt5_ticket,
                    'error': close_result.error_message
                }

        except Exception as e:
            self.logger.error(f"Error executing partial close: {e}")
            return {
                'success': False,
                'processing_id': processing_id,
                'error': f"Partial close exception: {e}"
            }

    async def _update_position_closed(
        self,
        position: Position,
        close_price: float,
        profit: float,
        volume_closed: float,
        processing_id: str
    ) -> None:
        """Update position record for full closure."""
        try:
            close_time = datetime.now()

            # Update position record
            success = await self.position_repo.update_position_closed(
                position.id,
                close_price,
                profit,
                close_time
            )

            # Record audit trail
            update_repo = self.repo_factory.get_position_update_repository()
            await update_repo.record_close_attempt(
                position.id,
                "FULL_CLOSE",
                volume_closed,
                success,
                None if success else "Database update failed"
            )

            if success:
                self.logger.info(
                    f"Successfully updated position {position.id} as closed",
                    extra={
                        'processing_id': processing_id,
                        'position_id': position.id,
                        'close_price': close_price,
                        'profit': profit
                    }
                )
            else:
                self.logger.error(
                    f"Failed to update position {position.id} as closed",
                    extra={'processing_id': processing_id}
                )

        except Exception as e:
            self.logger.error(f"Error updating position closure: {e}")
            # Still record the audit trail for the failure
            try:
                update_repo = self.repo_factory.get_position_update_repository()
                await update_repo.record_close_attempt(
                    position.id,
                    "FULL_CLOSE",
                    volume_closed,
                    False,
                    str(e)
                )
            except Exception as audit_error:
                self.logger.error(f"Failed to record audit trail: {audit_error}")

    async def _update_position_partial_close(
        self,
        position: Position,
        close_price: float,
        profit: float,
        volume_closed: float,
        percentage: float,
        processing_id: str
    ) -> None:
        """Update position record for partial closure."""
        try:
            close_time = datetime.now()
            volume_remaining = position.volume - volume_closed

            # Update position record
            success = await self.position_repo.update_position_partial_close(
                position.id,
                close_price,
                profit,
                volume_remaining,
                close_time
            )

            # Record audit trail
            update_repo = self.repo_factory.get_position_update_repository()
            await update_repo.record_close_attempt(
                position.id,
                "PARTIAL_CLOSE",
                volume_closed,
                success,
                None if success else "Database update failed"
            )

            if success:
                self.logger.info(
                    f"Successfully updated position {position.id} for partial close",
                    extra={
                        'processing_id': processing_id,
                        'position_id': position.id,
                        'percentage': percentage,
                        'volume_closed': volume_closed,
                        'volume_remaining': volume_remaining,
                        'close_price': close_price,
                        'profit': profit
                    }
                )
            else:
                self.logger.error(
                    f"Failed to update position {position.id} for partial close",
                    extra={'processing_id': processing_id}
                )

        except Exception as e:
            self.logger.error(f"Error updating partial position closure: {e}")
            # Still record the audit trail for the failure
            try:
                update_repo = self.repo_factory.get_position_update_repository()
                await update_repo.record_close_attempt(
                    position.id,
                    "PARTIAL_CLOSE",
                    volume_closed,
                    False,
                    str(e)
                )
            except Exception as audit_error:
                self.logger.error(f"Failed to record audit trail: {audit_error}")
