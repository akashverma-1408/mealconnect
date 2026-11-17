"""Small helpers shared by several services."""

from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.engagement import AuditLog, Notification
from app.schemas.common import Page

R = TypeVar("R")

CENT = Decimal("0.01")
TAX_RATE = Decimal("0.05")  # business rule BR-7: 5 % of subtotal


def money(value: Decimal) -> Decimal:
    """Round to 2 decimals the way people expect (0.005 -> 0.01), not banker's rounding."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calc_totals(subtotal: Decimal, delivery_fee: Decimal) -> tuple[Decimal, Decimal]:
    """Return (tax, total) for an order."""
    tax = money(subtotal * TAX_RATE)
    return tax, money(subtotal + delivery_fee + tax)


def escape_like(term: str) -> str:
    """Escape % and _ so user input is matched literally inside ILIKE patterns."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def paginate(
    db: Session, stmt: Select[Any], page: int, size: int, mapper: Callable[[Any], R]
) -> Page[R]:
    """Run COUNT(*) + one page of `stmt` and wrap it in a Page."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(size).offset((page - 1) * size)).unique().all()
    return Page.create([mapper(r) for r in rows], total, page, size)


def notify(
    db: Session, user_id: int, type_: str, title: str, body: str, data: dict | None = None
) -> None:
    """Queue an in-app notification in the current transaction (committed by the caller)."""
    db.add(Notification(user_id=user_id, type=type_, title=title, body=body, data=data))


def audit(
    db: Session,
    actor_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )
