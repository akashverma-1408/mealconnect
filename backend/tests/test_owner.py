"""Restaurant owner: registration, profile, categories, menu items, analytics."""

from tests.conftest import API, place_paid_order

NEW = {
    "name": "Taco Town", "cuisine": "Mexican", "city": "Pune", "address": "4 Food Street",
    "delivery_fee": "25.50", "min_order_amount": "150",
}  # fmt: skip


def test_register_restaurant_starts_pending_and_hidden(client, world):
    res = client.post(f"{API}/owner/restaurants", json=NEW, headers=world.owner_h)
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "pending" and body["slug"] == "taco-town"
    assert body["delivery_fee"] == "25.50"
    public = client.get(f"{API}/restaurants", params={"q": "taco"}).json()
    assert public["total"] == 0  # not visible until approved
    mine = client.get(f"{API}/owner/restaurants", headers=world.owner_h).json()
    assert {r["name"] for r in mine} == {"Spice Route", "Taco Town"}


def test_duplicate_names_get_unique_slugs(client, world):
    a = client.post(f"{API}/owner/restaurants", json=NEW, headers=world.owner_h).json()
    b = client.post(f"{API}/owner/restaurants", json=NEW, headers=world.owner_h).json()
    assert (a["slug"], b["slug"]) == ("taco-town", "taco-town-2")


def test_restaurant_validation(client, world):
    bad = {**NEW, "delivery_fee": "-1", "opens_at": "10:00"}
    res = client.post(f"{API}/owner/restaurants", json=bad, headers=world.owner_h)
    assert res.status_code == 422
    fields = {d["field"] for d in res.json()["error"]["details"]}
    assert "delivery_fee" in fields


def test_only_owners_can_register(client, world):
    res = client.post(f"{API}/owner/restaurants", json=NEW, headers=world.customer_h)
    assert res.status_code == 403


def test_update_profile_and_toggle_open(client, world):
    rid = world.restaurant.id
    res = client.patch(f"{API}/owner/restaurants/{rid}", json={"is_open": False, "delivery_fee": 0},
                       headers=world.owner_h)  # fmt: skip
    assert res.json()["is_open"] is False and res.json()["delivery_fee"] == "0.00"
    bad = client.patch(f"{API}/owner/restaurants/{rid}", json={"name": None}, headers=world.owner_h)
    assert bad.status_code == 400


def test_category_crud(client, world):
    base = f"{API}/owner/restaurants/{world.restaurant.id}/categories"
    created = client.post(base, json={"name": "Desserts", "sort_order": 5}, headers=world.owner_h)
    assert created.status_code == 201
    dup = client.post(base, json={"name": "Desserts"}, headers=world.owner_h)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "CATEGORY_EXISTS"
    cid = created.json()["id"]
    renamed = client.patch(f"{base}/{cid}", json={"name": "Sweets"}, headers=world.owner_h)
    assert renamed.json()["name"] == "Sweets"
    assert client.delete(f"{base}/{cid}", headers=world.owner_h).status_code == 204
    assert [c["name"] for c in client.get(base, headers=world.owner_h).json()] == ["Mains"]


def test_deleting_category_keeps_items(client, world):
    base = f"{API}/owner/restaurants/{world.restaurant.id}"
    client.delete(f"{base}/categories/{world.category.id}", headers=world.owner_h)
    items = client.get(f"{base}/menu-items", headers=world.owner_h).json()
    assert len(items) == 3 and all(i["category_id"] is None for i in items)


def test_menu_item_crud_and_availability(client, world):
    base = f"{API}/owner/restaurants/{world.restaurant.id}/menu-items"
    body = {"name": "Gulab Jamun", "price": "79", "is_veg": True, "category_id": world.category.id}
    created = client.post(base, json=body, headers=world.owner_h)
    assert created.status_code == 201 and created.json()["price"] == "79.00"
    iid = created.json()["id"]

    upd = client.patch(f"{base}/{iid}", json={"price": "89.50"}, headers=world.owner_h)
    assert upd.json()["price"] == "89.50"
    off = client.patch(
        f"{base}/{iid}/availability", json={"is_available": False}, headers=world.owner_h
    )  # noqa: E501
    assert off.json()["is_available"] is False

    assert client.post(base, json={**body, "price": "0"}, headers=world.owner_h).status_code == 422
    assert client.delete(f"{base}/{iid}", headers=world.owner_h).status_code == 204
    assert (
        client.patch(f"{base}/{iid}", json={"price": "1"}, headers=world.owner_h).status_code == 404
    )


def test_item_cannot_use_another_restaurants_category(client, world):
    other = client.post(f"{API}/owner/restaurants", json=NEW, headers=world.owner_h).json()
    cat = client.post(f"{API}/owner/restaurants/{other['id']}/categories", json={"name": "Tacos"},
                      headers=world.owner_h).json()  # fmt: skip
    res = client.post(
        f"{API}/owner/restaurants/{world.restaurant.id}/menu-items",
        json={"name": "Thing", "price": "10", "is_veg": True, "category_id": cat["id"]},
        headers=world.owner_h,
    )
    assert res.status_code == 404 and res.json()["error"]["code"] == "CATEGORY_NOT_FOUND"


def test_deleting_item_keeps_order_history_and_clears_carts(client, world):
    order = place_paid_order(client, world)
    client.post(
        f"{API}/cart/items", json={"menu_item_id": world.items[0].id}, headers=world.other_h
    )
    url = f"{API}/owner/restaurants/{world.restaurant.id}/menu-items/{world.items[0].id}"
    assert client.delete(url, headers=world.owner_h).status_code == 204
    again = client.get(f"{API}/orders/{order['id']}", headers=world.customer_h).json()
    assert "Paneer Tikka" in [i["item_name"] for i in again["items"]]
    assert client.get(f"{API}/cart", headers=world.other_h).json()["items"] == []


def test_other_owner_cannot_manage_restaurant(client, world, db_session):
    from app.models.user import UserRole
    from tests.conftest import headers_for, make_user

    make_user(db_session, "rival@example.com", UserRole.RESTAURANT_OWNER)
    rival = headers_for(client, "rival@example.com")
    base = f"{API}/owner/restaurants/{world.restaurant.id}"
    assert client.patch(base, json={"name": "Hacked"}, headers=rival).status_code == 404
    assert client.get(f"{base}/menu-items", headers=rival).status_code == 404


def test_analytics(client, world):
    o1 = place_paid_order(client, world)  # 2 x Paneer + 1 Naan
    o2 = place_paid_order(client, world, quantities=((1, 1),))  # 1 Butter Chicken
    client.post(f"{API}/owner/orders/{o2['id']}/reject", json={"reason": "Closed"},
                headers=world.owner_h)  # fmt: skip
    res = client.get(
        f"{API}/owner/restaurants/{world.restaurant.id}/analytics", headers=world.owner_h
    )
    data = res.json()
    assert res.status_code == 200
    assert data["order_count"] == 1  # the rejected order is not revenue
    assert data["revenue"] == o1["total"]
    assert data["orders_by_status"] == {"PLACED": 1, "REJECTED": 1}
    assert data["top_items"][0]["name"] == "Paneer Tikka" and data["top_items"][0]["quantity"] == 2
    assert len(data["daily"]) == 30 and sum(d["orders"] for d in data["daily"]) == 1

    bad = client.get(f"{API}/owner/restaurants/{world.restaurant.id}/analytics",
                     params={"date_from": "2026-02-01", "date_to": "2026-01-01"},
                     headers=world.owner_h)  # fmt: skip
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_RANGE"
