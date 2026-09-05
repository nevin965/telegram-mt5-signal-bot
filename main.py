#!/usr/bin/env python3
"""
Main application entry point for Telegram Signal EA.
Orchestrates the entire signal processing and trading pipeline with graceful shutdown handling.
"""

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, Optional

# ✅ Import Telethon events for message handling
from telethon import events

from openai import OpenAI
import MetaTrader5 as mt5

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config.logging_config import get_logger, setup_logging
from config.settings import settings
from src.monitoring.health_checker import HealthMonitor
from src.monitoring.metrics_collector import MetricsCollector
from src.monitoring.console_dashboard import ConsoleDashboard
from src.telegram_client import TelegramClient
from src.mt5_executor.connection import MT5Connection


class ApplicationManager:
    """
    Main application manager with graceful shutdown capabilities.
    Manages all system components and handles shutdown procedures.
    """
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.shutdown_event = asyncio.Event()
        self.shutdown_timeout = 30  # seconds
        
        # System components
        self.telegram_client = None
        self.mt5_connection = None
        self.openai_client = None
        self.health_monitor: Optional[HealthMonitor] = None
        self.metrics_collector: Optional[MetricsCollector] = None  
        self.console_dashboard: Optional[ConsoleDashboard] = None
        
        self._component_tasks: Dict[str, asyncio.Task] = {}
        self._queue_states: Dict[str, Any] = {}
        
        # Queue counters for dashboard
        self._raw_queue_count = 0
        self._parsed_queue_count = 0
        self._message_count_today = 0

        # ✅ Track messages -> trade tickets for editing
        self._message_to_trade: Dict[tuple, Dict] = {}  # (chat_id, msg_id) -> trade_info

        # ✅ Martingale lot sizing: next lot size to use, persisted to disk so
        # it survives restarts. Doubles... actually 1.5x's after an SL hit,
        # resets to base after a TP hit. Untouched by manual closes.
        self._lot_state_path = Path("state/lot_size_state.json")
        self._current_lot_size: float = self._load_lot_size_state()
        self._trade_lot_sizes: Dict[int, float] = {}  # ticket -> lot size used for that trade
        self._tracked_tickets: set = set()  # tickets we're watching to see if they hit SL/TP
        self._lot_last_check_time = datetime.now(UTC)
        self._martingale_active: bool = False  # True = currently in an escalated round, waiting for one order to fill
        self._pending_orders: Dict[int, Dict] = {}  # ticket -> {symbol, order_type, price, sl, tp, lot_size} for OUR pending orders not yet filled
        self.MAGIC_NUMBER = 123456  # used to filter "our" trades out of MT5's full history/positions

        self.logger.info("Application manager initialized")

    def _load_lot_size_state(self) -> float:
        """Load the next martingale lot size from disk, or fall back to BASE_LOT_SIZE."""
        base = float(os.getenv("BASE_LOT_SIZE", "0.01"))
        try:
            if self._lot_state_path.exists():
                data = json.loads(self._lot_state_path.read_text())
                size = float(data.get("next_lot_size", base))
                self.logger.info(f"📊 Loaded martingale lot-size state: next lot = {size}")
                return size
        except Exception as e:
            self.logger.warning(f"Could not load lot-size state, using base {base}: {e}")
        return base

    def _save_lot_size_state(self, next_lot_size: float) -> None:
        """Persist the next martingale lot size to disk so it survives restarts."""
        try:
            self._lot_state_path.parent.mkdir(parents=True, exist_ok=True)
            self._lot_state_path.write_text(json.dumps({"next_lot_size": next_lot_size}))
        except Exception as e:
            self.logger.error(f"Failed to persist lot-size state: {e}")

    @staticmethod
    def _round_to_lot_step(size: float, step: float = 0.01) -> float:
        """Round a lot size to the broker's step (default 0.01), avoiding
        float-precision issues (e.g. 0.015 landing on 0.01 instead of 0.02)."""
        step_dec = Decimal(str(step))
        return float((Decimal(str(size)) / step_dec).to_integral_value(rounding=ROUND_HALF_UP) * step_dec)
    
    async def startup(self) -> None:
        """Initialize and start all application components."""
        try:
            self.logger.info("Starting Telegram Signal EA application")
            
            await self._initialize_monitoring_components()
            
            # ---------- START TELEGRAM ----------
            self.logger.info("Initializing Telegram client...")
            self.telegram_client = TelegramClient()
            try:
                init_ok = await asyncio.wait_for(
                    self.telegram_client.initialize(),
                    timeout=10.0
                )
                if init_ok:
                    self.logger.info("Telegram client initialized successfully")
                    try:
                        connect_ok = await asyncio.wait_for(
                            self.telegram_client.connect(),
                            timeout=15.0
                        )
                        if connect_ok:
                            self.logger.info("✅ Telegram client connected successfully!")
                            if self.health_monitor:
                                self.health_monitor.telegram_client = self.telegram_client
                                self.logger.info("Registered Telegram client with health monitor")
                            if self.telegram_client.client and await self.telegram_client.is_authorized():
                                await self.telegram_client.connect_to_groups()
                                self.logger.info("Connected to Telegram groups")
                                # ✅ ADD MESSAGE HANDLER AFTER CONNECTING TO GROUPS
                                await self._register_message_handler()
                        else:
                            self.logger.warning("Telegram client connect() returned False")
                    except asyncio.TimeoutError:
                        self.logger.error("Telegram client connection timed out after 15 seconds")
                    except Exception as e:
                        self.logger.error(f"Error during Telegram connection: {e}")
                else:
                    self.logger.warning("Telegram client initialization failed")
            except asyncio.TimeoutError:
                self.logger.error("Telegram client initialization timed out after 10 seconds")
            except Exception as e:
                self.logger.error(f"Error during Telegram initialization: {e}")
            
            # ---------- START MT5 ----------
            self.logger.info("Initializing MT5 connection...")
            self.mt5_connection = MT5Connection(connection_id="main")
            try:
                login = settings.get_mt5_login_int()
                password = settings.mt5_password
                server = settings.mt5_server

                if hasattr(self.mt5_connection, 'connect'):
                    mt5_ok = await asyncio.wait_for(
                        self.mt5_connection.connect(
                            login=login,
                            password=password,
                            server=server
                        ),
                        timeout=10.0
                    )
                    if mt5_ok:
                        self.logger.info("✅ MT5 initialized successfully!")
                        if self.health_monitor:
                            self.health_monitor.mt5_connection = self.mt5_connection
                            self.logger.info("Registered MT5 with health monitor")
                    else:
                        self.logger.warning("MT5 connection failed")
                else:
                    self.logger.warning("MT5 connect method not found")
            except asyncio.TimeoutError:
                self.logger.error("MT5 connection timed out after 10 seconds")
            except Exception as e:
                self.logger.error(f"Error during MT5 initialization: {e}")
            
            # ---------- START OPENAI ----------
            self.logger.info("Initializing OpenAI client...")
            try:
                self.openai_client = OpenAI(api_key=settings.openai_api_key)
                if self.openai_client:
                    self.logger.info("✅ OpenAI client initialized successfully!")
                    if self.health_monitor:
                        self.health_monitor.set_openai_client(self.openai_client)
                        self.logger.info("Registered OpenAI with health monitor")
                else:
                    self.logger.warning("OpenAI client initialization returned None")
            except Exception as e:
                self.logger.error(f"Error during OpenAI initialization: {e}")
                self.openai_client = None
            
            # ✅ Start position updater (runs silently in background)
            self._component_tasks['position_updater'] = asyncio.create_task(
                self._position_updater_loop()
            )
            self.logger.info("✅ Position updater started")

            # ✅ Check MT5's own history for the last closed trade before
            # deciding this session's starting lot size (rule 2)
            await self._initialize_martingale_state_from_history()

            # ✅ Start martingale lot-size monitor (watches for SL/TP hits)
            self._component_tasks['martingale_monitor'] = asyncio.create_task(
                self._martingale_monitor_loop()
            )
            self.logger.info(f"✅ Martingale monitor started (next lot size: {self._current_lot_size})")
            
            self.logger.info("Application startup complete - ready to process signals")
            
        except Exception as e:
            self.logger.error(f"Error during startup: {e}", exc_info=True)
            raise

    async def _position_updater_loop(self) -> None:
        """Periodically update position stats from MT5."""
        self.logger.debug("Position updater loop started")
        while True:
            try:
                await self._update_position_stats()
                await asyncio.sleep(10)  # Update every 10 seconds
            except asyncio.CancelledError:
                self.logger.info("Position updater loop cancelled")
                raise
            except Exception as e:
                self.logger.error(f"Position updater loop error: {e}")
                await asyncio.sleep(10)

    async def _update_position_stats(self) -> None:
        """Update dashboard position stats from MT5."""
        try:
            # ✅ Ensure MT5 terminal is initialized
            if not mt5.terminal_info():
                self.logger.warning("MT5 terminal not initialized in updater, initializing...")
                if not mt5.initialize(settings.mt5_path or None):
                    self.logger.error("Failed to initialize MT5 in updater")
                    return
                if not mt5.login(settings.get_mt5_login_int(), settings.mt5_password, settings.mt5_server):
                    self.logger.error(f"Failed to login to MT5 in updater: {mt5.last_error()}")
                    return

            # Get open positions
            positions = mt5.positions_get()
            open_positions = len(positions) if positions else 0

            # Get account info for P&L
            account_info = mt5.account_info()
            today_pnl = account_info.profit if account_info else 0.0

            # Update dashboard
            if self.console_dashboard:
                self.console_dashboard.set_position_stats(
                    open_positions=open_positions,
                    today_pnl=today_pnl,
                    break_evens_applied=0
                )
        except Exception as e:
            self.logger.error(f"Error updating position stats: {e}")

    async def _resize_pending_orders(self, new_lot_size: float) -> None:
        """
        Cancel and re-place every currently-tracked pending order at
        new_lot_size, keeping price/SL/TP identical. Used when entering or
        exiting a martingale round, so ALL orders currently sitting pending
        move together (rule: not just the next new trade, but everything
        already placed too).
        """
        if not self._pending_orders:
            return
        for ticket, info in list(self._pending_orders.items()):
            if abs(info.get("lot_size", 0) - new_lot_size) < 1e-9:
                continue  # already at the right size, nothing to do

            cancel_request = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
            cancel_result = mt5.order_send(cancel_request)
            if cancel_result is None or cancel_result.retcode != mt5.TRADE_RETCODE_DONE:
                err = cancel_result.comment if cancel_result is not None else mt5.last_error()
                self.logger.error(f"Could not resize pending order {ticket}: cancel failed ({err})")
                continue

            self._tracked_tickets.discard(ticket)
            self._trade_lot_sizes.pop(ticket, None)
            del self._pending_orders[ticket]

            new_request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": info["symbol"],
                "volume": new_lot_size,
                "type": info["order_type"],
                "price": info["price"],
                "deviation": 50,
                "magic": self.MAGIC_NUMBER,
                "comment": "Telegram Signal EA (martingale resize)",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }
            if info.get("sl"):
                new_request["sl"] = info["sl"]
            if info.get("tp"):
                new_request["tp"] = info["tp"]

            result = mt5.order_send(new_request)
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                new_ticket = result.order
                self.logger.info(
                    f"🔁 Resized pending order {ticket} -> {new_ticket}: "
                    f"{info.get('lot_size')} -> {new_lot_size} lots (martingale)"
                )
                new_info = {**info, "lot_size": new_lot_size}
                self._pending_orders[new_ticket] = new_info
                self._tracked_tickets.add(new_ticket)
                self._trade_lot_sizes[new_ticket] = new_lot_size
                # keep the edit-handler's ticket mapping in sync too
                for trade_info in self._message_to_trade.values():
                    if trade_info.get("ticket") == ticket:
                        trade_info["ticket"] = new_ticket
                        trade_info["lot_size"] = new_lot_size
                        break
            else:
                err = result.comment if result is not None else mt5.last_error()
                self.logger.error(f"Failed to re-place resized pending order (old ticket {ticket}): {err}")

    async def _check_pending_order_fills(self) -> None:
        """
        Detect pending orders that just left the pending book - either
        because they FILLED (became a live position) or were cancelled/
        expired. The first pending order to fill during a martingale round
        is "the" trade whose outcome decides the next round; every other
        currently-pending order (and all future new trades) immediately
        drops back to base lot size.
        """
        if not self._pending_orders:
            return
        try:
            if not mt5.terminal_info():
                return
            current_order_tickets = {o.ticket for o in (mt5.orders_get() or []) if o.magic == self.MAGIC_NUMBER}
            open_position_tickets = {p.ticket for p in (mt5.positions_get() or []) if p.magic == self.MAGIC_NUMBER}

            for ticket in list(self._pending_orders.keys()):
                if ticket in current_order_tickets:
                    continue  # still sitting pending, nothing happened yet

                info = self._pending_orders.pop(ticket)
                if ticket in open_position_tickets:
                    self.logger.info(f"✅ Pending order {ticket} FILLED at {info.get('lot_size')} lots")
                    if self._martingale_active:
                        base_lot_size = float(os.getenv("BASE_LOT_SIZE", "0.01"))
                        self._current_lot_size = base_lot_size
                        self._martingale_active = False
                        self._save_lot_size_state(self._current_lot_size)
                        self.logger.info(
                            f"🎯 Martingale order {ticket} executed - reverting all other "
                            f"pending/future trades to base {base_lot_size} lots"
                        )
                        await self._resize_pending_orders(base_lot_size)
                    # ticket stays in _tracked_tickets/_trade_lot_sizes so its
                    # eventual SL/TP close is still picked up below.
                else:
                    self.logger.info(f"Pending order {ticket} no longer active (cancelled/expired) - dropping from tracking")
                    self._tracked_tickets.discard(ticket)
                    self._trade_lot_sizes.pop(ticket, None)
        except Exception as e:
            self.logger.error(f"Error checking pending order fills: {e}")

    async def _initialize_martingale_state_from_history(self) -> None:
        """
        On startup, check MT5's own trade history for the last CLOSED trade
        placed by this bot (matched via magic number), and seed the
        martingale state from that reality rather than only trusting the
        local state file - covers a fresh install, a deleted state file, or
        the state file drifting from what actually happened in MT5.
        """
        try:
            if not mt5.terminal_info():
                self.logger.warning("MT5 not ready - skipping startup martingale history check")
                return
            from_date = datetime.now(UTC) - timedelta(days=30)
            deals = mt5.history_deals_get(from_date, datetime.now(UTC))
            if not deals:
                self.logger.info("No trade history found - starting martingale at current/base lot size")
                return

            closing_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT and d.magic == self.MAGIC_NUMBER]
            if not closing_deals:
                self.logger.info("No closed trades from this bot in history - starting at current/base lot size")
                return

            last_deal = max(closing_deals, key=lambda d: d.time)
            base_lot_size = float(os.getenv("BASE_LOT_SIZE", "0.01"))

            if last_deal.reason == mt5.DEAL_REASON_SL:
                self._current_lot_size = self._round_to_lot_step(last_deal.volume * 1.5)
                self._martingale_active = True
                self._save_lot_size_state(self._current_lot_size)
                self.logger.info(
                    f"📉 Startup check: last trade (position {last_deal.position_id}) hit SL at "
                    f"{last_deal.volume} lots - starting this session at {self._current_lot_size} lots (martingale)"
                )
            elif last_deal.reason == mt5.DEAL_REASON_TP:
                self._current_lot_size = base_lot_size
                self._martingale_active = False
                self._save_lot_size_state(self._current_lot_size)
                self.logger.info(f"📈 Startup check: last trade hit TP - starting at base {base_lot_size} lots")
            else:
                self.logger.info(
                    f"Startup check: last trade closed for reason={last_deal.reason} (not SL/TP) - "
                    f"keeping lot size at {self._current_lot_size}"
                )
        except Exception as e:
            self.logger.error(f"Error checking startup trade history for martingale: {e}")

    async def _martingale_monitor_loop(self) -> None:
        """Periodically check for trades of ours that just closed, and
        adjust the next lot size if they closed via SL or TP."""
        self.logger.debug("Martingale monitor loop started")
        while True:
            try:
                await self._check_pending_order_fills()
                await self._check_closed_trades_for_martingale()
                await asyncio.sleep(15)
            except asyncio.CancelledError:
                self.logger.info("Martingale monitor loop cancelled")
                raise
            except Exception as e:
                self.logger.error(f"Martingale monitor loop error: {e}")
                await asyncio.sleep(15)

    async def _check_closed_trades_for_martingale(self) -> None:
        """
        Look at MT5 deal history since the last check. For any of OUR
        tracked tickets that closed:
          - hit SL  -> next lot size = (lot size that trade used) * 1.5
          - hit TP  -> next lot size = base lot size (reset)
          - anything else (manual close, expert modify, stop-out, etc.)
            -> lot size left untouched, per the user's requirement that
               this only reacts to actual SL/TP hits.
        """
        if not self._tracked_tickets:
            return
        try:
            if not mt5.terminal_info():
                return  # other loops will handle reconnecting; skip this cycle

            now = datetime.now(UTC)
            deals = mt5.history_deals_get(self._lot_last_check_time, now)
            self._lot_last_check_time = now
            if not deals:
                return

            base_lot_size = float(os.getenv("BASE_LOT_SIZE", "0.01"))

            for deal in deals:
                if deal.entry != mt5.DEAL_ENTRY_OUT:
                    continue  # only closing deals matter here
                ticket = deal.position_id
                if ticket not in self._tracked_tickets:
                    continue  # not one of ours (or already processed)

                lot_used = self._trade_lot_sizes.get(ticket, self._current_lot_size)

                if deal.reason == mt5.DEAL_REASON_SL:
                    self._current_lot_size = self._round_to_lot_step(lot_used * 1.5)
                    self._martingale_active = True
                    self._save_lot_size_state(self._current_lot_size)
                    self.logger.info(
                        f"📉 Position {ticket} hit STOP LOSS (was {lot_used} lots) - "
                        f"martingale: next trade(s) will use {self._current_lot_size} lots"
                    )
                    await self._resize_pending_orders(self._current_lot_size)
                elif deal.reason == mt5.DEAL_REASON_TP:
                    self._current_lot_size = base_lot_size
                    self._martingale_active = False
                    self._save_lot_size_state(self._current_lot_size)
                    self.logger.info(
                        f"📈 Position {ticket} hit TAKE PROFIT - lot size reset to base {self._current_lot_size}"
                    )
                    await self._resize_pending_orders(self._current_lot_size)
                else:
                    self.logger.info(
                        f"ℹ️ Position {ticket} closed (reason={deal.reason}, not SL/TP) - lot size unchanged"
                    )

                self._tracked_tickets.discard(ticket)
                self._trade_lot_sizes.pop(ticket, None)

        except Exception as e:
            self.logger.error(f"Error checking closed trades for martingale: {e}")

    async def _register_message_handler(self) -> None:
        """Register the message handler for incoming Telegram messages."""
        if not self.telegram_client or not self.telegram_client.client:
            self.logger.warning("Telegram client not available for message handler")
            return

        # Get the list of connected group IDs
        group_ids = list(self.telegram_client._connected_groups.keys())
        self.logger.info(f"DEBUG: Connected group IDs: {group_ids}")

        if not group_ids:
            self.logger.warning("No groups connected, message handler not registered")
            return

        self.logger.info(f"Registering message handler for {len(group_ids)} groups: {group_ids}")

        # ----- NEW MESSAGE HANDLER -----
        @self.telegram_client.client.on(events.NewMessage)
        async def handler(event):
            try:
                chat_id = event.chat_id
                self.logger.info(f"🔥 Handler triggered for chat_id: {chat_id}")

                # ✅ Filter manually: ignore messages from groups we don't monitor
                if str(chat_id) not in [str(g) for g in group_ids]:
                    self.logger.info(f"⏩ Ignoring message from non-monitored chat: {chat_id}")
                    return

                message = event.message
                text = message.text or ""
                msg_id = message.id
                self.logger.info(f"📩 New message from {chat_id} (ID: {msg_id}): {text[:100]}")

                # ✅ Increment RAW queue
                self._raw_queue_count += 1
                self._message_count_today += 1
                if self.console_dashboard:
                    self.console_dashboard.set_queue_stats(
                        raw_queue=self._raw_queue_count,
                        parsed_queue=self._parsed_queue_count,
                        priority_queue=0
                    )
                    self.console_dashboard.set_message_stats(
                        messages_today=self._message_count_today,
                        last_message_time=datetime.now(UTC),
                        success_rate=0.0,
                        processing_latency_ms=0
                    )

                # Parse the message using the regex parser
                from src.signal_parser.regex_parser import RegexParser
                parser = RegexParser()
                parsed = parser.parse(text)
                if parsed:
                    self.logger.info(f"✅ Signal parsed: {parsed.parsed_action} {parsed.symbol} at {parsed.entry_price}")

                    # ✅ EXECUTE TRADE VIA MT5 – store ticket info
                    ticket_info = await self._execute_trade(parsed)
                    if ticket_info:
                        # Store mapping for later edits
                        key = (chat_id, msg_id)
                        self._message_to_trade[key] = ticket_info
                        self.logger.info(f"📌 Stored trade info for message {msg_id}: ticket={ticket_info.get('ticket')}")

                        # ✅ "Parsed" count = messages that actually resulted in an
                        # MT5 order, not just ones regex recognized but that then
                        # failed to execute (bad price/connection/etc).
                        self._parsed_queue_count += 1
                        if self.console_dashboard:
                            self.console_dashboard.set_queue_stats(
                                raw_queue=self._raw_queue_count,
                                parsed_queue=self._parsed_queue_count,
                                priority_queue=0
                            )

                        # ✅ Get chat title and current time, then send to dashboard
                        if self.console_dashboard:
                            try:
                                chat_title = "Unknown"
                                try:
                                    chat_entity = await self.telegram_client.client.get_entity(chat_id)
                                    if hasattr(chat_entity, 'title'):
                                        chat_title = chat_entity.title
                                    elif hasattr(chat_entity, 'first_name'):
                                        chat_title = f"{chat_entity.first_name} {chat_entity.last_name or ''}".strip()
                                    else:
                                        chat_title = str(chat_entity.id)
                                except Exception as e:
                                    self.logger.warning(f"Could not get chat title for {chat_id}: {e}")

                                current_time = datetime.now().strftime("%H:%M:%S")
                                signal_summary = (
                                    f"{parsed.parsed_action.value} {parsed.symbol} @ {parsed.entry_price} "
                                    f"(SL: {parsed.stop_loss}, TP: {parsed.take_profit}) → #{ticket_info.get('ticket')} "
                                    f"- {chat_title} at {current_time}"
                                )
                                self.console_dashboard.add_recent_signal(signal_text=signal_summary)
                                self.logger.info("📊 Signal with chat/time sent to dashboard")
                            except Exception as e:
                                self.logger.error(f"Failed to send signal to dashboard: {e}")
                    else:
                        self.logger.warning("Signal parsed but trade execution failed - not counted as parsed")
                else:
                    if parser.is_tp_hit_notification(text):
                        await self._handle_tp_hit_notification(chat_id, msg_id, text, event)
                    else:
                        self.logger.info("ℹ️ Message not recognized as a trading signal")
            except Exception as e:
                self.logger.error(f"Error processing message: {e}")

        # ----- EDITED MESSAGE HANDLER (FIXED) -----
        @self.telegram_client.client.on(events.MessageEdited)
        async def edit_handler(event):
            try:
                chat_id = event.chat_id
                if str(chat_id) not in [str(g) for g in group_ids]:
                    return

                msg_id = event.message.id
                new_text = event.message.text or ""
                if not new_text:
                    return

                self.logger.info(f"✏️ Message edited in {chat_id} (ID: {msg_id}): {new_text[:100]}")

                # Look up if we have a trade for this message
                key = (chat_id, msg_id)
                trade_info = self._message_to_trade.get(key)
                if not trade_info:
                    self.logger.info("No trade associated with this message – ignoring edit")
                    return

                # Re‑parse the edited message
                from src.signal_parser.regex_parser import RegexParser
                parser = RegexParser()
                parsed = parser.parse(new_text)
                if not parsed:
                    self.logger.info("Edited message no longer a valid signal – ignoring")
                    return

                old_entry = trade_info.get('entry')
                old_sl = trade_info.get('sl')  # already offset-adjusted from when it was placed/last edited
                old_tp = trade_info.get('tp')
                ticket = trade_info.get('ticket')
                symbol = trade_info.get('symbol')
                is_pending = trade_info.get('is_pending', True)

                # Entry/TP have no offset applied, so raw parsed values compare directly.
                # If a field isn't present in the edited text (parser returned None),
                # treat it as "unchanged" rather than wiping it out.
                new_entry = float(parsed.entry_price) if parsed.entry_price else old_entry
                new_tp = float(parsed.take_profit) if parsed.take_profit else old_tp

                # SL needs the SAME offset math used at trade placement time before
                # it's comparable to old_sl or safe to send to MT5.
                raw_new_sl = float(parsed.stop_loss) if parsed.stop_loss else None
                new_sl = (
                    self._calculate_sl_with_offset(raw_new_sl, parsed.parsed_action.value)
                    if raw_new_sl is not None else old_sl
                )

                # For an open position the entry price can no longer change (it's filled),
                # so only SL/TP matter when deciding whether anything meaningful changed.
                if is_pending:
                    unchanged = (
                        self._prices_equal(old_entry, new_entry)
                        and self._prices_equal(old_sl, new_sl)
                        and self._prices_equal(old_tp, new_tp)
                    )
                else:
                    unchanged = (
                        self._prices_equal(old_sl, new_sl)
                        and self._prices_equal(old_tp, new_tp)
                    )

                if unchanged:
                    self.logger.info("No changes – ignoring edit")
                    return

                # If pending order and entry changed → cancel and replace
                if is_pending and not self._prices_equal(old_entry, new_entry):
                    self.logger.info(f"Entry price changed from {old_entry} to {new_entry} – will replace pending order")
                    cancel_request = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": ticket,
                    }
                    cancel_result = mt5.order_send(cancel_request)
                    if cancel_result is None or cancel_result.retcode != mt5.TRADE_RETCODE_DONE:
                        err = cancel_result.comment if cancel_result is not None else mt5.last_error()
                        self.logger.error(f"Failed to cancel order {ticket}: {err}")
                        return
                    self.logger.info(f"Old pending order {ticket} cancelled.")
                    self._tracked_tickets.discard(ticket)
                    self._trade_lot_sizes.pop(ticket, None)
                    self._pending_orders.pop(ticket, None)

                    # Remove old mapping, place new order
                    del self._message_to_trade[key]
                    new_trade_info = await self._execute_trade(parsed)
                    if new_trade_info:
                        self._message_to_trade[key] = new_trade_info
                        self.logger.info(f"🔄 Replaced pending order with new ticket {new_trade_info.get('ticket')}")
                        if self.console_dashboard:
                            chat_title = "Unknown"
                            try:
                                chat_entity = await self.telegram_client.client.get_entity(chat_id)
                                chat_title = chat_entity.title if hasattr(chat_entity, 'title') else str(chat_entity.id)
                            except:
                                pass
                            current_time = datetime.now().strftime("%H:%M:%S")
                            signal_summary = (
                                f"🔄 REPLACED (entry changed): {parsed.parsed_action.value} {parsed.symbol} @ {new_entry} "
                                f"(SL: {new_sl}, TP: {new_tp}) - {chat_title} at {current_time}"
                            )
                            self.console_dashboard.add_recent_signal(signal_text=signal_summary)
                    else:
                        self.logger.error("Failed to place new pending order after cancellation")
                    return
                else:
                    # Modify SL/TP only (entry unchanged or position already open)
                    self.logger.info(f"Modifying SL/TP for order/position {ticket}")

                    if is_pending:
                        # Get the pending order using orders_get (plural) – FIXED
                        orders = mt5.orders_get(ticket=ticket)
                        if not orders:
                            self.logger.warning(f"Order {ticket} not found – maybe already filled")
                            return
                        order = orders[0]  # first (should be only one)
                        request = {
                            "action": mt5.TRADE_ACTION_MODIFY,
                            "order": ticket,
                            "price": order.price_open,  # keep entry price
                            "sl": new_sl,
                            "tp": new_tp,
                        }
                        result = mt5.order_send(request)
                        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                            self.logger.info(f"✅ Pending order {ticket} modified: SL={new_sl}, TP={new_tp}")
                            trade_info['sl'] = new_sl
                            trade_info['tp'] = new_tp
                            if ticket in self._pending_orders:
                                self._pending_orders[ticket]['sl'] = new_sl
                                self._pending_orders[ticket]['tp'] = new_tp
                            if self.console_dashboard:
                                chat_title = "Unknown"
                                try:
                                    chat_entity = await self.telegram_client.client.get_entity(chat_id)
                                    chat_title = chat_entity.title if hasattr(chat_entity, 'title') else str(chat_entity.id)
                                except:
                                    pass
                                current_time = datetime.now().strftime("%H:%M:%S")
                                signal_summary = (
                                    f"🔄 EDITED (SL/TP): {parsed.parsed_action.value} {parsed.symbol} @ {old_entry} "
                                    f"(SL: {new_sl}, TP: {new_tp}) - {chat_title} at {current_time}"
                                )
                                self.console_dashboard.add_recent_signal(signal_text=signal_summary)
                        else:
                            err = result.comment if result is not None else mt5.last_error()
                            retcode = result.retcode if result is not None else "N/A"
                            self.logger.error(f"❌ Order modification failed: {err} (retcode {retcode})")
                    else:
                        # Open position – use positions_get (plural) – FIXED
                        positions = mt5.positions_get(ticket=ticket)
                        if not positions:
                            self.logger.warning(f"Position {ticket} not found – maybe closed")
                            return
                        position = positions[0]
                        request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "sl": new_sl,
                            "tp": new_tp,
                        }
                        result = mt5.order_send(request)
                        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                            self.logger.info(f"✅ Position {ticket} modified: SL={new_sl}, TP={new_tp}")
                            trade_info['sl'] = new_sl
                            trade_info['tp'] = new_tp
                            if self.console_dashboard:
                                chat_title = "Unknown"
                                try:
                                    chat_entity = await self.telegram_client.client.get_entity(chat_id)
                                    chat_title = chat_entity.title if hasattr(chat_entity, 'title') else str(chat_entity.id)
                                except:
                                    pass
                                current_time = datetime.now().strftime("%H:%M:%S")
                                signal_summary = (
                                    f"🔄 EDITED (SL/TP): {parsed.parsed_action.value} {parsed.symbol} @ {old_entry} "
                                    f"(SL: {new_sl}, TP: {new_tp}) - {chat_title} at {current_time}"
                                )
                                self.console_dashboard.add_recent_signal(signal_text=signal_summary)
                        else:
                            err = result.comment if result is not None else mt5.last_error()
                            retcode = result.retcode if result is not None else "N/A"
                            self.logger.error(f"❌ Position modification failed: {err} (retcode {retcode})")

            except Exception as e:
                self.logger.error(f"Error processing edited message: {e}")

        self.logger.info("✅ Message handlers registered successfully")
    
    def _calculate_sl_with_offset(self, sl: Optional[float], action_value: str) -> Optional[float]:
        """
        Apply the spread-buffer offset to a raw SL price from a signal.
        Used both when placing a brand-new trade and when re-applying SL
        from an edited message, so the two code paths always agree on
        what the "real" SL is.

        Args:
            sl: Raw stop-loss price from the parsed signal (or None)
            action_value: "BUY" or "SELL"

        Returns:
            Offset-adjusted SL, or None if no SL was given
        """
        if sl is None:
            return None
        sl_offset = float(os.getenv("SL_OFFSET", "2.0"))
        if action_value == "BUY":
            adjusted = sl - sl_offset
            self.logger.info(f"📊 BUY SL adjusted: original {sl} → {adjusted} (offset -{sl_offset})")
        else:  # SELL
            adjusted = sl + sl_offset
            self.logger.info(f"📊 SELL SL adjusted: original {sl} → {adjusted} (offset +{sl_offset})")
        return adjusted

    @staticmethod
    def _prices_equal(a: Optional[float], b: Optional[float], tolerance: float = 1e-4) -> bool:
        """Compare two optional prices with float-safe tolerance."""
        if a is None or b is None:
            return a == b
        return abs(a - b) < tolerance

    async def _handle_tp_hit_notification(self, chat_id, msg_id, text: str, event=None) -> None:
        """
        A 'TP1 HIT' / 'Target 1 Done' style follow-up message (any of the
        formats different channels use) means the market has already
        reached a target - which can happen even when OUR pending order
        (still waiting for the entry zone) was never filled, e.g. if price
        ran straight to target without ever pulling back into the entry
        zone. In that case the pending order is stale and should be
        cancelled rather than left sitting there to potentially fill late,
        into a move that's already over.

        Matching is scoped strictly to the SAME chat: a TP-hit message in
        one channel only ever cancels a pending order that channel itself
        placed, never another channel's order.
        """
        try:
            target_key = None

            # Prefer an explicit Telegram reply link, if this message is a
            # reply to the original signal message.
            reply_msg_id = None
            if event is not None:
                reply_to = getattr(event.message, "reply_to", None)
                reply_msg_id = getattr(reply_to, "reply_to_msg_id", None) if reply_to else None
            if reply_msg_id:
                candidate_key = (chat_id, reply_msg_id)
                if candidate_key in self._message_to_trade:
                    target_key = candidate_key

            # Fall back to the most recent still-tracked trade from this SAME chat
            if target_key is None:
                same_chat_keys = [k for k in self._message_to_trade if k[0] == chat_id]
                if same_chat_keys:
                    target_key = max(same_chat_keys, key=lambda k: k[1])  # highest msg_id = most recent

            if target_key is None:
                self.logger.info(f"ℹ️ TP-hit style message from chat {chat_id} but no tracked trade found to match against")
                return

            trade_info = self._message_to_trade.get(target_key)
            if not trade_info:
                return

            ticket = trade_info.get("ticket")
            if not trade_info.get("is_pending", False):
                self.logger.info(f"ℹ️ TP-hit message matched trade {ticket}, but it's already a live position (not pending) - nothing to cancel")
                return

            # Confirm it's genuinely still pending in MT5 right now before cancelling
            if not mt5.terminal_info():
                self.logger.warning("MT5 not ready - cannot verify/cancel pending order for TP-hit message")
                return
            order = mt5.orders_get(ticket=ticket)
            if not order:
                self.logger.info(f"ℹ️ Order {ticket} is no longer pending in MT5 (already filled/cancelled) - nothing to do")
                self._message_to_trade.pop(target_key, None)
                return

            cancel_request = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
            cancel_result = mt5.order_send(cancel_request)
            if cancel_result is not None and cancel_result.retcode == mt5.TRADE_RETCODE_DONE:
                self.logger.info(
                    f"🗑️ Cancelled pending order {ticket} - chat {chat_id} reported a target hit "
                    f"('{text[:80]}') while the order was still pending (never reached entry)"
                )
                self._tracked_tickets.discard(ticket)
                self._trade_lot_sizes.pop(ticket, None)
                self._pending_orders.pop(ticket, None)
                self._message_to_trade.pop(target_key, None)

                # ✅ Clean, human-readable dashboard entry (not the raw message text)
                chat_title = "Unknown"
                try:
                    chat_entity = await self.telegram_client.client.get_entity(chat_id)
                    if hasattr(chat_entity, 'title'):
                        chat_title = chat_entity.title
                    elif hasattr(chat_entity, 'first_name'):
                        chat_title = f"{chat_entity.first_name} {chat_entity.last_name or ''}".strip()
                except Exception as e:
                    self.logger.warning(f"Could not get chat title for {chat_id}: {e}")

                time_str = datetime.now().strftime("%H:%M:%S")
                symbol = trade_info.get("symbol", "N/A")
                action_val = trade_info.get("action", "N/A")
                dashboard_msg = (
                    f"❌ CANCELLED | {symbol} {action_val} pending #{ticket} | "
                    f"Chat: {chat_title} | Reason: target hit before entry | {time_str}"
                )
                if self.console_dashboard:
                    self.console_dashboard.add_recent_signal(signal_text=dashboard_msg)

                # ✅ This message caused a real MT5 action, so it counts toward
                # "parsed" the same way an executed trade signal does
                self._parsed_queue_count += 1
                if self.console_dashboard:
                    self.console_dashboard.set_queue_stats(
                        raw_queue=self._raw_queue_count,
                        parsed_queue=self._parsed_queue_count,
                        priority_queue=0
                    )
            else:
                err = cancel_result.comment if cancel_result is not None else mt5.last_error()
                self.logger.error(f"Failed to cancel pending order {ticket} after TP-hit notification: {err}")
        except Exception as e:
            self.logger.error(f"Error handling TP-hit notification: {e}")

    async def _execute_trade(self, parsed_signal) -> Optional[Dict]:
        """Execute a trade based on the parsed signal using raw MT5 API.
        Returns a dict with ticket, symbol, sl, tp, is_pending on success, else None.
        """
        try:
            # ✅ Martingale lot sizing: 1.5x after an SL hit, reset to base after a TP hit
            lot_size = self._current_lot_size
            
            # Extract trade parameters
            symbol = parsed_signal.symbol
            action = parsed_signal.parsed_action
            entry = float(parsed_signal.entry_price)
            sl = float(parsed_signal.stop_loss) if parsed_signal.stop_loss else None
            tp = float(parsed_signal.take_profit) if parsed_signal.take_profit else None
            
            # ✅ DEBUG: Log TP value
            self.logger.info(f"📊 DEBUG: entry={entry}, sl={sl}, tp={tp}, parsed_tp={parsed_signal.take_profit}")
            
            # ✅ Apply SL offset (spread buffer)
            sl = self._calculate_sl_with_offset(sl, action.value)
            
            self.logger.info(f"📊 Executing trade: {action.value} {symbol} {lot_size} lots at {entry}, SL: {sl}, TP: {tp}")
            
            # ✅ Map symbol to broker symbol (BTCUSD -> BTCUSDm, XAUUSD -> XAUUSDm)
            if symbol == "BTCUSD":
                symbol = "BTCUSDm"
                self.logger.info(f"✅ Mapped symbol to: {symbol}")
            elif symbol == "XAUUSD" or symbol == "GOLD":
                symbol = "XAUUSDm"
                self.logger.info(f"✅ Mapped symbol to: {symbol}")
            
            # ✅ Use raw MT5 API directly
            try:
                # Ensure MT5 is initialized and logged in
                if not mt5.terminal_info():
                    self.logger.warning("MT5 terminal not initialized, attempting to initialize...")
                    if not mt5.initialize(settings.mt5_path or None):
                        self.logger.error("Failed to initialize MT5 terminal")
                        return None
                    if not mt5.login(settings.get_mt5_login_int(), settings.mt5_password, settings.mt5_server):
                        self.logger.error(f"Failed to login to MT5: {mt5.last_error()}")
                        return None
                
                # ✅ Get current price to determine market vs pending order
                tick = mt5.symbol_info_tick(symbol)
                if not tick:
                    self.logger.error(f"Could not get tick for {symbol}")
                    return None
                
                current_price = tick.ask if action.value == "BUY" else tick.bid
                self.logger.info(f"💰 Current {symbol} price: {current_price}")
                self.logger.info(f"📊 Entry: {entry} | Current: {current_price} | Diff: {entry - current_price:.2f}")
                
                # ✅ Determine order type (ALL 6 TYPES)
                is_pending = False
                if action.value == "BUY":
                    if entry > current_price:
                        order_type = mt5.ORDER_TYPE_BUY_STOP
                        order_type_name = "BUY STOP"
                        price = entry
                        is_pending = True
                    elif entry < current_price:
                        order_type = mt5.ORDER_TYPE_BUY_LIMIT
                        order_type_name = "BUY LIMIT"
                        price = entry
                        is_pending = True
                    else:  # entry == current_price
                        order_type = mt5.ORDER_TYPE_BUY
                        order_type_name = "BUY MARKET"
                        price = current_price
                        is_pending = False
                else:  # SELL
                    if entry < current_price:
                        order_type = mt5.ORDER_TYPE_SELL_STOP
                        order_type_name = "SELL STOP"
                        price = entry
                        is_pending = True
                    elif entry > current_price:
                        order_type = mt5.ORDER_TYPE_SELL_LIMIT
                        order_type_name = "SELL LIMIT"
                        price = entry
                        is_pending = True
                    else:  # entry == current_price
                        order_type = mt5.ORDER_TYPE_SELL
                        order_type_name = "SELL MARKET"
                        price = current_price
                        is_pending = False
                
                self.logger.info(f"📊 Order type: {order_type_name} at {price}")
                
                # ✅ Prepare order request
                if is_pending:
                    request = {
                        "action": mt5.TRADE_ACTION_PENDING,
                        "symbol": symbol,
                        "volume": lot_size,
                        "type": order_type,
                        "price": price,
                        "deviation": 50,
                        "magic": self.MAGIC_NUMBER,
                        "comment": "Telegram Signal EA",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_RETURN,
                    }
                else:
                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": symbol,
                        "volume": lot_size,
                        "type": order_type,
                        "price": price,
                        "deviation": 50,
                        "magic": self.MAGIC_NUMBER,
                        "comment": "Telegram Signal EA",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_FOK,
                    }
                
                # ✅ ADD SL AND TP WITH LOGGING
                if sl:
                    request["sl"] = sl
                    self.logger.info(f"📊 SL added to request: {sl}")
                else:
                    self.logger.warning("⚠️ SL is None, not adding to order")
                
                if tp:
                    request["tp"] = tp
                    self.logger.info(f"📊 TP added to request: {tp}")
                else:
                    self.logger.warning("⚠️ TP is None, not adding to order")
                
                # ✅ Log the FULL request to see if TP is there
                self.logger.info(f"📤 FULL ORDER REQUEST: {request}")
                
                result = mt5.order_send(request)
                
                if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.logger.info(f"✅ Trade executed successfully! Ticket: {result.order}")
                    # ✅ Force immediate position update
                    await self._update_position_stats()
                    # ✅ Watch this ticket so the martingale monitor can react
                    # once it closes (via SL, TP, or otherwise)
                    self._tracked_tickets.add(result.order)
                    self._trade_lot_sizes[result.order] = lot_size
                    if is_pending:
                        self._pending_orders[result.order] = {
                            "symbol": symbol,
                            "order_type": order_type,
                            "price": price,
                            "sl": sl,
                            "tp": tp,
                            "lot_size": lot_size,
                        }
                    # Return trade info for tracking
                    return {
                        "ticket": result.order,
                        "symbol": symbol,
                        "action": action.value,
                        "entry": entry,
                        "sl": sl,
                        "tp": tp,
                        "is_pending": is_pending,
                        "lot_size": lot_size,
                    }
                else:
                    err = result.comment if result is not None else mt5.last_error()
                    retcode = result.retcode if result is not None else "N/A"
                    self.logger.error(f"❌ Trade execution failed: {err} (retcode: {retcode})")
                    return None
                    
            except Exception as e:
                self.logger.error(f"❌ Trade execution error: {e}")
                import traceback
                self.logger.error(traceback.format_exc())
                return None
                
        except Exception as e:
            self.logger.error(f"❌ Error executing trade: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None
    
    async def _initialize_monitoring_components(self) -> None:
        """Initialize health monitoring, metrics collection, and dashboard."""
        self.logger.info("Initializing monitoring components")
        
        self.health_monitor = HealthMonitor(check_interval=60)
        self.metrics_collector = MetricsCollector(max_history_minutes=60)
        self.console_dashboard = ConsoleDashboard(
            health_monitor=self.health_monitor,
            refresh_interval=2
        )
        
        await self.health_monitor.start_monitoring()
        self.logger.info("Health monitoring started")
        
        # Start dashboard in background with error recovery
        try:
            self._component_tasks['dashboard'] = asyncio.create_task(
                self._run_dashboard_safely()
            )
            self.logger.info("Console dashboard started")
        except Exception as e:
            self.logger.error(f"Failed to start dashboard: {e}")
            self.logger.warning("Bot will continue running in headless mode. Check logs/app.log for updates.")
    
    async def _run_dashboard_safely(self) -> None:
        """Run the dashboard with error recovery – restarts if it crashes."""
        while True:
            try:
                await self.console_dashboard.start_dashboard()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(f"Dashboard crashed: {e}. Restarting in 5 seconds...")
                await asyncio.sleep(5)
            await asyncio.sleep(2)
    
    async def run(self) -> None:
        """Main application run loop – keeps the bot alive."""
        try:
            self.logger.info("Bot is running. Press Ctrl+C to stop.")
            while not self.shutdown_event.is_set():
                await asyncio.sleep(1)
            self.logger.info("Shutdown signal received, initiating graceful shutdown")
        except asyncio.CancelledError:
            self.logger.info("Run loop cancelled")
        except Exception as e:
            self.logger.error(f"Error in main run loop: {e}", exc_info=True)
            raise
    
    async def shutdown(self) -> None:
        """Perform graceful shutdown."""
        self.logger.info("Starting graceful shutdown process")
        try:
            await self._save_application_state()
            await self._shutdown_monitoring_components()
            
            if self.telegram_client:
                self.logger.info("Disconnecting Telegram client...")
                await self.telegram_client.disconnect()
                self.logger.info("Telegram client disconnected")
            
            if self.mt5_connection:
                self.logger.info("Disconnecting MT5...")
                if hasattr(self.mt5_connection, 'disconnect'):
                    await self.mt5_connection.disconnect()
                self.logger.info("MT5 disconnected")
            
            # Shutdown MT5
            try:
                mt5.shutdown()
            except:
                pass
            
            await self._cancel_component_tasks()
            await self._shutdown_logging()
            
            self.logger.info("Graceful shutdown completed successfully")
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}", exc_info=True)
            raise
    
    async def _save_application_state(self) -> None:
        """Save state to disk."""
        try:
            state_dir = Path("data/state")
            state_dir.mkdir(parents=True, exist_ok=True)
            
            queue_state_file = state_dir / "queue_states.json"
            with open(queue_state_file, 'w') as f:
                json.dump(self._queue_states, f, indent=2, default=str)
            
            if self.metrics_collector:
                metrics_file = state_dir / "metrics_summary.json"
                with open(metrics_file, 'w') as f:
                    json.dump(self.metrics_collector.get_all_metrics_summary(), f, indent=2, default=str)
            
            if self.health_monitor:
                health_file = state_dir / "health_status.json"
                health_data = {
                    comp: health.to_dict()
                    for comp, health in self.health_monitor.get_all_component_healths().items()
                }
                with open(health_file, 'w') as f:
                    json.dump(health_data, f, indent=2, default=str)
            
            self.logger.info("Application state saved successfully")
        except Exception as e:
            self.logger.error(f"Error saving application state: {e}", exc_info=True)
    
    async def _shutdown_monitoring_components(self) -> None:
        """Shutdown monitoring components."""
        try:
            if self.console_dashboard:
                await self.console_dashboard.stop_dashboard()
                self.logger.info("Console dashboard stopped")
            
            if self.health_monitor:
                await self.health_monitor.stop_monitoring()
                self.logger.info("Health monitoring stopped")
        except Exception as e:
            self.logger.error(f"Error stopping monitoring components: {e}")
    
    async def _cancel_component_tasks(self) -> None:
        """Cancel background tasks."""
        if not self._component_tasks:
            return
        self.logger.info(f"Cancelling {len(self._component_tasks)} component tasks")
        for task_name, task in self._component_tasks.items():
            if not task.done():
                self.logger.debug(f"Cancelling task: {task_name}")
                task.cancel()
        if self._component_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._component_tasks.values(), return_exceptions=True),
                    timeout=self.shutdown_timeout
                )
            except asyncio.TimeoutError:
                self.logger.warning(f"Some tasks did not complete within {self.shutdown_timeout}s")
            except Exception as e:
                self.logger.error(f"Error waiting for tasks: {e}")
        self._component_tasks.clear()
        self.logger.info("All component tasks cancelled")
    
    async def _shutdown_logging(self) -> None:
        """Flush and close logging handlers."""
        try:
            for handler in logging.root.handlers[:]:
                handler.flush()
                if hasattr(handler, 'close'):
                    handler.close()
            self.logger.info("Logging handlers flushed and closed")
        except Exception as e:
            print(f"Error shutting down logging: {e}")
    
    def signal_shutdown(self) -> None:
        """Signal the application to begin shutdown."""
        self.logger.info("Shutdown signal received")
        self.shutdown_event.set()


app_manager: Optional[ApplicationManager] = None

def signal_handler(sig: int, frame) -> None:
    global app_manager
    signal_names = {signal.SIGTERM: "SIGTERM", signal.SIGINT: "SIGINT"}
    signal_name = signal_names.get(sig, f"Signal {sig}")
    if app_manager:
        print(f"\nReceived {signal_name}, initiating graceful shutdown...")
        app_manager.signal_shutdown()
    else:
        print(f"\nReceived {signal_name}, exiting immediately...")
        sys.exit(1)

async def main() -> None:
    global app_manager
    setup_logging()
    logger = get_logger(__name__)
    try:
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        app_manager = ApplicationManager()
        await app_manager.startup()
        await app_manager.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if app_manager:
            try:
                await asyncio.wait_for(app_manager.shutdown(), timeout=app_manager.shutdown_timeout)
            except asyncio.TimeoutError:
                logger.error("Shutdown timeout")
                sys.exit(1)
            except Exception as e:
                logger.error(f"Shutdown error: {e}", exc_info=True)
                sys.exit(1)
        logger.info("Application shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())