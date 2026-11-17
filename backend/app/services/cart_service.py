"""Server-side cart. Rule BR-1: a cart holds items from ONE restaurant only."""

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.order import CartItem
from app.models.restaurant import MenuItem, Restaurant
from app.models.user import User
from app.schemas.order import CartLine, CartRead
from app.schemas.restaurant import RestaurantRef
from app.services.common import calc_totals, money
from app.services.restaurant_service import visible_conditions

MAX_QUANTITY = 50


def load_cart_rows(db: Session, user: User, lock: bool = False) -> list[CartItem]:
    stmt = (
        select(CartItem)
        .where(CartItem.user_id == user.id)
        .options(joinedload(CartItem.menu_item).joinedload(MenuItem.restaurant))
        .order_by(CartItem.created_at, CartItem.menu_item_id)
    )
    if lock:  # SELECT ... FOR UPDATE OF cart_items: blocks a parallel checkout
        stmt = stmt.with_for_update(of=CartItem)
    return list(db.scalars(stmt).unique())


def item_is_orderable(item: MenuItem) -> bool:
    return item.deleted_at is None and item.is_available


def build_cart(rows: list[CartItem]) -> CartRead:
    zero = Decimal("0.00")
    if not rows:
        return CartRead(
            restaurant=None, items=[], item_count=0, subtotal=zero, delivery_fee=zero, tax=zero,
            total=zero, min_order_amount=zero, can_checkout=False, problems=["Cart is empty"],
        )  # fmt: skip
    restaurant = rows[0].menu_item.restaurant
    lines, problems = [], []
    subtotal = Decimal("0")
    for row in rows:
        item = row.menu_item
        available = item_is_orderable(item)
        line_total = money(item.price * row.quantity)
        if available:
            subtotal += line_total
        else:
            problems.append(f"'{item.name}' is no longer available")
        lines.append(
            CartLine(
                menu_item_id=item.id, name=item.name, unit_price=item.price,
                quantity=row.quantity, line_total=line_total, is_veg=item.is_veg,
                is_available=available,
            )
        )  # fmt: skip
    subtotal = money(subtotal)
    tax, total = calc_totals(subtotal, restaurant.delivery_fee)
    if not restaurant.is_open:
        problems.append("Restaurant is currently closed")
    if subtotal < restaurant.min_order_amount:
        problems.append(f"Minimum order amount is {restaurant.min_order_amount:.2f}")
    return CartRead(
        restaurant=RestaurantRef.model_validate(restaurant),
        items=lines,
        item_count=sum(r.quantity for r in rows),
        subtotal=subtotal,
        delivery_fee=restaurant.delivery_fee,
        tax=tax,
        total=total,
        min_order_amount=restaurant.min_order_amount,
        can_checkout=not problems,
        problems=problems,
    )


def get_cart(db: Session, user: User) -> CartRead:
    return build_cart(load_cart_rows(db, user))


def add_item(db: Session, user: User, menu_item_id: int, quantity: int) -> CartRead:
    item = db.scalar(
        select(MenuItem)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .where(MenuItem.id == menu_item_id, MenuItem.deleted_at.is_(None), *visible_conditions())
    )
    if item is None:
        raise NotFoundError("Menu item not found", code="MENU_ITEM_NOT_FOUND")
    if not item.is_available:
        raise BadRequestError(f"'{item.name}' is currently unavailable", code="ITEM_UNAVAILABLE")

    rows = load_cart_rows(db, user)
    if rows and rows[0].menu_item.restaurant_id != item.restaurant_id:
        raise ConflictError(
            "Your cart has items from another restaurant. Clear the cart first.",
            code="CART_RESTAURANT_MISMATCH",
            details={"cart_restaurant_id": rows[0].menu_item.restaurant_id},
        )
    existing = next((r for r in rows if r.menu_item_id == item.id), None)
    new_quantity = quantity + (existing.quantity if existing else 0)
    if new_quantity > MAX_QUANTITY:
        raise BadRequestError(
            f"At most {MAX_QUANTITY} of one item per order", code="QUANTITY_LIMIT"
        )
    if existing:
        existing.quantity = new_quantity
    else:
        db.add(CartItem(user_id=user.id, menu_item_id=item.id, quantity=quantity))
    db.commit()
    return get_cart(db, user)


def _get_row(db: Session, user: User, menu_item_id: int) -> CartItem:
    row = db.get(CartItem, (user.id, menu_item_id))
    if row is None:
        raise NotFoundError("Item is not in your cart", code="CART_ITEM_NOT_FOUND")
    return row


def update_quantity(db: Session, user: User, menu_item_id: int, quantity: int) -> CartRead:
    _get_row(db, user, menu_item_id).quantity = quantity
    db.commit()
    return get_cart(db, user)


def remove_item(db: Session, user: User, menu_item_id: int) -> CartRead:
    db.delete(_get_row(db, user, menu_item_id))
    db.commit()
    return get_cart(db, user)


def clear(db: Session, user: User) -> None:
    db.execute(delete(CartItem).where(CartItem.user_id == user.id))
    db.commit()
