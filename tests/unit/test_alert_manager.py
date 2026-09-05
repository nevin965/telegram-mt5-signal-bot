"""
Unit tests for alert manager component.
Tests alert triggering, throttling, and multi-channel delivery.
"""

import asyncio
import pytest
from datetime import datetime, UTC, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

from src.monitoring.alert_manager import AlertManager, Alert, AlertType, AlertSeverity
from src.database.repository import BaseRepository


class TestAlertManager:
    """Test AlertManager class."""
    
    @pytest.fixture
    def mock_repository(self):
        """Create a mock repository for testing."""
        repo = MagicMock(spec=BaseRepository)
        return repo
    
    @pytest.fixture
    def alert_manager(self, mock_repository):
        """Create an AlertManager instance for testing."""
        return AlertManager(repository=mock_repository, throttle_seconds=5)  # 5 second throttle for tests
    
    def test_alert_manager_initialization(self, alert_manager, mock_repository):
        """Test AlertManager initialization."""
        assert alert_manager.repository == mock_repository
        assert alert_manager.throttle_seconds == 5
        assert not alert_manager._last_alert_time
        assert not alert_manager._active_alerts
        assert not alert_manager._visual_indicators
    
    @pytest.mark.asyncio
    async def test_trigger_alert_basic(self, alert_manager):
        """Test basic alert triggering."""
        alert = await alert_manager.trigger_alert(
            AlertType.BE_FAILED,
            "Test BE failure",
            "risk_manager",
            AlertSeverity.WARNING,
            {"position_id": "123"}
        )
        
        assert alert is not None
        assert alert.alert_type == AlertType.BE_FAILED
        assert alert.severity == AlertSeverity.WARNING
        assert alert.message == "Test BE failure"
        assert alert.component == "risk_manager"
        assert alert.metadata["position_id"] == "123"
        
        # Check alert is stored
        assert alert.alert_id in alert_manager._active_alerts
        assert alert_manager._visual_indicators[AlertType.BE_FAILED] is True
    
    @pytest.mark.asyncio
    async def test_alert_throttling(self, alert_manager):
        """Test alert throttling mechanism."""
        # First alert should succeed
        alert1 = await alert_manager.trigger_alert(
            AlertType.BE_FAILED,
            "First failure",
            "risk_manager"
        )
        assert alert1 is not None
        
        # Second alert within throttle window should be throttled
        alert2 = await alert_manager.trigger_alert(
            AlertType.BE_FAILED,
            "Second failure",
            "risk_manager"
        )
        assert alert2 is None
        
        # Different alert type should not be throttled
        alert3 = await alert_manager.trigger_alert(
            AlertType.POSITION_NOT_FOUND,
            "Position missing",
            "mt5_executor"
        )
        assert alert3 is not None
    
    @pytest.mark.asyncio
    async def test_critical_alert_bypass_throttling(self, alert_manager):
        """Test that critical alerts bypass throttling."""
        # First critical alert
        alert1 = await alert_manager.trigger_alert(
            AlertType.CONNECTION_LOST,
            "Connection failed",
            "telegram",
            AlertSeverity.CRITICAL
        )
        assert alert1 is not None
        
        # Second critical alert should bypass throttling
        alert2 = await alert_manager.trigger_alert(
            AlertType.CONNECTION_LOST,
            "Connection still failed",
            "telegram",
            AlertSeverity.CRITICAL
        )
        assert alert2 is not None
    
    @pytest.mark.asyncio
    async def test_forced_alert_bypass_throttling(self, alert_manager):
        """Test that forced alerts bypass throttling."""
        # First alert
        alert1 = await alert_manager.trigger_alert(
            AlertType.BE_FAILED,
            "First failure",
            "risk_manager"
        )
        assert alert1 is not None
        
        # Forced alert should bypass throttling
        alert2 = await alert_manager.trigger_alert(
            AlertType.BE_FAILED,
            "Forced failure",
            "risk_manager",
            force=True
        )
        assert alert2 is not None
    
    def test_acknowledge_alert(self, alert_manager):
        """Test alert acknowledgment."""
        # Create an alert manually
        alert = Alert(
            AlertType.BE_FAILED,
            AlertSeverity.WARNING,
            "Test alert",
            "test_component"
        )
        alert_manager._active_alerts[alert.alert_id] = alert
        alert_manager._visual_indicators[AlertType.BE_FAILED] = True
        
        # Acknowledge the alert
        result = alert_manager.acknowledge_alert(alert.alert_id)
        assert result is True
        assert alert.acknowledged is True
        assert alert.acknowledged_at is not None
        
        # Visual indicator should be cleared
        assert alert_manager._visual_indicators[AlertType.BE_FAILED] is False
    
    def test_acknowledge_nonexistent_alert(self, alert_manager):
        """Test acknowledging a non-existent alert."""
        result = alert_manager.acknowledge_alert("non-existent-id")
        assert result is False
    
    def test_get_active_alerts(self, alert_manager):
        """Test getting active alerts."""
        # Create test alerts
        alert1 = Alert(AlertType.BE_FAILED, AlertSeverity.WARNING, "Alert 1", "component1")
        alert2 = Alert(AlertType.POSITION_NOT_FOUND, AlertSeverity.CRITICAL, "Alert 2", "component2")
        alert3 = Alert(AlertType.CORRELATION_UNCERTAIN, AlertSeverity.INFO, "Alert 3", "component3")
        
        # Add to manager
        alert_manager._active_alerts[alert1.alert_id] = alert1
        alert_manager._active_alerts[alert2.alert_id] = alert2
        alert_manager._active_alerts[alert3.alert_id] = alert3
        
        # Acknowledge one alert
        alert2.acknowledged = True
        
        # Get active alerts
        active_alerts = alert_manager.get_active_alerts()
        assert len(active_alerts) == 2
        assert alert1 in active_alerts
        assert alert3 in active_alerts
        assert alert2 not in active_alerts
        
        # Get active alerts by severity
        critical_alerts = alert_manager.get_active_alerts(AlertSeverity.CRITICAL)
        assert len(critical_alerts) == 0  # alert2 is acknowledged
        
        warning_alerts = alert_manager.get_active_alerts(AlertSeverity.WARNING)
        assert len(warning_alerts) == 1
        assert alert1 in warning_alerts
    
    def test_get_alert_history(self, alert_manager):
        """Test getting alert history."""
        now = datetime.now(UTC)
        
        # Create alerts with different timestamps
        alert1 = Alert(AlertType.BE_FAILED, AlertSeverity.WARNING, "Recent alert", "component1")
        alert1.timestamp = now
        
        alert2 = Alert(AlertType.POSITION_NOT_FOUND, AlertSeverity.CRITICAL, "Old alert", "component2")
        alert2.timestamp = now - timedelta(hours=25)  # Older than 24 hours
        
        alert_manager._active_alerts[alert1.alert_id] = alert1
        alert_manager._active_alerts[alert2.alert_id] = alert2
        
        # Get 24-hour history
        history = alert_manager.get_alert_history(hours=24)
        assert len(history) == 1
        assert alert1 in history
        assert alert2 not in history
        
        # Get history filtered by type
        be_history = alert_manager.get_alert_history(hours=48, alert_type=AlertType.BE_FAILED)
        assert len(be_history) == 1
        assert alert1 in be_history
    
    def test_get_alert_stats(self, alert_manager):
        """Test getting alert statistics."""
        now = datetime.now(UTC)
        
        # Create test alerts - pass timestamp in constructor to ensure proper ID generation
        alert1 = Alert(
            AlertType.BE_FAILED, 
            AlertSeverity.WARNING, 
            "Alert 1", 
            "component1",
            timestamp=now
        )
        alert1.acknowledged = True
        
        alert2 = Alert(
            AlertType.BE_FAILED, 
            AlertSeverity.CRITICAL, 
            "Alert 2", 
            "component2",
            timestamp=now + timedelta(seconds=1)  # Different timestamp for unique ID
        )
        
        alert3 = Alert(
            AlertType.POSITION_NOT_FOUND, 
            AlertSeverity.WARNING, 
            "Alert 3", 
            "component3",
            timestamp=now - timedelta(hours=25)  # Outside window
        )
        
        alert_manager._active_alerts[alert1.alert_id] = alert1
        alert_manager._active_alerts[alert2.alert_id] = alert2
        alert_manager._active_alerts[alert3.alert_id] = alert3
        
        stats = alert_manager.get_alert_stats(hours=24)
        
        assert stats["total_alerts"] == 2  # Only alerts within 24 hours
        assert stats["alerts_by_type"]["BE_FAILED"] == 2
        assert stats["alerts_by_severity"]["warning"] == 1  # Enum value is lowercase
        assert stats["alerts_by_severity"]["critical"] == 1  # Enum value is lowercase
        assert stats["acknowledgment_rate"] == 50.0  # 1 of 2 acknowledged
        assert stats["active_alerts"] == 2  # All unacknowledged alerts (includes old alert3)
    
    def test_clear_old_alerts(self, alert_manager):
        """Test clearing old acknowledged alerts."""
        now = datetime.now(UTC)
        
        # Create old acknowledged alert
        old_alert = Alert(AlertType.BE_FAILED, AlertSeverity.WARNING, "Old alert", "component1")
        old_alert.timestamp = now - timedelta(hours=73)  # Older than 72 hours
        old_alert.acknowledged = True
        old_alert.acknowledged_at = now - timedelta(hours=72)
        
        # Create recent alert
        recent_alert = Alert(AlertType.POSITION_NOT_FOUND, AlertSeverity.CRITICAL, "Recent alert", "component2")
        recent_alert.timestamp = now
        
        # Create old unacknowledged alert (should not be cleared)
        old_unack_alert = Alert(AlertType.CORRELATION_UNCERTAIN, AlertSeverity.INFO, "Old unack", "component3")
        old_unack_alert.timestamp = now - timedelta(hours=73)
        
        alert_manager._active_alerts[old_alert.alert_id] = old_alert
        alert_manager._active_alerts[recent_alert.alert_id] = recent_alert
        alert_manager._active_alerts[old_unack_alert.alert_id] = old_unack_alert
        
        # Clear old alerts
        cleared_count = alert_manager.clear_old_alerts(hours=72)
        
        assert cleared_count == 1
        assert old_alert.alert_id not in alert_manager._active_alerts
        assert recent_alert.alert_id in alert_manager._active_alerts
        assert old_unack_alert.alert_id in alert_manager._active_alerts  # Unacknowledged should remain
    
    @pytest.mark.asyncio
    async def test_convenience_methods(self, alert_manager):
        """Test convenience methods for common alert types."""
        # Test BE failed alert
        be_alert = await alert_manager.alert_be_failed("pos123", "MT5 error", {"ticket": 456})
        assert be_alert is not None
        assert be_alert.alert_type == AlertType.BE_FAILED
        assert "pos123" in be_alert.message
        assert be_alert.metadata["position_id"] == "pos123"
        
        # Test position not found alert
        pos_alert = await alert_manager.alert_position_not_found("pos456", "close", {"reason": "expired"})
        assert pos_alert is not None
        assert pos_alert.alert_type == AlertType.POSITION_NOT_FOUND
        assert "pos456" in pos_alert.message
        
        # Test correlation uncertain alert
        corr_alert = await alert_manager.alert_correlation_uncertain("msg789", 0.65, {"attempt": 2})
        assert corr_alert is not None
        assert corr_alert.alert_type == AlertType.CORRELATION_UNCERTAIN
        assert "0.65" in corr_alert.message
        
        # Test connection lost alert (critical, should force)
        conn_alert = await alert_manager.alert_connection_lost("telegram", "timeout", {"duration": 30})
        assert conn_alert is not None
        assert conn_alert.alert_type == AlertType.CONNECTION_LOST
        assert conn_alert.severity == AlertSeverity.CRITICAL
        
        # Test emergency stop alert (critical, should force)
        stop_alert = await alert_manager.alert_emergency_stop("manual", {"user": "admin"})
        assert stop_alert is not None
        assert stop_alert.alert_type == AlertType.EMERGENCY_STOP
        assert stop_alert.severity == AlertSeverity.CRITICAL
    
    def test_visual_indicators(self, alert_manager):
        """Test visual indicator management."""
        # Initially no indicators
        indicators = alert_manager.get_visual_indicators()
        assert not any(indicators.values())
        
        # Add alert - should set indicator
        alert = Alert(AlertType.BE_FAILED, AlertSeverity.WARNING, "Test", "component")
        alert_manager._active_alerts[alert.alert_id] = alert
        alert_manager._visual_indicators[AlertType.BE_FAILED] = True
        
        indicators = alert_manager.get_visual_indicators()
        assert indicators[AlertType.BE_FAILED] is True
        
        # Acknowledge alert - should clear indicator
        alert_manager.acknowledge_alert(alert.alert_id)
        indicators = alert_manager.get_visual_indicators()
        assert indicators[AlertType.BE_FAILED] is False
    
    @pytest.mark.asyncio
    async def test_shutdown(self, alert_manager):
        """Test alert manager shutdown."""
        # Add some active alerts
        alert1 = Alert(AlertType.BE_FAILED, AlertSeverity.WARNING, "Alert 1", "component1")
        alert2 = Alert(AlertType.POSITION_NOT_FOUND, AlertSeverity.CRITICAL, "Alert 2", "component2")
        
        alert_manager._active_alerts[alert1.alert_id] = alert1
        alert_manager._active_alerts[alert2.alert_id] = alert2
        alert_manager._visual_indicators[AlertType.BE_FAILED] = True
        
        # Shutdown
        await alert_manager.shutdown()
        
        # Visual indicators should be cleared
        assert not any(alert_manager._visual_indicators.values())
    
    @pytest.mark.asyncio
    async def test_alert_delivery_with_console_beep(self, alert_manager):
        """Test alert delivery includes console beep for critical alerts."""
        with patch('builtins.print') as mock_print:
            # Critical alert should trigger beep
            alert = await alert_manager.trigger_alert(
                AlertType.CONNECTION_LOST,
                "Critical failure",
                "system",
                AlertSeverity.CRITICAL
            )
            
            # Verify print was called with bell character
            mock_print.assert_called_with("\a", end="", flush=True)
    
    @pytest.mark.asyncio
    async def test_alert_delivery_without_beep(self, alert_manager):
        """Test alert delivery does not beep for non-critical alerts."""
        with patch('builtins.print') as mock_print:
            # Warning alert should not trigger beep
            alert = await alert_manager.trigger_alert(
                AlertType.BE_FAILED,
                "Warning failure",
                "system",
                AlertSeverity.WARNING
            )
            
            # Verify print was not called
            mock_print.assert_not_called()