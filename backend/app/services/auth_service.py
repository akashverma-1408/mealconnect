"""Authentication business logic: registration, login, token rotation, logout.

Services contain the rules and talk to the database. They raise domain exceptions
(ConflictError, UnauthorizedError, ...) and never deal with HTTP details directly.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, ForbiddenError, UnauthorizedError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import RefreshToken, User, UserRole
from app.schemas.auth import RegisterRequest, TokenPair

logger = logging.getLogger(__name__)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def register_user(db: Session, data: RegisterRequest) -> User:
    if get_user_by_email(db, data.email):
        raise ConflictError("An account with this email already exists", code="EMAIL_TAKEN")

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        phone=data.phone,
        role=UserRole(data.role),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # Two simultaneous sign-ups with the same email: the UNIQUE constraint is the
        # real guard; the check above only gives a nicer error in the common case.
        db.rollback()
        raise ConflictError(
            "An account with this email already exists", code="EMAIL_TAKEN"
        ) from exc
    db.refresh(user)
    logger.info("user registered", extra={"user_id": user.id, "role": user.role.value})
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    if user is None:
        verify_password(password, DUMMY_PASSWORD_HASH)  # same timing as a real check
        raise UnauthorizedError("Invalid email or password", code="INVALID_CREDENTIALS")
    if not verify_password(password, user.password_hash):
        raise UnauthorizedError("Invalid email or password", code="INVALID_CREDENTIALS")
    if not user.is_active:
        raise ForbiddenError("This account has been suspended", code="ACCOUNT_SUSPENDED")
    return user


def issue_tokens(db: Session, user: User) -> TokenPair:
    """Create an access + refresh token pair and record the refresh token."""
    access = create_access_token(user.id, user.role.value)
    refresh = create_refresh_token(user.id)
    db.add(RefreshToken(user_id=user.id, jti=refresh.jti, expires_at=refresh.expires_at))
    db.commit()
    return TokenPair(
        access_token=access.token,
        refresh_token=refresh.token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def revoke_all_refresh_tokens(db: Session, user_id: int) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def rotate_refresh_token(db: Session, refresh_token: str) -> tuple[User, TokenPair]:
    """Exchange a valid refresh token for a new pair; the old one is revoked (rotation).

    If an already-revoked token is presented, someone may have stolen it: we revoke every
    session of that user (refresh-token reuse detection).
    """
    try:
        payload = decode_token(refresh_token, "refresh")
    except InvalidTokenError as exc:
        raise UnauthorizedError(str(exc), code="INVALID_TOKEN") from exc

    record = db.scalar(
        select(RefreshToken).where(RefreshToken.jti == payload["jti"]).with_for_update()
    )
    if record is None or str(record.user_id) != payload["sub"]:
        raise UnauthorizedError("Invalid token", code="INVALID_TOKEN")

    if record.revoked_at is not None:
        revoke_all_refresh_tokens(db, record.user_id)
        db.commit()
        logger.warning("refresh token reuse detected", extra={"user_id": record.user_id})
        raise UnauthorizedError("Token has been revoked", code="TOKEN_REVOKED")

    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise ForbiddenError("This account has been suspended", code="ACCOUNT_SUSPENDED")

    record.revoked_at = datetime.now(UTC)
    tokens = issue_tokens(db, user)  # commits the revocation and the new token together
    return user, tokens


def logout(db: Session, user: User, refresh_token: str) -> None:
    """Revoke one refresh token belonging to the current user. Idempotent."""
    try:
        payload = decode_token(refresh_token, "refresh")
    except InvalidTokenError:
        return  # an invalid/expired token is effectively already logged out
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.jti == payload["jti"],
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()
