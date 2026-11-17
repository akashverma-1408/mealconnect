"""Rate limiting with Redis (fixed-window counters).

For a rule like "5/minute" and key "login:1.2.3.4:asha@example.com":
    count = INCR  mc:rl:<key>:<window number>
    EXPIRE that key after one window (only when it was just created)
    count > 5  ->  429 Too Many Requests with a Retry-After header

Fixed windows are simple and cheap (2 Redis commands). Their known weakness is a burst
at a window boundary (up to 2x the limit across two adjacent windows); sliding-window
or token-bucket algorithms fix that at the cost of more Redis work.

Like the cache, the limiter fails OPEN: if Redis is unavailable, requests are allowed.
"""

import logging
import time

import redis
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.exceptions import TooManyRequestsError, error_response
from app.core.redis import get_redis, mark_redis_down, redis_is_down

logger = logging.getLogger(__name__)

UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_rate(rate: str) -> tuple[int, int]:
    """'5/minute' -> (5, 60)"""
    count, _, unit = rate.partition("/")
    return int(count), UNITS[unit.strip().rstrip("s")]


def hit(key: str, rate: str) -> tuple[bool, int]:
    """Count one request for `key`. Returns (allowed, seconds_until_reset)."""
    if not settings.RATE_LIMIT_ENABLED or redis_is_down():
        return True, 0
    limit, window = parse_rate(rate)
    now = int(time.time())
    window_no = now // window
    retry_after = window - (now % window)
    redis_key = f"mc:rl:{key}:{window_no}"
    try:
        pipe = get_redis().pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window, nx=True)
        count, _ = pipe.execute()
    except redis.RedisError:
        mark_redis_down()  # fail open: allow the request
        return True, 0
    return count <= limit, retry_after


def enforce(key: str, rate: str, message: str = "Too many requests") -> None:
    """Raise 429 if `key` exceeded `rate` (used inside endpoints, e.g. login)."""
    allowed, retry_after = hit(key, rate)
    if not allowed:
        logger.warning("rate limit exceeded", extra={"rate_key": key.split(":")[0]})
        raise TooManyRequestsError(
            f"{message}. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


def client_ip(scope: Scope) -> str:
    """Client IP. Behind N trusted proxies, take the Nth-from-right X-Forwarded-For entry
    (entries further left can be forged by the client)."""
    if settings.TRUSTED_PROXY_COUNT > 0:
        headers = dict(scope.get("headers") or [])
        forwarded = headers.get(b"x-forwarded-for", b"").decode("latin-1")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if len(hops) >= settings.TRUSTED_PROXY_COUNT:
            return hops[-settings.TRUSTED_PROXY_COUNT]
    client = scope.get("client")
    return client[0] if client else "unknown"


class RateLimitMiddleware:
    """Global per-IP limit for every /api request (health checks excluded)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/") or "/health" in path:
            await self.app(scope, receive, send)
            return
        allowed, retry_after = hit(f"ip:{client_ip(scope)}", settings.RATE_LIMIT_DEFAULT)
        if not allowed:
            response = error_response(
                429,
                "RATE_LIMITED",
                f"Too many requests. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
