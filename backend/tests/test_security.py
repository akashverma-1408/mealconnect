"""Unit tests for app.core.security (no database, no HTTP)."""

import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password():
    hashed = hash_password("Secret123")
    assert hashed != "Secret123"
    assert verify_password("Secret123", hashed)
    assert not verify_password("secret123", hashed)


def test_same_password_gets_different_hashes():
    assert hash_password("Secret123") != hash_password("Secret123")  # random salt


def test_verify_password_with_malformed_hash_returns_false():
    assert verify_password("Secret123", "not-a-bcrypt-hash") is False


def test_access_token_round_trip():
    issued = create_access_token(42, "customer")
    payload = decode_token(issued.token, "access")
    assert payload["sub"] == "42"
    assert payload["role"] == "customer"
    assert payload["jti"] == issued.jti


def test_token_type_is_enforced():
    refresh = create_refresh_token(42)
    with pytest.raises(InvalidTokenError, match="Wrong token type"):
        decode_token(refresh.token, "access")


def test_tampered_token_is_rejected():
    token = create_access_token(42, "customer").token
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(InvalidTokenError):
        decode_token(tampered, "access")
