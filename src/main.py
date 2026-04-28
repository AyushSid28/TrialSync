from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logfire

from src.api.router import router as api_router
from src.core import settings
from src.core.logger import setup_logging, shutdown_logging
from src.db.session import close_db

import src.db.models  # noqa: F401 — register ORM mappers at import time

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize logging
    use_logfire = settings.ENVIRONMENT == "production" and bool(settings.LOGFIRE_WRITE_TOKEN)
    setup_logging(env=settings.ENVIRONMENT, use_logfire=use_logfire, log_level=settings.LOG_LEVEL)

    if use_logfire:
        try:
            logfire.instrument_fastapi(app)
            logger.info("Logfire FastAPI instrumentation enabled")
        except Exception as e:
            logger.warning(f"Failed to instrument FastAPI with Logfire: {e}")

    logger.info(
        "Application starting",
        extra={
            "app_name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        },
    )

    yield

    # Shutdown: Close database and logging
    logger.info("Application shutting down")
    close_db()
    shutdown_logging()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
