"""Request/response schemas for authentication."""

from typing import Literal

from pydantic import BaseModel, EmailStr, field_validator

from app.schemas.user import FullName, Password, Phone, UserRead


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    full_name: FullName
    phone: Phone = None
    # Admins cannot self-register: only these two roles are accepted (anything else → 422).
    role: Literal["customer", "restaurant_owner"] = "customer"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds until the access token expires


class LoginResponse(TokenPair):
    user: UserRead
