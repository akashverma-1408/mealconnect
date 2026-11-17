"""Restaurant, category and menu-item schemas."""

from datetime import datetime, time
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.restaurant import RestaurantStatus
from app.schemas.common import Money
from app.schemas.user import Phone

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
Url = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^https?://", max_length=500)
]
Price = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
NonNegMoney = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


# ------------------------------------------------------------------ restaurants
class RestaurantCreate(BaseModel):
    name: Name
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    cuisine: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
    city: Short
    address: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=255)]
    phone: Phone = None
    image_url: Url | None = None
    is_veg_only: bool = False
    opens_at: time | None = None
    closes_at: time | None = None
    delivery_fee: NonNegMoney = Decimal("0")
    min_order_amount: NonNegMoney = Decimal("0")

    @model_validator(mode="after")
    def hours_together(self) -> "RestaurantCreate":
        if (self.opens_at is None) != (self.closes_at is None):
            raise ValueError("opens_at and closes_at must be given together")
        return self


class RestaurantUpdate(BaseModel):
    name: Name | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    cuisine: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)] | None
    ) = None
    city: Short | None = None
    address: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=255)]
        | None
    ) = None
    phone: Phone = None
    image_url: Url | None = None
    is_veg_only: bool | None = None
    is_open: bool | None = None
    opens_at: time | None = None
    closes_at: time | None = None
    delivery_fee: NonNegMoney | None = None
    min_order_amount: NonNegMoney | None = None


class RestaurantSummary(BaseModel):
    """Card shown in listings."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    cuisine: str
    city: str
    image_url: str | None
    is_veg_only: bool
    is_open: bool
    delivery_fee: Money
    min_order_amount: Money
    avg_rating: Annotated[Decimal, Field()]  # e.g. "4.3"
    rating_count: int


class RestaurantRead(RestaurantSummary):
    description: str | None
    address: str
    phone: str | None
    opens_at: time | None
    closes_at: time | None


class OwnerRestaurantRead(RestaurantRead):
    """Owners and admins also see moderation status."""

    status: RestaurantStatus
    status_reason: str | None
    owner_id: int
    created_at: datetime


RestaurantSort = Literal[
    "-avg_rating", "avg_rating", "delivery_fee", "-delivery_fee", "-created_at", "name"
]


class RestaurantFilters(BaseModel):
    q: str | None = Field(None, max_length=100, description="Search name or cuisine")
    city: str | None = Field(None, max_length=80)
    cuisine: str | None = Field(None, max_length=60)
    is_veg: bool | None = Field(None, description="Only pure-veg restaurants")
    min_rating: float | None = Field(None, ge=0, le=5)
    open_now: bool | None = None
    sort: RestaurantSort = "-avg_rating"


# ------------------------------------------------------------------ categories
class CategoryCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
    sort_order: int = Field(0, ge=0, le=1000)


class CategoryUpdate(BaseModel):
    name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)] | None
    ) = None
    sort_order: int | None = Field(None, ge=0, le=1000)


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sort_order: int


# ------------------------------------------------------------------ menu items
class MenuItemCreate(BaseModel):
    name: Name
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None
    price: Price
    is_veg: bool
    category_id: int | None = None
    image_url: Url | None = None
    is_available: bool = True


class MenuItemUpdate(BaseModel):
    name: Name | None = None
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None
    price: Price | None = None
    is_veg: bool | None = None
    category_id: int | None = None
    image_url: Url | None = None


class AvailabilityUpdate(BaseModel):
    is_available: bool


class MenuItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    price: Money
    is_veg: bool
    is_available: bool
    image_url: str | None
    category_id: int | None


class MenuSection(BaseModel):
    category: CategoryRead | None  # None = items without a category
    items: list[MenuItemRead]


class MenuRead(BaseModel):
    restaurant: RestaurantRead
    sections: list[MenuSection]


class RestaurantRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str


class MenuItemSearchResult(MenuItemRead):
    restaurant: RestaurantRef
