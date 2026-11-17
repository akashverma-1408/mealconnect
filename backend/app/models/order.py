"""Cart, orders, order items and the order status timeline."""

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin, pg_enum
from app.models.restaurant import MONEY, MenuItem, Restaurant
from app.models.user import User

if TYPE_CHECKING:
    from app.models.payment import Payment


class OrderStatus(enum.StrEnum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PLACED = "PLACED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PREPARING = "PREPARING"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


ORDER_STATUS_ENUM = pg_enum(OrderStatus, "order_status")


class CartItem(TimestampMixin, Base):
    """Server-side cart: one row per (customer, menu item)."""

    __tablename__ = "cart_items"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    menu_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("menu_items.id", ondelete="CASCADE"), primary_key=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    menu_item: Mapped[MenuItem] = relationship()

    __table_args__ = (
        CheckConstraint("quantity BETWEEN 1 AND 50", name="quantity_range"),
        Index("ix_cart_items_menu_item_id", "menu_item_id"),
    )


class Order(IdMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(
        ORDER_STATUS_ENUM, nullable=False, server_default=OrderStatus.PENDING_PAYMENT.value
    )
    subtotal: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    delivery_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    tax: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # Snapshot of the address at checkout: editing/deleting the address later
    # must not change where a past order was delivered.
    delivery_address: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    customer: Mapped[User] = relationship()
    restaurant: Mapped[Restaurant] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )
    history: Mapped[list["OrderStatusHistory"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderStatusHistory.id"
    )
    payment: Mapped["Payment | None"] = relationship(back_populates="order", uselist=False)

    __table_args__ = (
        CheckConstraint(
            "subtotal >= 0 AND delivery_fee >= 0 AND tax >= 0", name="amounts_non_negative"
        ),
        CheckConstraint("total = subtotal + delivery_fee + tax", name="total_matches"),
        Index("ix_orders_customer_id_created_at", "customer_id", "created_at"),
        Index("ix_orders_restaurant_status_created", "restaurant_id", "status", "created_at"),
        Index("ix_orders_status_created_at", "status", "created_at"),
    )


class OrderItem(IdMixin, Base):
    __tablename__ = "order_items"

    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    menu_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("menu_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Price and name are copied at order time (menu prices change later).
    item_name: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("line_total = unit_price * quantity", name="line_total_matches"),
    )


class OrderStatusHistory(IdMixin, Base):
    """Append-only timeline used for order tracking."""

    __tablename__ = "order_status_history"

    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[OrderStatus | None] = mapped_column(ORDER_STATUS_ENUM)
    to_status: Mapped[OrderStatus] = mapped_column(ORDER_STATUS_ENUM, nullable=False)
    # NULL = changed by the system (e.g. payment webhook).
    changed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    order: Mapped[Order] = relationship(back_populates="history")

    __table_args__ = (Index("ix_order_status_history_order_created", "order_id", "created_at"),)
