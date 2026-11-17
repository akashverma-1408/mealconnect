"""Reusable FastAPI dependencies: database session, current user, role checks.

FastAPI calls these automatically for any endpoint that declares them as parameters,
so authentication and authorization are written once and reused everywhere.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import InvalidTokenError, decode_token
from app.db.session import get_db
from app.models.user import User, UserRole

DbSession = Annotated[Session, Depends(get_db)]

# auto_error=False: we raise our own 401 with the standard error body.
bearer_scheme = HTTPBearer(auto_error=False, description="Paste the access_token from /auth/login")


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise UnauthorizedError("Authentication required", code="NOT_AUTHENTICATED")
    try:
        payload = decode_token(credentials.credentials, "access")
    except InvalidTokenError as exc:
        code = "TOKEN_EXPIRED" if "expired" in str(exc) else "INVALID_TOKEN"
        raise UnauthorizedError(str(exc), code=code) from exc

    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise UnauthorizedError("User no longer exists", code="INVALID_TOKEN")
    # Checked on every request, so suspending an account takes effect immediately,
    # even though the user's access token has not expired yet.
    if not user.is_active:
        raise ForbiddenError("This account has been suspended", code="ACCOUNT_SUSPENDED")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    """Dependency factory: `Depends(require_roles(UserRole.ADMIN))`."""

    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise ForbiddenError(
                "Your role is not allowed to perform this action", code="ROLE_FORBIDDEN"
            )
        return user

    return checker


CustomerUser = Annotated[User, Depends(require_roles(UserRole.CUSTOMER))]
OwnerUser = Annotated[User, Depends(require_roles(UserRole.RESTAURANT_OWNER))]
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
