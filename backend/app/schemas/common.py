"""Schemas shared by many endpoints."""

from typing import Any

from pydantic import BaseModel


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


# Reusable OpenAPI `responses=` entries so Swagger shows our error format.
def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: {"model": ErrorResponse} for code in codes}
