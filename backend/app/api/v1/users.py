"""/users/me endpoints: profile, password, delivery addresses."""

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, CustomerUser, DbSession
from app.schemas.common import errors
from app.schemas.user import (
    AddressCreate,
    AddressRead,
    AddressUpdate,
    PasswordChange,
    UserRead,
    UserUpdate,
)
from app.services import user_service

router = APIRouter(prefix="/users/me", tags=["Users"], responses=errors(401, 403))


@router.get("", response_model=UserRead, summary="Current user's profile")
def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("", response_model=UserRead, summary="Update name / phone", responses=errors(422))
def update_me(data: UserUpdate, user: CurrentUser, db: DbSession) -> UserRead:
    return UserRead.model_validate(user_service.update_profile(db, user, data))


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change password (signs out all other sessions)",
    responses=errors(400, 422),
)
def change_password(data: PasswordChange, user: CurrentUser, db: DbSession) -> Response:
    user_service.change_password(db, user, data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- addresses (customers)
@router.get("/addresses", response_model=list[AddressRead], summary="List my addresses")
def list_addresses(user: CustomerUser, db: DbSession) -> list[AddressRead]:
    return [AddressRead.model_validate(a) for a in user_service.list_addresses(db, user)]


@router.post(
    "/addresses",
    response_model=AddressRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an address (the first one becomes the default)",
    responses=errors(400, 422),
)
def create_address(data: AddressCreate, user: CustomerUser, db: DbSession) -> AddressRead:
    return AddressRead.model_validate(user_service.create_address(db, user, data))


@router.patch(
    "/addresses/{address_id}",
    response_model=AddressRead,
    summary="Edit an address",
    responses=errors(400, 404, 422),
)
def update_address(
    address_id: int, data: AddressUpdate, user: CustomerUser, db: DbSession
) -> AddressRead:
    return AddressRead.model_validate(user_service.update_address(db, user, address_id, data))


@router.delete(
    "/addresses/{address_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an address",
    responses=errors(404),
)
def delete_address(address_id: int, user: CustomerUser, db: DbSession) -> Response:
    user_service.delete_address(db, user, address_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
