"""Shared pytest fixtures.

Strategy
--------
1. Point the app at the *test* database before anything imports app settings.
2. Once per test run: wipe the test schema and run every Alembic migration
   (this also proves the migrations work on an empty database).
3. Per test: open a transaction, run the test, roll everything back — each test starts
   with empty tables and tests cannot affect each other.
"""

import os
from collections.abc import Iterator
from pathlib import Path

from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parents[1]
_env = {**dotenv_values(BACKEND_DIR / ".env"), **os.environ}
TEST_DATABASE_URL = _env.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL or not TEST_DATABASE_URL.rsplit("/", 1)[-1].endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL must be set and point to a database ending in _test")

# Environment variables override backend/.env, so the app now uses the test database.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app.db.session import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False  # keep pytest's logging setup
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A session whose changes are rolled back after the test.

    join_transaction_mode="create_savepoint": when app code calls commit(), only a
    SAVEPOINT is released; the outer transaction is still rolled back at the end.
    """
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """HTTP client calling the app in-process, using the rolled-back test session."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ----------------------------------------------------------------- helpers
DEFAULT_PASSWORD = "Secret123"


def register(
    client: TestClient,
    email: str = "asha@example.com",
    role: str = "customer",
    password: str = DEFAULT_PASSWORD,
    **extra: str,
):
    body = {"email": email, "password": password, "full_name": "Asha Rao", "role": role, **extra}
    return client.post("/api/v1/auth/register", json=body)


def login(client: TestClient, email: str = "asha@example.com", password: str = DEFAULT_PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def customer_tokens(client: TestClient) -> dict:
    assert register(client).status_code == 201
    return login(client).json()


@pytest.fixture
def customer_headers(customer_tokens: dict) -> dict[str, str]:
    return auth_headers(customer_tokens["access_token"])


# ----------------------------------------------------------------- domain fixtures
API = "/api/v1"


def make_user(db, email: str, role, name: str = "Test User"):
    """Insert a user directly (faster than the API) — login still goes through the API."""
    from app.core.security import hash_password
    from app.models.user import User

    user = User(
        email=email, full_name=name, role=role, password_hash=hash_password(DEFAULT_PASSWORD)
    )
    db.add(user)
    db.commit()
    return user


def headers_for(client: TestClient, email: str) -> dict[str, str]:
    res = login(client, email=email)
    assert res.status_code == 200, res.text
    return auth_headers(res.json()["access_token"])


@pytest.fixture
def world(client, db_session):
    """A small marketplace: admin, owner with an approved restaurant + menu, two customers."""
    from decimal import Decimal
    from types import SimpleNamespace

    from app.models.restaurant import MenuCategory, MenuItem, Restaurant, RestaurantStatus
    from app.models.user import Address, UserRole

    admin = make_user(db_session, "admin@example.com", UserRole.ADMIN, "Ada Admin")
    owner = make_user(db_session, "owner@example.com", UserRole.RESTAURANT_OWNER, "Omar Owner")
    customer = make_user(db_session, "cust@example.com", UserRole.CUSTOMER, "Cara Customer")
    make_user(db_session, "other@example.com", UserRole.CUSTOMER, "Otto Other")

    restaurant = Restaurant(
        owner_id=owner.id, name="Spice Route", slug="spice-route", cuisine="North Indian",
        city="Pune", address="1 Main Street, Pune", status=RestaurantStatus.APPROVED,
        delivery_fee=Decimal("30.00"), min_order_amount=Decimal("100.00"),
    )  # fmt: skip
    db_session.add(restaurant)
    db_session.flush()
    category = MenuCategory(restaurant_id=restaurant.id, name="Mains")
    db_session.add(category)
    db_session.flush()
    items = [
        MenuItem(restaurant_id=restaurant.id, category_id=category.id, name="Paneer Tikka",
                 price=Decimal("249.00"), is_veg=True),
        MenuItem(restaurant_id=restaurant.id, category_id=category.id, name="Butter Chicken",
                 price=Decimal("349.00"), is_veg=False),
        MenuItem(restaurant_id=restaurant.id, name="Garlic Naan", price=Decimal("59.00"),
                 is_veg=True),
    ]  # fmt: skip
    db_session.add_all(items)
    address = Address(user_id=customer.id, label="Home", line1="12 MG Road", city="Pune",
                      state="MH", postal_code="411001", is_default=True)  # fmt: skip
    db_session.add(address)
    db_session.commit()

    return SimpleNamespace(
        admin=admin, owner=owner, customer=customer, restaurant=restaurant,
        category=category, items=items, address=address,
        admin_h=headers_for(client, "admin@example.com"),
        owner_h=headers_for(client, "owner@example.com"),
        customer_h=headers_for(client, "cust@example.com"),
        other_h=headers_for(client, "other@example.com"),
    )  # fmt: skip


def place_paid_order(client: TestClient, w, quantities=((0, 2), (2, 1))) -> dict:
    """Cart -> order -> checkout -> successful sandbox payment. Returns the order JSON."""
    for idx, qty in quantities:
        res = client.post(
            f"{API}/cart/items",
            json={"menu_item_id": w.items[idx].id, "quantity": qty},
            headers=w.customer_h,
        )
        assert res.status_code == 200, res.text
    order = client.post(f"{API}/orders", json={"address_id": w.address.id}, headers=w.customer_h)
    assert order.status_code == 201, order.text
    oid = order.json()["id"]
    assert (
        client.post(f"{API}/payments/orders/{oid}/checkout", headers=w.customer_h).status_code
        == 200
    )  # noqa: E501
    paid = client.post(f"{API}/payments/sandbox/orders/{oid}/pay", headers=w.customer_h)
    assert paid.json() == {"status": "processed"}, paid.text
    return client.get(f"{API}/orders/{oid}", headers=w.customer_h).json()
