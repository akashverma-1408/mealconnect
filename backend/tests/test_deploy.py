"""Settings and worker behaviour that hosted (free-tier) deployments rely on."""

import threading

import pytest
import redis
from pydantic import ValidationError

import app.worker as worker
from app.core.config import Settings
from app.core.jobs import QUEUE, enqueue
from app.core.redis import get_worker_redis

BASE = {"JWT_SECRET_KEY": "x" * 32, "PAYMENT_WEBHOOK_SECRET": "y" * 32}


@pytest.mark.unit
@pytest.mark.parametrize(
    "given",
    ["postgres://u:p@h/db?sslmode=require", "postgresql://u:p@h/db?sslmode=require"],
)
def test_hosted_database_urls_use_the_psycopg_driver(given):
    s = Settings(DATABASE_URL=given, **BASE)
    assert s.DATABASE_URL == "postgresql+psycopg://u:p@h/db?sslmode=require"


@pytest.mark.unit
def test_explicit_driver_is_left_alone():
    url = "postgresql+psycopg://u:p@h/db"
    assert url == Settings(DATABASE_URL=url, **BASE).DATABASE_URL


@pytest.mark.unit
@pytest.mark.parametrize("bad", [0, 26])
def test_worker_poll_must_stay_below_the_socket_timeout(bad):
    with pytest.raises(ValidationError):
        Settings(DATABASE_URL="postgresql://u:p@h/db", WORKER_POLL_SECONDS=bad, **BASE)


def test_polling_fallback_when_redis_rejects_blocking_commands(monkeypatch):
    real = get_worker_redis()

    class NoBlocking:
        def blmove(self, *a, **k):
            raise redis.ResponseError("unknown command 'BLMOVE'")

        def __getattr__(self, name):
            return getattr(real, name)

    monkeypatch.setattr(worker, "_blocking_supported", True)
    seen = []
    monkeypatch.setitem(worker.HANDLERS, "ping", lambda **p: seen.append(p))
    enqueue("ping", {"n": 1})
    assert worker.process_one(NoBlocking(), timeout=1) is True
    assert seen == [{"n": 1}]
    assert worker._blocking_supported is False
    # empty queue: polls, sleeps for the timeout, reports nothing done
    assert worker.process_one(NoBlocking(), timeout=1) is False


def test_embedded_worker_processes_jobs_and_stops(monkeypatch):
    monkeypatch.setattr(worker, "_blocking_supported", True)
    done = threading.Event()
    monkeypatch.setitem(worker.HANDLERS, "ping", lambda **p: done.set())
    monkeypatch.setattr(worker.settings, "WORKER_POLL_SECONDS", 1)
    thread, stop = worker.start_embedded_worker()
    try:
        enqueue("ping", {})
        assert done.wait(5), "embedded worker did not run the job"
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()
    assert get_worker_redis().llen(QUEUE) == 0
