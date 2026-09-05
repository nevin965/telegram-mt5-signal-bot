#!/usr/bin/env python3
"""
Database migration utility script for Telegram Signal EA.

This script provides command-line interface for running database migrations
using Alembic. It supports initialization, migration generation, upgrade,
downgrade, and status checking operations.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)


class DatabaseMigrator:
    """Database migration manager."""
    
    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize migrator.
        
        Args:
            database_url: Database URL override
        """
        self.project_root = Path(__file__).parent.parent
        self.migrations_dir = self.project_root / "src" / "database" / "migrations"
        self.database_url = database_url or self._get_default_database_url()
        
        # Setup Alembic config
        self.alembic_cfg = Config(str(self.migrations_dir / "alembic.ini"))
        self.alembic_cfg.set_main_option("script_location", str(self.migrations_dir))
        
        if database_url:
            self.alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    
    def _get_default_database_url(self) -> str:
        """Get default database URL."""
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            return db_url
        
        data_dir = self.project_root / "data"
        data_dir.mkdir(exist_ok=True)
        return f"sqlite+aiosqlite:///{data_dir / 'signal_ea.db'}"
    
    def init_migrations(self) -> None:
        """Initialize Alembic migrations."""
        try:
            if self.migrations_dir.exists():
                logger.warning("Migrations directory already exists")
                return
            
            # Create migrations directory
            self.migrations_dir.mkdir(parents=True, exist_ok=True)
            
            # Initialize Alembic
            command.init(self.alembic_cfg, str(self.migrations_dir))
            logger.info("Initialized Alembic migrations")
            
        except Exception as e:
            logger.error(f"Failed to initialize migrations: {e}")
            raise
    
    def create_migration(self, message: str, autogenerate: bool = True) -> None:
        """
        Create new migration.
        
        Args:
            message: Migration description
            autogenerate: Whether to auto-generate migration from model changes
        """
        try:
            if autogenerate:
                command.revision(self.alembic_cfg, message=message, autogenerate=True)
            else:
                command.revision(self.alembic_cfg, message=message)
            
            logger.info(f"Created migration: {message}")
            
        except Exception as e:
            logger.error(f"Failed to create migration: {e}")
            raise
    
    def upgrade_database(self, revision: str = "head") -> None:
        """
        Upgrade database to specified revision.
        
        Args:
            revision: Target revision (default: head)
        """
        try:
            command.upgrade(self.alembic_cfg, revision)
            logger.info(f"Upgraded database to {revision}")
            
        except Exception as e:
            logger.error(f"Failed to upgrade database: {e}")
            raise
    
    def downgrade_database(self, revision: str) -> None:
        """
        Downgrade database to specified revision.
        
        Args:
            revision: Target revision
        """
        try:
            command.downgrade(self.alembic_cfg, revision)
            logger.info(f"Downgraded database to {revision}")
            
        except Exception as e:
            logger.error(f"Failed to downgrade database: {e}")
            raise
    
    def show_current_revision(self) -> None:
        """Show current database revision."""
        try:
            command.current(self.alembic_cfg)
            
        except Exception as e:
            logger.error(f"Failed to show current revision: {e}")
            raise
    
    def show_migration_history(self) -> None:
        """Show migration history."""
        try:
            command.history(self.alembic_cfg)
            
        except Exception as e:
            logger.error(f"Failed to show migration history: {e}")
            raise
    
    def show_migration_heads(self) -> None:
        """Show migration heads."""
        try:
            command.heads(self.alembic_cfg)
            
        except Exception as e:
            logger.error(f"Failed to show migration heads: {e}")
            raise
    
    def stamp_database(self, revision: str) -> None:
        """
        Stamp database with specific revision without running migrations.
        
        Args:
            revision: Revision to stamp
        """
        try:
            command.stamp(self.alembic_cfg, revision)
            logger.info(f"Stamped database with revision {revision}")
            
        except Exception as e:
            logger.error(f"Failed to stamp database: {e}")
            raise
    
    async def test_connection(self) -> bool:
        """Test database connection."""
        try:
            engine = create_async_engine(self.database_url)
            async with engine.connect() as conn:
                await conn.execute("SELECT 1")
            await engine.dispose()
            logger.info("Database connection successful")
            return True
            
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return False
    
    def create_initial_migration(self) -> None:
        """Create initial migration with all tables."""
        try:
            self.create_migration("Initial migration with all tables", autogenerate=True)
            
        except Exception as e:
            logger.error(f"Failed to create initial migration: {e}")
            raise


def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(description="Database migration utility")
    parser.add_argument(
        "--database-url", 
        help="Database URL override"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize migrations")
    
    # Create migration command
    create_parser = subparsers.add_parser("create", help="Create new migration")
    create_parser.add_argument("message", help="Migration message")
    create_parser.add_argument(
        "--no-autogenerate",
        action="store_true",
        help="Don't auto-generate migration"
    )
    
    # Upgrade command
    upgrade_parser = subparsers.add_parser("upgrade", help="Upgrade database")
    upgrade_parser.add_argument(
        "revision",
        nargs="?",
        default="head",
        help="Target revision (default: head)"
    )
    
    # Downgrade command
    downgrade_parser = subparsers.add_parser("downgrade", help="Downgrade database")
    downgrade_parser.add_argument("revision", help="Target revision")
    
    # Status commands
    subparsers.add_parser("current", help="Show current revision")
    subparsers.add_parser("history", help="Show migration history")
    subparsers.add_parser("heads", help="Show migration heads")
    
    # Stamp command
    stamp_parser = subparsers.add_parser("stamp", help="Stamp database with revision")
    stamp_parser.add_argument("revision", help="Revision to stamp")
    
    # Test connection command
    subparsers.add_parser("test-connection", help="Test database connection")
    
    # Initial migration command
    subparsers.add_parser("create-initial", help="Create initial migration")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    setup_logging(args.verbose)
    
    migrator = DatabaseMigrator(args.database_url)
    
    try:
        if args.command == "init":
            migrator.init_migrations()
            
        elif args.command == "create":
            autogenerate = not args.no_autogenerate
            migrator.create_migration(args.message, autogenerate)
            
        elif args.command == "upgrade":
            migrator.upgrade_database(args.revision)
            
        elif args.command == "downgrade":
            migrator.downgrade_database(args.revision)
            
        elif args.command == "current":
            migrator.show_current_revision()
            
        elif args.command == "history":
            migrator.show_migration_history()
            
        elif args.command == "heads":
            migrator.show_migration_heads()
            
        elif args.command == "stamp":
            migrator.stamp_database(args.revision)
            
        elif args.command == "test-connection":
            success = asyncio.run(migrator.test_connection())
            sys.exit(0 if success else 1)
            
        elif args.command == "create-initial":
            migrator.create_initial_migration()
        
        logger.info("Migration command completed successfully")
        
    except Exception as e:
        logger.error(f"Migration command failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()