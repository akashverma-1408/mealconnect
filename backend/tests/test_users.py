"""Profile, password change and address management."""

import pytest

from tests.conftest import auth_headers, login, register

ME = "/api/v1/users/me"
ADDR = "/api/v1/users/me/addresses"

HOME = {
    "label": "Home",
    "line1": "12 MG Road",
    "city": "Pune",
    "state": "MH",
    "postal_code": "411001",
}
WORK = {
    "label": "Work",
    "line1": "5 Tech Park",
    "city": "Pune",
    "state": "MH",
    "postal_code": "411057",
}


# ------------------------------------------------------------------ profile
def test_update_profile(client, customer_headers):
    res = client.patch(
        ME, json={"full_name": "  Asha R.  ", "phone": "9876543210"}, headers=customer_headers
    )
    assert res.status_code == 200
    assert res.json()["full_name"] == "Asha R."
    assert res.json()["phone"] == "9876543210"


def test_update_profile_rejects_bad_phone(client, customer_headers):
    res = client.patch(ME, json={"phone": "12ab"}, headers=customer_headers)
    assert res.status_code == 422


def test_profile_cannot_change_role_or_email(client, customer_headers):
    res = client.patch(ME, json={"role": "admin", "email": "x@y.com"}, headers=customer_headers)
    assert res.status_code == 200  # unknown fields are ignored...
    assert res.json()["role"] == "customer"  # ...so the role is unchanged
    assert res.json()["email"] == "asha@example.com"


# ------------------------------------------------------------------ password
def test_change_password_wrong_current(client, customer_headers):
    res = client.post(
        f"{ME}/change-password",
        json={"current_password": "Nope12345", "new_password": "NewSecret456"},
        headers=customer_headers,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "WRONG_PASSWORD"


def test_change_password_success_signs_out_other_sessions(
    client, customer_tokens, customer_headers
):
    res = client.post(
        f"{ME}/change-password",
        json={"current_password": "Secret123", "new_password": "NewSecret456"},
        headers=customer_headers,
    )
    assert res.status_code == 204
    old_refresh = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": customer_tokens["refresh_token"]}
    )
    assert old_refresh.status_code == 401
    assert login(client, password="Secret123").status_code == 401
    assert login(client, password="NewSecret456").status_code == 200


# ------------------------------------------------------------------ addresses
def test_first_address_becomes_default(client, customer_headers):
    res = client.post(ADDR, json=HOME, headers=customer_headers)
    assert res.status_code == 201
    assert res.json()["is_default"] is True


def test_new_default_address_replaces_old_default(client, customer_headers):
    home = client.post(ADDR, json=HOME, headers=customer_headers).json()
    work = client.post(ADDR, json={**WORK, "is_default": True}, headers=customer_headers).json()
    listing = {a["id"]: a["is_default"] for a in client.get(ADDR, headers=customer_headers).json()}
    assert listing == {home["id"]: False, work["id"]: True}


def test_patch_address_to_default(client, customer_headers):
    home = client.post(ADDR, json=HOME, headers=customer_headers).json()
    work = client.post(ADDR, json=WORK, headers=customer_headers).json()
    res = client.patch(
        f"{ADDR}/{work['id']}",
        json={"is_default": True, "line2": "Floor 3"},
        headers=customer_headers,
    )
    assert res.status_code == 200
    assert res.json()["is_default"] is True
    assert res.json()["line2"] == "Floor 3"
    listing = {a["id"]: a["is_default"] for a in client.get(ADDR, headers=customer_headers).json()}
    assert listing == {home["id"]: False, work["id"]: True}


def test_patch_address_cannot_null_required_field(client, customer_headers):
    home = client.post(ADDR, json=HOME, headers=customer_headers).json()
    res = client.patch(f"{ADDR}/{home['id']}", json={"city": None}, headers=customer_headers)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "FIELD_REQUIRED"


def test_deleting_default_promotes_another_address(client, customer_headers):
    home = client.post(ADDR, json=HOME, headers=customer_headers).json()
    work = client.post(ADDR, json=WORK, headers=customer_headers).json()
    assert client.delete(f"{ADDR}/{home['id']}", headers=customer_headers).status_code == 204
    remaining = client.get(ADDR, headers=customer_headers).json()
    assert [(a["id"], a["is_default"]) for a in remaining] == [(work["id"], True)]


@pytest.mark.parametrize("bad", [{"postal_code": "!!"}, {"line1": ""}, {"city": "x" * 81}])
def test_address_validation(client, customer_headers, bad):
    res = client.post(ADDR, json={**HOME, **bad}, headers=customer_headers)
    assert res.status_code == 422


def test_cannot_see_or_edit_another_users_address(client, customer_headers):
    home = client.post(ADDR, json=HOME, headers=customer_headers).json()
    register(client, email="ravi@example.com")
    ravi = auth_headers(login(client, email="ravi@example.com").json()["access_token"])

    assert client.get(ADDR, headers=ravi).json() == []
    res = client.patch(f"{ADDR}/{home['id']}", json={"city": "Goa"}, headers=ravi)
    assert res.status_code == 404  # "not found", not 403: don't reveal it exists
    assert client.delete(f"{ADDR}/{home['id']}", headers=ravi).status_code == 404


def test_restaurant_owner_cannot_use_customer_addresses(client):
    register(client, email="owner@example.com", role="restaurant_owner")
    owner = auth_headers(login(client, email="owner@example.com").json()["access_token"])
    res = client.get(ADDR, headers=owner)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "ROLE_FORBIDDEN"
