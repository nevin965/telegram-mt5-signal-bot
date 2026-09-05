"""
Time-based correlation fallback for orphaned message handling.

This module implements time-window based correlation for messages that don't
have explicit reply relationships. Uses temporal proximity and text similarity
to establish correlations with confidence scoring.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.database.models import Position, Signal
from src.database.repository import PositionRepository, SignalRepository


@dataclass
class TimeMatchCandidate:
    """Candidate position for time-based correlation with scoring."""
    position: Position
    signal: Signal
    time_score: float
    text_score: float
    confidence: float
    metadata: dict[str, Any]


class TimeMatcher:
    """
    Time-based correlation engine for orphaned message matching.
    
    Uses temporal proximity and text pattern analysis to correlate
    messages with recent trading positions when explicit reply
    relationships are not available.
    """

    def __init__(self, signal_repo: SignalRepository, position_repo: PositionRepository):
        """
        Initialize time matcher with repository dependencies.
        
        Args:
            signal_repo: Signal repository for database queries
            position_repo: Position repository for database queries
        """
        self.logger = logging.getLogger(__name__)
        self.signal_repo = signal_repo
        self.position_repo = position_repo

        # Correlation parameters
        self.default_window_minutes = 5
        self.min_confidence_threshold = 0.75
        self.max_candidates = 10

        # Text pattern matching for correlation hints
        self.update_patterns = {
            'break_even': re.compile(r'\b(break\s*even|be)\b', re.IGNORECASE),
            'close': re.compile(r'\b(close|fermer|closed)\b', re.IGNORECASE),
            'stop_loss': re.compile(r'\b(sl|stop\s*loss|stop)\b', re.IGNORECASE),
            'take_profit': re.compile(r'\b(tp|take\s*profit|profit)\b', re.IGNORECASE),
            'modify': re.compile(r'\b(modif|modify|change|changer)\b', re.IGNORECASE),
            'partial': re.compile(r'\b(partial|partiel)\b', re.IGNORECASE)
        }

        # Symbol extraction patterns
        self.symbol_patterns = {
            'gold': re.compile(r'\b(gold|or|xau|xauusd)\b', re.IGNORECASE),
            'eur': re.compile(r'\b(eur|euro)\b', re.IGNORECASE),
            'gbp': re.compile(r'\b(gbp|pound|livre)\b', re.IGNORECASE),
        }

        # Statistics tracking
        self._match_attempts = 0
        self._successful_matches = 0
        self._candidate_evaluations = 0

    async def find_matches(self, message: Any, window_minutes: int = None) -> list[dict[str, Any]]:
        """
        Find time-based correlation matches for orphaned message.
        
        Args:
            message: TelegramMessage object to match
            window_minutes: Time window in minutes (default: 5)
            
        Returns:
            List of candidate matches with confidence scores
        """
        window_minutes = window_minutes or self.default_window_minutes
        match_id = f"time_match_{message.telegram_message_id}_{datetime.now().timestamp()}"

        try:
            self._match_attempts += 1

            self.logger.info(
                f"Starting time-based matching for message {message.telegram_message_id}",
                extra={
                    'match_id': match_id,
                    'window_minutes': window_minutes,
                    'message_text': message.raw_text[:50] + '...' if len(message.raw_text) > 50 else message.raw_text
                }
            )

            # Define time window
            end_time = message.timestamp
            start_time = end_time - timedelta(minutes=window_minutes)

            # Extract potential symbols from message text
            detected_symbols = self._extract_symbols(message.raw_text)

            # Get candidate positions within time window
            candidates = await self._get_candidate_positions(
                start_time, end_time, detected_symbols, match_id
            )

            if not candidates:
                self.logger.debug(
                    f"No candidate positions found in {window_minutes}min window",
                    extra={'match_id': match_id}
                )
                return []

            # Score and rank candidates
            scored_candidates = await self._score_candidates(
                message, candidates, match_id
            )

            # Filter by minimum confidence
            valid_candidates = [
                c for c in scored_candidates
                if c.confidence >= self.min_confidence_threshold
            ]

            if valid_candidates:
                self._successful_matches += 1

            # Convert to dictionary format for return
            result = [
                {
                    'position': candidate.position,
                    'signal': candidate.signal,
                    'confidence': candidate.confidence,
                    'time_score': candidate.time_score,
                    'text_score': candidate.text_score,
                    'metadata': candidate.metadata
                }
                for candidate in valid_candidates[:self.max_candidates]
            ]

            self.logger.info(
                f"Time matching complete: {len(scored_candidates)} candidates, "
                f"{len(valid_candidates)} above threshold",
                extra={
                    'match_id': match_id,
                    'valid_matches': len(valid_candidates)
                }
            )

            return result

        except Exception as e:
            self.logger.error(
                f"Error in time-based matching: {e}",
                extra={'match_id': match_id}
            )
            return []

    async def _get_candidate_positions(self, start_time: datetime, end_time: datetime,
                                     symbols: set[str], match_id: str) -> list[Position]:
        """
        Get candidate positions within time window.
        
        Args:
            start_time: Window start time
            end_time: Window end time
            symbols: Detected symbols to filter by
            match_id: Match ID for logging
            
        Returns:
            List of candidate positions
        """
        try:
            # Calculate window in minutes for signal query
            window_minutes = int((end_time - start_time).total_seconds() / 60)

            # Get recent signals in time window
            recent_signals = await self.signal_repo.get_recent_signals(
                minutes=window_minutes + 2  # Add buffer
            )

            # Filter signals by time window and symbols
            filtered_signals = []
            for signal in recent_signals:
                # Check time bounds
                if not (start_time <= signal.timestamp <= end_time):
                    continue

                # Check symbol match if symbols detected
                if symbols and signal.symbol.upper() not in symbols:
                    continue

                filtered_signals.append(signal)

            # Get positions for filtered signals
            candidate_positions = []
            for signal in filtered_signals:
                positions = await self.position_repo.get_positions_by_signal(signal.id)
                for position in positions:
                    # Prefer open positions for correlation
                    if position.is_open or not candidate_positions:
                        candidate_positions.append(position)

            self.logger.debug(
                f"Found {len(candidate_positions)} candidate positions from "
                f"{len(filtered_signals)} signals",
                extra={'match_id': match_id}
            )

            return candidate_positions[:20]  # Limit for performance

        except Exception as e:
            self.logger.error(f"Error getting candidate positions: {e}")
            return []

    async def _score_candidates(self, message: Any, candidates: list[Position],
                              match_id: str) -> list[TimeMatchCandidate]:
        """
        Score and rank candidate positions for correlation.
        
        Args:
            message: Message to correlate
            candidates: Candidate positions
            match_id: Match ID for logging
            
        Returns:
            List of scored candidates sorted by confidence
        """
        scored_candidates = []

        for position in candidates:
            try:
                self._candidate_evaluations += 1

                # Get associated signal
                signal = await self.signal_repo.get_by_id(position.signal_id)
                if not signal:
                    continue

                # Calculate time-based score
                time_score = self._calculate_time_score(message.timestamp, signal.timestamp)

                # Calculate text similarity score
                text_score = self._calculate_text_score(message.raw_text, signal.raw_text)

                # Calculate composite confidence score
                confidence = self._calculate_confidence(
                    time_score, text_score, position, signal
                )

                # Create metadata for debugging
                metadata = {
                    'time_diff_seconds': (message.timestamp - signal.timestamp).total_seconds(),
                    'signal_action': signal.parsed_action.value if signal.parsed_action else None,
                    'position_status': position.status.value if position.status else None,
                    'symbol_match': signal.symbol,
                    'scoring_method': 'time_based'
                }

                scored_candidate = TimeMatchCandidate(
                    position=position,
                    signal=signal,
                    time_score=time_score,
                    text_score=text_score,
                    confidence=confidence,
                    metadata=metadata
                )

                scored_candidates.append(scored_candidate)

            except Exception as e:
                self.logger.warning(
                    f"Error scoring candidate position {position.id}: {e}",
                    extra={'match_id': match_id}
                )
                continue

        # Sort by confidence descending
        scored_candidates.sort(key=lambda x: x.confidence, reverse=True)

        self.logger.debug(
            f"Scored {len(scored_candidates)} candidates, "
            f"best confidence: {scored_candidates[0].confidence:.3f}" if scored_candidates else "no candidates",
            extra={'match_id': match_id}
        )

        return scored_candidates

    def _calculate_time_score(self, message_time: datetime, signal_time: datetime) -> float:
        """
        Calculate time proximity score (0.0 to 1.0).
        
        Args:
            message_time: Message timestamp
            signal_time: Signal timestamp
            
        Returns:
            Time score (1.0 = same time, decreases with distance)
        """
        time_diff = abs((message_time - signal_time).total_seconds())

        # Score decreases exponentially with time distance
        # 0 seconds = 1.0, 60 seconds = 0.8, 300 seconds (5 min) = 0.6
        max_diff = 300  # 5 minutes
        if time_diff >= max_diff:
            return 0.6

        # Exponential decay function
        normalized_diff = time_diff / max_diff
        score = 1.0 - (0.4 * normalized_diff)

        return max(0.6, score)

    def _calculate_text_score(self, message_text: str, signal_text: str) -> float:
        """
        Calculate text pattern similarity score.
        
        Args:
            message_text: Update message text
            signal_text: Original signal text
            
        Returns:
            Text similarity score (0.0 to 1.0)
        """
        if not message_text or not signal_text:
            return 0.5

        message_lower = message_text.lower()
        signal_lower = signal_text.lower()

        score = 0.5  # Base score

        # Check for update pattern keywords
        for pattern_name, pattern in self.update_patterns.items():
            if pattern.search(message_lower):
                score += 0.1
                # Extra boost if related words in signal
                if (pattern_name == 'break_even' and 'entry' in signal_lower) or (pattern_name in ['close', 'stop_loss'] and ('sl' in signal_lower or 'stop' in signal_lower)) or (pattern_name == 'take_profit' and ('tp' in signal_lower or 'profit' in signal_lower)):
                    score += 0.1

        # Check for common words/phrases
        message_words = set(message_lower.split())
        signal_words = set(signal_lower.split())

        if message_words and signal_words:
            common_words = message_words.intersection(signal_words)
            word_similarity = len(common_words) / max(len(message_words), len(signal_words))
            score += word_similarity * 0.2

        return min(1.0, score)

    def _calculate_confidence(self, time_score: float, text_score: float,
                            position: Position, signal: Signal) -> float:
        """
        Calculate composite confidence score for correlation.
        
        Args:
            time_score: Time proximity score
            text_score: Text similarity score
            position: Position object
            signal: Signal object
            
        Returns:
            Composite confidence score (0.0 to 1.0)
        """
        # Base score weighted by time and text
        base_confidence = (time_score * 0.6) + (text_score * 0.4)

        # Boost for open positions (more likely to receive updates)
        if position.is_open:
            base_confidence *= 1.1

        # Boost for recent signals (within 2 minutes)
        signal_age_seconds = (datetime.now(UTC).replace(tzinfo=None) - signal.timestamp).total_seconds()
        if signal_age_seconds < 120:  # 2 minutes
            base_confidence *= 1.05

        # Slight penalty for very old signals
        if signal_age_seconds > 600:  # 10 minutes
            base_confidence *= 0.95

        return min(1.0, base_confidence)

    def _extract_symbols(self, text: str) -> set[str]:
        """
        Extract trading symbols from message text.
        
        Args:
            text: Message text to analyze
            
        Returns:
            Set of detected symbol names in uppercase
        """
        detected = set()
        text_lower = text.lower()

        for symbol_name, pattern in self.symbol_patterns.items():
            if pattern.search(text_lower):
                # Map to standard symbol format
                if symbol_name == 'gold':
                    detected.add('GOLD')
                    detected.add('XAUUSD')
                elif symbol_name == 'eur':
                    detected.add('EURUSD')
                elif symbol_name == 'gbp':
                    detected.add('GBPUSD')

        return detected

    def get_matcher_stats(self) -> dict[str, Any]:
        """Get time matcher statistics for monitoring."""
        success_rate = (
            self._successful_matches / self._match_attempts
            if self._match_attempts > 0 else 0.0
        )

        avg_evaluations = (
            self._candidate_evaluations / self._match_attempts
            if self._match_attempts > 0 else 0.0
        )

        return {
            'match_attempts': self._match_attempts,
            'successful_matches': self._successful_matches,
            'success_rate': round(success_rate, 3),
            'total_evaluations': self._candidate_evaluations,
            'avg_evaluations_per_match': round(avg_evaluations, 1),
            'min_confidence_threshold': self.min_confidence_threshold,
            'default_window_minutes': self.default_window_minutes
        }
