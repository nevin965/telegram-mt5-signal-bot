#!/usr/bin/env python3
"""
Simple runner for Telegram Signal EA without dashboard.
Runs the bot in headless mode and keeps it alive.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config.logging_config import setup_logging, get_logger
from src.telegram_client import TelegramClient

async def main():
    # Setup logging
    setup_logging()
    logger = get_logger(__name__)
    
    logger.info("=" * 60)
    logger.info("🚀 Starting Telegram Signal EA (Headless Mode)")
    logger.info("=" * 60)
    
    # Initialize Telegram
    logger.info("Initializing Telegram client...")
    telegram = TelegramClient()
    
    if await telegram.initialize():
        logger.info("✅ Telegram initialized")
        if await telegram.connect():
            logger.info("✅ Telegram connected")
            # Connect to groups
            await telegram.connect_to_groups()
        else:
            logger.error("❌ Telegram connection failed")
    else:
        logger.error("❌ Telegram initialization failed")
    
    # Initialize MT5 (try, but don't crash if it fails)
        # Initialize MT5 (try, but don't crash if it fails)
    try:
        from src.mt5_executor.connection import MT5Connection
        from config.settings import settings
        logger.info("Initializing MT5 connection...")
        mt5 = MT5Connection(connection_id="main")
        # Read credentials from settings
        login = settings.get_mt5_login_int()
        password = settings.mt5_password
        server = settings.mt5_server
        if await mt5.connect(login, password, server):
            logger.info("✅ MT5 connected")
        else:
            logger.error("❌ MT5 connection failed")
    except Exception as e:
        logger.error(f"❌ MT5 error: {e}")
        logger.warning("⚠️ MT5 initialization skipped – bot will still monitor Telegram")
    
    logger.info("=" * 60)
    logger.info("✅ Bot is running and monitoring for signals...")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    # Keep the bot running
    try:
        await asyncio.Event().wait()  # Wait forever
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await telegram.disconnect()
        logger.info("Bot stopped")

if __name__ == "__main__":
    asyncio.run(main())