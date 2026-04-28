"""
Per-IP sliding-window rate limiter with cooldown support.

Design notes:
- Uses an in-memory store (dict of deques + cooldown timestamps).
- Appropriate for single-worker deployments (WORKERS=1).
- For multi-worker or horizontally-scaled deployments, replace the in-memory
  store with a Redis backend using atomic Lua scripts or `redis-py` pipelines.
- asyncio.Lock ensures coroutine-safe access; no thread-safety overhead needed
  because FastAPI / uvicorn runs in a single-threaded async event loop per worker.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque

from src.core.config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Sliding-window rate limiter with optional cooldown punishment.

    Algorithm (per IP):
    1. Evict timestamps older than `window_seconds` from the deque.
    2. If the IP is currently in cooldown → reject with retry-after.
    3. If the deque length >= `requests` → start cooldown, reject.
    4. Otherwise → append current timestamp, allow.

    Cooldown is a separate "penalty box" window activated the moment a client
    exceeds the limit. During cooldown, all requests are rejected even if the
    sliding window would otherwise clear.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._cooldowns: dict[str, float] = {}

    async def is_allowed(self, ip: str) -> tuple[bool, int]:
        """
        Determine whether a request from `ip` is permitted.

        Returns:
            (allowed, retry_after_seconds)
              - (True, 0)  → request is permitted
              - (False, N) → request is blocked; client should wait N seconds
        """
        if not settings.RATE_LIMIT_ENABLED:
            return True, 0

        now = time.monotonic()
        window_seconds: int = settings.RATE_LIMIT_WINDOW_SECONDS
        limit: int = settings.RATE_LIMIT_REQUESTS
        cooldown_seconds: int = settings.RATE_LIMIT_COOLDOWN_SECONDS

        async with self._lock:
            # --- Active cooldown check ---
            cooldown_until = self._cooldowns.get(ip, 0.0)
            if now < cooldown_until:
                retry_after = int(cooldown_until - now) + 1
                logger.debug("Request blocked (cooldown)", extra={"client_ip": ip, "retry_after": retry_after})
                return False, retry_after

            # --- Evict timestamps outside the sliding window ---
            window_start = now - window_seconds
            dq = self._windows[ip]
            while dq and dq[0] <= window_start:
                dq.popleft()

            # --- Enforce the request limit ---
            if len(dq) >= limit:
                expiry = now + cooldown_seconds
                self._cooldowns[ip] = expiry
                logger.warning(
                    "Rate limit exceeded — cooldown started",
                    extra={
                        "client_ip": ip,
                        "limit": limit,
                        "window_seconds": window_seconds,
                        "cooldown_seconds": cooldown_seconds,
                    },
                )
                return False, cooldown_seconds

            # --- Allow ---
            dq.append(now)
            return True, 0

    def reset(self, ip: str) -> None:
        """Clear all rate-limit state for a given IP (useful in tests / admin tooling)."""
        self._windows.pop(ip, None)
        self._cooldowns.pop(ip, None)

    def stats(self, ip: str) -> dict[str, int | bool]:
        """Return current window hit count and cooldown status for an IP (read-only)."""
        now = time.monotonic()
        dq = self._windows.get(ip, deque())
        window_start = now - settings.RATE_LIMIT_WINDOW_SECONDS
        active_hits = sum(1 for t in dq if t > window_start)
        cooldown_until = self._cooldowns.get(ip, 0.0)
        in_cooldown = now < cooldown_until
        return {
            "active_hits": active_hits,
            "limit": settings.RATE_LIMIT_REQUESTS,
            "in_cooldown": in_cooldown,
            "retry_after": max(0, int(cooldown_until - now) + 1) if in_cooldown else 0,
        }


# Module-level singleton — shared across all requests within the same worker process.
rate_limiter = RateLimiter()
