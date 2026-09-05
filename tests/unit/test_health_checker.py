"""
Unit tests for health checker component.
Tests health check logic, status reporting, and monitoring functionality.
"""

import asyncio
import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from src.monitoring.health_checker import HealthMonitor, HealthStatus, ComponentHealth


class TestComponentHealth:
    """Test ComponentHealth class."""
    
    def test_component_health_initialization(self):
        """Test ComponentHealth initialization with default values."""
        health = ComponentHealth("test_component")
        
        assert health.name == "test_component"
        assert health.status == HealthStatus.UNHEALTHY
        assert health.message == ""
        assert isinstance(health.last_check, datetime)
        assert health.details == {}
    
    def test_component_health_with_values(self):
        """Test ComponentHealth initialization with custom values."""
        timestamp = datetime.now(UTC)
        details = {"connection_count": 5}
        
        health = ComponentHealth(
            name="telegram",
            status=HealthStatus.HEALTHY,
            message="All systems operational",
            last_check=timestamp,
            details=details
        )
        
        assert health.name == "telegram"
        assert health.status == HealthStatus.HEALTHY
        assert health.message == "All systems operational"
        assert health.last_check == timestamp
        assert health.details == details
    
    def test_component_health_to_dict(self):
        """Test ComponentHealth dictionary conversion."""
        timestamp = datetime.now(UTC)
        health = ComponentHealth(
            name="mt5",
            status=HealthStatus.DEGRADED,
            message="Connection intermittent",
            last_check=timestamp,
            details={"retry_count": 3}
        )
        
        result = health.to_dict()
        
        assert result["name"] == "mt5"
        assert result["status"] == "degraded"
        assert result["message"] == "Connection intermittent"
        assert result["last_check"] == timestamp.isoformat()
        assert result["details"] == {"retry_count": 3}


class TestHealthMonitor:
    """Test HealthMonitor class."""
    
    @pytest.fixture
    def health_monitor(self):
        """Create a HealthMonitor instance for testing."""
        return HealthMonitor(check_interval=1)  # 1 second for faster tests
    
    def test_health_monitor_initialization(self, health_monitor):
        """Test HealthMonitor initialization."""
        assert health_monitor.check_interval == 1
        assert not health_monitor._is_running
        assert health_monitor._monitoring_task is None
        assert health_monitor.telegram_client is None
        assert health_monitor.mt5_connection is None
        assert health_monitor.openai_client is None
    
    def test_set_component_references(self, health_monitor):
        """Test setting component references."""
        mock_telegram = MagicMock()
        mock_mt5 = MagicMock()
        mock_openai = MagicMock()
        
        health_monitor.set_telegram_client(mock_telegram)
        health_monitor.set_mt5_connection(mock_mt5)
        health_monitor.set_openai_client(mock_openai)
        
        assert health_monitor.telegram_client == mock_telegram
        assert health_monitor.mt5_connection == mock_mt5
        assert health_monitor.openai_client == mock_openai
    
    @pytest.mark.asyncio
    async def test_start_stop_monitoring(self, health_monitor):
        """Test starting and stopping health monitoring."""
        # Initially not running
        assert not health_monitor.is_monitoring_active()
        
        # Start monitoring
        await health_monitor.start_monitoring()
        assert health_monitor._is_running
        assert health_monitor._monitoring_task is not None
        assert health_monitor.is_monitoring_active()
        
        # Wait a short time for monitoring to start
        await asyncio.sleep(0.1)
        
        # Stop monitoring
        await health_monitor.stop_monitoring()
        assert not health_monitor._is_running
        assert health_monitor._monitoring_task is None
        assert not health_monitor.is_monitoring_active()
    
    @pytest.mark.asyncio
    async def test_multiple_start_calls(self, health_monitor):
        """Test that multiple start calls don't create multiple tasks."""
        await health_monitor.start_monitoring()
        first_task = health_monitor._monitoring_task
        
        await health_monitor.start_monitoring()  # Second call
        second_task = health_monitor._monitoring_task
        
        # Should be the same task
        assert first_task == second_task
        
        await health_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_telegram_health_check_healthy(self, health_monitor):
        """Test Telegram health check when connection is healthy."""
        # Mock telegram client - get_connection_status is sync, others are async
        mock_telegram = AsyncMock()
        mock_telegram.is_connected.return_value = True
        mock_telegram.is_authorized.return_value = True
        
        # get_connection_status should be a sync method, not async
        mock_telegram.get_connection_status = MagicMock(return_value={
            "connected_groups_count": 2,
            "connection_failures": 0,
            "last_health_check": "2025-01-01T00:00:00Z",
            "auto_reconnect_enabled": True
        })
        
        health_monitor.set_telegram_client(mock_telegram)
        
        # Perform health check
        await health_monitor._check_telegram_health()
        
        # Verify health status
        telegram_health = health_monitor.get_component_health("telegram")
        assert telegram_health is not None
        assert telegram_health.status == HealthStatus.HEALTHY
        assert telegram_health.message == "Connection active and authorized"
        assert telegram_health.details["connected_groups"] == 2
    
    @pytest.mark.asyncio
    async def test_telegram_health_check_degraded(self, health_monitor):
        """Test Telegram health check when connection is degraded."""
        # Mock telegram client - connected but not authorized
        mock_telegram = AsyncMock()
        mock_telegram.is_connected.return_value = True
        mock_telegram.is_authorized.return_value = False
        
        health_monitor.set_telegram_client(mock_telegram)
        
        # Perform health check
        await health_monitor._check_telegram_health()
        
        # Verify health status
        telegram_health = health_monitor.get_component_health("telegram")
        assert telegram_health is not None
        assert telegram_health.status == HealthStatus.DEGRADED
        assert telegram_health.message == "Connected but not authorized"
    
    @pytest.mark.asyncio
    async def test_telegram_health_check_unhealthy(self, health_monitor):
        """Test Telegram health check when connection is unhealthy."""
        # Mock telegram client - not connected
        mock_telegram = AsyncMock()
        mock_telegram.is_connected.return_value = False
        mock_telegram.is_authorized.return_value = False
        
        health_monitor.set_telegram_client(mock_telegram)
        
        # Perform health check
        await health_monitor._check_telegram_health()
        
        # Verify health status
        telegram_health = health_monitor.get_component_health("telegram")
        assert telegram_health is not None
        assert telegram_health.status == HealthStatus.UNHEALTHY
        assert telegram_health.message == "Not connected to Telegram"
    
    @pytest.mark.asyncio
    async def test_telegram_health_check_exception(self, health_monitor):
        """Test Telegram health check when an exception occurs."""
        # Mock telegram client to raise exception
        mock_telegram = AsyncMock()
        mock_telegram.is_connected.side_effect = Exception("Connection error")
        
        health_monitor.set_telegram_client(mock_telegram)
        
        # Perform health check
        await health_monitor._check_telegram_health()
        
        # Verify health status
        telegram_health = health_monitor.get_component_health("telegram")
        assert telegram_health is not None
        assert telegram_health.status == HealthStatus.UNHEALTHY
        assert "Health check failed: Connection error" in telegram_health.message
    
    @pytest.mark.asyncio
    async def test_no_telegram_client_configured(self, health_monitor):
        """Test health check when no Telegram client is configured."""
        # Don't set telegram client
        await health_monitor._perform_health_checks()
        
        # Verify health status
        telegram_health = health_monitor.get_component_health("telegram")
        assert telegram_health is not None
        assert telegram_health.status == HealthStatus.UNHEALTHY
        assert telegram_health.message == "Telegram client not configured"
    
    def test_get_overall_health_status(self, health_monitor):
        """Test overall health status calculation."""
        # No components - should be unhealthy
        assert health_monitor.get_overall_health_status() == HealthStatus.UNHEALTHY
        
        # Add healthy component
        health_monitor._update_component_health("telegram", HealthStatus.HEALTHY, "OK")
        assert health_monitor.get_overall_health_status() == HealthStatus.HEALTHY
        
        # Add degraded component
        health_monitor._update_component_health("mt5", HealthStatus.DEGRADED, "Slow")
        assert health_monitor.get_overall_health_status() == HealthStatus.DEGRADED
        
        # Add unhealthy component
        health_monitor._update_component_health("openai", HealthStatus.UNHEALTHY, "Down")
        assert health_monitor.get_overall_health_status() == HealthStatus.UNHEALTHY
    
    def test_get_component_health(self, health_monitor):
        """Test retrieving specific component health."""
        # Non-existent component
        assert health_monitor.get_component_health("nonexistent") is None
        
        # Add component and retrieve
        health_monitor._update_component_health("test", HealthStatus.HEALTHY, "OK")
        health = health_monitor.get_component_health("test")
        
        assert health is not None
        assert health.name == "test"
        assert health.status == HealthStatus.HEALTHY
        assert health.message == "OK"
    
    def test_get_all_component_healths(self, health_monitor):
        """Test retrieving all component healths."""
        # Initially empty
        all_healths = health_monitor.get_all_component_healths()
        assert len(all_healths) == 0
        
        # Add components
        health_monitor._update_component_health("telegram", HealthStatus.HEALTHY, "OK")
        health_monitor._update_component_health("mt5", HealthStatus.DEGRADED, "Slow")
        
        all_healths = health_monitor.get_all_component_healths()
        assert len(all_healths) == 2
        assert "telegram" in all_healths
        assert "mt5" in all_healths
        assert all_healths["telegram"].status == HealthStatus.HEALTHY
        assert all_healths["mt5"].status == HealthStatus.DEGRADED
    
    @pytest.mark.asyncio
    async def test_force_health_check(self, health_monitor):
        """Test forcing immediate health check."""
        # Mock telegram client - get_connection_status is sync
        mock_telegram = AsyncMock()
        mock_telegram.is_connected.return_value = True
        mock_telegram.is_authorized.return_value = True
        mock_telegram.get_connection_status = MagicMock(return_value={})
        
        health_monitor.set_telegram_client(mock_telegram)
        
        # Force health check
        results = await health_monitor.force_health_check()
        
        # Verify results
        assert isinstance(results, dict)
        assert "telegram" in results
        assert results["telegram"].status == HealthStatus.HEALTHY
    
    @pytest.mark.asyncio
    async def test_context_manager(self, health_monitor):
        """Test HealthMonitor as async context manager."""
        async with health_monitor as hm:
            assert hm == health_monitor
            assert health_monitor.is_monitoring_active()
        
        # Should be stopped after context
        assert not health_monitor.is_monitoring_active()
    
    @pytest.mark.asyncio
    async def test_monitoring_loop_cancellation(self, health_monitor):
        """Test that monitoring loop handles cancellation properly."""
        await health_monitor.start_monitoring()
        
        # Let it run briefly
        await asyncio.sleep(0.1)
        
        # Stop should cancel without errors
        await health_monitor.stop_monitoring()
        assert not health_monitor.is_monitoring_active()
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self, health_monitor):
        """Test that circuit breaker decorator is applied to health checks."""
        # Mock telegram client to simulate failures
        mock_telegram = AsyncMock()
        mock_telegram.is_connected.return_value = True
        mock_telegram.is_authorized.return_value = True
        mock_telegram.get_connection_status.side_effect = Exception("Circuit breaker test")
        
        health_monitor.set_telegram_client(mock_telegram)
        
        # Multiple calls should trigger circuit breaker eventually
        for _ in range(5):
            await health_monitor._check_telegram_health()
            await asyncio.sleep(0.01)  # Small delay
        
        # Health should be marked unhealthy due to exceptions
        telegram_health = health_monitor.get_component_health("telegram")
        assert telegram_health.status == HealthStatus.UNHEALTHY