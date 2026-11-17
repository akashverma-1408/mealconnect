"""Profile, password and address management."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.security import hash_password, verify_password
from app.models.user import Address, User
from app.schemas.user import AddressCreate, AddressUpdate, PasswordChange, UserUpdate
from app.services.auth_service import revoke_all_refresh_tokens


def update_profile(db: Session, user: User, data: UserUpdate) -> User:
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "full_name" and value is None:
            continue  # name is required; ignore an explicit null
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, user: User, data: PasswordChange) -> None:
    if not verify_password(data.current_password, user.password_hash):
        raise BadRequestError("Current password is incorrect", code="WRONG_PASSWORD")
    if data.current_password == data.new_password:
        raise BadRequestError("New password must be different", code="PASSWORD_UNCHANGED")
    user.password_hash = hash_password(data.new_password)
    # Log out every other session: anyone holding an old refresh token loses access.
    revoke_all_refresh_tokens(db, user.id)
    db.commit()


# ------------------------------------------------------------------ addresses
def list_addresses(db: Session, user: User) -> list[Address]:
    return list(db.scalars(select(Address).where(Address.user_id == user.id).order_by(Address.id)))


def get_address(db: Session, user: User, address_id: int) -> Address:
    # Filtering by user_id too means another user's address is simply "not found".
    address = db.scalar(select(Address).where(Address.id == address_id, Address.user_id == user.id))
    if address is None:
        raise NotFoundError("Address not found", code="ADDRESS_NOT_FOUND")
    return address


def _clear_default(db: Session, user_id: int) -> None:
    db.execute(
        update(Address)
        .where(Address.user_id == user_id, Address.is_default.is_(True))
        .values(is_default=False)
    )


MAX_ADDRESSES = 10


def create_address(db: Session, user: User, data: AddressCreate) -> Address:
    existing = list_addresses(db, user)
    if len(existing) >= MAX_ADDRESSES:
        raise BadRequestError(
            f"You can save at most {MAX_ADDRESSES} addresses", code="ADDRESS_LIMIT"
        )
    make_default = data.is_default or not existing  # first address becomes the default
    if make_default:
        _clear_default(db, user.id)
    address = Address(user_id=user.id, **data.model_dump(exclude={"is_default"}))
    address.is_default = make_default
    db.add(address)
    db.commit()  # one transaction: unsetting the old default + inserting the new address
    db.refresh(address)
    return address


def update_address(db: Session, user: User, address_id: int, data: AddressUpdate) -> Address:
    address = get_address(db, user, address_id)
    changes = data.model_dump(exclude_unset=True)
    required = {"line1", "city", "state", "postal_code"}
    for field, value in changes.items():
        if field in required and value is None:
            raise BadRequestError(f"{field} cannot be empty", code="FIELD_REQUIRED")
    if changes.pop("is_default", None) is True and not address.is_default:
        _clear_default(db, user.id)
        db.flush()  # make sure the old default is cleared before setting the new one
        address.is_default = True
    for field, value in changes.items():
        setattr(address, field, value)
    db.commit()
    db.refresh(address)
    return address


def delete_address(db: Session, user: User, address_id: int) -> None:
    address = get_address(db, user, address_id)
    was_default = address.is_default
    db.delete(address)
    db.flush()
    if was_default:  # promote the oldest remaining address so a default always exists
        replacement = db.scalar(
            select(Address).where(Address.user_id == user.id).order_by(Address.id).limit(1)
        )
        if replacement:
            replacement.is_default = True
    db.commit()
