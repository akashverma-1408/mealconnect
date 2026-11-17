"""Cart, order and payment schemas."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.order import OrderStatus
from app.models.payment import PaymentStatus
from app.schemas.common import Money
from app.schemas.restaurant import RestaurantRef

Quantity = Annotated[int, Field(ge=1, le=50)]


# ------------------------------------------------------------------ cart
class CartItemAdd(BaseModel):
    menu_item_id: int
    quantity: Quantity = 1


class CartItemUpdate(BaseModel):
    quantity: Quantity


class CartLine(BaseModel):
    menu_item_id: int
    name: str
    unit_price: Money
    quantity: int
    line_total: Money
    is_veg: bool
    is_available: bool  # False if the item was disabled after being added


class CartRead(BaseModel):
    restaurant: RestaurantRef | None
    items: list[CartLine]
    item_count: int
    subtotal: Money
    delivery_fee: Money
    tax: Money
    total: Money
    min_order_amount: Money
    can_checkout: bool
    problems: list[str]  # human-readable reasons why checkout is blocked


# ------------------------------------------------------------------ orders
class OrderCreate(BaseModel):
    address_id: int
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    menu_item_id: int
    item_name: str
    unit_price: Money
    quantity: int
    line_total: Money


class StatusChange(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: OrderStatus | None
    to_status: OrderStatus
    note: str | None
    created_at: datetime


class OrderSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: OrderStatus
    restaurant: RestaurantRef
    total: Money
    item_count: int
    created_at: datetime


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: OrderStatus
    customer_id: int
    restaurant: RestaurantRef
    items: list[OrderItemRead]
    subtotal: Money
    delivery_fee: Money
    tax: Money
    total: Money
    delivery_address: dict[str, Any]
    notes: str | None
    rejection_reason: str | None
    payment_status: PaymentStatus | None
    history: list[StatusChange]
    created_at: datetime
    updated_at: datetime


class CancelRequest(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None


class RejectRequest(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]


class OwnerStatusUpdate(BaseModel):
    status: Literal["PREPARING", "OUT_FOR_DELIVERY", "DELIVERED"]


# ------------------------------------------------------------------ payments
class CheckoutResponse(BaseModel):
    payment_id: int
    order_id: int
    provider: str
    provider_payment_id: str
    amount: Money
    currency: str
    status: PaymentStatus
    checkout: dict[str, Any]  # provider-specific data the frontend needs


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    provider: str
    provider_payment_id: str | None
    amount: Money
    currency: str
    status: PaymentStatus
    failure_reason: str | None
    refunded_at: datetime | None
    created_at: datetime


class WebhookAck(BaseModel):
    status: Literal["processed", "duplicate", "ignored"]
