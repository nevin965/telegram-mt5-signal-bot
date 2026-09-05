"""
Unit tests for metrics collector component.
Tests metrics collection, aggregation, and calculation accuracy.
"""

import pytest
from datetime import datetime, UTC, timedelta
from collections import deque
from unittest.mock import patch, MagicMock

from src.monitoring.metrics_collector import MetricsCollector, MetricData


class TestMetricData:
    """Test MetricData class."""
    
    def test_metric_data_initialization(self):
        """Test MetricData initialization with default values."""
        metric = MetricData(100.5)
        
        assert metric.value == 100.5
        assert isinstance(metric.timestamp, datetime)
        assert metric.metadata == {}
    
    def test_metric_data_with_values(self):
        """Test MetricData initialization with custom values."""
        timestamp = datetime.now(UTC)
        metadata = {"source": "test", "category": "performance"}
        
        metric = MetricData(42, timestamp, metadata)
        
        assert metric.value == 42
        assert metric.timestamp == timestamp
        assert metric.metadata == metadata


class TestMetricsCollector:
    """Test MetricsCollector class."""
    
    @pytest.fixture
    def metrics_collector(self):
        """Create a MetricsCollector instance for testing."""
        return MetricsCollector(max_history_minutes=5)  # Shorter for testing
    
    def test_metrics_collector_initialization(self, metrics_collector):
        """Test MetricsCollector initialization."""
        assert metrics_collector.max_history_minutes == 5
        assert len(metrics_collector._metrics) == 0
        assert len(metrics_collector._counters) == 0
        assert len(metrics_collector._latencies) == 0
        assert isinstance(metrics_collector._connection_events, deque)
        assert isinstance(metrics_collector._processing_events, deque)
    
    def test_record_metric(self, metrics_collector):
        """Test recording time-series metrics."""
        metrics_collector.record_metric("cpu_usage", 75.5)
        metrics_collector.record_metric("memory_usage", 1024, {"unit": "MB"})
        
        # Check metrics storage
        assert "cpu_usage" in metrics_collector._metrics
        assert "memory_usage" in metrics_collector._metrics
        
        cpu_metrics = list(metrics_collector._metrics["cpu_usage"])
        memory_metrics = list(metrics_collector._metrics["memory_usage"])
        
        assert len(cpu_metrics) == 1
        assert len(memory_metrics) == 1
        assert cpu_metrics[0].value == 75.5
        assert memory_metrics[0].value == 1024
        assert memory_metrics[0].metadata == {"unit": "MB"}
    
    def test_increment_counter(self, metrics_collector):
        """Test counter incrementation."""
        # Initial increment
        metrics_collector.increment_counter("requests_total")
        assert metrics_collector.get_counter("requests_total") == 1
        
        # Multiple increments
        metrics_collector.increment_counter("requests_total", 5)
        assert metrics_collector.get_counter("requests_total") == 6
        
        # Different counter
        metrics_collector.increment_counter("errors_total", 2)
        assert metrics_collector.get_counter("errors_total") == 2
        assert metrics_collector.get_counter("requests_total") == 6
    
    def test_record_latency(self, metrics_collector):
        """Test latency recording."""
        metrics_collector.record_latency("api_call", 150.5)
        metrics_collector.record_latency("database_query", 25.0, {"query_type": "SELECT"})
        
        # Check latency storage
        assert "api_call" in metrics_collector._latencies
        assert "database_query" in metrics_collector._latencies
        
        api_latencies = list(metrics_collector._latencies["api_call"])
        db_latencies = list(metrics_collector._latencies["database_query"])
        
        assert len(api_latencies) == 1
        assert len(db_latencies) == 1
        assert api_latencies[0].value == 150.5
        assert db_latencies[0].value == 25.0
        assert db_latencies[0].metadata == {"query_type": "SELECT"}
        
        # Check that latency is also recorded as time-series metric
        assert "api_call_latency_ms" in metrics_collector._metrics
    
    def test_record_connection_event(self, metrics_collector):
        """Test connection event recording."""
        metrics_collector.record_connection_event("telegram", "connect", True)
        metrics_collector.record_connection_event("telegram", "health_check", False, {"error": "timeout"})
        
        # Check events storage
        events = list(metrics_collector._connection_events)
        assert len(events) == 2
        
        assert events[0]["component"] == "telegram"
        assert events[0]["event_type"] == "connect"
        assert events[0]["success"] is True
        
        assert events[1]["component"] == "telegram"
        assert events[1]["event_type"] == "health_check"
        assert events[1]["success"] is False
        assert events[1]["metadata"] == {"error": "timeout"}
        
        # Check counters
        assert metrics_collector.get_counter("telegram_connection_connect_total") == 1
        assert metrics_collector.get_counter("telegram_connection_connect_success") == 1
        assert metrics_collector.get_counter("telegram_connection_health_check_total") == 1
        assert metrics_collector.get_counter("telegram_connection_health_check_failure") == 1
    
    def test_record_message_processing(self, metrics_collector):
        """Test message processing event recording."""
        correlation_id = "test-123"
        
        metrics_collector.record_message_processing(correlation_id, "parse", True, 50.0)
        metrics_collector.record_message_processing(correlation_id, "execute", False, 200.0, {"error": "invalid_signal"})
        
        # Check processing events
        events = list(metrics_collector._processing_events)
        assert len(events) == 2
        
        assert events[0]["correlation_id"] == correlation_id
        assert events[0]["stage"] == "parse"
        assert events[0]["success"] is True
        assert events[0]["latency_ms"] == 50.0
        
        assert events[1]["correlation_id"] == correlation_id
        assert events[1]["stage"] == "execute"
        assert events[1]["success"] is False
        assert events[1]["latency_ms"] == 200.0
        assert events[1]["metadata"] == {"error": "invalid_signal"}
        
        # Check counters
        assert metrics_collector.get_counter("message_processing_parse_total") == 1
        assert metrics_collector.get_counter("message_processing_parse_success") == 1
        assert metrics_collector.get_counter("message_processing_execute_total") == 1
        assert metrics_collector.get_counter("message_processing_execute_failure") == 1
        
        # Check latencies
        assert "message_processing_parse" in metrics_collector._latencies
        assert "message_processing_execute" in metrics_collector._latencies
    
    @patch('psutil.cpu_percent')
    @patch('psutil.cpu_count')
    @patch('psutil.virtual_memory')
    @patch('psutil.disk_usage')
    def test_get_system_metrics(self, mock_disk, mock_memory, mock_cpu_count, mock_cpu_percent, metrics_collector):
        """Test system metrics collection."""
        # Mock system data
        mock_cpu_percent.return_value = 45.2
        mock_cpu_count.return_value = 8
        
        mock_memory_obj = MagicMock()
        mock_memory_obj.used = 8 * 1024 * 1024 * 1024  # 8GB in bytes
        mock_memory_obj.available = 2 * 1024 * 1024 * 1024  # 2GB in bytes
        mock_memory_obj.percent = 80.0
        mock_memory_obj.total = 10 * 1024 * 1024 * 1024  # 10GB in bytes
        mock_memory.return_value = mock_memory_obj
        
        mock_disk_obj = MagicMock()
        mock_disk_obj.used = 100 * 1024 * 1024 * 1024  # 100GB in bytes
        mock_disk_obj.free = 50 * 1024 * 1024 * 1024   # 50GB in bytes
        mock_disk_obj.total = 150 * 1024 * 1024 * 1024 # 150GB in bytes
        mock_disk.return_value = mock_disk_obj
        
        # Get system metrics
        metrics = metrics_collector.get_system_metrics()
        
        # Verify results
        assert metrics["cpu"]["percent"] == 45.2
        assert metrics["cpu"]["count"] == 8
        assert metrics["memory"]["used_mb"] == 8192  # 8GB
        assert metrics["memory"]["available_mb"] == 2048  # 2GB
        assert metrics["memory"]["percent"] == 80.0
        assert metrics["memory"]["total_mb"] == 10240  # 10GB
        assert metrics["disk"]["used_gb"] == 100.0
        assert metrics["disk"]["free_gb"] == 50.0
        assert round(metrics["disk"]["percent"], 1) == 66.7  # 100/150 * 100
        assert "timestamp" in metrics
    
    def test_get_metric_history(self, metrics_collector):
        """Test retrieving metric history."""
        # Add some metrics
        metrics_collector.record_metric("test_metric", 10)
        metrics_collector.record_metric("test_metric", 20)
        metrics_collector.record_metric("test_metric", 30)
        
        # Get all history
        history = metrics_collector.get_metric_history("test_metric")
        assert len(history) == 3
        assert [m.value for m in history] == [10, 20, 30]
        
        # Get non-existent metric
        empty_history = metrics_collector.get_metric_history("nonexistent")
        assert len(empty_history) == 0
    
    def test_get_latency_stats(self, metrics_collector):
        """Test latency statistics calculation."""
        # Add latency measurements
        latencies = [100, 150, 200, 120, 180, 300, 90, 110]
        for latency in latencies:
            metrics_collector.record_latency("test_operation", latency)
        
        # Get statistics
        stats = metrics_collector.get_latency_stats("test_operation")
        
        assert stats["count"] == 8
        assert stats["mean"] == 156.25  # Average of the values
        assert stats["median"] == 135.0  # Median of sorted values
        assert stats["min"] == 90
        assert stats["max"] == 300
        assert "p95" in stats
        assert "p99" in stats
        
        # Test empty operation
        empty_stats = metrics_collector.get_latency_stats("empty_operation")
        assert len(empty_stats) == 0
    
    def test_percentile_calculation(self, metrics_collector):
        """Test percentile calculation helper method."""
        # Test with simple dataset
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        
        # Test various percentiles
        assert metrics_collector._percentile(data, 50) == 5.5  # Median
        assert metrics_collector._percentile(data, 0) == 1     # Min
        assert metrics_collector._percentile(data, 100) == 10  # Max
        
        # Test empty data
        assert metrics_collector._percentile([], 50) == 0.0
    
    def test_get_connection_stability(self, metrics_collector):
        """Test connection stability metrics."""
        # Add connection events
        metrics_collector.record_connection_event("telegram", "connect", True)
        metrics_collector.record_connection_event("telegram", "health_check", True)
        metrics_collector.record_connection_event("telegram", "health_check", False)
        metrics_collector.record_connection_event("telegram", "reconnect", True)
        
        # Get stability metrics
        stability = metrics_collector.get_connection_stability("telegram")
        
        assert stability["total_events"] == 4
        assert stability["success_rate"] == 75.0  # 3 out of 4 successful
        assert stability["reconnects"] == 1
        assert stability["last_event"]["type"] == "reconnect"
        assert stability["last_event"]["success"] is True
        
        # Test component with no events
        empty_stability = metrics_collector.get_connection_stability("mt5")
        assert empty_stability["total_events"] == 0
        assert empty_stability["success_rate"] == 100.0  # Assume stable if no events
        assert empty_stability["reconnects"] == 0
        assert empty_stability["last_event"] is None
    
    def test_get_processing_success_rate(self, metrics_collector):
        """Test processing success rate calculation."""
        correlation_id = "test-123"
        
        # Add processing events
        metrics_collector.record_message_processing(correlation_id + "1", "parse", True)
        metrics_collector.record_message_processing(correlation_id + "2", "parse", True)
        metrics_collector.record_message_processing(correlation_id + "3", "parse", False)
        metrics_collector.record_message_processing(correlation_id + "4", "execute", True)
        
        # Test overall success rate
        overall_rate = metrics_collector.get_processing_success_rate()
        assert overall_rate == 75.0  # 3 out of 4 successful
        
        # Test stage-specific success rate
        parse_rate = metrics_collector.get_processing_success_rate("parse")
        assert abs(parse_rate - 66.67) < 0.01  # 2 out of 3 parse events successful (approximately)
        
        execute_rate = metrics_collector.get_processing_success_rate("execute")
        assert execute_rate == 100.0  # 1 out of 1 execute event successful
        
        # Test non-existent stage
        empty_rate = metrics_collector.get_processing_success_rate("nonexistent")
        assert empty_rate == 100.0  # Assume success if no data
    
    def test_get_messages_per_minute(self, metrics_collector):
        """Test messages per minute calculation."""
        correlation_id = "test-123"
        
        # Add complete processing events (only 'complete' stage counted)
        for i in range(5):
            metrics_collector.record_message_processing(f"{correlation_id}-{i}", "complete", True)
        
        # Test over 5 minutes
        rate = metrics_collector.get_messages_per_minute(minutes=5)
        assert rate == 1.0  # 5 messages / 5 minutes = 1.0
        
        # Test with no messages
        empty_collector = MetricsCollector()
        empty_rate = empty_collector.get_messages_per_minute()
        assert empty_rate == 0.0
    
    def test_get_queue_depths(self, metrics_collector):
        """Test queue depth reporting (placeholder implementation)."""
        queue_names = ["raw_queue", "parsed_queue", "priority_queue"]
        depths = metrics_collector.get_queue_depths(queue_names)
        
        # Currently returns placeholder data
        assert len(depths) == 3
        assert all(depths[name] == 0 for name in queue_names)
    
    def test_daily_counter_reset(self, metrics_collector):
        """Test daily counter reset functionality."""
        # Increment some counters
        metrics_collector.increment_counter("daily_messages", 100)
        metrics_collector.increment_counter("daily_errors", 5)
        
        assert metrics_collector.get_counter("daily_messages") == 100
        assert metrics_collector.get_counter("daily_errors") == 5
        
        # Mock time to next day
        with patch.object(metrics_collector, '_daily_reset_time', datetime.now(UTC) - timedelta(days=1)):
            # This should trigger reset
            metrics_collector.increment_counter("daily_messages", 1)
            
            # Old counters should be reset
            assert metrics_collector.get_counter("daily_messages") == 1
            assert metrics_collector.get_counter("daily_errors") == 0
    
    def test_get_all_metrics_summary(self, metrics_collector):
        """Test comprehensive metrics summary."""
        # Add some test data
        metrics_collector.record_metric("cpu_usage", 50.0)
        metrics_collector.increment_counter("requests_total", 100)
        metrics_collector.record_latency("api_call", 150.0)
        metrics_collector.record_connection_event("telegram", "connect", True)
        metrics_collector.record_message_processing("test-123", "parse", True, 25.0)
        
        # Get summary
        summary = metrics_collector.get_all_metrics_summary()
        
        # Verify structure
        assert "system" in summary
        assert "counters" in summary
        assert "processing" in summary
        assert "latencies" in summary
        assert "connections" in summary
        assert "timestamp" in summary
        
        # Verify processing metrics
        assert "success_rate_overall" in summary["processing"]
        assert "messages_per_minute" in summary["processing"]
        
        # Verify connections
        assert "telegram" in summary["connections"]
        assert "mt5" in summary["connections"]
        assert "openai" in summary["connections"]
    
    def test_maxlen_enforcement(self, metrics_collector):
        """Test that deque maxlen is enforced for metrics storage."""
        # Fill beyond maxlen for metrics (5 minutes * 60 seconds = 300 max)
        for i in range(350):
            metrics_collector.record_metric("test_metric", i)
        
        history = metrics_collector.get_metric_history("test_metric")
        assert len(history) <= 300  # Should be limited by maxlen
        
        # Fill beyond maxlen for latencies (1000 max)
        for i in range(1050):
            metrics_collector.record_latency("test_operation", i)
        
        latencies = list(metrics_collector._latencies["test_operation"])
        assert len(latencies) <= 1000  # Should be limited by maxlen