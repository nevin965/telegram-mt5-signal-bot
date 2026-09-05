"""
Correlation Engine Module

Provides message correlation functionality for linking Telegram replies 
to original signals and positions. Supports both exact reply correlation
and time-based fallback matching with confidence scoring.

Key Components:
- CorrelationEngine: Main correlation orchestrator
- ReplyTracer: Multi-level reply chain traversal 
- TimeMatcher: Time-based correlation fallback
- TelegramMessage: Message data structure

Usage:
    from src.correlation_engine import CorrelationEngine, TelegramMessage
    
    engine = CorrelationEngine(db_manager, telegram_client)
    position = await engine.correlate_message(message)
"""

from .correlator import CorrelationEngine, CorrelationResult, TelegramMessage
from .reply_tracer import ReplyChainCache, ReplyTracer
from .time_matcher import TimeMatchCandidate, TimeMatcher

__all__ = [
    'CorrelationEngine',
    'CorrelationResult',
    'ReplyChainCache',
    'ReplyTracer',
    'TelegramMessage',
    'TimeMatchCandidate',
    'TimeMatcher'
]

__version__ = '1.0.0'
