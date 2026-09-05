"""
Rich console dashboard for system monitoring.
Follows coding standards: use logger instead of print(), handle async cancellation.
"""

import asyncio
import logging
import sys
from datetime import UTC, datetime
from typing import Any

import psutil
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.monitoring.health_checker import HealthMonitor, HealthStatus
from src.utils.emergency_stop import emergency_stop_manager


class ConsoleDashboard:
    """
    Rich terminal-based dashboard for system monitoring.
    Displays connection status, system metrics, and recent activity.
    """

    # How many recent signals to retain/display - raised from the old
    # hardcoded 10-stored/5-shown limit so the dashboard shows real history
    # instead of just the last few.
    MAX_RECENT_SIGNALS = 200

    def __init__(self, health_monitor: HealthMonitor, refresh_interval: int = 2):
        """
        Initialize console dashboard.
        
        Args:
            health_monitor: Health monitor instance for status data
            refresh_interval: Dashboard refresh interval in seconds
        """
        self.logger = logging.getLogger(__name__)
        self.health_monitor = health_monitor
        self.refresh_interval = refresh_interval

        # Rich components
        self.console = Console()
        self.layout = Layout()

        # System tracking
        self._start_time = datetime.now(UTC)
        self._is_running = False
        self._dashboard_task: asyncio.Task | None = None

        # Statistics tracking
        self._message_stats = {
            'messages_today': 0,
            'last_message_time': None,
            'success_rate': 0.0,
            'processing_latency_ms': 0
        }

        self._position_stats = {
            'open_positions': 0,
            'today_pnl': 0.0,
            'break_evens_applied': 0
        }

        self._queue_stats = {
            'raw_queue': 0,
            'parsed_queue': 0,
            'priority_queue': 0
        }

        self._recent_signals: list[dict[str, Any]] = []

        # Emergency stop status tracking
        self._emergency_stop_status = {
            'is_stopped': False,
            'stop_reason': None,
            'stop_time': None
        }

        self.logger.info("Console dashboard initialized")

    def set_message_stats(
        self,
        messages_today: int = 0,
        last_message_time: datetime | None = None,
        success_rate: float = 0.0,
        processing_latency_ms: int = 0
    ) -> None:
        """Update message processing statistics."""
        self._message_stats = {
            'messages_today': messages_today,
            'last_message_time': last_message_time,
            'success_rate': success_rate,
            'processing_latency_ms': processing_latency_ms
        }

    def set_position_stats(
        self,
        open_positions: int = 0,
        today_pnl: float = 0.0,
        break_evens_applied: int = 0
    ) -> None:
        """Update position/trading statistics."""
        self._position_stats = {
            'open_positions': open_positions,
            'today_pnl': today_pnl,
            'break_evens_applied': break_evens_applied
        }

    def set_queue_stats(
        self,
        raw_queue: int = 0,
        parsed_queue: int = 0,
        priority_queue: int = 0
    ) -> None:
        """Update queue statistics."""
        self._queue_stats = {
            'raw_queue': raw_queue,
            'parsed_queue': parsed_queue,
            'priority_queue': priority_queue
        }

    def add_recent_signal(
        self,
        signal_type: str = "TRADE",
        symbol: str = "",
        action: str = "",
        price: float = 0.0,
        ticket_id: str | None = None,
        timestamp: datetime | None = None,
        signal_text: str | None = None  # ✅ New parameter for direct text
    ) -> None:
        """
        Add a recent signal to the display.
        
        Args:
            signal_type: Type of signal (e.g., "TRADE")
            symbol: Trading symbol
            action: BUY or SELL
            price: Entry price
            ticket_id: Optional ticket ID
            timestamp: Signal timestamp
            signal_text: Optional pre-formatted text (for compatibility)
        """
        # If signal_text is provided, use it directly
        if signal_text:
            # Store as a dictionary with a 'text' field
            signal = {
                'text': signal_text,
                'timestamp': timestamp or datetime.now(UTC),
                'symbol': symbol or 'N/A',
                'action': action or 'N/A',
                'price': price or 0.0,
                'type': signal_type,
                'ticket_id': ticket_id
            }
        else:
            signal = {
                'timestamp': timestamp or datetime.now(UTC),
                'type': signal_type,
                'symbol': symbol,
                'action': action,
                'price': price,
                'ticket_id': ticket_id
            }

        self._recent_signals.append(signal)

        # Keep a generous history instead of just the last 10 - the display
        # itself shows as many as the terminal has room for.
        if len(self._recent_signals) > self.MAX_RECENT_SIGNALS:
            self._recent_signals.pop(0)

    async def handle_command(self, command: str) -> bool:
        """
        Handle console commands.
        
        Args:
            command: Command string to process
            
        Returns:
            True if command was handled, False otherwise
        """
        command = command.strip().upper()
        
        if command == "STOP ALL":
            await self._handle_emergency_stop()
            return True
        elif command == "RESUME":
            await self._handle_resume()
            return True
        elif command == "STATUS":
            await self._handle_status_command()
            return True
        elif command in ["HELP", "?"]:
            await self._handle_help_command()
            return True
        else:
            self.logger.warning(f"Unknown command: {command}")
            return False

    async def _handle_emergency_stop(self) -> None:
        """Handle emergency stop command."""
        await emergency_stop_manager.trigger_emergency_stop("Console command: STOP ALL")
        self._emergency_stop_status = emergency_stop_manager.get_stop_info()
        self.logger.critical("Emergency stop triggered via console command")

    async def _handle_resume(self) -> None:
        """Handle resume operations command."""
        await emergency_stop_manager.resume_operations()
        self._emergency_stop_status = emergency_stop_manager.get_stop_info()
        self.logger.warning("Operations resumed via console command")

    async def _handle_status_command(self) -> None:
        """Handle status inquiry command."""
        stop_info = emergency_stop_manager.get_stop_info()
        if stop_info['is_stopped']:
            self.logger.info(f"Emergency stop active: {stop_info['stop_reason']} (since {stop_info['stop_time']})")
        else:
            self.logger.info("System operational - no emergency stop active")

    async def _handle_help_command(self) -> None:
        """Handle help command."""
        help_text = """
Available commands:
  STOP ALL - Trigger emergency stop
  RESUME   - Resume normal operations  
  STATUS   - Show system status
  HELP     - Show this help message
        """
        self.logger.info(help_text)

    async def start_dashboard(self) -> None:
        """Start the dashboard display loop."""
        if self._is_running:
            self.logger.warning("Dashboard already running")
            return

        self.logger.info("Starting console dashboard")
        self._is_running = True

        try:
            with Live(self._build_layout(), refresh_per_second=1/self.refresh_interval, console=self.console) as live:
                while self._is_running:
                    try:
                        # Update emergency stop status
                        self._emergency_stop_status = emergency_stop_manager.get_stop_info()
                        
                        live.update(self._build_layout())
                        await asyncio.sleep(self.refresh_interval)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        self.logger.error(f"Error updating dashboard: {e}")
                        await asyncio.sleep(self.refresh_interval)

        except asyncio.CancelledError:
            self.logger.info("Dashboard cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Dashboard terminated with error: {e}")
        finally:
            self._is_running = False

    async def stop_dashboard(self) -> None:
        """Stop the dashboard display loop."""
        if not self._is_running:
            return

        self.logger.info("Stopping console dashboard")
        self._is_running = False

        if self._dashboard_task:
            try:
                self._dashboard_task.cancel()
                await self._dashboard_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.logger.error(f"Error stopping dashboard task: {e}")
            finally:
                self._dashboard_task = None

    def _build_layout(self) -> Layout:
        """Build the main dashboard layout."""
        layout = Layout()

        # Split into header, main content, and footer
        layout.split_column(
            Layout(self._build_header(), name="header", size=3),
            Layout(name="main"),
            Layout(self._build_footer(), name="footer", size=3)
        )

        # Split main content into sections
        layout["main"].split_column(
            Layout(self._build_status_section(), name="status", size=8),
            Layout(self._build_signals_section(), name="signals")
        )

        return layout

    def _build_header(self) -> Panel:
        """Build the dashboard header with title and key metrics."""
        # Get system metrics
        uptime = self._get_uptime()
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        ram_mb = round(memory.used / (1024 * 1024))

        # Check for emergency stop first
        if self._emergency_stop_status.get('is_stopped', False):
            status_color = "red"
            status_icon = "⏹"
            status_text = "EMERGENCY STOP"
        else:
            # Determine overall health
            overall_health = self.health_monitor.get_overall_health_status()
            if overall_health == HealthStatus.HEALTHY:
                status_color = "green"
                status_icon = "●"
                status_text = overall_health.value.upper()
            elif overall_health == HealthStatus.DEGRADED:
                status_color = "yellow"
                status_icon = "◐"
                status_text = overall_health.value.upper()
            else:
                status_color = "red"
                status_icon = "○"
                status_text = overall_health.value.upper()

        header_text = Text()
        header_text.append("Signal EA Monitor v1.0", style="bold blue")
        header_text.append(" | ")
        header_text.append("Status: ", style="white")
        header_text.append(f"{status_icon} {status_text}", style=f"bold {status_color}")
        header_text.append(f" | Uptime: {uptime} | CPU: {cpu_percent}% | RAM: {ram_mb}MB", style="white")

        return Panel(header_text, style="bold")

    def _build_footer(self) -> Panel:
        """Build the dashboard footer with commands and emergency stop info."""
        footer_text = Text()
        
        # Emergency stop status
        if self._emergency_stop_status.get('is_stopped', False):
            stop_reason = self._emergency_stop_status.get('stop_reason', 'Unknown')
            footer_text.append("⚠️  EMERGENCY STOP ACTIVE", style="bold red")
            footer_text.append(f" - {stop_reason}", style="red")
            footer_text.append(" | Type 'RESUME' to restart operations", style="yellow")
        else:
            footer_text.append("Commands: ", style="white")
            footer_text.append("STOP ALL", style="bold red")
            footer_text.append(" | ", style="white")
            footer_text.append("RESUME", style="bold green")
            footer_text.append(" | ", style="white")
            footer_text.append("STATUS", style="bold cyan")
            footer_text.append(" | ", style="white")
            footer_text.append("HELP", style="bold yellow")
        
        return Panel(footer_text, style="dim")

    def _build_status_section(self) -> Layout:
        """Build the main status section with connections, signals, and queues."""
        status_layout = Layout()

        # Split into three columns
        status_layout.split_row(
            Layout(self._build_connections_panel(), name="connections"),
            Layout(self._build_signals_panel(), name="signals"),
            Layout(self._build_positions_panel(), name="positions")
        )

        # Add bottom row for queues and performance
        bottom_layout = Layout()
        bottom_layout.split_row(
            Layout(self._build_queues_panel(), name="queues"),
            Layout(self._build_performance_panel(), name="performance")
        )

        # Combine top and bottom
        combined_layout = Layout()
        combined_layout.split_column(
            status_layout,
            bottom_layout
        )

        return combined_layout

    def _build_connections_panel(self) -> Panel:
        """Build the connections status panel."""
        table = Table.grid(padding=(0, 2))
        table.add_column("Service", style="cyan")
        table.add_column("Status", justify="left")

        # Get component healths
        component_healths = self.health_monitor.get_all_component_healths()

        # Telegram status
        telegram_health = component_healths.get('telegram')
        if telegram_health:
            if telegram_health.status == HealthStatus.HEALTHY:
                telegram_status = "[green]● Connected[/green]"
            elif telegram_health.status == HealthStatus.DEGRADED:
                telegram_status = "[yellow]◐ Degraded[/yellow]"
            else:
                telegram_status = "[red]○ Disconnected[/red]"
        else:
            telegram_status = "[red]○ Not configured[/red]"

        table.add_row("Telegram:", telegram_status)

        # MT5 status
        mt5_health = component_healths.get('mt5')
        if mt5_health and mt5_health.status == HealthStatus.HEALTHY:
            mt5_status = "[green]● Connected[/green]"
        else:
            mt5_status = "[yellow]◐ Not connected[/yellow]"

        table.add_row("MT5:", mt5_status)

        # OpenAI status
        openai_health = component_healths.get('openai')
        if openai_health and openai_health.status == HealthStatus.HEALTHY:
            openai_status = "[green]● Connected[/green]"
        else:
            openai_status = "[yellow]◐ Not connected[/yellow]"

        table.add_row("OpenAI:", openai_status)

        return Panel(table, title="[bold cyan]CONNECTIONS[/bold cyan]", border_style="cyan")

    def _build_signals_panel(self) -> Panel:
        """Build the signals statistics panel."""
        table = Table.grid(padding=(0, 2))
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="left")

        # Last signal time
        last_msg = self._message_stats['last_message_time']
        if last_msg:
            time_diff = datetime.now(UTC) - last_msg
            if time_diff.total_seconds() < 60:
                last_signal = f"{int(time_diff.total_seconds())}s ago"
            elif time_diff.total_seconds() < 3600:
                last_signal = f"{int(time_diff.total_seconds() / 60)}m ago"
            else:
                last_signal = f"{int(time_diff.total_seconds() / 3600)}h ago"
        else:
            last_signal = "Never"

        table.add_row("Last:", last_signal)
        table.add_row("Today:", str(self._message_stats['messages_today']))
        table.add_row("Success:", f"{self._message_stats['success_rate']:.1f}%")

        return Panel(table, title="[bold green]SIGNALS[/bold green]", border_style="green")

    def _build_positions_panel(self) -> Panel:
        """Build the positions/trading panel."""
        table = Table.grid(padding=(0, 2))
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="left")

        open_positions = self._position_stats['open_positions']
        today_pnl = self._position_stats['today_pnl']
        be_applied = self._position_stats['break_evens_applied']

        # Color P&L based on value
        if today_pnl > 0:
            pnl_text = f"[green]+${today_pnl:.0f}[/green]"
        elif today_pnl < 0:
            pnl_text = f"[red]-${abs(today_pnl):.0f}[/red]"
        else:
            pnl_text = "$0"

        table.add_row("Open:", str(open_positions))
        table.add_row("Today P/L:", pnl_text)
        table.add_row("BE Applied:", str(be_applied))

        return Panel(table, title="[bold yellow]POSITIONS[/bold yellow]", border_style="yellow")

    def _build_queues_panel(self) -> Panel:
        """Build the queues status panel."""
        table = Table.grid(padding=(0, 2))
        table.add_column("Queue", style="cyan")
        table.add_column("Count", justify="left")

        raw_count = self._queue_stats['raw_queue']
        parsed_count = self._queue_stats['parsed_queue']
        priority_count = self._queue_stats['priority_queue']

        table.add_row("Raw:", str(raw_count))
        table.add_row("Parsed:", str(parsed_count))
        table.add_row("Priority:", str(priority_count))

        return Panel(table, title="[bold magenta]QUEUES[/bold magenta]", border_style="magenta")

    def _build_performance_panel(self) -> Panel:
        """Build the performance metrics panel."""
        table = Table.grid(padding=(0, 2))
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="left")

        parse_latency = self._message_stats['processing_latency_ms']
        success_rate = self._message_stats['success_rate']

        table.add_row("Parse Latency:", f"{parse_latency}ms")
        table.add_row("Execution Latency:", "N/A")  # Placeholder for future implementation
        table.add_row("Correlation Success:", f"{success_rate:.1f}%")

        return Panel(table, title="[bold white]PERFORMANCE[/bold white]", border_style="white")

    def _build_signals_section(self) -> Panel:
        """Build the recent signals section."""
        if not self._recent_signals:
            content = Text("No recent signals", style="dim")
        else:
            content = Text()

            for signal in reversed(self._recent_signals):  # Show full stored history (up to MAX_RECENT_SIGNALS)
                # ✅ Handle both dict and string formats
                if isinstance(signal, dict):
                    # If it has a 'text' field, use it directly
                    if 'text' in signal:
                        content.append(signal['text'] + "\n", style="white")
                        continue
                    
                    # Otherwise build from fields
                    timestamp = signal.get('timestamp', datetime.now(UTC)).strftime("%H:%M:%S")
                    symbol = signal.get('symbol', 'N/A')
                    action = signal.get('action', 'N/A')
                    price = signal.get('price', 0.0)
                    ticket = signal.get('ticket_id', 'N/A')

                    line = f"{timestamp} [{symbol}] {action} @ {price:.2f}"
                    if ticket and ticket != 'N/A':
                        line += f" → #{ticket}"

                    # Color code by action type
                    if 'BUY' in str(action).upper():
                        style = "green"
                    elif 'SELL' in str(action).upper():
                        style = "red"
                    elif 'CLOSE' in str(action).upper():
                        style = "yellow"
                    else:
                        style = "white"

                    content.append(line + "\n", style=style)
                else:
                    # It's a string, just display it
                    content.append(str(signal) + "\n", style="white")

        return Panel(content, title="[bold blue]Recent Signals[/bold blue]", border_style="blue")

    def _get_uptime(self) -> str:
        """Get formatted uptime string."""
        uptime = datetime.now(UTC) - self._start_time

        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"

    def is_running(self) -> bool:
        """Check if dashboard is currently running."""
        return self._is_running

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start_dashboard()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with proper cleanup."""
        await self.stop_dashboard()