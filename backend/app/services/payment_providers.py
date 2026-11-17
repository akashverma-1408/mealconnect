"""Payment gateway adapters.

Every provider exposes the same small interface, so the rest of the app never knows which
gateway is in use. Phase 8 adds a real gateway (test mode) as another class here.

The MockPaymentProvider behaves like a real gateway where it matters for security:
webhooks are JSON bodies signed with HMAC-SHA256 using a shared secret, and the server
rejects any webhook whose signature does not match.
"""

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

import httpx

from app.core.config import settings

EventType = Literal["payment.succeeded", "payment.failed"]


@dataclass(frozen=True)
class WebhookEvent:
    event_id: str
    type: str
    provider_payment_id: str
    amount: Decimal
    raw: dict
    charge_id: str | None = None  # the gateway's id for the actual charge, if it sends one


class InvalidSignatureError(Exception):
    pass


class PaymentProvider(Protocol):
    name: str

    def create_payment(self, amount: Decimal, currency: str, reference: str) -> tuple[str, dict]:
        """Return (provider_payment_id, data the frontend needs to show checkout)."""

    def parse_webhook(self, body: bytes, headers: dict[str, str]) -> WebhookEvent:
        """Verify the signature and parse the event, or raise InvalidSignatureError."""

    def refund(self, provider_payment_id: str, charge_id: str | None, amount: Decimal) -> str:
        """Refund a payment; return the provider's refund id."""


def sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class MockPaymentProvider:
    name = "mock"
    SIGNATURE_HEADER = "x-mock-signature"

    def __init__(self, secret: str) -> None:
        self.secret = secret

    def create_payment(self, amount: Decimal, currency: str, reference: str) -> tuple[str, dict]:
        provider_payment_id = f"mock_pay_{uuid.uuid4().hex[:20]}"
        return provider_payment_id, {
            "provider": self.name,
            "provider_payment_id": provider_payment_id,
            "amount": f"{amount:.2f}",
            "currency": currency,
            "reference": reference,
            "test_cards": {"success": "4111 1111 1111 1111", "failure": "4000 0000 0000 0002"},
        }

    def parse_webhook(self, body: bytes, headers: dict[str, str]) -> WebhookEvent:
        received = headers.get(self.SIGNATURE_HEADER, "")
        # compare_digest takes the same time whether 1 or 64 characters match,
        # so an attacker cannot guess the signature byte by byte from timing.
        if not received or not hmac.compare_digest(received, sign(body, self.secret)):
            raise InvalidSignatureError("Invalid webhook signature")
        try:
            data = json.loads(body)
            return WebhookEvent(
                event_id=str(data["id"]),
                type=str(data["type"]),
                provider_payment_id=str(data["data"]["provider_payment_id"]),
                amount=Decimal(str(data["data"]["amount"])),
                raw=data,
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise InvalidSignatureError("Malformed webhook payload") from exc

    def build_webhook(
        self, provider_payment_id: str, event_type: EventType, amount: Decimal
    ) -> tuple[bytes, dict[str, str]]:
        """What the gateway would send us. Used by the sandbox 'pay' endpoint and tests."""
        body = json.dumps(
            {
                "id": f"evt_{uuid.uuid4().hex[:20]}",
                "type": event_type,
                "data": {"provider_payment_id": provider_payment_id, "amount": f"{amount:.2f}"},
            }
        ).encode()
        return body, {self.SIGNATURE_HEADER: sign(body, self.secret)}

    def refund(self, provider_payment_id: str, charge_id: str | None, amount: Decimal) -> str:
        return f"mock_ref_{uuid.uuid4().hex[:20]}"


class PaymentGatewayError(Exception):
    """The gateway could not be reached or refused the request."""


class RazorpayProvider:
    """Razorpay in TEST MODE (https://razorpay.com/docs/payments/).

    Flow: we create a Razorpay Order (server-side, amount in paise) -> the browser opens
    Razorpay Checkout with that order id -> Razorpay calls our webhook with
    `payment.captured` / `payment.failed`, signed with HMAC-SHA256(webhook secret, raw body)
    in the X-Razorpay-Signature header.
    """

    name = "razorpay"
    SIGNATURE_HEADER = "x-razorpay-signature"
    EVENT_ID_HEADER = "x-razorpay-event-id"
    EVENTS = {"payment.captured": "payment.succeeded", "payment.failed": "payment.failed"}

    def __init__(self, key_id: str, key_secret: str, webhook_secret: str, api_url: str) -> None:
        self.key_id = key_id
        self.auth = (key_id, key_secret)  # HTTP Basic auth, as Razorpay requires
        self.webhook_secret = webhook_secret
        self.api_url = api_url.rstrip("/")

    def _post(self, path: str, body: dict) -> dict:
        try:
            res = httpx.post(f"{self.api_url}{path}", json=body, auth=self.auth, timeout=10)
            res.raise_for_status()
            return res.json()
        except httpx.HTTPError as exc:
            raise PaymentGatewayError(f"Razorpay request failed: {exc}") from exc

    @staticmethod
    def to_paise(amount: Decimal) -> int:
        return int((amount * 100).to_integral_value())

    def create_payment(self, amount: Decimal, currency: str, reference: str) -> tuple[str, dict]:
        order = self._post(
            "/orders",
            {"amount": self.to_paise(amount), "currency": currency, "receipt": reference},
        )
        return order["id"], {
            "provider": self.name,
            "key_id": self.key_id,  # public key, safe for the browser
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": currency,
            "name": "MealConnect",
            "description": reference.replace("_", " #"),
        }

    def parse_webhook(self, body: bytes, headers: dict[str, str]) -> WebhookEvent:
        received = headers.get(self.SIGNATURE_HEADER, "")
        if not received or not hmac.compare_digest(received, sign(body, self.webhook_secret)):
            raise InvalidSignatureError("Invalid webhook signature")
        try:
            data = json.loads(body)
            entity = data["payload"]["payment"]["entity"]
            return WebhookEvent(
                event_id=headers.get(self.EVENT_ID_HEADER) or f"{data['event']}:{entity['id']}",
                type=self.EVENTS.get(data["event"], data["event"]),
                provider_payment_id=entity["order_id"],
                amount=Decimal(entity["amount"]) / 100,
                raw=data,
                charge_id=entity["id"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise InvalidSignatureError("Malformed webhook payload") from exc

    def refund(self, provider_payment_id: str, charge_id: str | None, amount: Decimal) -> str:
        if not charge_id:
            raise PaymentGatewayError("Cannot refund: no Razorpay payment id recorded")
        refund = self._post(f"/payments/{charge_id}/refund", {"amount": self.to_paise(amount)})
        return refund["id"]


def get_provider() -> MockPaymentProvider | RazorpayProvider:
    if settings.PAYMENT_PROVIDER == "mock":
        return MockPaymentProvider(settings.PAYMENT_WEBHOOK_SECRET)
    if settings.PAYMENT_PROVIDER == "razorpay":
        if not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET):
            raise RuntimeError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set")
        return RazorpayProvider(
            settings.RAZORPAY_KEY_ID,
            settings.RAZORPAY_KEY_SECRET,
            settings.PAYMENT_WEBHOOK_SECRET,
            settings.RAZORPAY_API_URL,
        )
    raise RuntimeError(f"Unknown payment provider {settings.PAYMENT_PROVIDER}")
