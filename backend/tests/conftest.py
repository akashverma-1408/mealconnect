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
