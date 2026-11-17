"""Schemas shared by many endpoints."""

from decimal import Decimal
from math import ceil
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, Field, PlainSerializer

T = TypeVar("T")

# Money: exact Decimal in Python, serialized as a string with 2 decimals ("249.00")
# so JavaScript never turns it into an imprecise float.
Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=10, decimal_places=2),
    PlainSerializer(lambda v: f"{v:.2f}", return_type=str, when_used="json"),
]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Shape of every error response — documented in OpenAPI via `responses=`."""

    error: ErrorBody


class Message(BaseModel):
    message: str


class Page(BaseModel, Generic[T]):
    """Standard paginated response."""

    items: list[T]
    total: int
    page: int
    size: int
    pages: int

    @classmethod
    def create(cls, items: list[T], total: int, page: int, size: int) -> "Page[T]":
        return cls(items=items, total=total, page=page, size=size, pages=ceil(total / size))


# Reusable OpenAPI `responses=` entries so Swagger shows our error format.
def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: {"model": ErrorResponse} for code in codes}
