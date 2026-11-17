"""Customer endpoints: cart, orders, payments, reviews, complaints."""

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import CustomerUser, DbSession, Pagination
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.order import OrderStatus
from app.schemas.common import Page, errors
from app.schemas.engagement import ComplaintCreate, ComplaintRead, ReviewCreate, ReviewRead
from app.schemas.order import (
    CancelRequest,
    CartItemAdd,
    CartItemUpdate,
    CartRead,
    CheckoutResponse,
    OrderCreate,
    OrderRead,
    OrderSummary,
    PaymentRead,
    WebhookAck,
)
from app.services import cart_service, engagement_service, order_service, payment_service

cart = APIRouter(prefix="/cart", tags=["Cart"], responses=errors(401, 403))
orders = APIRouter(prefix="/orders", tags=["Orders"], responses=errors(401, 403))
payments = APIRouter(prefix="/payments", tags=["Payments"])
complaints = APIRouter(prefix="/complaints", tags=["Complaints"], responses=errors(401, 403))


# ================================================================== cart
@cart.get("", response_model=CartRead, summary="My cart with live prices and totals")
def get_cart(user: CustomerUser, db: DbSession) -> CartRead:
    return cart_service.get_cart(db, user)


@cart.post(
    "/items",
    response_model=CartRead,
    summary="Add an item (one restaurant per cart)",
    responses=errors(400, 404, 409, 422),
)
def add_to_cart(data: CartItemAdd, user: CustomerUser, db: DbSession) -> CartRead:
    return cart_service.add_item(db, user, data.menu_item_id, data.quantity)


@cart.patch(
    "/items/{menu_item_id}",
    response_model=CartRead,
    summary="Change quantity",
    responses=errors(404, 422),
)
def update_cart_item(
    menu_item_id: int, data: CartItemUpdate, user: CustomerUser, db: DbSession
) -> CartRead:
    return cart_service.update_quantity(db, user, menu_item_id, data.quantity)


@cart.delete(
    "/items/{menu_item_id}",
    response_model=CartRead,
    summary="Remove an item",
    responses=errors(404),
)
def remove_cart_item(menu_item_id: int, user: CustomerUser, db: DbSession) -> CartRead:
    return cart_service.remove_item(db, user, menu_item_id)


@cart.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Empty the cart")
def clear_cart(user: CustomerUser, db: DbSession) -> Response:
    cart_service.clear(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ================================================================== orders
@orders.post(
    "",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order from the cart (status PENDING_PAYMENT)",
    responses=errors(400, 404, 422),
)
def place_order(data: OrderCreate, user: CustomerUser, db: DbSession) -> OrderRead:
    return order_service.to_read(order_service.place_order(db, user, data))


@orders.get("", response_model=Page[OrderSummary], summary="My orders, newest first")
def list_orders(
    user: CustomerUser, db: DbSession, pagination: Pagination, status: OrderStatus | None = None
) -> Page[OrderSummary]:
    return order_service.list_customer_orders(db, user, status, pagination.page, pagination.size)


@orders.get(
    "/{order_id}",
    response_model=OrderRead,
    summary="Order details with status timeline (for tracking)",
    responses=errors(404),
)
def get_order(order_id: int, user: CustomerUser, db: DbSession) -> OrderRead:
    return order_service.to_read(order_service.get_customer_order(db, user, order_id))


@orders.post(
    "/{order_id}/cancel",
    response_model=OrderRead,
    summary="Cancel before the restaurant accepts (refund if paid)",
    responses=errors(400, 404),
)
def cancel_order(
    order_id: int, user: CustomerUser, db: DbSession, data: CancelRequest | None = None
) -> OrderRead:
    reason = data.reason if data else None
    return order_service.to_read(order_service.cancel_by_customer(db, user, order_id, reason))


@orders.post(
    "/{order_id}/review",
    response_model=ReviewRead,
    status_code=status.HTTP_201_CREATED,
    summary="Rate a delivered order (once)",
    responses=errors(400, 404, 409, 422),
)
def review_order(
    order_id: int, data: ReviewCreate, user: CustomerUser, db: DbSession
) -> ReviewRead:
    return engagement_service.create_review(db, user, order_id, data)


# ================================================================== payments
@payments.post(
    "/orders/{order_id}/checkout",
    response_model=CheckoutResponse,
    summary="Start payment for a PENDING_PAYMENT order",
    responses=errors(401, 403, 404, 409),
)
def checkout(order_id: int, user: CustomerUser, db: DbSession) -> CheckoutResponse:
    return payment_service.create_checkout(db, user, order_id)


@payments.get(
    "/orders/{order_id}",
    response_model=PaymentRead,
    summary="Payment status of my order",
    responses=errors(401, 403, 404),
)
def get_payment(order_id: int, user: CustomerUser, db: DbSession) -> PaymentRead:
    return PaymentRead.model_validate(payment_service.get_for_order(db, user, order_id))


@payments.post(
    "/webhook",
    response_model=WebhookAck,
    summary="Payment gateway webhook (HMAC-signed, idempotent)",
    responses=errors(400),
)
async def payment_webhook(request: Request, db: DbSession) -> WebhookAck:
    # The raw bytes are needed: the signature is computed over the exact body sent.
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    result = await run_in_threadpool(payment_service.handle_webhook, db, body, headers)
    return WebhookAck(status=result)


@payments.post(
    "/sandbox/orders/{order_id}/pay",
    response_model=WebhookAck,
    summary="SANDBOX ONLY: simulate the gateway completing or declining the payment",
    responses=errors(400, 401, 403, 404),
)
def sandbox_pay(
    order_id: int,
    user: CustomerUser,
    db: DbSession,
    outcome: Literal["success", "failure"] = "success",
) -> WebhookAck:
    if not settings.sandbox_payments_enabled:
        raise NotFoundError("Not found")
    event = "payment.succeeded" if outcome == "success" else "payment.failed"
    return WebhookAck(status=payment_service.simulate_gateway(db, user, order_id, event))


# ================================================================== complaints
@complaints.post(
    "",
    response_model=ComplaintRead,
    status_code=status.HTTP_201_CREATED,
    summary="Raise a complaint (optionally about an order)",
    responses=errors(404, 422),
)
def create_complaint(data: ComplaintCreate, user: CustomerUser, db: DbSession) -> ComplaintRead:
    return ComplaintRead.model_validate(engagement_service.create_complaint(db, user, data))


@complaints.get("", response_model=Page[ComplaintRead], summary="My complaints")
def my_complaints(user: CustomerUser, db: DbSession, pagination: Pagination) -> Page[ComplaintRead]:
    return engagement_service.list_my_complaints(db, user, pagination.page, pagination.size)
