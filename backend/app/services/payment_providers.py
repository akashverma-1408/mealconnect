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

from app.core.config import settings

EventType = Literal["payment.succeeded", "payment.failed"]


@dataclass(frozen=True)
class WebhookEvent:
    event_id: str
    type: str
    provider_payment_id: str
    amount: Decimal
    raw: dict


class InvalidSignatureError(Exception):
    pass


class PaymentProvider(Protocol):
    name: str

    def create_payment(self, amount: Decimal, currency: str, reference: str) -> tuple[str, dict]:
        """Return (provider_payment_id, data the frontend needs to show checkout)."""

    def parse_webhook(self, body: bytes, headers: dict[str, str]) -> WebhookEvent:
        """Verify the signature and parse the event, or raise InvalidSignatureError."""

    def refund(self, provider_payment_id: str, amount: Decimal) -> str:
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

    def refund(self, provider_payment_id: str, amount: Decimal) -> str:
        return f"mock_ref_{uuid.uuid4().hex[:20]}"


def get_provider() -> MockPaymentProvider:
    if settings.PAYMENT_PROVIDER == "mock":
        return MockPaymentProvider(settings.PAYMENT_WEBHOOK_SECRET)
    raise RuntimeError(f"Unknown payment provider {settings.PAYMENT_PROVIDER}")
