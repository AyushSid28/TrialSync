import logging

from fastapi import APIRouter, Depends

from src.api.dependencies import check_rate_limit, verify_api_key
from src.api.routes.agent_routes import router as agent_router
from src.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

router.include_router(
    agent_router,
    prefix=settings.API_V1_PREFIX,
    # Rate limiting runs before API-key verification so abusive clients are
    # throttled even before we do crypto comparisons.
    dependencies=[Depends(check_rate_limit), Depends(verify_api_key)],
)


@router.get("/")
async def root() -> dict[str, str]:
    logger.info("Root endpoint accessed")
    return {"message": "Hello World"}


@router.get("/health")
async def health_check() -> dict[str, str]:
    logger.debug("Health check endpoint accessed")
    return {"status": "healthy", "version": settings.APP_VERSION}
