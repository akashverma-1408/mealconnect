"""Orders: checkout, the status state machine, and customer/owner/admin views."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import Select, delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.core.jobs import enqueue_after_commit
from app.models.order import CartItem, Order, OrderItem, OrderStatus, OrderStatusHistory
from app.models.payment import PaymentStatus
from app.models.restaurant import Restaurant, RestaurantStatus
from app.models.user import User
from app.schemas.common import Page
from app.schemas.order import OrderCreate, OrderRead, OrderSummary
from app.schemas.restaurant import RestaurantRef
from app.services import cart_service, user_service
from app.services.common import audit, calc_totals, money, notify, paginate

S = OrderStatus
Actor = Literal["customer", "restaurant_owner", "admin", "system"]

# ------------------------------------------------------------------ state machine
# (from, to) -> who may make that move. Anything not listed is an invalid transition.
TRANSITIONS: dict[tuple[OrderStatus, OrderStatus], set[str]] = {
    (S.PENDING_PAYMENT, S.PLACED): {"system"},  # only a verified payment webhook
    (S.PENDING_PAYMENT, S.CANCELLED): {"customer", "admin", "system"},
    (S.PLACED, S.ACCEPTED): {"restaurant_owner"},
    (S.PLACED, S.REJECTED): {"restaurant_owner"},
    (S.PLACED, S.CANCELLED): {"customer", "admin"},
    (S.ACCEPTED, S.PREPARING): {"restaurant_owner"},
    (S.PREPARING, S.OUT_FOR_DELIVERY): {"restaurant_owner"},
    (S.OUT_FOR_DELIVERY, S.DELIVERED): {"restaurant_owner"},
    # Admins can force-cancel anything not yet finished.
    (S.ACCEPTED, S.CANCELLED): {"admin"},
    (S.PREPARING, S.CANCELLED): {"admin"},
    (S.OUT_FOR_DELIVERY, S.CANCELLED): {"admin"},
}
FINAL = {S.DELIVERED, S.REJECTED, S.CANCELLED}
# Orders that count as revenue: paid and not refunded.
REVENUE_STATUSES = (S.PLACED, S.ACCEPTED, S.PREPARING, S.OUT_FOR_DELIVERY, S.DELIVERED)

CUSTOMER_MESSAGES = {
    S.PLACED: ("Order placed", "Payment received. Waiting for the restaurant to accept."),
    S.ACCEPTED: ("Order accepted", "The restaurant accepted your order."),
    S.REJECTED: (
        "Order rejected",
        "The restaurant could not take your order. A refund is on its way.",
    ),  # noqa: E501
    S.PREPARING: ("Being prepared", "Your food is being prepared."),
    S.OUT_FOR_DELIVERY: ("Out for delivery", "Your order is on its way."),
    S.DELIVERED: ("Delivered", "Enjoy your meal! You can now rate the restaurant."),
    S.CANCELLED: ("Order cancelled", "Your order was cancelled."),
}


def transition(
    db: Session,
    order: Order,
    to: OrderStatus,
    actor: Actor,
    actor_id: int | None,
    note: str | None = None,
) -> None:
    """Validate and apply one status change. The caller commits.

    Always call with the order row locked (SELECT ... FOR UPDATE) so two requests
    cannot both move the same order.
    """
    allowed = TRANSITIONS.get((order.status, to))
    if allowed is None:
        raise BadRequestError(
            f"Cannot move order from {order.status} to {to}",
            code="ORDER_INVALID_TRANSITION",
            details={"current_status": order.status},
        )
    if actor not in allowed:
        raise ForbiddenError(
            f"You cannot move this order to {to}", code="ORDER_TRANSITION_FORBIDDEN"
        )

    db.add(
        OrderStatusHistory(
            order_id=order.id, from_status=order.status, to_status=to,
            changed_by=actor_id, note=note,
        )
    )  # fmt: skip
    previous = order.status
    order.status = to

    # E-mail goes through the background worker, and only if this transaction commits.
    enqueue_after_commit(db, "order_status_email", {"order_id": order.id, "status": to.value})

    title, body = CUSTOMER_MESSAGES[to]
    if not (to == S.CANCELLED and actor == "customer"):
        notify(db, order.customer_id, f"order.{to.lower()}", title, body, {"order_id": order.id})
    if to == S.PLACED or (to == S.CANCELLED and previous != S.PENDING_PAYMENT):
        verb = "New order received" if to == S.PLACED else "Order cancelled"
        notify(
            db, order.restaurant.owner_id, f"owner.order.{to.lower()}", verb,
            f"Order #{order.id} — total {order.total:.2f}", {"order_id": order.id},
        )  # fmt: skip

    # Money back if a paid order ends without delivery.
    payment = order.payment
    if to in (S.REJECTED, S.CANCELLED) and payment and payment.status == PaymentStatus.SUCCEEDED:
        from app.services import payment_service  # local import avoids a cycle

        payment_service.refund(db, payment)


# ------------------------------------------------------------------ checkout
def place_order(db: Session, user: User, data: OrderCreate) -> Order:
    """Create an order from the cart in ONE transaction (all-or-nothing)."""
    address = user_service.get_address(db, user, data.address_id)
    rows = cart_service.load_cart_rows(db, user, lock=True)
    if not rows:
        raise BadRequestError("Your cart is empty", code="CART_EMPTY")

    restaurant = rows[0].menu_item.restaurant
    if restaurant.status != RestaurantStatus.APPROVED or restaurant.deleted_at is not None:
        raise BadRequestError("This restaurant is not available", code="RESTAURANT_UNAVAILABLE")
    if not restaurant.is_open:
        raise BadRequestError("This restaurant is currently closed", code="RESTAURANT_CLOSED")

    unavailable = [
        r.menu_item.name for r in rows if not cart_service.item_is_orderable(r.menu_item)
    ]
    if unavailable:
        raise BadRequestError(
            "Some items are no longer available", code="ITEM_UNAVAILABLE", details=unavailable
        )

    # Prices are re-read from the database now — never trusted from the client (CUS-6).
    subtotal = money(sum((r.menu_item.price * r.quantity for r in rows), start=Decimal("0")))
    if subtotal < restaurant.min_order_amount:
        raise BadRequestError(
            f"Minimum order amount is {restaurant.min_order_amount:.2f}",
            code="MIN_ORDER_NOT_MET",
            details={"min_order_amount": f"{restaurant.min_order_amount:.2f}"},
        )
    tax, total = calc_totals(subtotal, restaurant.delivery_fee)

    order = Order(
        customer_id=user.id,
        restaurant_id=restaurant.id,
        status=S.PENDING_PAYMENT,
        subtotal=subtotal,
        delivery_fee=restaurant.delivery_fee,
        tax=tax,
        total=total,
        notes=data.notes,
        delivery_address={
            "label": address.label, "line1": address.line1, "line2": address.line2,
            "city": address.city, "state": address.state, "postal_code": address.postal_code,
        },
        items=[
            OrderItem(
                menu_item_id=r.menu_item.id, item_name=r.menu_item.name,
                unit_price=r.menu_item.price, quantity=r.quantity,
                line_total=money(r.menu_item.price * r.quantity),
            )
            for r in rows
        ],
    )  # fmt: skip
    db.add(order)
    db.flush()  # assigns order.id
    db.add(OrderStatusHistory(order_id=order.id, to_status=S.PENDING_PAYMENT, changed_by=user.id))
    db.execute(delete(CartItem).where(CartItem.user_id == user.id))
    db.commit()
    return load_order(db, order.id)


# ------------------------------------------------------------------ reading
def load_order(db: Session, order_id: int) -> Order:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.items),
            selectinload(Order.history),
            selectinload(Order.restaurant),
            selectinload(Order.payment),
        )
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise NotFoundError("Order not found", code="ORDER_NOT_FOUND")
    return order


def to_read(order: Order) -> OrderRead:
    return OrderRead(
        id=order.id,
        status=order.status,
        customer_id=order.customer_id,
        restaurant=RestaurantRef.model_validate(order.restaurant),
        items=order.items,
        subtotal=order.subtotal,
        delivery_fee=order.delivery_fee,
        tax=order.tax,
        total=order.total,
        delivery_address=order.delivery_address,
        notes=order.notes,
        rejection_reason=order.rejection_reason,
        payment_status=order.payment.status if order.payment else None,
        history=order.history,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def to_summary(order: Order) -> OrderSummary:
    return OrderSummary(
        id=order.id,
        status=order.status,
        restaurant=RestaurantRef.model_validate(order.restaurant),
        total=order.total,
        item_count=sum(i.quantity for i in order.items),
        created_at=order.created_at,
    )


def _list_stmt() -> Select:
    return select(Order).options(selectinload(Order.items), selectinload(Order.restaurant))


def _date_filter(stmt: Select, date_from: date | None, date_to: date | None) -> Select:
    if date_from:
        stmt = stmt.where(Order.created_at >= datetime.combine(date_from, time.min))
    if date_to:  # inclusive end date
        stmt = stmt.where(
            Order.created_at < datetime.combine(date_to + timedelta(days=1), time.min)
        )
    return stmt


def _locked(db: Session, stmt: Select) -> Order:
    order = db.scalar(stmt.with_for_update(of=Order))
    if order is None:
        raise NotFoundError("Order not found", code="ORDER_NOT_FOUND")
    return order


# ------------------------------------------------------------------ customer
def list_customer_orders(
    db: Session, user: User, status: OrderStatus | None, page: int, size: int
) -> Page[OrderSummary]:
    stmt = _list_stmt().where(Order.customer_id == user.id)
    if status:
        stmt = stmt.where(Order.status == status)
    return paginate(
        db, stmt.order_by(Order.created_at.desc(), Order.id.desc()), page, size, to_summary
    )  # noqa: E501


def get_customer_order(db: Session, user: User, order_id: int) -> Order:
    order = load_order(db, order_id)
    if order.customer_id != user.id:
        raise NotFoundError("Order not found", code="ORDER_NOT_FOUND")
    return order


def cancel_by_customer(db: Session, user: User, order_id: int, reason: str | None) -> Order:
    order = _locked(db, select(Order).where(Order.id == order_id, Order.customer_id == user.id))
    transition(db, order, S.CANCELLED, "customer", user.id, reason)
    db.commit()
    return load_order(db, order.id)


# ------------------------------------------------------------------ restaurant owner
def _owner_order_stmt(owner: User, order_id: int) -> Select:
    # Owners never see unpaid (PENDING_PAYMENT) orders.
    return (
        select(Order)
        .join(Restaurant, Order.restaurant_id == Restaurant.id)
        .where(
            Order.id == order_id,
            Restaurant.owner_id == owner.id,
            Order.status != S.PENDING_PAYMENT,
        )
    )


def list_restaurant_orders(
    db: Session,
    owner: User,
    restaurant_id: int,
    status: OrderStatus | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    size: int,
) -> Page[OrderSummary]:
    from app.services.restaurant_service import get_owned

    get_owned(db, owner, restaurant_id)
    stmt = _list_stmt().where(
        Order.restaurant_id == restaurant_id, Order.status != S.PENDING_PAYMENT
    )
    if status:
        stmt = stmt.where(Order.status == status)
    stmt = _date_filter(stmt, date_from, date_to)
    return paginate(
        db, stmt.order_by(Order.created_at.desc(), Order.id.desc()), page, size, to_summary
    )  # noqa: E501


def get_owner_order(db: Session, owner: User, order_id: int) -> Order:
    order_id_found = db.scalar(_owner_order_stmt(owner, order_id).with_only_columns(Order.id))
    if order_id_found is None:
        raise NotFoundError("Order not found", code="ORDER_NOT_FOUND")
    return load_order(db, order_id)


def owner_transition(
    db: Session, owner: User, order_id: int, to: OrderStatus, reason: str | None = None
) -> Order:
    order = _locked(db, _owner_order_stmt(owner, order_id))
    if to == S.REJECTED:
        order.rejection_reason = reason
    transition(db, order, to, "restaurant_owner", owner.id, reason)
    db.commit()
    return load_order(db, order.id)


# ------------------------------------------------------------------ admin
def list_all_orders(
    db: Session,
    status: OrderStatus | None,
    restaurant_id: int | None,
    customer_id: int | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    size: int,
) -> Page[OrderSummary]:
    stmt = _list_stmt()
    if status:
        stmt = stmt.where(Order.status == status)
    if restaurant_id:
        stmt = stmt.where(Order.restaurant_id == restaurant_id)
    if customer_id:
        stmt = stmt.where(Order.customer_id == customer_id)
    stmt = _date_filter(stmt, date_from, date_to)
    return paginate(
        db, stmt.order_by(Order.created_at.desc(), Order.id.desc()), page, size, to_summary
    )  # noqa: E501


def admin_cancel(db: Session, admin: User, order_id: int, reason: str | None) -> Order:
    order = _locked(db, select(Order).where(Order.id == order_id))
    previous = order.status
    transition(db, order, S.CANCELLED, "admin", admin.id, reason)
    audit(db, admin.id, "order.force_cancel", "order", order.id,
          {"from_status": previous, "reason": reason})  # fmt: skip
    db.commit()
    return load_order(db, order.id)
