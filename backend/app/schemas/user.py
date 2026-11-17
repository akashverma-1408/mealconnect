"""Request/response schemas for users and addresses.

Schemas are the API contract: they validate input (FastAPI returns 422 automatically when
validation fails) and control exactly which fields leave the server — e.g. UserRead has
no password_hash, so it can never leak.
"""

import re
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.core.security import BCRYPT_MAX_BYTES
from app.models.user import UserRole, UserStatus

PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


def _check_password(value: str) -> str:
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("Password must contain at least one letter and one digit")
    if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes")
    return value


def _check_phone(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"[\s-]", "", value)
    if not PHONE_RE.match(cleaned):
        raise ValueError("Phone must be 7-15 digits, optionally starting with +")
    return cleaned


Password = Annotated[str, Field(min_length=8, max_length=72), AfterValidator(_check_password)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
Phone = Annotated[str | None, AfterValidator(_check_phone)]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # build from ORM objects

    id: int
    email: str
    full_name: str
    phone: str | None
    role: UserRole
    status: UserStatus
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: FullName | None = None
    phone: Phone = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: Password


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class AddressBase(BaseModel):
    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)] | None = None
    line1: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]
    line2: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    city: ShortText
    state: ShortText
    postal_code: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9 -]{3,12}$")]


class AddressCreate(AddressBase):
    is_default: bool = False


class AddressUpdate(BaseModel):
    """PATCH: every field optional; only the fields sent are changed."""

    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)] | None = None
    line1: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]
        | None
    ) = None
    line2: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    city: ShortText | None = None
    state: ShortText | None = None
    postal_code: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9 -]{3,12}$")] | None = None
    is_default: bool | None = None


class AddressRead(AddressBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_default: bool
