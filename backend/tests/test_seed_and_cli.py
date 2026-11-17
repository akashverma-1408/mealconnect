"""The demo-data seed and the create-admin command, run inside a rolled-back transaction."""

from contextlib import nullcontext

import pytest
from sqlalchemy import func, select

from app import cli
from app.models import Complaint, MenuItem, Order, Restaurant, Review, User, UserRole
from app.seed import DEMO_PASSWORD, seed
from tests.conftest import login


def test_seed_creates_consistent_demo_data(db_session):
    counts = seed(db_session)
    assert counts == {"users": 6, "restaurants": 7, "orders": 18}
    assert db_session.scalar(select(func.count(MenuItem.id))) == 36

    # Every denormalized rating matches its reviews.
    for r in db_session.scalars(select(Restaurant)):
        avg = db_session.scalar(select(func.avg(Review.rating)).where(Review.restaurant_id == r.id))
        count = db_session.scalar(select(func.count(Review.id)).where(Review.restaurant_id == r.id))
        assert r.rating_count == count
        assert float(r.avg_rating) == pytest.approx(float(avg or 0), abs=0.05)

    # The complaint points at one of Asha's own orders (no hard-coded ids).
    complaint = db_session.scalar(select(Complaint))
    order = db_session.get(Order, complaint.order_id)
    assert order.customer.email == "asha@example.com"
    assert complaint.restaurant_id == order.restaurant_id


def test_seeded_accounts_can_log_in(client, db_session):
    seed(db_session)
    for email in ("admin@example.com", "owner.spice@example.com", "asha@example.com"):
        assert login(client, email=email, password=DEMO_PASSWORD).status_code == 200


def run_cli(monkeypatch, db_session, args, passwords):
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db_session))
    answers = iter(passwords)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    monkeypatch.setattr("sys.argv", ["app.cli", *args])
    return cli.main()


def test_create_admin(monkeypatch, db_session, capsys):
    code = run_cli(monkeypatch, db_session,
                   ["create-admin", "--email", "Boss@Example.com", "--name", "Big Boss"],
                   ["Secret123", "Secret123"])  # fmt: skip
    assert code == 0
    admin = db_session.scalar(select(User).where(User.email == "boss@example.com"))
    assert admin.role == UserRole.ADMIN
    assert "Admin created" in capsys.readouterr().out


@pytest.mark.parametrize(
    "passwords,message",
    [
        (["Secret123", "Different1"], "Passwords do not match"),
        (["weak", "weak"], "password"),  # same strength rules as the API
    ],
)
def test_create_admin_rejects_bad_passwords(monkeypatch, db_session, capsys, passwords, message):
    code = run_cli(
        monkeypatch,
        db_session,
        ["create-admin", "--email", "a@example.com", "--name", "Al"],
        passwords,
    )
    assert code == 1
    assert message in capsys.readouterr().err


def test_create_admin_refuses_duplicate_email(monkeypatch, db_session, capsys):
    args = ["create-admin", "--email", "boss@example.com", "--name", "Big Boss"]
    assert run_cli(monkeypatch, db_session, args, ["Secret123", "Secret123"]) == 0
    assert run_cli(monkeypatch, db_session, args, ["Secret123", "Secret123"]) == 1
    assert "already exists" in capsys.readouterr().err


def test_reset_clears_cached_catalogue_and_rate_limits():
    from app.core.redis import get_redis
    from app.seed import clear_redis_state

    r = get_redis()
    r.set("mc:cache:menu:1", "{}")
    r.set("mc:rl:login:1.2.3.4:a@b.c:1", 5)
    r.set("mc:jobs:keep-me", 1)  # queued jobs are NOT cache: leave them alone
    assert clear_redis_state() == 2
    assert r.exists("mc:jobs:keep-me") and not r.exists("mc:cache:menu:1")
