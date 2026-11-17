"""Load demo data into the DEVELOPMENT database.

    python -m app.seed            # only if the database is empty
    python -m app.seed --reset    # wipe all app tables first (never allowed in production)

Demo accounts (local development only — every one uses the password DemoPass123):

    admin@example.com              administrator
    owner.spice@example.com        owns Spice Route, Green Bowl
    owner.coastal@example.com      owns Coastal Curry House, Pizza Piazza
    owner.dragon@example.com       owns Dragon Wok, Biryani Junction, Burger Barn (pending)
    asha@example.com               customer (2 addresses, order history)
    ravi@example.com               customer
"""

import argparse
import random
import sys
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import (
    Address,
    Complaint,
    MenuCategory,
    MenuItem,
    Notification,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    Payment,
    PaymentStatus,
    Restaurant,
    RestaurantStatus,
    Review,
    User,
    UserRole,
)
from app.services.common import calc_totals, money

DEMO_PASSWORD = "DemoPass123"
S = OrderStatus

# name, cuisine, city, veg_only, fee, min_order, menu {category: [(item, price, veg)]}
RESTAURANTS = {
    "owner.spice@example.com": [
        ("Spice Route", "North Indian", "Pune", False, "30", "150", {
            "Starters": [("Paneer Tikka", "249", True), ("Chicken Tikka", "289", False),
                         ("Hara Bhara Kebab", "199", True)],
            "Mains": [("Butter Chicken", "349", False), ("Dal Makhani", "229", True),
                      ("Kadai Paneer", "279", True)],
            "Breads": [("Butter Naan", "49", True), ("Garlic Naan", "59", True)],
        }),
        ("Green Bowl", "Healthy", "Pune", True, "20", "100", {
            "Bowls": [("Quinoa Power Bowl", "299", True), ("Mexican Burrito Bowl", "279", True)],
            "Salads": [("Greek Salad", "219", True), ("Sprout Chaat Salad", "149", True)],
            "Drinks": [("Cold-Pressed Orange Juice", "129", True)],
        }),
    ],
    "owner.coastal@example.com": [
        ("Coastal Curry House", "South Indian", "Mumbai", False, "40", "200", {
            "Tiffin": [("Masala Dosa", "129", True), ("Idli Sambar", "89", True),
                       ("Medu Vada", "99", True)],
            "Seafood": [("Prawn Curry", "399", False), ("Fish Fry", "349", False)],
            "Rice": [("Lemon Rice", "149", True), ("Curd Rice", "129", True)],
        }),
        ("Pizza Piazza", "Italian", "Mumbai", False, "50", "250", {
            "Pizza": [("Margherita", "299", True), ("Farmhouse", "379", True),
                      ("Pepperoni", "429", False)],
            "Pasta": [("Penne Arrabbiata", "289", True), ("Alfredo Chicken Pasta", "339", False)],
            "Desserts": [("Tiramisu", "199", True)],
        }),
    ],
    "owner.dragon@example.com": [
        ("Dragon Wok", "Chinese", "Bengaluru", False, "35", "150", {
            "Starters": [("Veg Spring Rolls", "169", True), ("Chilli Chicken", "259", False)],
            "Noodles & Rice": [("Hakka Noodles", "199", True), ("Schezwan Fried Rice", "209", True),
                               ("Chicken Fried Rice", "239", False)],
        }),
        ("Biryani Junction", "Biryani", "Bengaluru", False, "25", "200", {
            "Biryani": [("Hyderabadi Chicken Biryani", "329", False),
                        ("Veg Dum Biryani", "249", True), ("Mutton Biryani", "419", False)],
            "Sides": [("Raita", "49", True), ("Mirchi Ka Salan", "79", True)],
        }),
    ],
}  # fmt: skip


def wipe(db: Session) -> None:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    db.commit()


def make_user(db: Session, email: str, name: str, role: UserRole, phone: str | None = None) -> User:
    user = User(
        email=email, full_name=name, role=role, phone=phone,
        password_hash=hash_password(DEMO_PASSWORD),
    )  # fmt: skip
    db.add(user)
    db.flush()
    return user


def seed(db: Session) -> dict[str, int]:
    rng = random.Random(42)  # fixed seed: the same data every run
    now = datetime.now(UTC)

    make_user(db, "admin@example.com", "Platform Admin", UserRole.ADMIN)
    owners = {
        "owner.spice@example.com": make_user(
            db, "owner.spice@example.com", "Meera Kapoor", UserRole.RESTAURANT_OWNER
        ),  # noqa: E501
        "owner.coastal@example.com": make_user(
            db, "owner.coastal@example.com", "Arjun Nair", UserRole.RESTAURANT_OWNER
        ),  # noqa: E501
        "owner.dragon@example.com": make_user(
            db, "owner.dragon@example.com", "Li Wei", UserRole.RESTAURANT_OWNER
        ),  # noqa: E501
    }
    asha = make_user(db, "asha@example.com", "Asha Rao", UserRole.CUSTOMER, "9876543210")
    ravi = make_user(db, "ravi@example.com", "Ravi Kumar", UserRole.CUSTOMER, "9123456780")
    home = Address(user_id=asha.id, label="Home", line1="12 MG Road", city="Pune",
                   state="Maharashtra", postal_code="411001", is_default=True)  # fmt: skip
    work = Address(user_id=asha.id, label="Work", line1="5 Tech Park, Hinjewadi", city="Pune",
                   state="Maharashtra", postal_code="411057")  # fmt: skip
    ravi_home = Address(user_id=ravi.id, label="Home", line1="88 Linking Road", city="Mumbai",
                        state="Maharashtra", postal_code="400050", is_default=True)  # fmt: skip
    db.add_all([home, work, ravi_home])

    restaurants: list[tuple[Restaurant, list[MenuItem]]] = []
    for owner_email, entries in RESTAURANTS.items():
        for name, cuisine, city, veg, fee, min_order, menu in entries:
            r = Restaurant(
                owner_id=owners[owner_email].id, name=name,
                slug=name.lower().replace(" ", "-"), cuisine=cuisine, city=city,
                address=f"{rng.randint(1, 200)} Main Street, {city}",
                description=f"Freshly made {cuisine.lower()} favourites in {city}.",
                phone=f"98{rng.randint(10000000, 99999999)}", is_veg_only=veg,
                delivery_fee=Decimal(fee), min_order_amount=Decimal(min_order),
                opens_at=time(10, 0), closes_at=time(23, 0),
                status=RestaurantStatus.APPROVED,
            )  # fmt: skip
            db.add(r)
            db.flush()
            items = []
            for sort, (category_name, dishes) in enumerate(menu.items()):
                category = MenuCategory(restaurant_id=r.id, name=category_name, sort_order=sort)
                db.add(category)
                db.flush()
                for dish, price, is_veg in dishes:
                    item = MenuItem(
                        restaurant_id=r.id, category_id=category.id, name=dish,
                        description=f"House-special {dish.lower()}.", price=Decimal(price),
                        is_veg=is_veg,
                    )  # fmt: skip
                    db.add(item)
                    items.append(item)
            db.flush()
            restaurants.append((r, items))

    # One restaurant waiting for approval (to try the admin flow).
    db.add(
        Restaurant(
            owner_id=owners["owner.dragon@example.com"].id, name="Burger Barn",
            slug="burger-barn", cuisine="American", city="Bengaluru",
            address="7 Church Street, Bengaluru", delivery_fee=Decimal("30"),
            status=RestaurantStatus.PENDING,
        )
    )  # fmt: skip
    # One item sold out, to show greyed-out menu entries.
    restaurants[0][1][2].is_available = False

    # ---- order history over the last 20 days
    flow = [S.PENDING_PAYMENT, S.PLACED, S.ACCEPTED, S.PREPARING, S.OUT_FOR_DELIVERY, S.DELIVERED]
    plan = [S.DELIVERED] * 14 + [S.CANCELLED, S.REJECTED, S.PREPARING, S.PLACED]
    comments = ["Delicious and hot!", "Good portions.", "Arrived a bit late but tasty.",
                "Will order again.", None]  # fmt: skip
    orders_created = 0
    for i, final in enumerate(plan):
        customer, address = (asha, home) if i % 3 else (ravi, ravi_home)
        restaurant, items = restaurants[i % len(restaurants)]
        picks = rng.sample([it for it in items if it.is_available], k=min(3, len(items)))
        lines = [(it, rng.randint(1, 3)) for it in picks]
        subtotal = money(sum((it.price * q for it, q in lines), start=Decimal("0")))
        if subtotal < restaurant.min_order_amount:
            lines[0] = (lines[0][0], lines[0][1] + 2)
            subtotal = money(sum((it.price * q for it, q in lines), start=Decimal("0")))
        tax, total = calc_totals(subtotal, restaurant.delivery_fee)
        created = now - timedelta(days=20 - i, hours=rng.randint(0, 8))
        order = Order(
            customer_id=customer.id, restaurant_id=restaurant.id, status=final,
            subtotal=subtotal, delivery_fee=restaurant.delivery_fee, tax=tax, total=total,
            delivery_address={"label": address.label, "line1": address.line1, "line2": None,
                              "city": address.city, "state": address.state,
                              "postal_code": address.postal_code},
            rejection_reason="Kitchen closing early today" if final == S.REJECTED else None,
            created_at=created, updated_at=created,
            items=[OrderItem(menu_item_id=it.id, item_name=it.name, unit_price=it.price,
                             quantity=q, line_total=money(it.price * q)) for it, q in lines],
        )  # fmt: skip
        db.add(order)
        db.flush()
        steps = (
            [S.PENDING_PAYMENT, S.PLACED, final]
            if final in (S.CANCELLED, S.REJECTED)
            else flow[: flow.index(final) + 1]
        )
        prev = None
        for n, step in enumerate(steps):
            db.add(OrderStatusHistory(
                order_id=order.id, from_status=prev, to_status=step,
                changed_by=None if step == S.PLACED else customer.id,
                created_at=created + timedelta(minutes=8 * n),
            ))  # fmt: skip
            prev = step
        refunded = final in (S.CANCELLED, S.REJECTED)
        db.add(Payment(
            order_id=order.id, provider="mock", provider_payment_id=f"mock_pay_seed_{order.id}",
            amount=total, currency="INR",
            status=PaymentStatus.REFUNDED if refunded else PaymentStatus.SUCCEEDED,
            refunded_at=created + timedelta(minutes=30) if refunded else None,
        ))  # fmt: skip
        if final == S.DELIVERED and i % 4 != 3:
            rating = rng.choice([3, 4, 4, 5, 5])
            db.add(Review(order_id=order.id, customer_id=customer.id,
                          restaurant_id=restaurant.id, rating=rating,
                          comment=rng.choice(comments)))  # fmt: skip
        orders_created += 1
    db.flush()

    # ---- recompute denormalized ratings from the reviews just inserted
    for restaurant, _ in restaurants:
        avg, count = db.execute(
            select(func.avg(Review.rating), func.count(Review.id)).where(
                Review.restaurant_id == restaurant.id
            )
        ).one()
        restaurant.rating_count = count
        restaurant.avg_rating = Decimal(avg or 0).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    db.add(Complaint(
        raised_by=asha.id, order_id=1, restaurant_id=restaurants[0][0].id,
        subject="Missing item in my order",
        description="The garlic naan was missing from the delivered order.",
    ))  # fmt: skip
    db.add(Notification(user_id=asha.id, type="welcome", title="Welcome to MealConnect",
                        body="Browse restaurants near you and order in a few taps."))  # fmt: skip
    db.commit()
    return {"users": 6, "restaurants": len(restaurants) + 1, "orders": orders_created}


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seed")
    parser.add_argument("--reset", action="store_true", help="wipe all app tables first")
    args = parser.parse_args()
    if settings.is_production:
        print("Refusing to seed a production database.", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        if args.reset:
            wipe(db)
        elif db.scalar(select(func.count(User.id))):
            print("Database already has data. Use --reset to wipe and reseed.", file=sys.stderr)
            return 1
        counts = seed(db)
    print(f"Seeded: {counts}. Demo password for every account: {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
