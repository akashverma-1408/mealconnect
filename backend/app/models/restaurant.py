"""Restaurants, menu categories and menu items."""

import enum
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin, pg_enum
from app.models.user import User


class RestaurantStatus(enum.StrEnum):
    PENDING = "pending"  # registered, waiting for admin approval
    APPROVED = "approved"  # visible to customers
    REJECTED = "rejected"
    SUSPENDED = "suspended"  # hidden from customers by an admin


MONEY = Numeric(10, 2)  # exact decimal: never use FLOAT for money


class Restaurant(IdMixin, TimestampMixin, Base):
    __tablename__ = "restaurants"

    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    cuisine: Mapped[str] = mapped_column(String(60), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    image_url: Mapped[str | None] = mapped_column(String(500))
    is_veg_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    opens_at: Mapped[time | None] = mapped_column(Time)
    closes_at: Mapped[time | None] = mapped_column(Time)
    status: Mapped[RestaurantStatus] = mapped_column(
        pg_enum(RestaurantStatus, "restaurant_status"),
        nullable=False,
        server_default=RestaurantStatus.PENDING.value,
    )
    status_reason: Mapped[str | None] = mapped_column(Text)
    delivery_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    min_order_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    # Denormalized for fast sorting; updated in the same transaction as each new review.
    avg_rating: Mapped[Decimal] = mapped_column(Numeric(2, 1), nullable=False, server_default="0")
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped[User] = relationship()
    categories: Mapped[list["MenuCategory"]] = relationship(
        back_populates="restaurant", order_by="MenuCategory.sort_order, MenuCategory.id"
    )

    __table_args__ = (
        CheckConstraint("delivery_fee >= 0", name="delivery_fee_non_negative"),
        CheckConstraint("min_order_amount >= 0", name="min_order_non_negative"),
        CheckConstraint("avg_rating BETWEEN 0 AND 5", name="avg_rating_range"),
        CheckConstraint("rating_count >= 0", name="rating_count_non_negative"),
        Index("ix_restaurants_status_city", "status", "city"),
        Index("ix_restaurants_avg_rating", "avg_rating"),
        # Trigram GIN index: makes `name ILIKE '%piz%'` fast even with many rows.
        Index(
            "ix_restaurants_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )


class MenuCategory(IdMixin, TimestampMixin, Base):
    __tablename__ = "menu_categories"

    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    restaurant: Mapped[Restaurant] = relationship(back_populates="categories")

    __table_args__ = (UniqueConstraint("restaurant_id", "name"),)


class MenuItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "menu_items"

    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("menu_categories.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    is_veg: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    image_url: Mapped[str | None] = mapped_column(String(500))
    # Soft delete: past orders reference this row, so it is hidden, never removed.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    restaurant: Mapped[Restaurant] = relationship()
    category: Mapped[MenuCategory | None] = relationship()

    __table_args__ = (
        CheckConstraint("price > 0", name="price_positive"),
        Index(
            "ix_menu_items_restaurant_available",
            "restaurant_id",
            "is_available",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_menu_items_category_id", "category_id"),
        Index(
            "ix_menu_items_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )
