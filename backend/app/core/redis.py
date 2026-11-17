"""One shared Redis client for the process, plus a tiny circuit breaker.

Redis is an optimization here (cache, rate-limit counters, job queue), never the source
of truth. If it goes down the API must keep working at normal speed, so:
- the client does NOT retry failed commands (a retry storm would add seconds per request);
- after one failure the breaker "opens": callers skip Redis entirely for BREAKER_SECONDS,
  then try again ("half-open"). Without this, every request would wait on a dead socket.
"""

import logging
import time
from functools import lru_cache

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core.config import settings

logger = logging.getLogger(__name__)

BREAKER_SECONDS = 30
_down_until = 0.0


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,  # str in, str out
        socket_connect_timeout=0.5,  # never let a slow Redis stall a request for long
        socket_timeout=0.5,
        retry=Retry(NoBackoff(), 0),  # fail fast; the breaker below decides what to do
        health_check_interval=30,
    )


def redis_is_down() -> bool:
    return time.monotonic() < _down_until


def mark_redis_down() -> None:
    global _down_until
    if not redis_is_down():
        logger.error("redis unavailable: bypassing it for %ss", BREAKER_SECONDS)
    _down_until = time.monotonic() + BREAKER_SECONDS


def reset_breaker() -> None:
    global _down_until
    _down_until = 0.0


@lru_cache
def get_worker_redis() -> redis.Redis:
    """Client for the background worker.

    The worker WAITS on Redis (BLMOVE with a timeout of a few seconds). The API client's
    0.5 s socket timeout would cut those waits short, so the worker uses its own client
    whose socket timeout is longer than any blocking call it makes.
    """
    return redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=30,
        health_check_interval=30,
    )
