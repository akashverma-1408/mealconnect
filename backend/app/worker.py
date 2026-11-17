"""Background worker: processes jobs from the Redis queue (see app/core/jobs.py).

Run it next to the API:
    python -m app.worker

Stop with Ctrl-C (or SIGTERM in Docker): the current job finishes first.
"""

import json
import logging
import signal
import sys
import time
from collections.abc import Callable
from typing import Any

import redis
from sqlalchemy import select

from app.core.config import settings
from app.core.jobs import DEAD, MAX_ATTEMPTS, PROCESSING, QUEUE, make_job
from app.core.logging import setup_logging
from app.core.redis import get_worker_redis
from app.db.session import SessionLocal
from app.models.order import Order
from app.models.user import User
from app.services.email_service import send_email

logger = logging.getLogger("app.worker")

STATUS_EMAILS = {
    "PLACED": "We received your order #{id} from {restaurant}. Total: Rs {total}.",
    "ACCEPTED": "{restaurant} accepted your order #{id}.",
    "REJECTED": "{restaurant} could not accept order #{id}. Your payment will be refunded.",
    "OUT_FOR_DELIVERY": "Order #{id} is on its way!",
    "DELIVERED": "Order #{id} was delivered. Enjoy, and rate your meal in the app.",
    "CANCELLED": "Order #{id} was cancelled. Any payment has been refunded.",
}


# ------------------------------------------------------------------ job handlers
def order_status_email(order_id: int, status: str) -> None:
    template = STATUS_EMAILS.get(status)
    if template is None:
        return
    with SessionLocal() as db:
        order = db.scalar(select(Order).where(Order.id == order_id))
        if order is None:
            logger.warning("order %s not found for email", order_id)
            return
        text = template.format(id=order.id, restaurant=order.restaurant.name, total=order.total)
        send_email(order.customer.email, f"MealConnect order #{order.id}", text)


def welcome_email(user_id: int) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user:
            send_email(
                user.email,
                "Welcome to MealConnect",
                f"Hi {user.full_name.split()[0]}, your account is ready.",
            )


def refund_payment(payment_id: int) -> None:
    from app.services.payment_service import retry_refund

    with SessionLocal() as db:
        retry_refund(db, payment_id)


HANDLERS: dict[str, Callable[..., Any]] = {
    "order_status_email": order_status_email,
    "welcome_email": welcome_email,
    "refund_payment": refund_payment,
}


# ------------------------------------------------------------------ worker loop
def recover_stuck_jobs(r: redis.Redis) -> int:
    """Jobs left in `processing` by a crashed worker go back to the queue."""
    moved = 0
    while r.lmove(PROCESSING, QUEUE, "RIGHT", "LEFT") is not None:
        moved += 1
    if moved:
        logger.warning("recovered %d unfinished job(s)", moved)
    return moved


def process_one(r: redis.Redis, timeout: int = 5) -> bool:
    """Take one job (waiting up to `timeout` s) and run it. Returns False if none arrived.

    `r` must be the worker client (get_worker_redis): its socket timeout outlasts `timeout`.
    """
    raw = r.blmove(QUEUE, PROCESSING, timeout, "RIGHT", "LEFT")
    if raw is None:
        return False
    job = json.loads(raw)
    handler = HANDLERS.get(job["name"])
    try:
        if handler is None:
            raise LookupError(f"no handler for job {job['name']!r}")
        handler(**job["payload"])
        logger.info("job done", extra={"job": job["name"], "job_id": job["id"]})
    except Exception as exc:
        attempts = job["attempts"] + 1
        if attempts < MAX_ATTEMPTS and handler is not None:
            r.lpush(QUEUE, json.dumps(make_job(job["name"], job["payload"], attempts)))
            logger.warning(
                "job failed, will retry", extra={"job": job["name"], "attempt": attempts}
            )
        else:
            r.lpush(DEAD, json.dumps({**job, "attempts": attempts, "error": repr(exc)}))
            logger.error(
                "job moved to dead-letter queue", extra={"job": job["name"]}, exc_info=True
            )
    finally:
        r.lrem(PROCESSING, 1, raw)  # acknowledge
    return True


def main() -> int:
    setup_logging(settings.LOG_LEVEL, settings.LOG_JSON)
    r = get_worker_redis()
    running = True

    def stop(*_: Any) -> None:
        nonlocal running
        running = False
        logger.info("shutdown requested; finishing current job")

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    recover_stuck_jobs(r)
    logger.info("worker started", extra={"queue": QUEUE})
    while running:
        try:
            process_one(r, timeout=2)
        except redis.RedisError:
            logger.error("redis unavailable, retrying", exc_info=True)
            time.sleep(2)
    logger.info("worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
