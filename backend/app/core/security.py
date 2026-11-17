"""Password hashing and JWT creation/verification."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]

# bcrypt only uses the first 72 bytes of a password; bcrypt 5 raises an error beyond that,
# so the request schemas reject longer passwords up front.
BCRYPT_MAX_BYTES = 72


# ---------------------------------------------------------------- passwords
def hash_password(plain: str) -> str:
    """Return a salted bcrypt hash. The salt is stored inside the hash string itself."""
    return bcrypt.hashpw(
        plain.encode("utf-8"), bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    ).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time comparison of a plain password with a stored hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# A real hash of a random value, used to spend the same time verifying a password when the
# email does not exist — otherwise response timing would reveal which emails are registered.
DUMMY_PASSWORD_HASH = hash_password(uuid.uuid4().hex)


# ---------------------------------------------------------------- tokens
@dataclass(frozen=True)
class IssuedToken:
    token: str
    jti: str
    expires_at: datetime


def _create_token(
    subject: str, token_type: TokenType, expires_delta: timedelta, extra: dict[str, Any]
) -> IssuedToken:
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    jti = uuid.uuid4().hex
    payload = {
        "sub": subject,  # who the token belongs to (user id, as a string)
        "type": token_type,  # access or refresh — never accept one as the other
        "jti": jti,  # unique token id (used to revoke refresh tokens)
        "iat": now,
        "exp": expires_at,  # PyJWT rejects expired tokens automatically
        **extra,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return IssuedToken(token=token, jti=jti, expires_at=expires_at)


def create_access_token(user_id: int, role: str) -> IssuedToken:
    return _create_token(
        str(user_id),
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        {"role": role},
    )


def create_refresh_token(user_id: int) -> IssuedToken:
    return _create_token(
        str(user_id), "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), {}
    )


class InvalidTokenError(Exception):
    pass


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Verify signature + expiry + type and return the payload, or raise InvalidTokenError."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],  # never let the token choose its algorithm
            options={"require": ["sub", "exp", "jti", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("Token has expired") from exc
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Invalid token") from exc
    if payload.get("type") != expected_type:
        raise InvalidTokenError("Wrong token type")
    return payload
