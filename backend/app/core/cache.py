"""Read-through cache in Redis for hot, read-mostly data (restaurant lists, menus).

Design
- **Cache-aside**: look in Redis first; on a miss, run the query and store the JSON.
- **TTL** on every key, so even a missed invalidation heals itself within minutes.
- **Versioned keys for invalidation**: list keys include a "catalogue version" number.
  Any change that can affect listings does `INCR catalogue:version`, which makes every
  old list key unreachable at once (no need to find and delete them; they expire).
  Menus are per restaurant, so they are deleted directly.
- **Fail open**: if Redis is down the app still works, just slower (errors are logged).
"""

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

import redis

from app.core.config import settings
from app.core.redis import get_redis, mark_redis_down, redis_is_down

logger = logging.getLogger(__name__)

PREFIX = "mc:cache:"
VERSION_KEY = "mc:cache:catalogue:version"


def _client() -> redis.Redis | None:
    if not settings.CACHE_ENABLED or redis_is_down():
        return None
    return get_redis()


def _catalogue_version(r: redis.Redis) -> str:
    return r.get(VERSION_KEY) or "0"


def cached_json(key: str, ttl: int, loader: Callable[[], Any], versioned: bool = False) -> Any:
    """Return the cached JSON value for `key`, or call `loader()` and cache its result.

    `loader` must return something JSON-serializable (e.g. `model.model_dump(mode="json")`).
    """
    r = _client()
    if r is None:
        return loader()
    try:
        full_key = PREFIX + (f"v{_catalogue_version(r)}:" if versioned else "") + key
        hit = r.get(full_key)
        if hit is not None:
            return json.loads(hit)
    except redis.RedisError:
        mark_redis_down()
        return loader()

    value = loader()
    try:
        r.set(full_key, json.dumps(value), ex=ttl)
    except redis.RedisError:
        mark_redis_down()
    return value


def params_key(prefix: str, params: dict[str, Any]) -> str:
    """Stable short key for a set of query parameters."""
    raw = json.dumps(params, sort_keys=True, default=str)
    return f"{prefix}:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def invalidate_catalogue(restaurant_id: int | None = None) -> None:
    """Call after anything that changes what customers see in listings or a menu."""
    r = _client()
    if r is None:
        return
    try:
        pipe = r.pipeline()
        pipe.incr(VERSION_KEY)  # all versioned list/search keys become stale at once
        if restaurant_id is not None:
            pipe.delete(f"{PREFIX}menu:{restaurant_id}", f"{PREFIX}restaurant:{restaurant_id}")
        pipe.execute()
    except redis.RedisError:
        # A missed invalidation is bounded by the TTL; log it loudly.
        logger.error("cache invalidation failed", exc_info=True)
        mark_redis_down()
