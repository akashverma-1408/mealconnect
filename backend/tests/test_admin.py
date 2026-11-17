"""Administrator: user/restaurant moderation, order monitoring, complaints, analytics, audit."""

from tests.conftest import API, login, place_paid_order


def test_admin_endpoints_require_admin_role(client, world):
    for headers in (world.customer_h, world.owner_h):
        res = client.get(f"{API}/admin/users", headers=headers)
        assert res.status_code == 403
    assert client.get(f"{API}/admin/users").status_code == 401


def test_list_and_filter_users(client, world):
    res = client.get(f"{API}/admin/users", params={"role": "customer"}, headers=world.admin_h)
    assert {u["email"] for u in res.json()["items"]} == {"cust@example.com", "other@example.com"}
    q = client.get(f"{API}/admin/users", params={"q": "omar"}, headers=world.admin_h).json()
    assert [u["email"] for u in q["items"]] == ["owner@example.com"]


def test_suspend_user_blocks_access_and_is_audited(client, world):
    url = f"{API}/admin/users/{world.customer.id}/status"
    res = client.patch(url, json={"status": "suspended", "reason": "Fraud"}, headers=world.admin_h)
    assert res.status_code == 200 and res.json()["status"] == "suspended"
    assert client.get(f"{API}/users/me", headers=world.customer_h).status_code == 403
    assert login(client, email="cust@example.com").status_code == 403

    client.patch(url, json={"status": "active"}, headers=world.admin_h)
    assert login(client, email="cust@example.com").status_code == 200

    logs = client.get(f"{API}/admin/audit-logs", params={"entity_type": "user"},
                      headers=world.admin_h).json()  # fmt: skip
    assert [entry["action"] for entry in logs["items"]] == ["user.active", "user.suspended"]
    assert logs["items"][1]["details"]["reason"] == "Fraud"


def test_admin_cannot_suspend_self_or_admins(client, world):
    me = client.patch(f"{API}/admin/users/{world.admin.id}/status", json={"status": "suspended"},
                      headers=world.admin_h)  # fmt: skip
    assert me.status_code == 400 and me.json()["error"]["code"] == "CANNOT_MODIFY_SELF"


def test_restaurant_approval_flow(client, world):
    new = client.post(
        f"{API}/owner/restaurants",
        json={"name": "Taco Town", "cuisine": "Mexican", "city": "Pune", "address": "4 Food St"},
        headers=world.owner_h,
    ).json()
    pending = client.get(f"{API}/admin/restaurants", params={"status": "pending"},
                         headers=world.admin_h).json()  # fmt: skip
    assert [r["name"] for r in pending["items"]] == ["Taco Town"]

    url = f"{API}/admin/restaurants/{new['id']}/status"
    no_reason = client.patch(url, json={"status": "rejected"}, headers=world.admin_h)
    assert no_reason.json()["error"]["code"] == "REASON_REQUIRED"
    approved = client.patch(url, json={"status": "approved"}, headers=world.admin_h)
    assert approved.json()["status"] == "approved"
    assert client.get(f"{API}/restaurants/{new['id']}").status_code == 200

    client.patch(url, json={"status": "suspended", "reason": "Hygiene"}, headers=world.admin_h)
    assert client.get(f"{API}/restaurants/{new['id']}").status_code == 404
    owner_notes = client.get(f"{API}/notifications", headers=world.owner_h).json()["items"]
    assert owner_notes[0]["type"] == "restaurant.suspended"


def test_admin_monitors_and_force_cancels_orders(client, world):
    oid = place_paid_order(client, world)["id"]
    client.post(f"{API}/owner/orders/{oid}/accept", headers=world.owner_h)
    listing = client.get(f"{API}/admin/orders", params={"status": "ACCEPTED"},
                         headers=world.admin_h).json()  # fmt: skip
    assert [o["id"] for o in listing["items"]] == [oid]
    res = client.post(f"{API}/admin/orders/{oid}/cancel", json={"reason": "Customer complaint"},
                      headers=world.admin_h)  # fmt: skip
    assert res.json()["status"] == "CANCELLED" and res.json()["payment_status"] == "refunded"
    again = client.post(f"{API}/admin/orders/{oid}/cancel", headers=world.admin_h)
    assert again.status_code == 400  # already final


def test_complaint_lifecycle(client, world):
    oid = place_paid_order(client, world)["id"]
    created = client.post(
        f"{API}/complaints",
        json={"order_id": oid, "subject": "Cold food", "description": "Everything arrived cold."},
        headers=world.customer_h,
    )
    assert created.status_code == 201 and created.json()["restaurant_id"] == world.restaurant.id
    cid = created.json()["id"]
    foreign = client.post(f"{API}/complaints", json={"order_id": oid, "subject": "Not mine",
                          "description": "Someone else's order."}, headers=world.other_h)  # fmt: skip
    assert foreign.status_code == 404

    url = f"{API}/admin/complaints/{cid}"
    early = client.patch(url, json={"status": "resolved"}, headers=world.admin_h)
    assert early.json()["error"]["code"] == "RESOLUTION_NOTE_REQUIRED"
    assigned = client.patch(url, json={"status": "in_progress", "assigned_admin_id": world.admin.id},
                            headers=world.admin_h)  # fmt: skip
    assert assigned.json()["assigned_admin_id"] == world.admin.id
    bad_assignee = client.patch(url, json={"assigned_admin_id": world.customer.id},
                                headers=world.admin_h)  # fmt: skip
    assert bad_assignee.json()["error"]["code"] == "NOT_AN_ADMIN"
    done = client.patch(url, json={"status": "resolved", "resolution_note": "Refund issued"},
                        headers=world.admin_h)  # fmt: skip
    assert done.json()["status"] == "resolved" and done.json()["resolved_at"]
    mine = client.get(f"{API}/complaints", headers=world.customer_h).json()
    assert mine["items"][0]["status"] == "resolved"


def test_platform_analytics(client, world):
    o = place_paid_order(client, world)
    data = client.get(f"{API}/admin/analytics/overview", headers=world.admin_h).json()
    assert data["gmv"] == o["total"] and data["order_count"] == 1
    assert data["users_by_role"] == {"admin": 1, "restaurant_owner": 1, "customer": 2}
    assert data["restaurants_by_status"] == {"approved": 1}
    assert data["top_restaurants"][0]["name"] == "Spice Route"
    assert data["new_users"] == 4
