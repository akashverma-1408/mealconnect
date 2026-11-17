"""In-app notifications for any logged-in user."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, Pagination
from app.schemas.common import Page, errors
from app.schemas.engagement import NotificationRead, ReadAllResult
from app.services import engagement_service

router = APIRouter(prefix="/notifications", tags=["Notifications"], responses=errors(401, 403))


@router.get("", response_model=Page[NotificationRead], summary="My notifications, newest first")
def list_notifications(
    user: CurrentUser, db: DbSession, pagination: Pagination, is_read: bool | None = None
) -> Page[NotificationRead]:
    return engagement_service.list_notifications(
        db, user, is_read, pagination.page, pagination.size
    )


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="Mark one as read",
    responses=errors(404),
)
def mark_read(notification_id: int, user: CurrentUser, db: DbSession) -> NotificationRead:
    return NotificationRead.model_validate(engagement_service.mark_read(db, user, notification_id))


@router.post("/read-all", response_model=ReadAllResult, summary="Mark all as read")
def read_all(user: CurrentUser, db: DbSession) -> ReadAllResult:
    return ReadAllResult(updated=engagement_service.mark_all_read(db, user))
