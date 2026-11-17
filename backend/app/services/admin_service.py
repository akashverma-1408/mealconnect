"""Admin: user and restaurant moderation, audit log, analytics (owner + platform)."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Date, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.cache import invalidate_catalogue
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.models.engagement import AuditLog, Complaint
from app.models.order import Order, OrderItem, OrderStatus
from app.models.restaurant import Restaurant, RestaurantStatus
from app.models.user import User, UserRole, UserStatus
from app.schemas.common import Page
from app.schemas.engagement import (
    AuditLogRead,
    DailyPoint,
    PlatformAnalytics,
    RestaurantAnalytics,
    TopItem,
    TopRestaurant,
)
from app.schemas.restaurant import OwnerRestaurantRead
from app.schemas.user import UserRead
from app.services.auth_service import revoke_all_refresh_tokens
from app.services.common import audit, escape_like, money, notify, paginate
from app.services.order_service import REVENUE_STATUSES
from app.services.restaurant_service import get_owned

MAX_RANGE_DAYS = 366


# ================================================================== users
def list_users(
    db: Session, role: UserRole | None, status: UserStatus | None, q: str | None,
    page: int, size: int,
) -> Page[UserRead]:  # fmt: skip
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if status:
        stmt = stmt.where(User.status == status)
    if q:
        pattern = f"%{escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(User.email.ilike(pattern, escape="\\"), User.full_name.ilike(pattern, escape="\\"))
        )
    return paginate(db, stmt.order_by(User.id), page, size, UserRead.model_validate)


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found", code="USER_NOT_FOUND")
    return user


def set_user_status(
    db: Session, admin: User, user_id: int, status: UserStatus, reason: str | None
) -> User:
    user = get_user(db, user_id)
    if user.id == admin.id:
        raise BadRequestError("You cannot change your own status", code="CANNOT_MODIFY_SELF")
    if user.role == UserRole.ADMIN:
        raise ForbiddenError("Admins cannot be suspended here", code="CANNOT_MODIFY_ADMIN")
    previous = user.status
    user.status = status
    user.suspended_reason = reason if status == UserStatus.SUSPENDED else None
    if status == UserStatus.SUSPENDED:
        revoke_all_refresh_tokens(db, user.id)  # signs the user out everywhere
    audit(db, admin.id, f"user.{status.value}", "user", user.id,
          {"from": previous.value, "to": status.value, "reason": reason})  # fmt: skip
    db.commit()
    db.refresh(user)
    return user


# ================================================================== restaurants
def list_restaurants(
    db: Session, status: RestaurantStatus | None, city: str | None, q: str | None,
    page: int, size: int,
) -> Page[OwnerRestaurantRead]:  # fmt: skip
    stmt = select(Restaurant).where(Restaurant.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Restaurant.status == status)
    if city:
        stmt = stmt.where(Restaurant.city.ilike(escape_like(city.strip()), escape="\\"))
    if q:
        stmt = stmt.where(Restaurant.name.ilike(f"%{escape_like(q.strip())}%", escape="\\"))
    stmt = stmt.order_by(Restaurant.created_at.desc(), Restaurant.id.desc())
    return paginate(db, stmt, page, size, OwnerRestaurantRead.model_validate)


def set_restaurant_status(
    db: Session, admin: User, restaurant_id: int, status: RestaurantStatus, reason: str | None
) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id, with_for_update=True)
    if restaurant is None or restaurant.deleted_at is not None:
        raise NotFoundError("Restaurant not found", code="RESTAURANT_NOT_FOUND")
    if status == RestaurantStatus.PENDING:
        raise BadRequestError("A restaurant cannot be moved back to pending", code="INVALID_STATUS")
    if status == restaurant.status:
        raise BadRequestError(f"Restaurant is already {status}", code="STATUS_UNCHANGED")
    if status in (RestaurantStatus.REJECTED, RestaurantStatus.SUSPENDED) and not reason:
        raise BadRequestError("A reason is required", code="REASON_REQUIRED")
    previous = restaurant.status
    restaurant.status = status
    restaurant.status_reason = reason
    notify(
        db, restaurant.owner_id, f"restaurant.{status.value}",
        f"Restaurant {status.value}", f"'{restaurant.name}' is now {status.value}."
        + (f" Reason: {reason}" if reason else ""), {"restaurant_id": restaurant.id},
    )  # fmt: skip
    audit(db, admin.id, f"restaurant.{status.value}", "restaurant", restaurant.id,
          {"from": previous.value, "to": status.value, "reason": reason})  # fmt: skip
    db.commit()
    invalidate_catalogue(restaurant.id)  # approve/suspend changes what customers can see
    db.refresh(restaurant)
    return restaurant


def list_audit_logs(
    db: Session, actor_id: int | None, entity_type: str | None, page: int, size: int
) -> Page[AuditLogRead]:
    stmt = select(AuditLog)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    return paginate(db, stmt, page, size, AuditLogRead.model_validate)


# ================================================================== analytics
def resolve_range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = datetime.now(UTC).date()
    date_to = date_to or today
    date_from = date_from or (date_to - timedelta(days=29))  # default: last 30 days
    if date_from > date_to:
        raise BadRequestError("date_from must be on or before date_to", code="INVALID_RANGE")
    if (date_to - date_from).days >= MAX_RANGE_DAYS:
        raise BadRequestError(f"Range can be at most {MAX_RANGE_DAYS} days", code="INVALID_RANGE")
    return date_from, date_to


def _bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(date_from, time.min, tzinfo=UTC),
        datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC),
    )


def _daily(db: Session, conditions: list, date_from: date, date_to: date) -> list[DailyPoint]:
    day = cast(Order.created_at, Date)  # sessions run in UTC, so this is the UTC day
    rows = db.execute(
        select(day, func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
        .where(*conditions)
        .group_by(day)
    ).all()
    found = {d: (n, total) for d, n, total in rows}
    points, current = [], date_from
    while current <= date_to:  # fill days without orders with zeros
        n, total = found.get(current, (0, Decimal("0")))
        points.append(DailyPoint(date=current, orders=n, revenue=money(Decimal(total))))
        current += timedelta(days=1)
    return points


def restaurant_analytics(
    db: Session, owner: User, restaurant_id: int, date_from: date | None, date_to: date | None
) -> RestaurantAnalytics:
    get_owned(db, owner, restaurant_id)
    date_from, date_to = resolve_range(date_from, date_to)
    start, end = _bounds(date_from, date_to)
    in_range = [
        Order.restaurant_id == restaurant_id,
        Order.created_at >= start,
        Order.created_at < end,
    ]
    paid = [*in_range, Order.status.in_(REVENUE_STATUSES)]

    count, revenue = db.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0)).where(*paid)
    ).one()
    by_status = dict(
        db.execute(
            select(Order.status, func.count(Order.id))
            .where(*in_range, Order.status != OrderStatus.PENDING_PAYMENT)
            .group_by(Order.status)
        ).all()
    )
    top = db.execute(
        select(
            OrderItem.menu_item_id,
            OrderItem.item_name,
            func.sum(OrderItem.quantity).label("qty"),
            func.sum(OrderItem.line_total),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .where(*paid)
        .group_by(OrderItem.menu_item_id, OrderItem.item_name)
        .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.menu_item_id)
        .limit(5)
    ).all()
    revenue = money(Decimal(revenue))
    return RestaurantAnalytics(
        restaurant_id=restaurant_id, date_from=date_from, date_to=date_to,
        revenue=revenue, order_count=count,
        average_order_value=money(revenue / count) if count else Decimal("0.00"),
        orders_by_status=by_status,
        top_items=[
            TopItem(menu_item_id=i, name=n, quantity=q, revenue=money(r)) for i, n, q, r in top
        ],
        daily=_daily(db, paid, date_from, date_to),
    )  # fmt: skip


def platform_analytics(
    db: Session, date_from: date | None, date_to: date | None
) -> PlatformAnalytics:
    date_from, date_to = resolve_range(date_from, date_to)
    start, end = _bounds(date_from, date_to)
    paid = [Order.created_at >= start, Order.created_at < end, Order.status.in_(REVENUE_STATUSES)]

    count, gmv = db.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0)).where(*paid)
    ).one()
    gmv = money(Decimal(gmv))
    user_day = cast(User.created_at, Date)
    new_users_daily = dict(
        db.execute(
            select(user_day, func.count(User.id))
            .where(User.created_at >= start, User.created_at < end)
            .group_by(user_day)
        ).all()
    )
    top = db.execute(
        select(Restaurant.id, Restaurant.name, func.count(Order.id), func.sum(Order.total))
        .join(Order, Order.restaurant_id == Restaurant.id)
        .where(*paid)
        .group_by(Restaurant.id, Restaurant.name)
        .order_by(func.sum(Order.total).desc(), Restaurant.id)
        .limit(5)
    ).all()

    def counts(column) -> dict[str, int]:
        return {
            str(k.value): v for k, v in db.execute(select(column, func.count()).group_by(column))
        }

    return PlatformAnalytics(
        date_from=date_from, date_to=date_to, gmv=gmv, order_count=count,
        average_order_value=money(gmv / count) if count else Decimal("0.00"),
        new_users=sum(new_users_daily.values()),
        users_by_role=counts(User.role),
        restaurants_by_status=counts(Restaurant.status),
        complaints_by_status=counts(Complaint.status),
        top_restaurants=[
            TopRestaurant(restaurant_id=i, name=n, orders=c, revenue=money(r)) for i, n, c, r in top
        ],
        daily=_daily(db, paid, date_from, date_to),
        new_users_daily=new_users_daily,
    )  # fmt: skip
