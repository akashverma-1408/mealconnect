"""Phase 8: Redis cache, rate limiting, security headers, background jobs."""

import json
import logging

import pytest
import redis

from app.core import jobs
from app.core.config import settings
from app.core.redis import get_redis, get_worker_redis
from app.worker import process_one, recover_stuck_jobs
from tests.conftest import API, login, place_paid_order, register


# ------------------------------------------------------------------ cache
def test_restaurant_list_is_cached_and_invalidated_on_owner_change(client, world):
    first = client.get(f"{API}/restaurants").json()
    assert first["items"][0]["delivery_fee"] == "30.00"
    assert any(k.startswith("mc:cache:v") for k in get_redis().keys("mc:cache:*"))

    # Owner changes the fee -> the cached list must not serve the old value.
    client.patch(f"{API}/owner/restaurants/{world.restaurant.id}", json={"delivery_fee": "15"},
                 headers=world.owner_h)  # fmt: skip
    again = client.get(f"{API}/restaurants").json()
    assert again["items"][0]["delivery_fee"] == "15.00"


def test_menu_cache_reflects_availability_toggle(client, world):
    url = f"{API}/restaurants/{world.restaurant.id}/menu"

    def paneer_available():
        menu = client.get(url).json()
        return next(i for s in menu["sections"] for i in s["items"] if i["name"] == "Paneer Tikka")[
            "is_available"
        ]

    assert paneer_available() is True
    assert get_redis().exists(f"mc:cache:menu:{world.restaurant.id}")
    client.patch(f"{API}/owner/restaurants/{world.restaurant.id}/menu-items/{world.items[0].id}/availability",
                 json={"is_available": False}, headers=world.owner_h)  # fmt: skip
    assert paneer_available() is False


def test_cache_hit_does_not_query_the_database(client, world, monkeypatch):
    client.get(f"{API}/restaurants/{world.restaurant.id}/menu")  # warm the cache
    from app.services import restaurant_service

    def boom(*args, **kwargs):
        raise AssertionError("database should not be hit on a cache hit")

    monkeypatch.setattr(restaurant_service, "get_public_menu", boom)
    assert client.get(f"{API}/restaurants/{world.restaurant.id}/menu").status_code == 200


def test_suspending_restaurant_removes_it_from_cached_listing(client, world):
    assert client.get(f"{API}/restaurants").json()["total"] == 1
    client.patch(f"{API}/admin/restaurants/{world.restaurant.id}/status",
                 json={"status": "suspended", "reason": "Hygiene"}, headers=world.admin_h)  # fmt: skip
    assert client.get(f"{API}/restaurants").json()["total"] == 0
    assert client.get(f"{API}/restaurants/{world.restaurant.id}/menu").status_code == 404


def test_app_works_when_redis_is_down(client, world, monkeypatch):
    """Cache and rate limiter fail open: slower, but never broken."""
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    # Same client settings as production (app/core/redis.py), pointed at a closed port.
    dead = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.5,
                       retry=Retry(NoBackoff(), 0), decode_responses=True)  # fmt: skip
    monkeypatch.setattr("app.core.cache.get_redis", lambda: dead)
    monkeypatch.setattr("app.core.rate_limit.get_redis", lambda: dead)
    import time

    start = time.perf_counter()
    for _ in range(5):
        assert client.get(f"{API}/restaurants").status_code == 200
        assert client.get(f"{API}/restaurants/{world.restaurant.id}/menu").status_code == 200
    # Circuit breaker: after the first failure Redis is skipped, so 10 requests stay fast.
    assert time.perf_counter() - start < 2


# ------------------------------------------------------------------ rate limiting
def test_login_rate_limit_per_ip_and_email(client):
    register(client)
    for _ in range(5):
        assert login(client, password="Wrong1234").status_code == 401
    blocked = login(client)  # 6th attempt in the same minute, even with the right password
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert 0 < int(blocked.headers["retry-after"]) <= 60
    # A different account from the same IP is not affected.
    register(client, email="ravi@example.com")
    assert login(client, email="ravi@example.com").status_code == 200


def test_global_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "3/minute")
    codes = [client.get(f"{API}/restaurants").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert client.get(f"{API}/health").status_code == 200  # health checks are exempt


def test_trusted_proxy_ip_resolution(monkeypatch):
    from app.core.rate_limit import client_ip

    scope = {
        "client": ("10.0.0.5", 1234),
        "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.9")],
    }
    assert client_ip(scope) == "10.0.0.5"  # no trusted proxy: ignore the header
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
    assert (
        client_ip(scope) == "203.0.113.9"
    )  # one proxy: rightmost entry, not the forgeable left one


# ------------------------------------------------------------------ security headers
def test_security_headers(client):
    res = client.get(f"{API}/health")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in res.headers["content-security-policy"]
    assert "content-security-policy" not in client.get("/docs").headers  # Swagger needs its CDN


# ------------------------------------------------------------------ background jobs
def queued():
    return [json.loads(j) for j in get_redis().lrange(jobs.QUEUE, 0, -1)]


def test_registration_enqueues_welcome_email_after_commit(client):
    register(client)
    assert [j["name"] for j in queued()] == ["welcome_email"]


def test_failed_registration_enqueues_nothing(client):
    register(client)
    get_redis().delete(jobs.QUEUE)
    assert register(client).status_code == 409  # duplicate -> rolled back
    assert queued() == []


def test_order_status_change_emails_customer_via_worker(
    client, world, caplog, db_session, monkeypatch
):
    from contextlib import nullcontext

    # The worker normally opens its own session; in tests it must share the test
    # transaction (which is never committed), otherwise it cannot see the order.
    monkeypatch.setattr("app.worker.SessionLocal", lambda: nullcontext(db_session))
    get_redis().delete(jobs.QUEUE)
    place_paid_order(client, world)
    assert [(j["name"], j["payload"]["status"]) for j in queued()] == [
        ("order_status_email", "PLACED")
    ]

    with caplog.at_level(logging.INFO, logger="app.email"):
        assert process_one(get_worker_redis(), timeout=1) is True
    sent = [r for r in caplog.records if r.getMessage() == "email sent"]
    assert sent and sent[0].to == "cust@example.com" and "Spice Route" in sent[0].body
    assert get_redis().llen(jobs.PROCESSING) == 0  # acknowledged


def test_failing_job_is_retried_then_dead_lettered(monkeypatch):
    calls = []

    def flaky(**payload):
        calls.append(payload)
        raise RuntimeError("smtp down")

    monkeypatch.setitem(__import__("app.worker").worker.HANDLERS, "flaky", flaky)
    jobs.enqueue("flaky", {"n": 1})
    r = get_worker_redis()
    for _ in range(jobs.MAX_ATTEMPTS):
        process_one(r, timeout=1)
    assert len(calls) == jobs.MAX_ATTEMPTS
    assert r.llen(jobs.QUEUE) == 0
    dead = json.loads(r.lindex(jobs.DEAD, 0))
    assert dead["name"] == "flaky" and dead["attempts"] == 3 and "smtp down" in dead["error"]


def test_worker_recovers_jobs_from_a_crashed_worker():
    r = get_worker_redis()
    r.lpush(jobs.PROCESSING, json.dumps(jobs.make_job("welcome_email", {"user_id": 1})))
    assert recover_stuck_jobs(r) == 1
    assert r.llen(jobs.QUEUE) == 1 and r.llen(jobs.PROCESSING) == 0


@pytest.mark.parametrize(
    "rate,expected", [("5/minute", (5, 60)), ("10/hour", (10, 3600)), ("2/seconds", (2, 1))]
)
def test_parse_rate(rate, expected):
    from app.core.rate_limit import parse_rate

    assert parse_rate(rate) == expected


def test_worker_waits_on_an_empty_queue_without_socket_errors():
    """Regression: the worker's blocking wait must outlast its socket timeout."""
    assert process_one(get_worker_redis(), timeout=1) is False


def test_sandbox_and_docs_switches(client, world, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SANDBOX_PAYMENTS_ENABLED", None)
    assert settings.sandbox_payments_enabled is False and settings.docs_enabled is False
    assert (
        client.post(f"{API}/payments/sandbox/orders/1/pay", headers=world.customer_h).status_code
        == 404
    )
    monkeypatch.setattr(settings, "SANDBOX_PAYMENTS_ENABLED", True)  # demo deployment
    assert settings.sandbox_payments_enabled is True
    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", "razorpay")  # real gateway: never sandbox
    assert settings.sandbox_payments_enabled is False
