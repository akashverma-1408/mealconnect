"""Payments: checkout sessions, verified + idempotent webhooks, refunds."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    GatewayUnavailableError,
    NotFoundError,
)
from app.core.jobs import enqueue_after_commit
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentEvent, PaymentStatus
from app.models.user import User
from app.schemas.order import CheckoutResponse
from app.services import order_service
from app.services.payment_providers import (
    EventType,
    InvalidSignatureError,
    PaymentGatewayError,
    WebhookEvent,
    get_provider,
)

logger = logging.getLogger(__name__)


def _customer_order_locked(db: Session, user: User, order_id: int) -> Order:
    order = db.scalar(
        select(Order).where(Order.id == order_id, Order.customer_id == user.id).with_for_update()
    )
    if order is None:
        raise NotFoundError("Order not found", code="ORDER_NOT_FOUND")
    return order


def create_checkout(db: Session, user: User, order_id: int) -> CheckoutResponse:
    order = _customer_order_locked(db, user, order_id)
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise ConflictError(f"Order is {order.status} and cannot be paid", code="ORDER_NOT_PAYABLE")
    provider = get_provider()
    payment = order.payment
    if payment is None:
        payment = Payment(
            order_id=order.id, provider=provider.name, amount=order.total,
            currency=settings.CURRENCY, status=PaymentStatus.PENDING,
        )  # fmt: skip
        db.add(payment)
    elif payment.status == PaymentStatus.SUCCEEDED:
        raise ConflictError("Order is already paid", code="ALREADY_PAID")

    # A new gateway payment for every attempt (retry after failure is allowed).
    try:
        provider_payment_id, checkout = provider.create_payment(
            order.total, settings.CURRENCY, reference=f"order_{order.id}"
        )
    except PaymentGatewayError as exc:
        logger.error("payment gateway error", extra={"order_id": order.id}, exc_info=True)
        raise GatewayUnavailableError("Payment gateway unavailable, please retry") from exc
    payment.provider_payment_id = provider_payment_id
    payment.status = PaymentStatus.PENDING
    payment.failure_reason = None
    db.commit()
    return CheckoutResponse(
        payment_id=payment.id, order_id=order.id, provider=payment.provider,
        provider_payment_id=provider_payment_id, amount=payment.amount,
        currency=payment.currency, status=payment.status, checkout=checkout,
    )  # fmt: skip


def handle_webhook(db: Session, body: bytes, headers: dict[str, str]) -> str:
    """Process one gateway webhook. Returns 'processed', 'duplicate' or 'ignored'."""
    provider = get_provider()
    try:
        event = provider.parse_webhook(body, headers)
    except InvalidSignatureError as exc:
        logger.warning("rejected payment webhook: %s", exc)
        raise BadRequestError(str(exc), code="INVALID_SIGNATURE") from exc

    # Idempotency: INSERT ... ON CONFLICT DO NOTHING. If the event id was seen before,
    # nothing is inserted and we stop — gateways retry, and that must be harmless.
    inserted_id = db.scalar(
        insert(PaymentEvent)
        .values(provider_event_id=event.event_id, event_type=event.type, payload=event.raw)
        .on_conflict_do_nothing(index_elements=["provider_event_id"])
        .returning(PaymentEvent.id)
    )
    if inserted_id is None:
        db.rollback()
        logger.info("duplicate payment webhook ignored", extra={"event_id": event.event_id})
        return "duplicate"

    payment = db.scalar(
        select(Payment)
        .where(Payment.provider_payment_id == event.provider_payment_id)
        .with_for_update()
    )
    record = db.get(PaymentEvent, inserted_id)
    result = "processed"
    if payment is None:
        logger.warning("webhook for unknown payment", extra={"event_id": event.event_id})
        result = "ignored"
    else:
        record.payment_id = payment.id
        _apply_event(db, payment, event)
    record.processed_at = datetime.now(UTC)
    db.commit()
    return result


def _apply_event(db: Session, payment: Payment, event: WebhookEvent) -> None:
    if event.amount != payment.amount:  # never trust an amount we did not ask for
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = f"Amount mismatch: expected {payment.amount}, got {event.amount}"
        logger.error("payment amount mismatch", extra={"payment_id": payment.id})
        return

    if event.type == "payment.failed":
        if payment.status == PaymentStatus.PENDING:
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = "Payment declined"
        return
    if event.type != "payment.succeeded" or payment.status == PaymentStatus.SUCCEEDED:
        return

    payment.status = PaymentStatus.SUCCEEDED
    payment.failure_reason = None
    payment.provider_charge_id = event.charge_id
    order = db.scalar(select(Order).where(Order.id == payment.order_id).with_for_update())
    if order.status == OrderStatus.PENDING_PAYMENT:
        order_service.transition(db, order, OrderStatus.PLACED, "system", None, "Payment received")
    else:
        # Paid after the order was cancelled -> give the money back.
        refund(db, payment)
    logger.info("payment succeeded", extra={"payment_id": payment.id, "order_id": order.id})


def refund(db: Session, payment: Payment) -> None:
    """Refund a successful payment. Caller commits.

    If the gateway is unreachable, the order change still goes through and the refund
    is retried by the background worker (job "refund_payment").
    """
    if payment.status != PaymentStatus.SUCCEEDED:
        return
    provider = get_provider()
    try:
        payment.provider_refund_id = provider.refund(
            payment.provider_payment_id, payment.provider_charge_id, payment.amount
        )
    except PaymentGatewayError:
        logger.error("refund failed; queued for retry", extra={"payment_id": payment.id})
        payment.failure_reason = "Refund pending: gateway unavailable"
        enqueue_after_commit(db, "refund_payment", {"payment_id": payment.id})
        return
    payment.status = PaymentStatus.REFUNDED
    payment.refunded_at = datetime.now(UTC)
    payment.failure_reason = None
    logger.info("payment refunded", extra={"payment_id": payment.id})


def retry_refund(db: Session, payment_id: int) -> None:
    """Worker job: try a pending refund again (raises so the worker retries/dead-letters)."""
    payment = db.get(Payment, payment_id, with_for_update=True)
    if payment is None or payment.status != PaymentStatus.SUCCEEDED:
        return  # already refunded (idempotent) or nothing to do
    provider = get_provider()
    payment.provider_refund_id = provider.refund(
        payment.provider_payment_id, payment.provider_charge_id, payment.amount
    )
    payment.status = PaymentStatus.REFUNDED
    payment.refunded_at = datetime.now(UTC)
    payment.failure_reason = None
    db.commit()


def get_for_order(db: Session, user: User, order_id: int) -> Payment:
    payment = db.scalar(
        select(Payment)
        .join(Order, Payment.order_id == Order.id)
        .where(Order.id == order_id, Order.customer_id == user.id)
    )
    if payment is None:
        raise NotFoundError("No payment for this order yet", code="PAYMENT_NOT_FOUND")
    return payment


def simulate_gateway(db: Session, user: User, order_id: int, outcome: EventType) -> str:
    """Sandbox only: act as the gateway and send ourselves a correctly signed webhook.

    It goes through exactly the same verification path as a real webhook.
    """
    payment = get_for_order(db, user, order_id)
    if payment.provider_payment_id is None:
        raise BadRequestError("Start checkout first", code="CHECKOUT_NOT_STARTED")
    provider = get_provider()
    body, headers = provider.build_webhook(payment.provider_payment_id, outcome, payment.amount)
    return handle_webhook(db, body, headers)
