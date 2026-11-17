"""Reviews, complaints and notifications."""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.engagement import Complaint, ComplaintStatus, Notification, Review
from app.models.order import Order, OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.common import Page
from app.schemas.engagement import (
    ComplaintCreate,
    ComplaintRead,
    ComplaintUpdate,
    NotificationRead,
    ReviewCreate,
    ReviewRead,
)
from app.services import restaurant_service
from app.services.common import audit, notify, paginate


# ================================================================== reviews
def _review_read(review: Review) -> ReviewRead:
    return ReviewRead(
        id=review.id, order_id=review.order_id, restaurant_id=review.restaurant_id,
        rating=review.rating, comment=review.comment,
        author_name=review.customer.full_name.split()[0], created_at=review.created_at,
    )  # fmt: skip


def create_review(db: Session, user: User, order_id: int, data: ReviewCreate) -> ReviewRead:
    order = db.scalar(select(Order).where(Order.id == order_id, Order.customer_id == user.id))
    if order is None:
        raise NotFoundError("Order not found", code="ORDER_NOT_FOUND")
    if order.status != OrderStatus.DELIVERED:
        raise BadRequestError(
            "You can review an order only after it is delivered", code="ORDER_NOT_DELIVERED"
        )
    if db.scalar(select(Review.id).where(Review.order_id == order.id)) is not None:
        raise ConflictError("You already reviewed this order", code="ALREADY_REVIEWED")

    # Lock the restaurant row so two simultaneous reviews can't both read the old average.
    restaurant = db.scalar(
        select(Restaurant).where(Restaurant.id == order.restaurant_id).with_for_update()
    )
    review = Review(
        order_id=order.id, customer_id=user.id, restaurant_id=restaurant.id,
        rating=data.rating, comment=data.comment,
    )  # fmt: skip
    db.add(review)
    db.flush()
    # Recompute from the reviews themselves (indexed, cheap) instead of updating the
    # rounded stored average: incremental updates would accumulate rounding drift.
    avg, count = db.execute(
        select(func.avg(Review.rating), func.count(Review.id)).where(
            Review.restaurant_id == restaurant.id
        )
    ).one()
    restaurant.rating_count = count
    restaurant.avg_rating = Decimal(avg).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    try:
        db.commit()  # review + new average saved together, or neither
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("You already reviewed this order", code="ALREADY_REVIEWED") from exc
    db.refresh(review)
    return _review_read(review)


def list_reviews(db: Session, restaurant_id: int, page: int, size: int) -> Page[ReviewRead]:
    restaurant_service.get_public(db, restaurant_id)
    stmt = (
        select(Review)
        .where(Review.restaurant_id == restaurant_id)
        .options(joinedload(Review.customer))
        .order_by(Review.created_at.desc(), Review.id.desc())
    )
    return paginate(db, stmt, page, size, _review_read)


# ================================================================== complaints
def create_complaint(db: Session, user: User, data: ComplaintCreate) -> Complaint:
    restaurant_id = None
    if data.order_id is not None:
        order = db.scalar(
            select(Order).where(Order.id == data.order_id, Order.customer_id == user.id)
        )
        if order is None:
            raise NotFoundError("Order not found", code="ORDER_NOT_FOUND")
        restaurant_id = order.restaurant_id
    complaint = Complaint(
        raised_by=user.id, order_id=data.order_id, restaurant_id=restaurant_id,
        subject=data.subject, description=data.description,
    )  # fmt: skip
    db.add(complaint)
    db.commit()
    db.refresh(complaint)
    return complaint


def list_my_complaints(db: Session, user: User, page: int, size: int) -> Page[ComplaintRead]:
    stmt = (
        select(Complaint)
        .where(Complaint.raised_by == user.id)
        .order_by(Complaint.created_at.desc(), Complaint.id.desc())
    )
    return paginate(db, stmt, page, size, ComplaintRead.model_validate)


def admin_list_complaints(
    db: Session, status: ComplaintStatus | None, page: int, size: int
) -> Page[ComplaintRead]:
    stmt = select(Complaint)
    if status:
        stmt = stmt.where(Complaint.status == status)
    stmt = stmt.order_by(Complaint.created_at.desc(), Complaint.id.desc())
    return paginate(db, stmt, page, size, ComplaintRead.model_validate)


def admin_update_complaint(
    db: Session, admin: User, complaint_id: int, data: ComplaintUpdate
) -> Complaint:
    from datetime import UTC, datetime

    complaint = db.get(Complaint, complaint_id, with_for_update=True)
    if complaint is None:
        raise NotFoundError("Complaint not found", code="COMPLAINT_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True)

    if "assigned_admin_id" in changes and changes["assigned_admin_id"] is not None:
        assignee = db.get(User, changes["assigned_admin_id"])
        if assignee is None or assignee.role != UserRole.ADMIN:
            raise BadRequestError("Complaints can be assigned to admins only", code="NOT_AN_ADMIN")
        complaint.assigned_admin_id = assignee.id
    if data.resolution_note is not None:
        complaint.resolution_note = data.resolution_note

    new_status = changes.get("status")
    if new_status is not None and new_status != complaint.status:
        closing = new_status in (ComplaintStatus.RESOLVED, ComplaintStatus.REJECTED)
        if closing and not complaint.resolution_note:
            raise BadRequestError(
                "A resolution note is required to close a complaint",
                code="RESOLUTION_NOTE_REQUIRED",
            )
        complaint.status = new_status
        complaint.resolved_at = datetime.now(UTC) if closing else None
        if closing:
            notify(
                db, complaint.raised_by, "complaint.closed",
                f"Complaint {new_status}", complaint.resolution_note or "",
                {"complaint_id": complaint.id},
            )  # fmt: skip

    audit(db, admin.id, "complaint.update", "complaint", complaint.id,
          {k: str(v) for k, v in changes.items()})  # fmt: skip
    db.commit()
    db.refresh(complaint)
    return complaint


# ================================================================== notifications
def list_notifications(
    db: Session, user: User, is_read: bool | None, page: int, size: int
) -> Page[NotificationRead]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if is_read is not None:
        stmt = stmt.where(Notification.is_read.is_(is_read))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
    return paginate(db, stmt, page, size, NotificationRead.model_validate)


def mark_read(db: Session, user: User, notification_id: int) -> Notification:
    n = db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if n is None:
        raise NotFoundError("Notification not found", code="NOTIFICATION_NOT_FOUND")
    n.is_read = True
    db.commit()
    db.refresh(n)
    return n


def mark_all_read(db: Session, user: User) -> int:
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return result.rowcount
