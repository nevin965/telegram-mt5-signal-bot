"""
Alembic environment configuration for Telegram Signal EA database migrations.

This module configures Alembic to work with SQLite databases in both
online and offline modes, supporting async SQLAlchemy operations.
"""

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Add the project root to Python path
import sys
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Import the models
from src.database.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_database_url() -> str:
    """
    Get database URL from environment or use default.
    
    Returns:
        Database URL for SQLite with aiosqlite driver
    """
    # Check for environment variable first
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url
    
    # Default to project data directory
    project_root = Path(__file__).parent.parent.parent.parent
    db_path = project_root / "data" / "signal_ea.db"
    
    # Ensure data directory exists
    db_path.parent.mkdir(exist_ok=True)
    
    return f"sqlite+aiosqlite:///{db_path}"


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_database_url()
    # Remove +aiosqlite for offline mode
    url = url.replace("+aiosqlite", "")
    
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite-specific configurations
        render_as_batch=True,  # Required for SQLite ALTER operations
        compare_type=True,     # Compare column types
        compare_server_default=True,  # Compare default values
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    Run migrations with the given connection.
    
    Args:
        connection: Database connection to use for migrations
    """
    context.configure(
        connection=connection, 
        target_metadata=target_metadata,
        # SQLite-specific configurations
        render_as_batch=True,  # Required for SQLite ALTER operations
        compare_type=True,     # Compare column types
        compare_server_default=True,  # Compare default values
        # Include object name in batch operations
        render_item=lambda type_, obj, autogen_context: (
            f"    # {type_} {obj.name if hasattr(obj, 'name') else obj}"
            if autogen_context.get("render_item_extra_info")
            else False
        ),
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Run migrations in async mode.
    
    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    url = get_database_url()
    
    # Create async engine with SQLite optimizations
    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,  # Don't pool connections for migrations
        echo=False,  # Set to True for SQL debugging
        future=True,
        connect_args={
            "check_same_thread": False,
            "timeout": 30,
        }
    )

    async with connectable.connect() as connection:
        # Apply SQLite pragmas for consistency
        await connection.execute("PRAGMA foreign_keys=ON")
        await connection.execute("PRAGMA journal_mode=WAL")
        
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()