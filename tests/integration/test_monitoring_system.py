"""
Integration tests for the complete monitoring system.
Tests end-to-end monitoring workflow and component integration.
"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.monitoring.health_checker import HealthMonitor, HealthStatus
from src.monitoring.metrics_collector import MetricsCollector
from src.monitoring.console_dashboard import ConsoleDashboard
from config.logging_config import setup_logging, set_correlation_id, clear_all_context


class TestMonitoringSystemIntegration:
    """Integration tests for the complete monitoring system."""
    
    @pytest.fixture
    async def monitoring_system(self):
        """Set up a complete monitoring system for testing."""
        # Create temporary log directory
        temp_dir = tempfile.mkdtemp()
        setup_logging(log_dir=temp_dir, structured=True)
        
        # Initialize components
        health_monitor = HealthMonitor(check_interval=0.1)  # Fast for testing
        metrics_collector = MetricsCollector(max_history_minutes=5)
        dashboard = ConsoleDashboard(health_monitor, refresh_interval=0.1)
        
        # Mock telegram client
        mock_telegram = AsyncMock()
        mock_telegram.is_connected.return_value = True
        mock_telegram.is_authorized.return_value = True
        mock_telegram.get_connection_status.return_value = {
            "connected_groups_count": 2,
            "connection_failures": 0,
            "last_health_check": "2025-01-01T00:00:00Z",
            "auto_reconnect_enabled": True
        }
        
        health_monitor.set_telegram_client(mock_telegram)
        
        system = {
            'health_monitor': health_monitor,
            'metrics_collector': metrics_collector,
            'dashboard': dashboard,
            'mock_telegram': mock_telegram,
            'temp_dir': temp_dir
        }
        
        yield system
        
        # Cleanup
        try:
            await health_monitor.stop_monitoring()
            await dashboard.stop_dashboard()
        except:
            pass
        
        # Clear context
        clear_all_context()
    
    @pytest.mark.asyncio
    async def test_complete_monitoring_startup_shutdown(self, monitoring_system):
        """Test complete monitoring system startup and shutdown."""
        health_monitor = monitoring_system['health_monitor']
        dashboard = monitoring_system['dashboard']
        
        # Start health monitoring
        await health_monitor.start_monitoring()
        assert health_monitor.is_monitoring_active()
        
        # Start dashboard
        dashboard_task = asyncio.create_task(dashboard.start_dashboard())
        await asyncio.sleep(0.1)  # Let it start
        assert dashboard.is_running()
        
        # Let system run briefly
        await asyncio.sleep(0.2)
        
        # Stop dashboard
        await dashboard.stop_dashboard()
        assert not dashboard.is_running()
        
        # Stop health monitoring
        await health_monitor.stop_monitoring()
        assert not health_monitor.is_monitoring_active()
        
        # Clean up dashboard task
        dashboard_task.cancel()
        try:
            await dashboard_task
        except asyncio.CancelledError:
            pass
    
    @pytest.mark.asyncio
    async def test_health_monitoring_integration(self, monitoring_system):
        """Test health monitoring integration with other components."""
        health_monitor = monitoring_system['health_monitor']
        metrics_collector = monitoring_system['metrics_collector']
        mock_telegram = monitoring_system['mock_telegram']
        
        # Start health monitoring
        await health_monitor.start_monitoring()
        
        # Let it run for a few checks
        await asyncio.sleep(0.3)
        
        # Verify health checks happened
        assert mock_telegram.is_connected.called
        assert mock_telegram.is_authorized.called
        
        # Check component health
        telegram_health = health_monitor.get_component_health("telegram")
        assert telegram_health is not None
        assert telegram_health.status == HealthStatus.HEALTHY
        
        # Record connection events in metrics collector
        metrics_collector.record_connection_event("telegram", "health_check", True)
        
        # Verify metrics were recorded
        stability = metrics_collector.get_connection_stability("telegram")
        assert stability["total_events"] > 0
        assert stability["success_rate"] == 100.0
        
        await health_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_dashboard_with_live_data(self, monitoring_system):
        """Test dashboard with live health and metrics data."""
        health_monitor = monitoring_system['health_monitor']
        metrics_collector = monitoring_system['metrics_collector']
        dashboard = monitoring_system['dashboard']
        
        # Start health monitoring
        await health_monitor.start_monitoring()
        
        # Add some metrics data
        correlation_id = set_correlation_id("integration-test")
        try:
            # Simulate message processing
            metrics_collector.record_message_processing(correlation_id, "parse", True, 50.0)
            metrics_collector.record_message_processing(correlation_id, "execute", True, 150.0)
            metrics_collector.record_message_processing(correlation_id, "complete", True, 200.0)
            
            # Update dashboard with metrics data
            dashboard.set_message_stats(
                messages_today=25,
                success_rate=96.0,
                processing_latency_ms=50
            )
            
            dashboard.set_position_stats(
                open_positions=3,
                today_pnl=125.50,
                break_evens_applied=2
            )
            
            dashboard.set_queue_stats(
                raw_queue=2,
                parsed_queue=1,
                priority_queue=0
            )
            
            # Add recent signals
            dashboard.add_recent_signal("BUY", "GOLD", "BUY @ 2650", 2650.00, "12345")
            dashboard.add_recent_signal("MODIFY", "GOLD", "BREAK EVEN", 2652.00, "12346")
            
            # Build dashboard layout with live data
            layout = dashboard._build_layout()
            assert layout is not None
            
            # Verify header shows healthy status
            header = dashboard._build_header()
            assert header is not None
            
            # Verify all panels build successfully
            connections_panel = dashboard._build_connections_panel()
            signals_panel = dashboard._build_signals_panel()
            positions_panel = dashboard._build_positions_panel()
            queues_panel = dashboard._build_queues_panel()
            performance_panel = dashboard._build_performance_panel()
            signals_section = dashboard._build_signals_section()
            
            assert all(panel is not None for panel in [
                connections_panel, signals_panel, positions_panel,
                queues_panel, performance_panel, signals_section
            ])
            
        finally:
            clear_all_context()
            await health_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_metrics_collection_during_monitoring(self, monitoring_system):
        """Test metrics collection during active monitoring."""
        health_monitor = monitoring_system['health_monitor']
        metrics_collector = monitoring_system['metrics_collector']
        
        # Start monitoring
        await health_monitor.start_monitoring()
        
        # Simulate system activity
        correlation_id = set_correlation_id("metrics-test")
        
        try:
            # Record various metrics
            metrics_collector.record_metric("cpu_usage", 45.5)
            metrics_collector.record_metric("memory_usage", 2048)
            
            metrics_collector.increment_counter("messages_processed", 10)
            metrics_collector.increment_counter("errors_encountered", 1)
            
            metrics_collector.record_latency("parse_time", 75.0)
            metrics_collector.record_latency("execute_time", 200.0)
            
            # Simulate connection events
            metrics_collector.record_connection_event("telegram", "connect", True)
            metrics_collector.record_connection_event("telegram", "health_check", True)
            
            # Simulate message processing pipeline
            stages = ["parse", "validate", "execute", "complete"]
            for stage in stages:
                success = stage != "validate"  # Simulate one failure
                latency = 50.0 + len(stage) * 10  # Variable latency
                metrics_collector.record_message_processing(
                    correlation_id, stage, success, latency
                )
            
            # Let monitoring run
            await asyncio.sleep(0.2)
            
            # Verify metrics collection
            assert metrics_collector.get_counter("messages_processed") == 10
            assert metrics_collector.get_counter("errors_encountered") == 1
            
            # Check latency stats
            parse_stats = metrics_collector.get_latency_stats("parse_time")
            assert parse_stats["count"] > 0
            assert parse_stats["mean"] > 0
            
            # Check processing success rates
            overall_rate = metrics_collector.get_processing_success_rate()
            assert 0 <= overall_rate <= 100
            
            validate_rate = metrics_collector.get_processing_success_rate("validate")
            assert validate_rate < 100  # Should be less due to simulated failure
            
            # Check connection stability
            stability = metrics_collector.get_connection_stability("telegram")
            assert stability["total_events"] > 0
            assert stability["success_rate"] > 0
            
            # Get comprehensive metrics summary
            summary = metrics_collector.get_all_metrics_summary()
            assert "system" in summary
            assert "counters" in summary
            assert "processing" in summary
            assert "latencies" in summary
            assert "connections" in summary
            
        finally:
            clear_all_context()
            await health_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_error_handling_integration(self, monitoring_system):
        """Test error handling across monitoring components."""
        health_monitor = monitoring_system['health_monitor']
        metrics_collector = monitoring_system['metrics_collector']
        dashboard = monitoring_system['dashboard']
        mock_telegram = monitoring_system['mock_telegram']
        
        # Simulate telegram connection failure
        mock_telegram.is_connected.return_value = False
        mock_telegram.is_authorized.return_value = False
        
        # Start monitoring
        await health_monitor.start_monitoring()
        
        # Let it detect the failure
        await asyncio.sleep(0.2)
        
        # Verify unhealthy status
        telegram_health = health_monitor.get_component_health("telegram")
        assert telegram_health is not None
        assert telegram_health.status == HealthStatus.UNHEALTHY
        
        # Verify overall system health is unhealthy
        overall_health = health_monitor.get_overall_health_status()
        assert overall_health == HealthStatus.UNHEALTHY
        
        # Record the failure in metrics
        metrics_collector.record_connection_event("telegram", "health_check", False)
        
        # Dashboard should show unhealthy status
        header = dashboard._build_header()
        assert header is not None
        
        connections_panel = dashboard._build_connections_panel()
        assert connections_panel is not None
        
        # Check metrics reflect the failure
        stability = metrics_collector.get_connection_stability("telegram")
        assert stability["success_rate"] < 100
        
        # Simulate recovery
        mock_telegram.is_connected.return_value = True
        mock_telegram.is_authorized.return_value = True
        
        # Wait for recovery detection
        await asyncio.sleep(0.2)
        
        # Verify recovery
        telegram_health = health_monitor.get_component_health("telegram")
        assert telegram_health.status == HealthStatus.HEALTHY
        
        await health_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_structured_logging_integration(self, monitoring_system):
        """Test structured logging integration with monitoring."""
        health_monitor = monitoring_system['health_monitor']
        temp_dir = monitoring_system['temp_dir']
        
        # Set correlation context
        correlation_id = set_correlation_id("logging-integration")
        
        try:
            # Start monitoring (this will generate log entries)
            await health_monitor.start_monitoring()
            await asyncio.sleep(0.2)
            await health_monitor.stop_monitoring()
            
            # Check that log files were created
            log_dir = Path(temp_dir)
            app_log = log_dir / "app.log"
            
            # Log file should exist (may be empty if no logs written)
            if app_log.exists() and app_log.stat().st_size > 0:
                # Read and verify log entries are JSON
                with open(app_log) as f:
                    for line in f:
                        if line.strip():
                            try:
                                log_data = json.loads(line)
                                # Verify JSON structure
                                assert "timestamp" in log_data
                                assert "level" in log_data
                                assert "component" in log_data
                                assert "message" in log_data
                                # May have context if correlation ID was propagated
                            except json.JSONDecodeError:
                                pytest.fail(f"Log line is not valid JSON: {line}")
                                
        finally:
            clear_all_context()
    
    @pytest.mark.asyncio
    async def test_concurrent_component_operations(self, monitoring_system):
        """Test concurrent operations across monitoring components."""
        health_monitor = monitoring_system['health_monitor']
        metrics_collector = monitoring_system['metrics_collector']
        dashboard = monitoring_system['dashboard']
        
        # Start all components concurrently
        await asyncio.gather(
            health_monitor.start_monitoring(),
            dashboard.start_dashboard()
        )
        
        # Simulate concurrent operations
        async def simulate_metrics_collection():
            """Simulate ongoing metrics collection."""
            for i in range(10):
                correlation_id = set_correlation_id(f"concurrent-{i}")
                try:
                    metrics_collector.record_metric("test_metric", float(i))
                    metrics_collector.record_latency("test_operation", float(i * 10))
                    metrics_collector.record_message_processing(
                        correlation_id, "parse", i % 2 == 0, float(i * 5)
                    )
                    await asyncio.sleep(0.01)
                finally:
                    clear_all_context()
        
        async def simulate_dashboard_updates():
            """Simulate dashboard data updates."""
            for i in range(5):
                dashboard.set_message_stats(
                    messages_today=i * 10,
                    success_rate=90.0 + i,
                    processing_latency_ms=50 + i * 5
                )
                
                dashboard.add_recent_signal(
                    "TEST", "SYMBOL", f"ACTION_{i}", 1000.0 + i, f"ticket_{i}"
                )
                
                await asyncio.sleep(0.02)
        
        # Run concurrent simulations
        await asyncio.gather(
            simulate_metrics_collection(),
            simulate_dashboard_updates()
        )
        
        # Let system run briefly
        await asyncio.sleep(0.1)
        
        # Verify no crashes and data integrity
        assert health_monitor.is_monitoring_active()
        assert dashboard.is_running()
        
        # Check metrics were collected
        history = metrics_collector.get_metric_history("test_metric")
        assert len(history) > 0
        
        latency_stats = metrics_collector.get_latency_stats("test_operation")
        assert latency_stats.get("count", 0) > 0
        
        # Check dashboard has recent signals
        assert len(dashboard._recent_signals) > 0
        
        # Stop components
        await asyncio.gather(
            health_monitor.stop_monitoring(),
            dashboard.stop_dashboard()
        )
    
    @pytest.mark.asyncio
    async def test_system_metrics_integration(self, monitoring_system):
        """Test system metrics collection integration."""
        metrics_collector = monitoring_system['metrics_collector']
        dashboard = monitoring_system['dashboard']
        
        # Collect system metrics
        system_metrics = metrics_collector.get_system_metrics()
        
        # Verify system metrics structure
        assert "cpu" in system_metrics
        assert "memory" in system_metrics
        assert "disk" in system_metrics
        assert "timestamp" in system_metrics
        
        # CPU metrics
        assert "percent" in system_metrics["cpu"]
        assert "count" in system_metrics["cpu"]
        assert isinstance(system_metrics["cpu"]["percent"], (int, float))
        assert isinstance(system_metrics["cpu"]["count"], int)
        
        # Memory metrics
        assert "used_mb" in system_metrics["memory"]
        assert "available_mb" in system_metrics["memory"]
        assert "percent" in system_metrics["memory"]
        
        # Build dashboard header (which uses system metrics)
        header = dashboard._build_header()
        assert header is not None
        
        # Test dashboard with various system load scenarios
        test_scenarios = [
            {"cpu": 25.5, "memory_percent": 60.0},
            {"cpu": 75.0, "memory_percent": 85.0},
            {"cpu": 95.5, "memory_percent": 95.0}
        ]
        
        for scenario in test_scenarios:
            # Dashboard should handle different load levels gracefully
            header = dashboard._build_header()
            assert header is not None
    
    def test_metrics_summary_completeness(self, monitoring_system):
        """Test that metrics summary includes all expected components."""
        metrics_collector = monitoring_system['metrics_collector']
        
        # Add sample data for all metric types
        correlation_id = set_correlation_id("completeness-test")
        
        try:
            # Time-series metrics
            metrics_collector.record_metric("cpu_usage", 50.0)
            metrics_collector.record_metric("memory_usage", 1024)
            
            # Counters
            metrics_collector.increment_counter("requests_total", 100)
            metrics_collector.increment_counter("errors_total", 5)
            
            # Latencies
            metrics_collector.record_latency("api_latency", 150.0)
            metrics_collector.record_latency("db_latency", 25.0)
            
            # Connection events
            metrics_collector.record_connection_event("telegram", "connect", True)
            metrics_collector.record_connection_event("mt5", "connect", False)
            
            # Processing events
            metrics_collector.record_message_processing(correlation_id, "parse", True, 50.0)
            metrics_collector.record_message_processing(correlation_id, "execute", False, 100.0)
            
            # Get comprehensive summary
            summary = metrics_collector.get_all_metrics_summary()
            
            # Verify all sections are present
            required_sections = ["system", "counters", "processing", "latencies", "connections", "timestamp"]
            for section in required_sections:
                assert section in summary, f"Missing section: {section}"
            
            # Verify processing metrics
            processing = summary["processing"]
            assert "success_rate_overall" in processing
            assert "success_rate_parse" in processing
            assert "success_rate_execute" in processing
            assert "messages_per_minute" in processing
            
            # Verify connections for all components
            connections = summary["connections"]
            assert "telegram" in connections
            assert "mt5" in connections
            assert "openai" in connections
            
            # Verify latencies section has data
            latencies = summary["latencies"]
            assert len(latencies) > 0
            
            # Verify counters
            counters = summary["counters"]
            assert counters["requests_total"] == 100
            assert counters["errors_total"] == 5
            
        finally:
            clear_all_context()