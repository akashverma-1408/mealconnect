"""Restaurants and menus: public catalogue + owner management."""

import re
from datetime import UTC, datetime

from sqlalchemy import Select, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.cache import invalidate_catalogue
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.order import CartItem
from app.models.restaurant import MenuCategory, MenuItem, Restaurant, RestaurantStatus
from app.models.user import User
from app.schemas.common import Page
from app.schemas.restaurant import (
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    MenuItemCreate,
    MenuItemRead,
    MenuItemSearchResult,
    MenuItemUpdate,
    MenuRead,
    MenuSection,
    OwnerRestaurantRead,
    RestaurantCreate,
    RestaurantFilters,
    RestaurantRead,
    RestaurantRef,
    RestaurantSummary,
    RestaurantUpdate,
)
from app.services.common import escape_like, paginate

SORTS = {
    "-avg_rating": (Restaurant.avg_rating.desc(), Restaurant.rating_count.desc()),
    "avg_rating": (Restaurant.avg_rating.asc(),),
    "delivery_fee": (Restaurant.delivery_fee.asc(),),
    "-delivery_fee": (Restaurant.delivery_fee.desc(),),
    "-created_at": (Restaurant.created_at.desc(),),
    "name": (Restaurant.name.asc(),),
}


def visible_conditions() -> tuple:
    """Conditions for a restaurant customers may see (business rule BR-5)."""
    return (Restaurant.status == RestaurantStatus.APPROVED, Restaurant.deleted_at.is_(None))


# ================================================================== public catalogue
def list_public(db: Session, f: RestaurantFilters, page: int, size: int) -> Page[RestaurantSummary]:
    stmt: Select = select(Restaurant).where(*visible_conditions())
    if f.q:
        pattern = f"%{escape_like(f.q.strip())}%"
        stmt = stmt.where(
            or_(
                Restaurant.name.ilike(pattern, escape="\\"),
                Restaurant.cuisine.ilike(pattern, escape="\\"),
            )
        )
    if f.city:
        stmt = stmt.where(Restaurant.city.ilike(escape_like(f.city.strip()), escape="\\"))
    if f.cuisine:
        stmt = stmt.where(Restaurant.cuisine.ilike(escape_like(f.cuisine.strip()), escape="\\"))
    if f.is_veg:
        stmt = stmt.where(Restaurant.is_veg_only.is_(True))
    if f.min_rating is not None:
        stmt = stmt.where(Restaurant.avg_rating >= f.min_rating)
    if f.open_now:
        stmt = stmt.where(Restaurant.is_open.is_(True))
    stmt = stmt.order_by(*SORTS[f.sort], Restaurant.id)  # id = stable tie-breaker
    return paginate(db, stmt, page, size, RestaurantSummary.model_validate)


def get_public(db: Session, restaurant_id: int) -> Restaurant:
    restaurant = db.scalar(
        select(Restaurant).where(Restaurant.id == restaurant_id, *visible_conditions())
    )
    if restaurant is None:
        raise NotFoundError("Restaurant not found", code="RESTAURANT_NOT_FOUND")
    return restaurant


def build_menu(db: Session, restaurant: Restaurant) -> MenuRead:
    categories = db.scalars(
        select(MenuCategory)
        .where(MenuCategory.restaurant_id == restaurant.id)
        .order_by(MenuCategory.sort_order, MenuCategory.id)
    ).all()
    items = db.scalars(
        select(MenuItem)
        .where(MenuItem.restaurant_id == restaurant.id, MenuItem.deleted_at.is_(None))
        .order_by(MenuItem.name)
    ).all()

    by_category: dict[int | None, list[MenuItemRead]] = {}
    for item in items:
        by_category.setdefault(item.category_id, []).append(MenuItemRead.model_validate(item))
    sections = [
        MenuSection(category=CategoryRead.model_validate(c), items=by_category.get(c.id, []))
        for c in categories
    ]
    if by_category.get(None):
        sections.append(MenuSection(category=None, items=by_category[None]))
    return MenuRead(restaurant=RestaurantRead.model_validate(restaurant), sections=sections)


def get_public_menu(db: Session, restaurant_id: int) -> MenuRead:
    # Unavailable items are returned too, so the UI can show them greyed out (CUS-4).
    return build_menu(db, get_public(db, restaurant_id))


def search_menu_items(
    db: Session,
    q: str,
    city: str | None,
    is_veg: bool | None,
    max_price: float | None,
    page: int,
    size: int,
) -> Page[MenuItemSearchResult]:
    stmt = (
        select(MenuItem)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .options(joinedload(MenuItem.restaurant))
        .where(
            *visible_conditions(),
            MenuItem.deleted_at.is_(None),
            MenuItem.is_available.is_(True),
            MenuItem.name.ilike(f"%{escape_like(q.strip())}%", escape="\\"),
        )
    )
    if city:
        stmt = stmt.where(Restaurant.city.ilike(escape_like(city.strip()), escape="\\"))
    if is_veg:
        stmt = stmt.where(MenuItem.is_veg.is_(True))
    if max_price is not None:
        stmt = stmt.where(MenuItem.price <= max_price)
    stmt = stmt.order_by(Restaurant.avg_rating.desc(), MenuItem.price, MenuItem.id)

    def to_result(item: MenuItem) -> MenuItemSearchResult:
        return MenuItemSearchResult(
            **MenuItemRead.model_validate(item).model_dump(),
            restaurant=RestaurantRef.model_validate(item.restaurant),
        )

    return paginate(db, stmt, page, size, to_result)


# ================================================================== owner: restaurants
def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:120] or "restaurant"


def _unique_slug(db: Session, name: str) -> str:
    base = slug = _slugify(name)
    n = 2
    while db.scalar(select(Restaurant.id).where(Restaurant.slug == slug)) is not None:
        slug = f"{base}-{n}"
        n += 1
    return slug


def create_restaurant(db: Session, owner: User, data: RestaurantCreate) -> Restaurant:
    restaurant = Restaurant(
        owner_id=owner.id,
        slug=_unique_slug(db, data.name),
        status=RestaurantStatus.PENDING,  # RES-1: needs admin approval
        **data.model_dump(),
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def list_owned(db: Session, owner: User) -> list[OwnerRestaurantRead]:
    rows = db.scalars(
        select(Restaurant)
        .where(Restaurant.owner_id == owner.id, Restaurant.deleted_at.is_(None))
        .order_by(Restaurant.id)
    ).all()
    return [OwnerRestaurantRead.model_validate(r) for r in rows]


def get_owned(db: Session, owner: User, restaurant_id: int) -> Restaurant:
    """Owner's own restaurant, else 404 (we don't reveal other owners' restaurants)."""
    restaurant = db.scalar(
        select(Restaurant).where(
            Restaurant.id == restaurant_id,
            Restaurant.owner_id == owner.id,
            Restaurant.deleted_at.is_(None),
        )
    )
    if restaurant is None:
        raise NotFoundError("Restaurant not found", code="RESTAURANT_NOT_FOUND")
    return restaurant


REQUIRED_RESTAURANT_FIELDS = {
    "name",
    "cuisine",
    "city",
    "address",
    "is_veg_only",
    "is_open",
    "delivery_fee",
    "min_order_amount",
}


def update_restaurant(
    db: Session, owner: User, restaurant_id: int, data: RestaurantUpdate
) -> Restaurant:
    restaurant = get_owned(db, owner, restaurant_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        if field in REQUIRED_RESTAURANT_FIELDS and value is None:
            raise BadRequestError(f"{field} cannot be empty", code="FIELD_REQUIRED")
        setattr(restaurant, field, value)
    if (restaurant.opens_at is None) != (restaurant.closes_at is None):
        raise BadRequestError("opens_at and closes_at must be set together", code="INVALID_HOURS")
    db.commit()
    invalidate_catalogue(restaurant_id)
    db.refresh(restaurant)
    return restaurant


def get_owner_menu(db: Session, owner: User, restaurant_id: int) -> MenuRead:
    return build_menu(db, get_owned(db, owner, restaurant_id))


# ================================================================== owner: categories
def _get_category(db: Session, restaurant_id: int, category_id: int) -> MenuCategory:
    category = db.scalar(
        select(MenuCategory).where(
            MenuCategory.id == category_id, MenuCategory.restaurant_id == restaurant_id
        )
    )
    if category is None:
        raise NotFoundError("Category not found", code="CATEGORY_NOT_FOUND")
    return category


def _commit_unique_category(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "A category with this name already exists", code="CATEGORY_EXISTS"
        ) from exc


def list_categories(db: Session, owner: User, restaurant_id: int) -> list[MenuCategory]:
    get_owned(db, owner, restaurant_id)
    return list(
        db.scalars(
            select(MenuCategory)
            .where(MenuCategory.restaurant_id == restaurant_id)
            .order_by(MenuCategory.sort_order, MenuCategory.id)
        )
    )


def create_category(
    db: Session, owner: User, restaurant_id: int, data: CategoryCreate
) -> MenuCategory:
    get_owned(db, owner, restaurant_id)
    category = MenuCategory(restaurant_id=restaurant_id, **data.model_dump())
    db.add(category)
    _commit_unique_category(db)
    invalidate_catalogue(restaurant_id)
    db.refresh(category)
    return category


def update_category(
    db: Session, owner: User, restaurant_id: int, category_id: int, data: CategoryUpdate
) -> MenuCategory:
    get_owned(db, owner, restaurant_id)
    category = _get_category(db, restaurant_id, category_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(category, field, value)
    _commit_unique_category(db)
    invalidate_catalogue(restaurant_id)
    db.refresh(category)
    return category


def delete_category(db: Session, owner: User, restaurant_id: int, category_id: int) -> None:
    get_owned(db, owner, restaurant_id)
    db.delete(_get_category(db, restaurant_id, category_id))
    db.commit()  # its items become uncategorized (FK ON DELETE SET NULL)
    invalidate_catalogue(restaurant_id)


# ================================================================== owner: menu items
def _get_item(db: Session, restaurant_id: int, item_id: int) -> MenuItem:
    item = db.scalar(
        select(MenuItem).where(
            MenuItem.id == item_id,
            MenuItem.restaurant_id == restaurant_id,
            MenuItem.deleted_at.is_(None),
        )
    )
    if item is None:
        raise NotFoundError("Menu item not found", code="MENU_ITEM_NOT_FOUND")
    return item


def list_items(db: Session, owner: User, restaurant_id: int) -> list[MenuItem]:
    get_owned(db, owner, restaurant_id)
    return list(
        db.scalars(
            select(MenuItem)
            .where(MenuItem.restaurant_id == restaurant_id, MenuItem.deleted_at.is_(None))
            .order_by(MenuItem.id)
        )
    )


def create_item(db: Session, owner: User, restaurant_id: int, data: MenuItemCreate) -> MenuItem:
    get_owned(db, owner, restaurant_id)
    if data.category_id is not None:
        _get_category(db, restaurant_id, data.category_id)  # must be this restaurant's
    item = MenuItem(restaurant_id=restaurant_id, **data.model_dump())
    db.add(item)
    db.commit()
    invalidate_catalogue(restaurant_id)
    db.refresh(item)
    return item


def update_item(
    db: Session, owner: User, restaurant_id: int, item_id: int, data: MenuItemUpdate
) -> MenuItem:
    get_owned(db, owner, restaurant_id)
    item = _get_item(db, restaurant_id, item_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("category_id") is not None:
        _get_category(db, restaurant_id, changes["category_id"])
    for field, value in changes.items():
        if value is None and field in {"name", "price", "is_veg"}:
            raise BadRequestError(f"{field} cannot be empty", code="FIELD_REQUIRED")
        setattr(item, field, value)
    db.commit()
    invalidate_catalogue(restaurant_id)
    db.refresh(item)
    return item


def set_item_availability(
    db: Session, owner: User, restaurant_id: int, item_id: int, is_available: bool
) -> MenuItem:
    get_owned(db, owner, restaurant_id)
    item = _get_item(db, restaurant_id, item_id)
    item.is_available = is_available
    db.commit()
    invalidate_catalogue(restaurant_id)
    db.refresh(item)
    return item


def delete_item(db: Session, owner: User, restaurant_id: int, item_id: int) -> None:
    """Soft delete (RES-5): order history keeps pointing at the row."""
    get_owned(db, owner, restaurant_id)
    item = _get_item(db, restaurant_id, item_id)
    item.deleted_at = datetime.now(UTC)
    item.is_available = False
    db.execute(delete(CartItem).where(CartItem.menu_item_id == item.id))  # drop from carts
    db.commit()
    invalidate_catalogue(restaurant_id)
