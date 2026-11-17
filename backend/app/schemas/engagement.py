"""Reviews, complaints, notifications, admin and analytics schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.engagement import ComplaintStatus
from app.models.order import OrderStatus
from app.models.restaurant import RestaurantStatus
from app.models.user import UserStatus
from app.schemas.common import Money


# ------------------------------------------------------------------ reviews
class ReviewCreate(BaseModel):
    rating: Annotated[int, Field(ge=1, le=5)]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


class ReviewRead(BaseModel):
    id: int
    order_id: int
    restaurant_id: int
    rating: int
    comment: str | None
    author_name: str  # first name only, for privacy
    created_at: datetime


# ------------------------------------------------------------------ complaints
class ComplaintCreate(BaseModel):
    order_id: int | None = None
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=150)]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)
    ]


class ComplaintRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int | None
    restaurant_id: int | None
    raised_by: int
    assigned_admin_id: int | None
    subject: str
    description: str
    status: ComplaintStatus
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime


class ComplaintUpdate(BaseModel):
    status: ComplaintStatus | None = None
    assigned_admin_id: int | None = None
    resolution_note: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]
        | None
    ) = None


# ------------------------------------------------------------------ notifications
class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    body: str
    data: dict[str, Any] | None
    is_read: bool
    created_at: datetime


class ReadAllResult(BaseModel):
    updated: int


# ------------------------------------------------------------------ admin
class UserStatusUpdate(BaseModel):
    status: UserStatus
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class RestaurantStatusUpdate(BaseModel):
    status: RestaurantStatus
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int | None
    action: str
    entity_type: str
    entity_id: int
    details: dict[str, Any] | None
    created_at: datetime


# ------------------------------------------------------------------ analytics
class DailyPoint(BaseModel):
    date: date
    orders: int
    revenue: Money


class TopItem(BaseModel):
    menu_item_id: int
    name: str
    quantity: int
    revenue: Money


class RestaurantAnalytics(BaseModel):
    restaurant_id: int
    date_from: date
    date_to: date
    revenue: Money
    order_count: int
    average_order_value: Money
    orders_by_status: dict[OrderStatus, int]
    top_items: list[TopItem]
    daily: list[DailyPoint]


class TopRestaurant(BaseModel):
    restaurant_id: int
    name: str
    orders: int
    revenue: Money


class PlatformAnalytics(BaseModel):
    date_from: date
    date_to: date
    gmv: Money  # gross merchandise value: total of paid orders
    order_count: int
    average_order_value: Money
    new_users: int
    users_by_role: dict[str, int]
    restaurants_by_status: dict[str, int]
    complaints_by_status: dict[str, int]
    top_restaurants: list[TopRestaurant]
    daily: list[DailyPoint]
    new_users_daily: dict[date, int]


class RatingSummary(BaseModel):
    avg_rating: Decimal
    rating_count: int
