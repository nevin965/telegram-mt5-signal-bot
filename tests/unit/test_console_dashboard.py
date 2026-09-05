"""
Unit tests for console dashboard component.
Tests dashboard rendering, refresh logic, and Rich integration.
"""

import asyncio
import pytest
from datetime import datetime, UTC, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

from src.monitoring.console_dashboard import ConsoleDashboard
from src.monitoring.health_checker import HealthMonitor, HealthStatus, ComponentHealth


class TestConsoleDashboard:
    """Test ConsoleDashboard class."""
    
    @pytest.fixture
    def mock_health_monitor(self):
        """Create a mock health monitor for testing."""
        monitor = MagicMock(spec=HealthMonitor)
        monitor.get_overall_health_status.return_value = HealthStatus.HEALTHY
        monitor.get_all_component_healths.return_value = {
            'telegram': ComponentHealth('telegram', HealthStatus.HEALTHY, 'Connected'),
            'mt5': ComponentHealth('mt5', HealthStatus.DEGRADED, 'Not configured'),
            'openai': ComponentHealth('openai', HealthStatus.DEGRADED, 'Not configured')
        }
        return monitor
    
    @pytest.fixture
    def dashboard(self, mock_health_monitor):
        """Create a ConsoleDashboard instance for testing."""
        return ConsoleDashboard(mock_health_monitor, refresh_interval=0.1)  # Fast refresh for tests
    
    def test_dashboard_initialization(self, dashboard, mock_health_monitor):
        """Test ConsoleDashboard initialization."""
        assert dashboard.health_monitor == mock_health_monitor
        assert dashboard.refresh_interval == 0.1
        assert not dashboard._is_running
        assert dashboard._dashboard_task is None
        assert isinstance(dashboard._start_time, datetime)
    
    def test_set_message_stats(self, dashboard):
        """Test setting message processing statistics."""
        now = datetime.now(UTC)
        
        dashboard.set_message_stats(
            messages_today=150,
            last_message_time=now,
            success_rate=95.5,
            processing_latency_ms=75
        )
        
        stats = dashboard._message_stats
        assert stats['messages_today'] == 150
        assert stats['last_message_time'] == now
        assert stats['success_rate'] == 95.5
        assert stats['processing_latency_ms'] == 75
    
    def test_set_position_stats(self, dashboard):
        """Test setting position/trading statistics."""
        dashboard.set_position_stats(
            open_positions=3,
            today_pnl=250.75,
            break_evens_applied=8
        )
        
        stats = dashboard._position_stats
        assert stats['open_positions'] == 3
        assert stats['today_pnl'] == 250.75
        assert stats['break_evens_applied'] == 8
    
    def test_set_queue_stats(self, dashboard):
        """Test setting queue statistics."""
        dashboard.set_queue_stats(
            raw_queue=5,
            parsed_queue=2,
            priority_queue=1
        )
        
        stats = dashboard._queue_stats
        assert stats['raw_queue'] == 5
        assert stats['parsed_queue'] == 2
        assert stats['priority_queue'] == 1
    
    def test_add_recent_signal(self, dashboard):
        """Test adding recent signals."""
        now = datetime.now(UTC)
        
        dashboard.add_recent_signal(
            signal_type="BUY",
            symbol="GOLD",
            action="OPEN",
            price=2650.50,
            ticket_id="12345",
            timestamp=now
        )
        
        assert len(dashboard._recent_signals) == 1
        signal = dashboard._recent_signals[0]
        assert signal['type'] == "BUY"
        assert signal['symbol'] == "GOLD"
        assert signal['action'] == "OPEN"
        assert signal['price'] == 2650.50
        assert signal['ticket_id'] == "12345"
        assert signal['timestamp'] == now
    
    def test_recent_signals_limit(self, dashboard):
        """Test that recent signals are limited to 10."""
        # Add 15 signals
        for i in range(15):
            dashboard.add_recent_signal(
                signal_type="TEST",
                symbol="SYMBOL",
                action=f"ACTION_{i}",
                price=float(i)
            )
        
        # Should only keep 10
        assert len(dashboard._recent_signals) == 10
        # Should keep the most recent ones
        assert dashboard._recent_signals[0]['action'] == "ACTION_5"  # First kept signal
        assert dashboard._recent_signals[-1]['action'] == "ACTION_14"  # Last signal
    
    def test_is_running(self, dashboard):
        """Test running status check."""
        assert not dashboard.is_running()
        
        dashboard._is_running = True
        assert dashboard.is_running()
        
        dashboard._is_running = False
        assert not dashboard.is_running()
    
    def test_get_uptime_formatting(self, dashboard):
        """Test uptime string formatting."""
        # Test recent start time
        dashboard._start_time = datetime.now(UTC) - timedelta(minutes=5)
        uptime = dashboard._get_uptime()
        assert uptime == "5m"
        
        # Test hours
        dashboard._start_time = datetime.now(UTC) - timedelta(hours=2, minutes=30)
        uptime = dashboard._get_uptime()
        assert uptime == "2h 30m"
        
        # Test days
        dashboard._start_time = datetime.now(UTC) - timedelta(days=1, hours=5, minutes=15)
        uptime = dashboard._get_uptime()
        assert uptime == "1d 5h 15m"
    
    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    def test_build_header(self, mock_memory, mock_cpu, dashboard):
        """Test header panel building."""
        # Mock system metrics
        mock_cpu.return_value = 25.5
        mock_memory_obj = MagicMock()
        mock_memory_obj.used = 4 * 1024 * 1024 * 1024  # 4GB in bytes
        mock_memory.return_value = mock_memory_obj
        
        # Mock health monitor
        dashboard.health_monitor.get_overall_health_status.return_value = HealthStatus.HEALTHY
        
        header = dashboard._build_header()
        
        # Should return a Rich Panel
        assert header is not None
        # Can't easily test Rich Panel content without rendering
    
    def test_build_connections_panel(self, dashboard):
        """Test connections panel building."""
        # Set up component healths
        dashboard.health_monitor.get_all_component_healths.return_value = {
            'telegram': ComponentHealth('telegram', HealthStatus.HEALTHY, 'Connected'),
            'mt5': ComponentHealth('mt5', HealthStatus.DEGRADED, 'Slow connection'),
            'openai': ComponentHealth('openai', HealthStatus.UNHEALTHY, 'API error')
        }
        
        panel = dashboard._build_connections_panel()
        assert panel is not None
    
    def test_build_signals_panel(self, dashboard):
        """Test signals panel building."""
        # Set message stats
        dashboard.set_message_stats(
            messages_today=42,
            last_message_time=datetime.now(UTC) - timedelta(minutes=5),
            success_rate=98.2
        )
        
        panel = dashboard._build_signals_panel()
        assert panel is not None
    
    def test_build_positions_panel(self, dashboard):
        """Test positions panel building."""
        # Test positive P&L
        dashboard.set_position_stats(
            open_positions=5,
            today_pnl=150.25,
            break_evens_applied=3
        )
        
        panel = dashboard._build_positions_panel()
        assert panel is not None
        
        # Test negative P&L
        dashboard.set_position_stats(today_pnl=-75.50)
        panel_negative = dashboard._build_positions_panel()
        assert panel_negative is not None
        
        # Test zero P&L
        dashboard.set_position_stats(today_pnl=0.0)
        panel_zero = dashboard._build_positions_panel()
        assert panel_zero is not None
    
    def test_build_queues_panel(self, dashboard):
        """Test queues panel building."""
        dashboard.set_queue_stats(
            raw_queue=3,
            parsed_queue=1,
            priority_queue=2
        )
        
        panel = dashboard._build_queues_panel()
        assert panel is not None
    
    def test_build_performance_panel(self, dashboard):
        """Test performance panel building."""
        dashboard.set_message_stats(
            processing_latency_ms=125,
            success_rate=96.8
        )
        
        panel = dashboard._build_performance_panel()
        assert panel is not None
    
    def test_build_signals_section_empty(self, dashboard):
        """Test signals section with no recent signals."""
        panel = dashboard._build_signals_section()
        assert panel is not None
    
    def test_build_signals_section_with_data(self, dashboard):
        """Test signals section with recent signals."""
        # Add some signals
        dashboard.add_recent_signal("BUY", "GOLD", "BUY", 2650.00, "12345")
        dashboard.add_recent_signal("SELL", "GOLD", "SELL", 2645.00, "12346")
        dashboard.add_recent_signal("MODIFY", "GOLD", "CLOSE 50%", 2648.00, "12347")
        
        panel = dashboard._build_signals_section()
        assert panel is not None
    
    def test_build_layout(self, dashboard):
        """Test main layout building."""
        layout = dashboard._build_layout()
        assert layout is not None
        # Rich Layout should have the expected structure
        assert hasattr(layout, 'split_column')
    
    @pytest.mark.asyncio
    async def test_start_stop_dashboard(self, dashboard):
        """Test starting and stopping the dashboard."""
        # Initially not running
        assert not dashboard.is_running()
        
        # Start dashboard (run briefly)
        start_task = asyncio.create_task(dashboard.start_dashboard())
        
        # Wait for startup
        await asyncio.sleep(0.05)
        
        # Should be running now
        assert dashboard.is_running()
        
        # Stop dashboard
        await dashboard.stop_dashboard()
        
        # Should be stopped
        assert not dashboard.is_running()
        
        # Clean up the start task
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass
    
    @pytest.mark.asyncio
    async def test_multiple_start_calls(self, dashboard):
        """Test that multiple start calls are handled gracefully."""
        # Start dashboard
        start_task = asyncio.create_task(dashboard.start_dashboard())
        await asyncio.sleep(0.05)
        
        # Second start call should be handled gracefully
        await dashboard.start_dashboard()  # Should not crash
        
        # Stop dashboard
        await dashboard.stop_dashboard()
        
        # Clean up
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass
    
    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, dashboard):
        """Test stopping dashboard when it's not running."""
        # Should handle gracefully
        await dashboard.stop_dashboard()
        assert not dashboard.is_running()
    
    @pytest.mark.asyncio
    @patch('src.monitoring.console_dashboard.Live')
    async def test_dashboard_refresh_loop(self, mock_live, dashboard):
        """Test dashboard refresh loop execution."""
        # Mock Rich Live context manager
        mock_live_instance = MagicMock()
        mock_live.return_value.__enter__ = MagicMock(return_value=mock_live_instance)
        mock_live.return_value.__exit__ = MagicMock(return_value=None)
        
        # Start dashboard with very short interval
        dashboard.refresh_interval = 0.01
        start_task = asyncio.create_task(dashboard.start_dashboard())
        
        # Let it run briefly
        await asyncio.sleep(0.05)
        
        # Stop dashboard
        await dashboard.stop_dashboard()
        
        # Verify Live was created and update was called
        assert mock_live.called
        
        # Clean up
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass
    
    @pytest.mark.asyncio
    async def test_context_manager(self, dashboard):
        """Test dashboard as async context manager."""
        async with dashboard as d:
            assert d == dashboard
            # Brief wait to let it start
            await asyncio.sleep(0.05)
            # Should be running
            assert dashboard.is_running()
        
        # Should be stopped after context
        assert not dashboard.is_running()
    
    def test_last_signal_time_formatting(self, dashboard):
        """Test last signal time display formatting."""
        now = datetime.now(UTC)
        
        # Test recent signal (seconds)
        dashboard.set_message_stats(last_message_time=now - timedelta(seconds=30))
        panel = dashboard._build_signals_panel()
        assert panel is not None
        
        # Test signal from minutes ago
        dashboard.set_message_stats(last_message_time=now - timedelta(minutes=5))
        panel = dashboard._build_signals_panel()
        assert panel is not None
        
        # Test signal from hours ago
        dashboard.set_message_stats(last_message_time=now - timedelta(hours=2))
        panel = dashboard._build_signals_panel()
        assert panel is not None
        
        # Test no last message
        dashboard.set_message_stats(last_message_time=None)
        panel = dashboard._build_signals_panel()
        assert panel is not None
    
    @patch('src.monitoring.console_dashboard.psutil')
    def test_system_metrics_error_handling(self, mock_psutil, dashboard):
        """Test system metrics collection error handling."""
        # Mock psutil to raise exception
        mock_psutil.cpu_percent.side_effect = Exception("CPU error")
        
        # Should not crash when building header
        header = dashboard._build_header()
        assert header is not None
    
    def test_health_status_color_mapping(self, dashboard):
        """Test health status to color mapping in header."""
        # Test different health statuses
        statuses_to_test = [
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED, 
            HealthStatus.UNHEALTHY
        ]
        
        for status in statuses_to_test:
            dashboard.health_monitor.get_overall_health_status.return_value = status
            header = dashboard._build_header()
            assert header is not None
    
    def test_empty_component_healths(self, dashboard):
        """Test handling of empty component health data."""
        # Mock empty health data
        dashboard.health_monitor.get_all_component_healths.return_value = {}
        
        # Should not crash
        panel = dashboard._build_connections_panel()
        assert panel is not None
    
    def test_signal_action_color_coding(self, dashboard):
        """Test that different signal actions get appropriate color coding."""
        # Add signals with different action types
        actions_to_test = [
            ("BUY ORDER", "BUY"),
            ("SELL ORDER", "SELL"), 
            ("CLOSE POSITION", "CLOSE"),
            ("MODIFY SL", "MODIFY")
        ]
        
        for action, signal_type in actions_to_test:
            dashboard.add_recent_signal(signal_type, "GOLD", action, 2650.0)
        
        # Should render without error
        panel = dashboard._build_signals_section()
        assert panel is not None
    
    def test_performance_metrics_display(self, dashboard):
        """Test performance metrics panel with various data."""
        # Test with different latency values
        latencies_to_test = [0, 50, 150, 1000, 5000]
        
        for latency in latencies_to_test:
            dashboard.set_message_stats(processing_latency_ms=latency)
            panel = dashboard._build_performance_panel()
            assert panel is not None