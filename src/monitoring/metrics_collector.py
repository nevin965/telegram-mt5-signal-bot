"""
Metrics collection system for tracking system performance and statistics.
Follows coding standards: use logger, handle async cancellation, circuit breaker for external calls.
"""

import logging
import statistics
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Any

import psutil


class MetricData:
    """Container for a single metric measurement."""

    def __init__(self, value: int | float, timestamp: datetime | None = None, metadata: dict[str, Any] | None = None):
        self.value = value
        self.timestamp = timestamp or datetime.now(UTC)
        self.metadata = metadata or {}


class MetricsCollector:
    """
    System metrics collection and aggregation.
    Tracks performance metrics, message processing stats, and system health.
    """

    def __init__(self, max_history_minutes: int = 60):
        """
        Initialize metrics collector.
        
        Args:
            max_history_minutes: How many minutes of metrics to keep in memory
        """
        self.logger = logging.getLogger(__name__)
        self.max_history_minutes = max_history_minutes

        # Time-series metrics storage (value, timestamp)
        self._metrics: dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history_minutes * 60))  # 1 per second max

        # Counter metrics (reset daily)
        self._counters: dict[str, int] = defaultdict(int)
        self._daily_reset_time = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        # Latency measurements (for calculating percentiles)
        self._latencies: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))  # Last 1000 measurements

        # Connection stability tracking
        self._connection_events: deque = deque(maxlen=100)  # Last 100 connection events

        # Message processing tracking
        self._processing_events: deque = deque(maxlen=1000)  # Last 1000 processing events

        self.logger.info(f"Metrics collector initialized with {max_history_minutes}m history")

    def record_metric(self, metric_name: str, value: int | float, metadata: dict[str, Any] | None = None) -> None:
        """
        Record a time-series metric value.
        
        Args:
            metric_name: Name of the metric
            value: Metric value
            metadata: Optional metadata about this measurement
        """
        metric_data = MetricData(value, metadata=metadata)
        self._metrics[metric_name].append(metric_data)

        self.logger.debug(f"Recorded metric {metric_name}: {value}")

    def increment_counter(self, counter_name: str, amount: int = 1) -> None:
        """
        Increment a counter metric.
        
        Args:
            counter_name: Name of the counter
            amount: Amount to increment by
        """
        self._reset_daily_counters_if_needed()
        self._counters[counter_name] += amount

        self.logger.debug(f"Incremented counter {counter_name} by {amount} (total: {self._counters[counter_name]})")

    def record_latency(self, operation_name: str, latency_ms: float, metadata: dict[str, Any] | None = None) -> None:
        """
        Record a latency measurement.
        
        Args:
            operation_name: Name of the operation being measured
            latency_ms: Latency in milliseconds
            metadata: Optional metadata about this measurement
        """
        latency_data = MetricData(latency_ms, metadata=metadata)
        self._latencies[operation_name].append(latency_data)

        # Also record as time-series metric
        self.record_metric(f"{operation_name}_latency_ms", latency_ms, metadata)

        self.logger.debug(f"Recorded latency for {operation_name}: {latency_ms}ms")

    def record_connection_event(self, component: str, event_type: str, success: bool, metadata: dict[str, Any] | None = None) -> None:
        """
        Record a connection event for stability tracking.
        
        Args:
            component: Component name (e.g., 'telegram', 'mt5', 'openai')
            event_type: Event type ('connect', 'disconnect', 'reconnect', 'health_check')
            success: Whether the event was successful
            metadata: Optional metadata about this event
        """
        event_data = {
            'timestamp': datetime.now(UTC),
            'component': component,
            'event_type': event_type,
            'success': success,
            'metadata': metadata or {}
        }

        self._connection_events.append(event_data)

        # Update counters
        self.increment_counter(f"{component}_connection_{event_type}_total")
        if success:
            self.increment_counter(f"{component}_connection_{event_type}_success")
        else:
            self.increment_counter(f"{component}_connection_{event_type}_failure")

        self.logger.debug(f"Recorded connection event: {component} {event_type} {'success' if success else 'failure'}")

    def record_message_processing(self,
                                correlation_id: str,
                                stage: str,
                                success: bool,
                                latency_ms: float | None = None,
                                metadata: dict[str, Any] | None = None) -> None:
        """
        Record message processing event.
        
        Args:
            correlation_id: Message correlation ID for tracking
            stage: Processing stage ('parse', 'validate', 'execute', 'complete')
            success: Whether the stage was successful
            latency_ms: Stage processing time in milliseconds
            metadata: Optional metadata about this processing event
        """
        processing_data = {
            'timestamp': datetime.now(UTC),
            'correlation_id': correlation_id,
            'stage': stage,
            'success': success,
            'latency_ms': latency_ms,
            'metadata': metadata or {}
        }

        self._processing_events.append(processing_data)

        # Update counters
        self.increment_counter(f"message_processing_{stage}_total")
        if success:
            self.increment_counter(f"message_processing_{stage}_success")
        else:
            self.increment_counter(f"message_processing_{stage}_failure")

        # Record latency if provided
        if latency_ms is not None:
            self.record_latency(f"message_processing_{stage}", latency_ms, metadata)

        self.logger.debug(f"Recorded message processing: {stage} {'success' if success else 'failure'} ({latency_ms}ms)")

    def get_system_metrics(self) -> dict[str, Any]:
        """
        Get current system metrics (CPU, RAM, disk).
        
        Returns:
            Dictionary with system metrics
        """
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count()

            # Memory metrics
            memory = psutil.virtual_memory()
            memory_used_mb = round(memory.used / (1024 * 1024))
            memory_available_mb = round(memory.available / (1024 * 1024))
            memory_percent = memory.percent

            # Disk metrics (for logs directory)
            try:
                disk_usage = psutil.disk_usage('.')
                disk_used_gb = round(disk_usage.used / (1024 * 1024 * 1024), 1)
                disk_free_gb = round(disk_usage.free / (1024 * 1024 * 1024), 1)
                disk_percent = round((disk_usage.used / disk_usage.total) * 100, 1)
            except Exception:
                disk_used_gb = disk_free_gb = disk_percent = 0

            return {
                'cpu': {
                    'percent': cpu_percent,
                    'count': cpu_count
                },
                'memory': {
                    'used_mb': memory_used_mb,
                    'available_mb': memory_available_mb,
                    'percent': memory_percent,
                    'total_mb': round(memory.total / (1024 * 1024))
                },
                'disk': {
                    'used_gb': disk_used_gb,
                    'free_gb': disk_free_gb,
                    'percent': disk_percent
                },
                'timestamp': datetime.now(UTC).isoformat()
            }

        except Exception as e:
            self.logger.error(f"Error collecting system metrics: {e}")
            return {'error': str(e), 'timestamp': datetime.now(UTC).isoformat()}

    def get_counter(self, counter_name: str) -> int:
        """Get current value of a counter."""
        self._reset_daily_counters_if_needed()
        return self._counters[counter_name]

    def get_metric_history(self, metric_name: str, minutes: int | None = None) -> list[MetricData]:
        """
        Get historical values for a metric.
        
        Args:
            metric_name: Name of the metric
            minutes: Number of minutes of history (default: all available)
            
        Returns:
            List of MetricData objects
        """
        if metric_name not in self._metrics:
            return []

        history = list(self._metrics[metric_name])

        if minutes is not None:
            cutoff_time = datetime.now(UTC) - timedelta(minutes=minutes)
            history = [m for m in history if m.timestamp >= cutoff_time]

        return history

    def get_latency_stats(self, operation_name: str, minutes: int | None = None) -> dict[str, float]:
        """
        Get latency statistics for an operation.
        
        Args:
            operation_name: Name of the operation
            minutes: Number of minutes to analyze (default: all available)
            
        Returns:
            Dictionary with latency statistics (mean, median, p95, p99, min, max)
        """
        if operation_name not in self._latencies:
            return {}

        latencies = list(self._latencies[operation_name])

        if minutes is not None:
            cutoff_time = datetime.now(UTC) - timedelta(minutes=minutes)
            latencies = [l for l in latencies if l.timestamp >= cutoff_time]

        if not latencies:
            return {}

        values = [l.value for l in latencies]

        try:
            return {
                'count': len(values),
                'mean': statistics.mean(values),
                'median': statistics.median(values),
                'p95': self._percentile(values, 95),
                'p99': self._percentile(values, 99),
                'min': min(values),
                'max': max(values)
            }
        except Exception as e:
            self.logger.error(f"Error calculating latency stats for {operation_name}: {e}")
            return {'error': str(e)}

    def get_connection_stability(self, component: str, minutes: int = 60) -> dict[str, Any]:
        """
        Get connection stability metrics for a component.
        
        Args:
            component: Component name
            minutes: Number of minutes to analyze
            
        Returns:
            Dictionary with stability metrics
        """
        cutoff_time = datetime.now(UTC) - timedelta(minutes=minutes)

        # Filter events for this component and time period
        component_events = [
            event for event in self._connection_events
            if event['component'] == component and event['timestamp'] >= cutoff_time
        ]

        if not component_events:
            return {
                'total_events': 0,
                'success_rate': 100.0,  # Assume stable if no events
                'reconnects': 0,
                'last_event': None
            }

        total_events = len(component_events)
        successful_events = sum(1 for event in component_events if event['success'])
        success_rate = (successful_events / total_events) * 100 if total_events > 0 else 100.0

        reconnects = sum(1 for event in component_events if event['event_type'] == 'reconnect')

        # Find most recent event
        last_event = max(component_events, key=lambda x: x['timestamp'])

        return {
            'total_events': total_events,
            'success_rate': round(success_rate, 1),
            'reconnects': reconnects,
            'last_event': {
                'type': last_event['event_type'],
                'success': last_event['success'],
                'timestamp': last_event['timestamp'].isoformat()
            }
        }

    def get_processing_success_rate(self, stage: str | None = None, minutes: int = 60) -> float:
        """
        Get message processing success rate.
        
        Args:
            stage: Specific processing stage (optional, gets overall rate if None)
            minutes: Number of minutes to analyze
            
        Returns:
            Success rate as percentage (0.0 - 100.0)
        """
        cutoff_time = datetime.now(UTC) - timedelta(minutes=minutes)

        # Filter processing events
        events = [
            event for event in self._processing_events
            if event['timestamp'] >= cutoff_time
        ]

        if stage:
            events = [event for event in events if event['stage'] == stage]

        if not events:
            return 100.0  # Assume success if no data

        successful = sum(1 for event in events if event['success'])
        total = len(events)

        return (successful / total) * 100 if total > 0 else 100.0

    def get_messages_per_minute(self, minutes: int = 60) -> float:
        """
        Get messages per minute rate.
        
        Args:
            minutes: Number of minutes to analyze
            
        Returns:
            Messages per minute rate
        """
        cutoff_time = datetime.now(UTC) - timedelta(minutes=minutes)

        # Count messages in time period (use 'complete' stage to avoid double counting)
        message_events = [
            event for event in self._processing_events
            if (event['timestamp'] >= cutoff_time and
                event['stage'] == 'complete')
        ]

        if not message_events:
            return 0.0

        return len(message_events) / minutes

    def get_queue_depths(self, queue_names: list[str]) -> dict[str, int]:
        """
        Get current queue depths (placeholder - would be implemented by queue manager).
        
        Args:
            queue_names: List of queue names to check
            
        Returns:
            Dictionary mapping queue names to depths
        """
        # This would be implemented to integrate with actual queue manager
        # For now, return placeholder data
        return dict.fromkeys(queue_names, 0)

    def _percentile(self, data: list[float], percentile: int) -> float:
        """Calculate percentile of a dataset."""
        if not data:
            return 0.0

        sorted_data = sorted(data)
        index = (percentile / 100) * (len(sorted_data) - 1)

        if index.is_integer():
            return sorted_data[int(index)]
        else:
            lower = sorted_data[int(index)]
            upper = sorted_data[int(index) + 1]
            return lower + (upper - lower) * (index - int(index))

    def _reset_daily_counters_if_needed(self) -> None:
        """Reset daily counters if a new day has started."""
        now = datetime.now(UTC)
        current_day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if current_day_start > self._daily_reset_time:
            self.logger.info("Resetting daily counters for new day")
            self._counters.clear()
            self._daily_reset_time = current_day_start

    def get_all_metrics_summary(self) -> dict[str, Any]:
        """
        Get comprehensive metrics summary.
        
        Returns:
            Dictionary with all collected metrics and statistics
        """
        return {
            'system': self.get_system_metrics(),
            'counters': dict(self._counters),
            'processing': {
                'success_rate_overall': round(self.get_processing_success_rate(), 1),
                'success_rate_parse': round(self.get_processing_success_rate('parse'), 1),
                'success_rate_execute': round(self.get_processing_success_rate('execute'), 1),
                'messages_per_minute': round(self.get_messages_per_minute(), 2)
            },
            'latencies': {
                op_name: self.get_latency_stats(op_name, minutes=30)
                for op_name in list(self._latencies.keys())[:5]  # Top 5 operations
            },
            'connections': {
                'telegram': self.get_connection_stability('telegram'),
                'mt5': self.get_connection_stability('mt5'),
                'openai': self.get_connection_stability('openai')
            },
            'timestamp': datetime.now(UTC).isoformat()
        }
