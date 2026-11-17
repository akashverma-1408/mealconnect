"""/auth endpoints: register, login, refresh, logout.

Routers stay thin: parse input (schemas), call a service, return a schema.
"""

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
)
from app.schemas.common import errors
from app.schemas.user import UserRead
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer or restaurant-owner account",
    responses=errors(409, 422),
)
def register(data: RegisterRequest, db: DbSession) -> UserRead:
    user = auth_service.register_user(db, data)
    return UserRead.model_validate(user)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Exchange email + password for an access/refresh token pair",
    responses=errors(401, 403, 422),
)
def login(data: LoginRequest, db: DbSession) -> LoginResponse:
    user = auth_service.authenticate(db, data.email, data.password)
    tokens = auth_service.issue_tokens(db, user)
    return LoginResponse(**tokens.model_dump(), user=UserRead.model_validate(user))


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotate tokens: old refresh token is revoked, a new pair is returned",
    responses=errors(401, 403),
)
def refresh(data: RefreshRequest, db: DbSession) -> TokenPair:
    _, tokens = auth_service.rotate_refresh_token(db, data.refresh_token)
    return tokens


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
    responses=errors(401),
)
def logout(data: RefreshRequest, user: CurrentUser, db: DbSession) -> Response:
    auth_service.logout(db, user, data.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
