"""Tests configuration and fixtures."""

import pytest
import pytest_asyncio
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.db.base import Base
import src.db.models  # noqa: F401 — register mappers
from src.core import settings

_db_url = str(settings.DATABASE_URL)
if "+asyncpg" not in _db_url:
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://")
TEST_DATABASE_URL = _db_url


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Fresh async engine per test to avoid asyncpg / event loop reuse issues."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=settings.DEBUG,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
def anyio_backend():
    return "asyncio"
