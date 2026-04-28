"""DB-backed pipeline cache: replaces the in-process TTL dict with PostgreSQL.

Benefits over the old in-memory singleton:
- Survives process restarts
- Shared across all Gunicorn/uvicorn workers without inter-process locking
- Queryable — cache state is observable via SQL
- TTL still enforced, but entries are lazily expired on read and can be
  batch-evicted by calling ``evict_expired()`` from a background task.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.scoring import PipelineCacheEntry

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 300  # 5 minutes


class DbPipelineCache:
    """Persistent pipeline cache tied to a single request's AsyncSession.

    Each agent that needs caching instantiates its own ``DbPipelineCache``
    in ``__init__``, passing ``session``. This mirrors the pattern used by
    ``TextToSQLAgent`` and ``TrialMatchOrchestrator``.
    """

    def __init__(self, session: AsyncSession, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._session = session
        self._ttl = ttl_seconds

    async def get(self, trial_id: str) -> dict | None:
        """Return cached ``{generated_sql, patient_ids}`` or ``None`` if missing/expired."""
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            select(PipelineCacheEntry).where(
                PipelineCacheEntry.trial_id == trial_id,
                PipelineCacheEntry.expires_at > now,
            )
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            logger.debug("DB cache miss for trial %s", trial_id)
            return None

        logger.info("DB cache hit for trial %s (expires %s)", trial_id, entry.expires_at)
        return {"generated_sql": entry.generated_sql, "patient_ids": entry.patient_ids}

    async def set(
        self,
        trial_id: str,
        generated_sql: str | None,
        patient_ids: list[str],
    ) -> None:
        """Upsert a cache entry. Updates expiry on repeated calls for the same trial."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self._ttl)

        stmt = (
            pg_insert(PipelineCacheEntry)
            .values(
                trial_id=trial_id,
                generated_sql=generated_sql,
                patient_ids=patient_ids,
                created_at=now,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                index_elements=["trial_id"],
                set_={
                    "generated_sql": generated_sql,
                    "patient_ids": patient_ids,
                    "created_at": now,
                    "expires_at": expires_at,
                },
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
        logger.debug(
            "DB cached Stage 1 result for trial %s (%d patients, TTL %ds)",
            trial_id,
            len(patient_ids),
            self._ttl,
        )

    async def clear(self, trial_id: str | None = None) -> None:
        """Delete one or all cache entries."""
        if trial_id:
            await self._session.execute(
                delete(PipelineCacheEntry).where(PipelineCacheEntry.trial_id == trial_id)
            )
        else:
            await self._session.execute(delete(PipelineCacheEntry))
        await self._session.flush()
        logger.info("DB cache cleared: %s", trial_id or "all entries")

    async def evict_expired(self) -> int:
        """Delete all rows whose TTL has elapsed.

        Safe to call from a periodic background task (e.g. APScheduler or a
        FastAPI lifespan task) to keep the table lean.
        """
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            delete(PipelineCacheEntry).where(PipelineCacheEntry.expires_at <= now)
        )
        count = result.rowcount
        if count:
            logger.info("Evicted %d expired pipeline cache entries", count)
        await self._session.flush()
        return count
