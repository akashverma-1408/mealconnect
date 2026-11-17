"""Import every model here so Base.metadata knows all tables (Alembic relies on this)."""

from app.models.engagement import AuditLog, Complaint, ComplaintStatus, Notification, Review
from app.models.order import CartItem, Order, OrderItem, OrderStatus, OrderStatusHistory
from app.models.payment import Payment, PaymentEvent, PaymentStatus
from app.models.restaurant import MenuCategory, MenuItem, Restaurant, RestaurantStatus
from app.models.user import Address, RefreshToken, User, UserRole, UserStatus

__all__ = [
    "Address",
    "AuditLog",
    "CartItem",
    "Complaint",
    "ComplaintStatus",
    "MenuCategory",
    "MenuItem",
    "Notification",
    "Order",
    "OrderItem",
    "OrderStatus",
    "OrderStatusHistory",
    "Payment",
    "PaymentEvent",
    "PaymentStatus",
    "RefreshToken",
    "Restaurant",
    "RestaurantStatus",
    "Review",
    "User",
    "UserRole",
    "UserStatus",
]
