"""Import every model here so Base.metadata knows all tables (Alembic relies on this)."""

from app.models.user import Address, RefreshToken, User, UserRole, UserStatus

__all__ = ["Address", "RefreshToken", "User", "UserRole", "UserStatus"]
