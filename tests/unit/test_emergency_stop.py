"""
Unit tests for emergency stop manager component.
Tests emergency stop triggering, resuming, and state management.
"""

import asyncio
import pytest
from datetime import datetime, UTC
from unittest.mock import patch

from src.utils.emergency_stop import EmergencyStopManager


class TestEmergencyStopManager:
    """Test EmergencyStopManager class."""
    
    @pytest.fixture
    def stop_manager(self):
        """Create an EmergencyStopManager instance for testing."""
        return EmergencyStopManager()
    
    def test_emergency_stop_manager_initialization(self, stop_manager):
        """Test EmergencyStopManager initialization."""
        assert not stop_manager._stop_flag
        assert stop_manager._stop_time is None
        assert stop_manager._stop_reason is None
        assert not stop_manager.is_stopped()
    
    @pytest.mark.asyncio
    async def test_trigger_emergency_stop(self, stop_manager):
        """Test triggering emergency stop."""
        reason = "Test emergency stop"
        
        await stop_manager.trigger_emergency_stop(reason)
        
        assert stop_manager.is_stopped()
        stop_info = stop_manager.get_stop_info()
        assert stop_info["is_stopped"] is True
        assert stop_info["stop_reason"] == reason
        assert stop_info["stop_time"] is not None
        assert stop_info["duration_seconds"] is not None
        assert stop_info["duration_seconds"] >= 0
    
    @pytest.mark.asyncio
    async def test_trigger_emergency_stop_default_reason(self, stop_manager):
        """Test triggering emergency stop with default reason."""
        await stop_manager.trigger_emergency_stop()
        
        assert stop_manager.is_stopped()
        stop_info = stop_manager.get_stop_info()
        assert stop_info["stop_reason"] == "Manual stop command"
    
    @pytest.mark.asyncio
    async def test_trigger_emergency_stop_already_stopped(self, stop_manager):
        """Test triggering emergency stop when already stopped."""
        # First stop
        await stop_manager.trigger_emergency_stop("First stop")
        first_info = stop_manager.get_stop_info()
        
        # Second stop attempt
        await stop_manager.trigger_emergency_stop("Second stop")
        second_info = stop_manager.get_stop_info()
        
        # Should still be stopped with original reason
        assert stop_manager.is_stopped()
        assert second_info["stop_reason"] == "First stop"
        assert second_info["stop_time"] == first_info["stop_time"]
    
    @pytest.mark.asyncio
    async def test_resume_operations(self, stop_manager):
        """Test resuming operations after emergency stop."""
        # First trigger stop
        await stop_manager.trigger_emergency_stop("Test stop")
        assert stop_manager.is_stopped()
        
        # Resume operations
        await stop_manager.resume_operations()
        
        assert not stop_manager.is_stopped()
        stop_info = stop_manager.get_stop_info()
        assert stop_info["is_stopped"] is False
        assert stop_info["stop_reason"] is None
        assert stop_info["stop_time"] is None
        assert stop_info["duration_seconds"] is None
    
    @pytest.mark.asyncio
    async def test_resume_operations_not_stopped(self, stop_manager):
        """Test resuming operations when not stopped."""
        # Should not raise error
        await stop_manager.resume_operations()
        
        assert not stop_manager.is_stopped()
    
    def test_is_stopped(self, stop_manager):
        """Test is_stopped method."""
        assert not stop_manager.is_stopped()
        
        # Manually set stop flag
        stop_manager._stop_flag = True
        assert stop_manager.is_stopped()
        
        # Clear stop flag
        stop_manager._stop_flag = False
        assert not stop_manager.is_stopped()
    
    def test_get_stop_info_not_stopped(self, stop_manager):
        """Test get_stop_info when not stopped."""
        stop_info = stop_manager.get_stop_info()
        
        assert stop_info["is_stopped"] is False
        assert stop_info["stop_time"] is None
        assert stop_info["stop_reason"] is None
        assert stop_info["duration_seconds"] is None
    
    @pytest.mark.asyncio
    async def test_get_stop_info_stopped(self, stop_manager):
        """Test get_stop_info when stopped."""
        reason = "Test stop reason"
        
        await stop_manager.trigger_emergency_stop(reason)
        stop_info = stop_manager.get_stop_info()
        
        assert stop_info["is_stopped"] is True
        assert stop_info["stop_reason"] == reason
        assert stop_info["stop_time"] is not None
        assert stop_info["duration_seconds"] is not None
        assert stop_info["duration_seconds"] >= 0
        
        # Check stop_time is ISO format
        assert isinstance(stop_info["stop_time"], str)
        datetime.fromisoformat(stop_info["stop_time"].replace('Z', '+00:00'))  # Should not raise
    
    @pytest.mark.asyncio
    async def test_concurrent_stop_operations(self, stop_manager):
        """Test concurrent emergency stop operations are thread-safe."""
        async def trigger_stop(reason):
            await stop_manager.trigger_emergency_stop(f"Stop {reason}")
        
        # Trigger multiple stops concurrently
        await asyncio.gather(
            trigger_stop("A"),
            trigger_stop("B"),
            trigger_stop("C")
        )
        
        # Should be stopped
        assert stop_manager.is_stopped()
        
        # Should have one of the stop reasons (first one to acquire lock)
        stop_info = stop_manager.get_stop_info()
        assert stop_info["stop_reason"] in ["Stop A", "Stop B", "Stop C"]
    
    @pytest.mark.asyncio
    async def test_concurrent_resume_operations(self, stop_manager):
        """Test concurrent resume operations are thread-safe."""
        # First trigger stop
        await stop_manager.trigger_emergency_stop("Test stop")
        assert stop_manager.is_stopped()
        
        async def resume():
            await stop_manager.resume_operations()
        
        # Resume multiple times concurrently
        await asyncio.gather(
            resume(),
            resume(),
            resume()
        )
        
        # Should be resumed
        assert not stop_manager.is_stopped()
    
    @pytest.mark.asyncio
    async def test_stop_resume_cycle(self, stop_manager):
        """Test multiple stop/resume cycles."""
        for i in range(3):
            # Stop
            reason = f"Stop cycle {i}"
            await stop_manager.trigger_emergency_stop(reason)
            
            assert stop_manager.is_stopped()
            stop_info = stop_manager.get_stop_info()
            assert stop_info["stop_reason"] == reason
            
            # Resume
            await stop_manager.resume_operations()
            
            assert not stop_manager.is_stopped()
            stop_info = stop_manager.get_stop_info()
            assert stop_info["stop_reason"] is None
    
    @pytest.mark.asyncio
    async def test_stop_duration_calculation(self, stop_manager):
        """Test that stop duration is calculated correctly."""
        await stop_manager.trigger_emergency_stop("Duration test")
        
        # Wait a small amount
        await asyncio.sleep(0.1)
        
        stop_info = stop_manager.get_stop_info()
        assert stop_info["duration_seconds"] >= 0.1
        assert stop_info["duration_seconds"] < 1.0  # Should be small
    
    @pytest.mark.asyncio
    async def test_logging_on_stop(self, stop_manager):
        """Test that emergency stop logs critical message."""
        with patch.object(stop_manager.logger, 'critical') as mock_critical:
            reason = "Test logging"
            await stop_manager.trigger_emergency_stop(reason)
            
            mock_critical.assert_called_once_with(f"EMERGENCY STOP TRIGGERED: {reason}")
    
    @pytest.mark.asyncio
    async def test_logging_on_resume(self, stop_manager):
        """Test that resume logs warning message."""
        # First trigger stop
        reason = "Test logging resume"
        await stop_manager.trigger_emergency_stop(reason)
        
        with patch.object(stop_manager.logger, 'warning') as mock_warning:
            await stop_manager.resume_operations()
            
            mock_warning.assert_called_once_with(f"Operations resumed after emergency stop: {reason}")
    
    @pytest.mark.asyncio
    async def test_logging_on_already_stopped(self, stop_manager):
        """Test logging when triggering stop while already stopped."""
        # First stop
        first_reason = "First stop"
        await stop_manager.trigger_emergency_stop(first_reason)
        
        with patch.object(stop_manager.logger, 'warning') as mock_warning:
            # Second stop attempt
            await stop_manager.trigger_emergency_stop("Second stop")
            
            mock_warning.assert_called_once_with(f"Emergency stop already active: {first_reason}")
    
    @pytest.mark.asyncio
    async def test_logging_on_resume_not_stopped(self, stop_manager):
        """Test logging when resuming while not stopped."""
        with patch.object(stop_manager.logger, 'info') as mock_info:
            await stop_manager.resume_operations()
            
            mock_info.assert_called_once_with("Resume called but emergency stop was not active")