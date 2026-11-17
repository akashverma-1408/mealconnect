"""Administrator endpoints. Every write is recorded in the audit log."""

from datetime import date

from fastapi import APIRouter

from app.api.deps import AdminUser, DbSession, Pagination
from app.models.engagement import ComplaintStatus
from app.models.order import OrderStatus
from app.models.restaurant import RestaurantStatus
from app.models.user import UserRole, UserStatus
from app.schemas.common import Page, errors
from app.schemas.engagement import (
    AuditLogRead,
    ComplaintRead,
    ComplaintUpdate,
    PlatformAnalytics,
    RestaurantStatusUpdate,
    UserStatusUpdate,
)
from app.schemas.order import CancelRequest, OrderRead, OrderSummary
from app.schemas.restaurant import OwnerRestaurantRead
from app.schemas.user import UserRead
from app.services import admin_service, engagement_service, order_service

router = APIRouter(prefix="/admin", tags=["Admin"], responses=errors(401, 403))


# ------------------------------------------------------------------ users
@router.get("/users", response_model=Page[UserRead], summary="Search users")
def list_users(
    admin: AdminUser,
    db: DbSession,
    pagination: Pagination,
    role: UserRole | None = None,
    status: UserStatus | None = None,
    q: str | None = None,
) -> Page[UserRead]:
    return admin_service.list_users(db, role, status, q, pagination.page, pagination.size)


@router.get(
    "/users/{user_id}", response_model=UserRead, summary="User details", responses=errors(404)
)
def get_user(user_id: int, admin: AdminUser, db: DbSession) -> UserRead:
    return UserRead.model_validate(admin_service.get_user(db, user_id))


@router.patch(
    "/users/{user_id}/status",
    response_model=UserRead,
    summary="Suspend or reactivate a user (suspension signs them out everywhere)",
    responses=errors(400, 404, 422),
)
def set_user_status(
    user_id: int, data: UserStatusUpdate, admin: AdminUser, db: DbSession
) -> UserRead:
    return UserRead.model_validate(
        admin_service.set_user_status(db, admin, user_id, data.status, data.reason)
    )


# ------------------------------------------------------------------ restaurants
@router.get("/restaurants", response_model=Page[OwnerRestaurantRead], summary="All restaurants")
def list_restaurants(
    admin: AdminUser,
    db: DbSession,
    pagination: Pagination,
    status: RestaurantStatus | None = None,
    city: str | None = None,
    q: str | None = None,
) -> Page[OwnerRestaurantRead]:
    return admin_service.list_restaurants(db, status, city, q, pagination.page, pagination.size)


@router.patch(
    "/restaurants/{restaurant_id}/status",
    response_model=OwnerRestaurantRead,
    summary="Approve, reject or suspend a restaurant",
    responses=errors(400, 404, 422),
)
def set_restaurant_status(
    restaurant_id: int, data: RestaurantStatusUpdate, admin: AdminUser, db: DbSession
) -> OwnerRestaurantRead:
    restaurant = admin_service.set_restaurant_status(
        db, admin, restaurant_id, data.status, data.reason
    )
    return OwnerRestaurantRead.model_validate(restaurant)


# ------------------------------------------------------------------ orders
@router.get("/orders", response_model=Page[OrderSummary], summary="Monitor all orders")
def list_orders(
    admin: AdminUser,
    db: DbSession,
    pagination: Pagination,
    status: OrderStatus | None = None,
    restaurant_id: int | None = None,
    customer_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Page[OrderSummary]:
    return order_service.list_all_orders(
        db, status, restaurant_id, customer_id, date_from, date_to,
        pagination.page, pagination.size,
    )  # fmt: skip


@router.get(
    "/orders/{order_id}", response_model=OrderRead, summary="Order details", responses=errors(404)
)
def get_order(order_id: int, admin: AdminUser, db: DbSession) -> OrderRead:
    return order_service.to_read(order_service.load_order(db, order_id))


@router.post(
    "/orders/{order_id}/cancel",
    response_model=OrderRead,
    summary="Force-cancel an unfinished order (refunds if paid)",
    responses=errors(400, 404),
)
def cancel_order(
    order_id: int, admin: AdminUser, db: DbSession, data: CancelRequest | None = None
) -> OrderRead:
    reason = data.reason if data else None
    return order_service.to_read(order_service.admin_cancel(db, admin, order_id, reason))


# ------------------------------------------------------------------ complaints
@router.get("/complaints", response_model=Page[ComplaintRead], summary="All complaints")
def list_complaints(
    admin: AdminUser, db: DbSession, pagination: Pagination, status: ComplaintStatus | None = None
) -> Page[ComplaintRead]:
    return engagement_service.admin_list_complaints(db, status, pagination.page, pagination.size)


@router.patch(
    "/complaints/{complaint_id}",
    response_model=ComplaintRead,
    summary="Assign, update or resolve a complaint",
    responses=errors(400, 404, 422),
)
def update_complaint(
    complaint_id: int, data: ComplaintUpdate, admin: AdminUser, db: DbSession
) -> ComplaintRead:
    return ComplaintRead.model_validate(
        engagement_service.admin_update_complaint(db, admin, complaint_id, data)
    )


# ------------------------------------------------------------------ analytics & audit
@router.get(
    "/analytics/overview",
    response_model=PlatformAnalytics,
    summary="Platform analytics (default: last 30 days)",
    responses=errors(400),
)
def analytics(
    admin: AdminUser, db: DbSession, date_from: date | None = None, date_to: date | None = None
) -> PlatformAnalytics:
    return admin_service.platform_analytics(db, date_from, date_to)


@router.get(
    "/audit-logs", response_model=Page[AuditLogRead], summary="Audit trail of admin actions"
)
def audit_logs(
    admin: AdminUser,
    db: DbSession,
    pagination: Pagination,
    actor_id: int | None = None,
    entity_type: str | None = None,
) -> Page[AuditLogRead]:
    return admin_service.list_audit_logs(
        db, actor_id, entity_type, pagination.page, pagination.size
    )
