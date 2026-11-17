"""Health checks used by Docker, the load balancer and monitoring."""

import logging

import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import settings

router = APIRouter(prefix="/health", tags=["System"])
logger = logging.getLogger(__name__)


@router.get("", summary="Liveness: the process is up")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness: database and Redis are reachable")
def ready(db: DbSession) -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.exception("readiness: database check failed")
        checks["database"] = "unavailable"
    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
        client.ping()
        checks["redis"] = "ok"
    except Exception:
        logger.exception("readiness: redis check failed")
        checks["redis"] = "unavailable"

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )
