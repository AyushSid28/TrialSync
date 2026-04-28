import logging
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine,
)
from src.db.base import Base
from src.core.config import settings
import logfire
import re
from functools import lru_cache

logger = logging.getLogger(__name__)


def fix_postgres_url(url: str) -> str:
    """Convert postgres:// to postgresql:// if needed and ensure async driver."""
    if url.startswith("postgres://"):
        url = re.sub(r"^postgres://", "postgresql://", url)

    if "postgresql://" in url and "postgresql+asyncpg://" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://")

    return url


@lru_cache(maxsize=1)
def create_engine() -> AsyncEngine:
    db_url = fix_postgres_url(str(settings.DATABASE_URL))
    logger.debug(f"Creating database engine", extra={"echo": settings.DEBUG})
    
    engine = create_async_engine(
        db_url,
        echo=settings.DEBUG,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=False,
        pool_recycle=300,
    )
    
    if settings.ENVIRONMENT == "production" and settings.LOGFIRE_WRITE_TOKEN:
        try:
            logfire.instrument_sqlalchemy(engine=engine)
            logger.info("Logfire SQLAlchemy instrumentation enabled")
        except Exception as e:
            logger.warning(f"Failed to instrument SQLAlchemy with Logfire: {e}")
    
    return engine


engine = create_engine()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            logger.debug("Database session created")
            yield session
            await session.commit()
            logger.debug("Database session committed")
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error: {e}", exc_info=True)
            raise
        finally:
            await session.close()


async def get_session() -> AsyncSession:
    async with engine.begin() as session:
        yield session


async def close_db() -> None:
    logger.info("Closing database connections")
    await engine.dispose()
    logger.info("Database connections closed")
