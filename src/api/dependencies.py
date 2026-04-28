from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.db.session import get_db
from src.services.rate_limiter import rate_limiter

DBSession = Annotated[AsyncSession, Depends(get_db)]


async def verify_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Reject requests when `X-API-Key` is missing or does not match `settings.API_KEY`."""
    expected = settings.API_KEY
    provided = x_api_key or ""
    if len(provided) != len(expected) or not compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def _extract_client_ip(request: Request) -> str:
    """
    Resolve the real client IP from the request, honouring common reverse-proxy
    headers so that Nginx / load-balancer deployments report the originating IP
    rather than the proxy's address.

    Priority:
    1. X-Forwarded-For  (leftmost address is the originating client)
    2. X-Real-IP
    3. request.client.host (direct connection fallback)
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else "unknown"


async def check_rate_limit(request: Request) -> None:
    """
    FastAPI dependency that enforces per-IP rate limiting.

    Raises HTTP 429 with a `Retry-After` header when the client has exceeded
    the configured request budget or is serving a cooldown penalty.
    """
    ip = _extract_client_ip(request)
    allowed, retry_after = await rate_limiter.is_allowed(ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
