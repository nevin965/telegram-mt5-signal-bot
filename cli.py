#!/usr/bin/env python3
"""
Command line interface for Telegram Signal EA.
Provides start, stop, status, and configuration commands.
"""

import argparse
import os
import signal
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config.logging_config import get_logger, setup_logging


class SignalEAManager:
    """Manages the Telegram Signal EA application lifecycle."""

    def __init__(self):
        self.logger = get_logger(__name__)
        self.pid_file = Path("data/signal_ea.pid")

    def start(self) -> None:
        """Start the Signal EA application."""
        if self.is_running():
            self.logger.warning("Signal EA is already running")
            print("Signal EA is already running")
            return

        self.logger.info("Starting Signal EA application")
        print("Starting Signal EA application...")

        # TODO: Implement daemon mode startup
        # For now, just run main.py
        os.system("python main.py &")
        print("Signal EA started successfully")

    def stop(self) -> None:
        """Stop the Signal EA application."""
        if not self.is_running():
            self.logger.warning("Signal EA is not running")
            print("Signal EA is not running")
            return

        pid = self.get_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                self.logger.info(f"Sent SIGTERM to process {pid}")
                print(f"Stopping Signal EA (PID: {pid})")

                # Wait for process to stop
                import time

                for _ in range(10):  # Wait up to 10 seconds
                    if not self.is_running():
                        break
                    time.sleep(1)

                if self.is_running():
                    # Force kill if still running
                    os.kill(pid, signal.SIGKILL)
                    self.logger.warning(f"Force killed process {pid}")
                    print("Force stopped Signal EA")
                else:
                    print("Signal EA stopped successfully")

            except ProcessLookupError:
                self.logger.info(f"Process {pid} not found")
                print("Process not found (already stopped)")
            except PermissionError:
                self.logger.error(f"Permission denied killing process {pid}")
                print("Permission denied - cannot stop process")

        # Clean up PID file
        if self.pid_file.exists():
            self.pid_file.unlink()

    def status(self) -> None:
        """Show Signal EA application status."""
        if self.is_running():
            pid = self.get_pid()
            print(f"Signal EA is running (PID: {pid})")

            # TODO: Add more detailed status information
            # - Database connection status
            # - Telegram client status
            # - MT5 connection status
            # - Recent activity summary

        else:
            print("Signal EA is not running")

    def is_running(self) -> bool:
        """Check if Signal EA is currently running."""
        if not self.pid_file.exists():
            return False

        pid = self.get_pid()
        if not pid:
            return False

        try:
            # Check if process exists
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def get_pid(self) -> int | None:
        """Get the PID of the running Signal EA process."""
        if not self.pid_file.exists():
            return None

        try:
            with open(self.pid_file) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None


def main() -> None:
    """CLI main function."""
    parser = argparse.ArgumentParser(
        description="Telegram Signal EA - Automated trading system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start the Signal EA application")
    start_parser.add_argument("--daemon", action="store_true", help="Run in daemon mode")

    # Stop command
    subparsers.add_parser("stop", help="Stop the Signal EA application")

    # Status command
    subparsers.add_parser("status", help="Show application status")

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Setup logging for CLI operations
    setup_logging()

    # Create manager and execute command
    manager = SignalEAManager()

    try:
        if args.command == "start":
            manager.start()
        elif args.command == "stop":
            manager.stop()
        elif args.command == "status":
            manager.status()

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
