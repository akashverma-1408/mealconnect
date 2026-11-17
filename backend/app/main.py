"""FastAPI application entry point.

Run locally:   uvicorn app.main:app --reload
API docs:      http://localhost:8000/docs
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import engine

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Code before `yield` runs at startup, code after it at shutdown."""
    logger.info("starting %s", settings.APP_NAME, extra={"environment": settings.ENVIRONMENT})
    yield
    engine.dispose()  # close pooled DB connections cleanly
    logger.info("shutdown complete")


def create_app() -> FastAPI:
    setup_logging(settings.LOG_LEVEL, settings.LOG_JSON)

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Food ordering and restaurant management platform.",
        lifespan=lifespan,
        # Hide interactive docs in production (the OpenAPI JSON can still be exported).
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
    )

    # Middleware: the last one added is the outermost (runs first).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    return app


app = create_app()
