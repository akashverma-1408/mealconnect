"""Registration, login, token refresh/rotation, logout and access control."""

from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select

from app.core.config import settings
from app.models.user import RefreshToken, User, UserStatus
from tests.conftest import auth_headers, login, register

ME = "/api/v1/users/me"


# ------------------------------------------------------------------ register
def test_register_success(client):
    res = register(client, email="  Asha@Example.COM ", phone="+91 98765-43210")
    assert res.status_code == 201
    body = res.json()
    assert body["email"] == "asha@example.com"  # normalized
    assert body["role"] == "customer"
    assert body["status"] == "active"
    assert body["phone"] == "+919876543210"
    assert "password" not in body and "password_hash" not in body


def test_timestamps_are_returned_in_utc(client):
    created_at = register(client).json()["created_at"]
    assert created_at.endswith("Z") or created_at.endswith("+00:00")


def test_register_stores_hash_not_password(client, db_session):
    register(client)
    user = db_session.scalar(select(User).where(User.email == "asha@example.com"))
    assert user.password_hash != "Secret123"
    assert user.password_hash.startswith("$2b$")  # bcrypt format


def test_register_restaurant_owner(client):
    res = register(client, email="owner@example.com", role="restaurant_owner")
    assert res.status_code == 201
    assert res.json()["role"] == "restaurant_owner"


def test_register_duplicate_email_is_case_insensitive(client):
    register(client)
    res = register(client, email="ASHA@example.com")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "EMAIL_TAKEN"


def test_register_cannot_create_admin(client):
    res = register(client, role="admin")
    assert res.status_code == 422
    assert res.json()["error"]["details"][0]["field"] == "role"


def test_register_rejects_weak_password(client):
    res = register(client, password="onlyletters")
    assert res.status_code == 422
    details = res.json()["error"]["details"]
    assert details[0]["field"] == "password"
    assert "letter and one digit" in details[0]["message"]


def test_register_rejects_short_password_and_bad_email(client):
    res = client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "a1", "full_name": "A"},
    )
    assert res.status_code == 422
    fields = {d["field"] for d in res.json()["error"]["details"]}
    assert fields == {"email", "password", "full_name"}


# ------------------------------------------------------------------ login
def test_login_success_returns_tokens_and_user(client):
    register(client)
    res = login(client, email="ASHA@example.com")
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert body["user"]["email"] == "asha@example.com"
    payload = jwt.decode(body["access_token"], settings.JWT_SECRET_KEY, algorithms=["HS256"])
    assert payload["type"] == "access"
    assert payload["role"] == "customer"


def test_login_wrong_password_and_unknown_email_look_identical(client):
    register(client)
    wrong_pw = login(client, password="Wrong1234")
    unknown = login(client, email="nobody@example.com")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert wrong_pw.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_suspended_user_is_forbidden(client, db_session):
    register(client)
    user = db_session.scalar(select(User).where(User.email == "asha@example.com"))
    user.status = UserStatus.SUSPENDED
    db_session.commit()
    res = login(client)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "ACCOUNT_SUSPENDED"


# ------------------------------------------------------------------ protected routes
def test_me_requires_token(client):
    res = client.get(ME)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "NOT_AUTHENTICATED"
    assert res.headers["www-authenticate"] == "Bearer"


def test_me_with_valid_token(client, customer_headers):
    res = client.get(ME, headers=customer_headers)
    assert res.status_code == 200
    assert res.json()["email"] == "asha@example.com"


def test_me_rejects_garbage_token(client):
    res = client.get(ME, headers=auth_headers("not.a.jwt"))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_TOKEN"


def test_me_rejects_refresh_token_used_as_access_token(client, customer_tokens):
    res = client.get(ME, headers=auth_headers(customer_tokens["refresh_token"]))
    assert res.status_code == 401
    assert res.json()["error"]["message"] == "Wrong token type"


def test_me_rejects_token_signed_with_other_secret(client, customer_tokens):
    payload = jwt.decode(
        customer_tokens["access_token"], settings.JWT_SECRET_KEY, algorithms=["HS256"]
    )
    forged = jwt.encode({**payload, "role": "admin"}, "attacker-secret-key-32-bytes-long!!")
    res = client.get(ME, headers=auth_headers(forged))
    assert res.status_code == 401


def test_me_rejects_expired_token(client, customer_tokens):
    payload = jwt.decode(
        customer_tokens["access_token"], settings.JWT_SECRET_KEY, algorithms=["HS256"]
    )
    payload["exp"] = datetime.now(UTC) - timedelta(minutes=1)
    expired = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")
    res = client.get(ME, headers=auth_headers(expired))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_suspension_blocks_existing_access_token_immediately(client, db_session, customer_headers):
    user = db_session.scalar(select(User).where(User.email == "asha@example.com"))
    user.status = UserStatus.SUSPENDED
    db_session.commit()
    res = client.get(ME, headers=customer_headers)
    assert res.status_code == 403


# ------------------------------------------------------------------ refresh / logout
def test_refresh_rotates_tokens(client, customer_tokens):
    res = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": customer_tokens["refresh_token"]}
    )
    assert res.status_code == 200
    new = res.json()
    assert new["refresh_token"] != customer_tokens["refresh_token"]
    assert client.get(ME, headers=auth_headers(new["access_token"])).status_code == 200


def test_refresh_token_reuse_revokes_all_sessions(client, db_session, customer_tokens):
    old = customer_tokens["refresh_token"]
    new = client.post("/api/v1/auth/refresh", json={"refresh_token": old}).json()

    # An attacker replays the old (already rotated) token...
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "TOKEN_REVOKED"

    # ...so the legitimate new refresh token is revoked as well.
    res = client.post("/api/v1/auth/refresh", json={"refresh_token": new["refresh_token"]})
    assert res.status_code == 401
    active = db_session.scalars(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
    assert list(active) == []


def test_refresh_rejects_access_token(client, customer_tokens):
    res = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": customer_tokens["access_token"]}
    )
    assert res.status_code == 401


def test_logout_revokes_refresh_token(client, customer_tokens, customer_headers):
    refresh_token = customer_tokens["refresh_token"]
    res = client.post(
        "/api/v1/auth/logout", json={"refresh_token": refresh_token}, headers=customer_headers
    )
    assert res.status_code == 204
    res = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert res.status_code == 401
    # Logging out twice is harmless (idempotent).
    res = client.post(
        "/api/v1/auth/logout", json={"refresh_token": refresh_token}, headers=customer_headers
    )
    assert res.status_code == 204
