"""A small, reliable background-job queue on Redis lists.

Why a queue? Slow or flaky work (sending e-mail/SMS, calling third parties) must not make
the customer wait or fail their request. The API pushes a job and returns; a separate
worker process (`python -m app.worker`) does the work.

Reliability ("at-least-once" delivery)
- Producer:  LPUSH mc:jobs <json>
- Worker:    BLMOVE mc:jobs -> mc:jobs:processing   (atomic: the job is never "in the air")
             run the handler
             success -> LREM from processing
             failure -> retry (attempts + 1) or move to mc:jobs:dead after MAX_ATTEMPTS
- On start, the worker moves anything left in `processing` (a crashed worker's jobs)
  back to the queue. Handlers must therefore be idempotent (safe to run twice).

Transactional enqueue
`enqueue_after_commit(db, ...)` stores the job on the SQLAlchemy session and pushes it
only after the transaction COMMITS. If the transaction rolls back, the job is dropped —
we never e-mail about an order that was not saved.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import redis
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.redis import get_redis, mark_redis_down

logger = logging.getLogger(__name__)

QUEUE = "mc:jobs"
PROCESSING = "mc:jobs:processing"
DEAD = "mc:jobs:dead"
MAX_ATTEMPTS = 3
_PENDING = "pending_jobs"


def make_job(name: str, payload: dict[str, Any], attempts: int = 0) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "payload": payload,
        "attempts": attempts,
        "enqueued_at": datetime.now(UTC).isoformat(),
    }


def push(job: dict[str, Any]) -> None:
    try:
        get_redis().lpush(QUEUE, json.dumps(job))
    except redis.RedisError:
        # Losing an e-mail must not break the request; it is logged for follow-up.
        logger.error("could not enqueue job", extra={"job": job["name"]}, exc_info=True)
        mark_redis_down()


def enqueue(name: str, payload: dict[str, Any]) -> None:
    """Push immediately (use only outside a database transaction)."""
    push(make_job(name, payload))


def enqueue_after_commit(db: Session, name: str, payload: dict[str, Any]) -> None:
    """Push when (and only if) the current transaction commits."""
    db.info.setdefault(_PENDING, []).append(make_job(name, payload))


@event.listens_for(Session, "after_commit")
def _flush_pending_jobs(session: Session) -> None:
    for job in session.info.pop(_PENDING, []):
        push(job)


@event.listens_for(Session, "after_rollback")
def _drop_pending_jobs(session: Session) -> None:
    dropped = session.info.pop(_PENDING, [])
    if dropped:
        logger.info("dropped %d job(s) after rollback", len(dropped))
