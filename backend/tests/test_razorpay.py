"""Razorpay (test mode) provider: order creation, signed webhooks, refunds, gateway outages.

No real network calls: httpx.post is replaced by a fake Razorpay API, and webhooks are
signed exactly the way Razorpay documents (HMAC-SHA256 of the raw body, hex digest).
"""

import json
from contextlib import nullcontext
from decimal import Decimal

import httpx
import pytest

from app.core import jobs
from app.core.config import settings
from app.core.redis import get_redis, get_worker_redis
from app.services.payment_providers import InvalidSignatureError, RazorpayProvider, sign
from app.worker import process_one
from tests.conftest import API

SECRET = settings.PAYMENT_WEBHOOK_SECRET


class FakeRazorpay:
    """Records calls and answers like the Razorpay Orders/Refunds API."""

    def __init__(self):
        self.calls = []
        self.down = False

    def post(self, url, json=None, auth=None, timeout=None):
        self.calls.append((url, json, auth))
        if self.down:
            raise httpx.ConnectError("connection refused")
        request = httpx.Request("POST", url)
        if url.endswith("/orders"):
            body = {
                "id": f"order_test{len(self.calls)}",
                "amount": json["amount"],
                "status": "created",
            }
        elif url.endswith("/refund"):
            body = {"id": "rfnd_test1", "amount": json["amount"]}
        else:
            return httpx.Response(404, request=request)
        return httpx.Response(200, json=body, request=request)


@pytest.fixture
def razorpay(monkeypatch):
    fake = FakeRazorpay()
    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "rzp_test_secret")
    monkeypatch.setattr("app.services.payment_providers.httpx.post", fake.post)
    return fake


def webhook(event, order_id, amount_paise, pay_id="pay_test123"):
    body = json.dumps({
        "event": event,
        "payload": {"payment": {"entity": {
            "id": pay_id, "order_id": order_id, "amount": amount_paise, "status": "captured",
        }}},
    }).encode()  # fmt: skip
    return body, {
        "x-razorpay-signature": sign(body, SECRET),
        "x-razorpay-event-id": f"evt_{pay_id}_{event}",
    }


def start_checkout(client, w):
    client.post(
        f"{API}/cart/items",
        json={"menu_item_id": w.items[0].id, "quantity": 2},
        headers=w.customer_h,
    )
    oid = client.post(
        f"{API}/orders", json={"address_id": w.address.id}, headers=w.customer_h
    ).json()["id"]
    res = client.post(f"{API}/payments/orders/{oid}/checkout", headers=w.customer_h)
    assert res.status_code == 200, res.text
    return oid, res.json()


# ------------------------------------------------------------------ unit
def test_paise_conversion_and_signature_parsing():
    provider = RazorpayProvider("rzp_test_key", "s", SECRET, "https://api.example")
    assert provider.to_paise(Decimal("552.90")) == 55290
    body, headers = webhook("payment.captured", "order_abc", 55290)
    event = provider.parse_webhook(body, headers)
    assert (event.type, event.provider_payment_id, event.amount, event.charge_id) == (
        "payment.succeeded", "order_abc", Decimal("552.90"), "pay_test123",
    )  # fmt: skip
    with pytest.raises(InvalidSignatureError):
        provider.parse_webhook(body, {"x-razorpay-signature": "0" * 64})
    with pytest.raises(InvalidSignatureError):
        provider.parse_webhook(body.replace(b"55290", b"100"), headers)  # tampered amount


# ------------------------------------------------------------------ end to end
def test_checkout_creates_razorpay_order_in_paise(client, world, razorpay):
    oid, checkout = start_checkout(client, world)
    url, body, auth = razorpay.calls[0]
    assert url.endswith("/orders")
    assert body == {"amount": 55290, "currency": "INR", "receipt": f"order_{oid}"}
    assert auth == ("rzp_test_key", "rzp_test_secret")
    assert checkout["provider"] == "razorpay"
    assert checkout["checkout"]["key_id"] == "rzp_test_key"  # public key only
    assert "rzp_test_secret" not in json.dumps(checkout)


def test_captured_webhook_places_order_and_reject_refunds_the_charge(client, world, razorpay):
    oid, checkout = start_checkout(client, world)
    body, headers = webhook("payment.captured", checkout["provider_payment_id"], 55290)
    assert client.post(f"{API}/payments/webhook", content=body, headers=headers).json() == {
        "status": "processed"
    }
    assert client.get(f"{API}/orders/{oid}", headers=world.customer_h).json()["status"] == "PLACED"

    res = client.post(
        f"{API}/owner/orders/{oid}/reject", json={"reason": "Closed"}, headers=world.owner_h
    )
    assert res.json()["payment_status"] == "refunded"
    refund_url, refund_body, _ = razorpay.calls[-1]
    assert refund_url.endswith("/payments/pay_test123/refund")  # refunds use the charge id
    assert refund_body == {"amount": 55290}


def test_gateway_down_at_checkout_returns_502(client, world, razorpay):
    razorpay.down = True
    client.post(
        f"{API}/cart/items",
        json={"menu_item_id": world.items[0].id, "quantity": 2},
        headers=world.customer_h,
    )
    oid = client.post(
        f"{API}/orders", json={"address_id": world.address.id}, headers=world.customer_h
    ).json()["id"]
    res = client.post(f"{API}/payments/orders/{oid}/checkout", headers=world.customer_h)
    assert res.status_code == 502 and res.json()["error"]["code"] == "GATEWAY_UNAVAILABLE"


def test_refund_is_retried_by_worker_when_gateway_is_down(
    client, world, razorpay, db_session, monkeypatch
):
    oid, checkout = start_checkout(client, world)
    body, headers = webhook("payment.captured", checkout["provider_payment_id"], 55290)
    client.post(f"{API}/payments/webhook", content=body, headers=headers)

    razorpay.down = True
    res = client.post(
        f"{API}/owner/orders/{oid}/reject", json={"reason": "Closed"}, headers=world.owner_h
    )
    assert res.status_code == 200 and res.json()["status"] == "REJECTED"  # order change still works
    assert res.json()["payment_status"] == "succeeded"  # refund not done yet
    queued = [json.loads(j)["name"] for j in get_redis().lrange(jobs.QUEUE, 0, -1)]
    assert "refund_payment" in queued

    razorpay.down = False
    monkeypatch.setattr("app.worker.SessionLocal", lambda: nullcontext(db_session))
    while process_one(get_worker_redis(), timeout=1):
        pass
    payment = client.get(f"{API}/payments/orders/{oid}", headers=world.customer_h).json()
    assert payment["status"] == "refunded"
