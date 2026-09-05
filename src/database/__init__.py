"""
Database package initialization.

This module provides the main database interface and initialization functions
for the Telegram Signal EA application. It manages database connections,
repositories, and ensures proper setup.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from .models import Base
from .repository import (
    DatabaseManager, RepositoryFactory, DatabaseError,
    SignalRepository, PositionRepository, CorrelationRepository,
    ConfigurationRepository, LLMCacheRepository, HealthMetricsRepository
)

logger = logging.getLogger(__name__)

# Global database manager and repository factory instances
_db_manager: Optional[DatabaseManager] = None
_repository_factory: Optional[RepositoryFactory] = None


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
    project_root = Path(__file__).parent.parent.parent
    db_path = project_root / "data" / "signal_ea.db"
    
    # Ensure data directory exists
    db_path.parent.mkdir(exist_ok=True)
    
    return f"sqlite+aiosqlite:///{db_path}"


async def initialize_database(database_url: Optional[str] = None, 
                            run_migrations: bool = True) -> None:
    """
    Initialize database connection and run migrations if needed.
    
    Args:
        database_url: Optional database URL override
        run_migrations: Whether to run database migrations
        
    Raises:
        DatabaseError: If initialization fails
    """
    global _db_manager, _repository_factory
    
    try:
        # Get database URL
        url = database_url or get_database_url()
        logger.info(f"Initializing database: {url.split(':///')[-1] if '///' in url else url}")
        
        # Initialize database manager
        _db_manager = DatabaseManager(url)
        await _db_manager.initialize()
        
        # Run migrations if requested
        if run_migrations:
            await run_database_migrations(url)
        
        # Initialize repository factory
        _repository_factory = RepositoryFactory(_db_manager)
        
        # Perform health check
        await perform_database_health_check()
        
        logger.info("Database initialization completed successfully")
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        if _db_manager:
            await _db_manager.close()
        raise DatabaseError(f"Failed to initialize database: {e}")


async def run_database_migrations(database_url: str) -> None:
    """
    Run database migrations programmatically.
    
    Args:
        database_url: Database URL for migrations
    """
    try:
        from alembic import command
        from alembic.config import Config
        
        # Setup Alembic config
        migrations_dir = Path(__file__).parent / "migrations"
        alembic_cfg = Config(str(migrations_dir / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(migrations_dir))
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)
        
        # Run migrations
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed")
        
    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        raise DatabaseError(f"Migration failed: {e}")


async def perform_database_health_check() -> bool:
    """
    Perform basic database health check.
    
    Returns:
        True if database is healthy, False otherwise
    """
    try:
        if not _db_manager:
            return False
        
        # Test basic connection
        async with _db_manager.get_session() as session:
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
        
        # Test repository access
        config_repo = get_configuration_repository()
        await config_repo.get_config_value("health_check", "ok")
        
        logger.info("Database health check passed")
        return True
        
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


def get_database_manager() -> DatabaseManager:
    """
    Get global database manager instance.
    
    Returns:
        DatabaseManager instance
        
    Raises:
        DatabaseError: If database not initialized
    """
    if not _db_manager:
        raise DatabaseError("Database not initialized. Call initialize_database() first.")
    return _db_manager


def get_repository_factory() -> RepositoryFactory:
    """
    Get global repository factory instance.
    
    Returns:
        RepositoryFactory instance
        
    Raises:
        DatabaseError: If database not initialized
    """
    if not _repository_factory:
        raise DatabaseError("Database not initialized. Call initialize_database() first.")
    return _repository_factory


# Convenience functions for getting repositories
def get_signal_repository() -> SignalRepository:
    """Get signal repository instance."""
    return get_repository_factory().get_signal_repository()


def get_position_repository() -> PositionRepository:
    """Get position repository instance."""
    return get_repository_factory().get_position_repository()


def get_correlation_repository() -> CorrelationRepository:
    """Get correlation repository instance."""
    return get_repository_factory().get_correlation_repository()


def get_configuration_repository() -> ConfigurationRepository:
    """Get configuration repository instance."""
    return get_repository_factory().get_configuration_repository()


def get_llm_cache_repository() -> LLMCacheRepository:
    """Get LLM cache repository instance."""
    return get_repository_factory().get_llm_cache_repository()


def get_health_metrics_repository() -> HealthMetricsRepository:
    """Get health metrics repository instance."""
    return get_repository_factory().get_health_metrics_repository()


async def close_database() -> None:
    """Close database connections and cleanup."""
    global _db_manager, _repository_factory
    
    try:
        if _db_manager:
            await _db_manager.close()
            _db_manager = None
            _repository_factory = None
            logger.info("Database connections closed")
            
    except Exception as e:
        logger.error(f"Error closing database: {e}")


async def reset_database(confirm: bool = False) -> None:
    """
    Reset database by dropping all tables and recreating them.
    
    Args:
        confirm: Must be True to actually perform the reset
        
    Warning:
        This will delete ALL data in the database!
    """
    if not confirm:
        raise ValueError("Database reset requires explicit confirmation")
    
    try:
        if not _db_manager:
            raise DatabaseError("Database not initialized")
        
        logger.warning("Resetting database - ALL DATA WILL BE LOST!")
        
        # Drop all tables
        async with _db_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("Database reset completed")
        
    except Exception as e:
        logger.error(f"Database reset failed: {e}")
        raise DatabaseError(f"Failed to reset database: {e}")


# Export commonly used classes and functions
__all__ = [
    # Core classes
    "DatabaseManager",
    "RepositoryFactory",
    "DatabaseError",
    
    # Repository classes
    "SignalRepository",
    "PositionRepository", 
    "CorrelationRepository",
    "ConfigurationRepository",
    "LLMCacheRepository",
    "HealthMetricsRepository",
    
    # Initialization functions
    "initialize_database",
    "close_database",
    "get_database_url",
    "perform_database_health_check",
    
    # Repository getter functions
    "get_database_manager",
    "get_repository_factory",
    "get_signal_repository",
    "get_position_repository",
    "get_correlation_repository", 
    "get_configuration_repository",
    "get_llm_cache_repository",
    "get_health_metrics_repository",
    
    # Utility functions
    "run_database_migrations",
    "reset_database",
]