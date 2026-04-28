"""
Verify database connection pool configuration for concurrent imports.

Run from project root:
    uv run python -m src.scrappers.verify_pool_config
"""

from __future__ import annotations

import asyncio
import logging

from src.core.config import settings
from src.db.session import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def verify_pool() -> None:
    """Check pool configuration and test concurrent connections."""
    
    logger.info("=== Database Pool Configuration ===")
    logger.info(f"Pool Size: {settings.DATABASE_POOL_SIZE}")
    logger.info(f"Max Overflow: {settings.DATABASE_MAX_OVERFLOW}")
    logger.info(f"Total Available Connections: {settings.DATABASE_POOL_SIZE + settings.DATABASE_MAX_OVERFLOW}")
    logger.info("")
    
    # Test connection
    logger.info("Testing database connection...")
    async with engine.connect() as conn:
        result = await conn.execute("SELECT version()")
        version = result.scalar()
        logger.info(f"PostgreSQL Version: {version}")
    
    logger.info("")
    logger.info("=== Recommendations ===")
    
    total_connections = settings.DATABASE_POOL_SIZE + settings.DATABASE_MAX_OVERFLOW
    
    if total_connections < 10:
        logger.warning(
            "⚠️  Pool size is small. Consider increasing for concurrent imports:"
        )
        logger.warning("   DATABASE_POOL_SIZE=20")
        logger.warning("   DATABASE_MAX_OVERFLOW=10")
    else:
        logger.info("✓ Pool configuration looks good for concurrent imports")
    
    max_recommended_workers = total_connections - 5  # Leave headroom
    logger.info(f"✓ Max recommended workers: {max_recommended_workers}")
    logger.info("")
    
    logger.info("Example import command for 21K records:")
    logger.info(
        f"  uv run python -m src.scrappers.import_kaggle_patients \\"
    )
    logger.info(f"    --file data/cvd_full.csv \\")
    logger.info(f"    --workers 4 \\")
    logger.info(f"    --batch-size 200 \\")
    logger.info(f"    --enable-consent")


async def main() -> None:
    try:
        await verify_pool()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
