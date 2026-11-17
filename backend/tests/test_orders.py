"""Cart, checkout, payments (webhooks), the order state machine, refunds, reviews."""

import json

from sqlalchemy import select

from app.models.engagement import Notification
from app.models.order import CartItem
from app.models.restaurant import Restaurant
from app.services.payment_providers import get_provider
from tests.conftest import API, place_paid_order


def add(client, w, idx, qty=1, headers=None):
    return client.post(
        f"{API}/cart/items",
        json={"menu_item_id": w.items[idx].id, "quantity": qty},
        headers=headers or w.customer_h,
    )


# ------------------------------------------------------------------ cart
def test_cart_totals(client, world):
    add(client, world, 0, 2)  # 2 x 249
    cart = add(client, world, 2, 1).json()  # + 59
    assert cart["subtotal"] == "557.00"
    assert cart["delivery_fee"] == "30.00"
    assert cart["tax"] == "27.85"  # 5 % of 557
    assert cart["total"] == "614.85"
    assert cart["item_count"] == 3 and cart["can_checkout"] is True


def test_adding_same_item_increases_quantity(client, world):
    add(client, world, 0, 2)
    cart = add(client, world, 0, 3).json()
    assert [(i["name"], i["quantity"]) for i in cart["items"]] == [("Paneer Tikka", 5)]
    assert add(client, world, 0, 46).json()["error"]["code"] == "QUANTITY_LIMIT"


def test_cart_is_single_restaurant(client, world, db_session):
    from decimal import Decimal

    from app.models.restaurant import MenuItem, RestaurantStatus

    other = Restaurant(owner_id=world.owner.id, name="Other", slug="other", cuisine="X",
                       city="Pune", address="2 Road", status=RestaurantStatus.APPROVED)  # fmt: skip
    db_session.add(other)
    db_session.flush()
    dish = MenuItem(restaurant_id=other.id, name="Dish", price=Decimal("100"), is_veg=True)
    db_session.add(dish)
    db_session.commit()
    add(client, world, 0)
    res = client.post(f"{API}/cart/items", json={"menu_item_id": dish.id}, headers=world.customer_h)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "CART_RESTAURANT_MISMATCH"


def test_cannot_add_unavailable_item(client, world, db_session):
    world.items[1].is_available = False
    db_session.commit()
    res = add(client, world, 1)
    assert res.status_code == 400 and res.json()["error"]["code"] == "ITEM_UNAVAILABLE"


def test_cart_update_remove_clear(client, world):
    add(client, world, 0)
    add(client, world, 2)
    item0 = world.items[0].id
    upd = client.patch(f"{API}/cart/items/{item0}", json={"quantity": 4}, headers=world.customer_h)
    assert upd.json()["item_count"] == 5
    rem = client.delete(f"{API}/cart/items/{item0}", headers=world.customer_h).json()
    assert [i["name"] for i in rem["items"]] == ["Garlic Naan"]
    assert client.delete(f"{API}/cart", headers=world.customer_h).status_code == 204
    assert client.get(f"{API}/cart", headers=world.customer_h).json()["items"] == []


def test_owner_cannot_use_cart(client, world):
    res = client.get(f"{API}/cart", headers=world.owner_h)
    assert res.status_code == 403 and res.json()["error"]["code"] == "ROLE_FORBIDDEN"


# ------------------------------------------------------------------ checkout
def test_place_order_snapshots_prices_and_clears_cart(client, world, db_session):
    add(client, world, 0, 2)
    res = client.post(f"{API}/orders", json={"address_id": world.address.id, "notes": "Less spicy"},
                      headers=world.customer_h)  # fmt: skip
    assert res.status_code == 201
    order = res.json()
    assert order["status"] == "PENDING_PAYMENT"
    assert order["total"] == "552.90"  # 498 + 30 + 24.90
    assert order["delivery_address"]["line1"] == "12 MG Road"
    assert [h["to_status"] for h in order["history"]] == ["PENDING_PAYMENT"]
    assert db_session.scalars(select(CartItem)).all() == []

    # Later price change does not affect the placed order.
    world.items[0].price = 999
    db_session.commit()
    again = client.get(f"{API}/orders/{order['id']}", headers=world.customer_h).json()
    assert again["items"][0]["unit_price"] == "249.00"


def test_checkout_rules(client, world, db_session):
    body = {"address_id": world.address.id}
    empty = client.post(f"{API}/orders", json=body, headers=world.customer_h)
    assert empty.json()["error"]["code"] == "CART_EMPTY"

    add(client, world, 2)  # 59 < minimum 100
    small = client.post(f"{API}/orders", json=body, headers=world.customer_h)
    assert small.json()["error"]["code"] == "MIN_ORDER_NOT_MET"

    add(client, world, 0)
    world.restaurant.is_open = False
    db_session.commit()
    closed = client.post(f"{API}/orders", json=body, headers=world.customer_h)
    assert closed.json()["error"]["code"] == "RESTAURANT_CLOSED"

    world.restaurant.is_open = True
    world.items[0].is_available = False
    db_session.commit()
    gone = client.post(f"{API}/orders", json=body, headers=world.customer_h)
    assert gone.json()["error"]["code"] == "ITEM_UNAVAILABLE"
    assert gone.json()["error"]["details"] == ["Paneer Tikka"]


def test_cannot_use_someone_elses_address(client, world):
    add(client, world, 0, 2, headers=world.other_h)
    res = client.post(f"{API}/orders", json={"address_id": world.address.id}, headers=world.other_h)
    assert res.status_code == 404


# ------------------------------------------------------------------ payments
def test_full_payment_flow_places_order_and_notifies(client, world, db_session):
    order = place_paid_order(client, world)
    assert order["status"] == "PLACED"
    assert order["payment_status"] == "succeeded"
    assert [h["to_status"] for h in order["history"]] == ["PENDING_PAYMENT", "PLACED"]
    owner_notes = db_session.scalars(
        select(Notification.type).where(Notification.user_id == world.owner.id)
    ).all()
    assert owner_notes == ["owner.order.placed"]


def test_webhook_rejects_bad_signature(client, world):
    body = json.dumps({"id": "evt_x", "type": "payment.succeeded",
                       "data": {"provider_payment_id": "mock_pay_x", "amount": "1.00"}})  # fmt: skip
    res = client.post(f"{API}/payments/webhook", content=body,
                      headers={"x-mock-signature": "0" * 64})  # fmt: skip
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_SIGNATURE"
    assert client.post(f"{API}/payments/webhook", content=body).status_code == 400


def test_webhook_is_idempotent(client, world):
    add(client, world, 0, 2)
    oid = client.post(f"{API}/orders", json={"address_id": world.address.id},
                      headers=world.customer_h).json()["id"]  # fmt: skip
    checkout = client.post(f"{API}/payments/orders/{oid}/checkout", headers=world.customer_h).json()
    body, headers = get_provider().build_webhook(
        checkout["provider_payment_id"],
        "payment.succeeded",
        __import__("decimal").Decimal(checkout["amount"]),  # noqa: E501
    )
    first = client.post(f"{API}/payments/webhook", content=body, headers=headers)
    second = client.post(f"{API}/payments/webhook", content=body, headers=headers)
    assert first.json() == {"status": "processed"}
    assert second.json() == {"status": "duplicate"}  # gateway retry: no double processing
    history = client.get(f"{API}/orders/{oid}", headers=world.customer_h).json()["history"]
    assert [h["to_status"] for h in history] == ["PENDING_PAYMENT", "PLACED"]


def test_webhook_amount_mismatch_fails_payment(client, world):
    from decimal import Decimal

    add(client, world, 0, 2)
    oid = client.post(f"{API}/orders", json={"address_id": world.address.id},
                      headers=world.customer_h).json()["id"]  # fmt: skip
    checkout = client.post(f"{API}/payments/orders/{oid}/checkout", headers=world.customer_h).json()
    body, headers = get_provider().build_webhook(
        checkout["provider_payment_id"], "payment.succeeded", Decimal("1.00")
    )
    client.post(f"{API}/payments/webhook", content=body, headers=headers)
    payment = client.get(f"{API}/payments/orders/{oid}", headers=world.customer_h).json()
    assert payment["status"] == "failed" and "mismatch" in payment["failure_reason"]
    assert (
        client.get(f"{API}/orders/{oid}", headers=world.customer_h).json()["status"]
        == "PENDING_PAYMENT"
    )  # noqa: E501


def test_failed_payment_can_be_retried(client, world):
    add(client, world, 0, 2)
    oid = client.post(f"{API}/orders", json={"address_id": world.address.id},
                      headers=world.customer_h).json()["id"]  # fmt: skip
    client.post(f"{API}/payments/orders/{oid}/checkout", headers=world.customer_h)
    client.post(f"{API}/payments/sandbox/orders/{oid}/pay", params={"outcome": "failure"},
                headers=world.customer_h)  # fmt: skip
    assert (
        client.get(f"{API}/payments/orders/{oid}", headers=world.customer_h).json()["status"]
        == "failed"
    )  # noqa: E501
    retry = client.post(f"{API}/payments/orders/{oid}/checkout", headers=world.customer_h)
    assert retry.status_code == 200 and retry.json()["status"] == "pending"
    client.post(f"{API}/payments/sandbox/orders/{oid}/pay", headers=world.customer_h)
    assert client.get(f"{API}/orders/{oid}", headers=world.customer_h).json()["status"] == "PLACED"


def test_cannot_pay_twice(client, world):
    order = place_paid_order(client, world)
    res = client.post(f"{API}/payments/orders/{order['id']}/checkout", headers=world.customer_h)
    assert res.status_code == 409 and res.json()["error"]["code"] == "ORDER_NOT_PAYABLE"


# ------------------------------------------------------------------ state machine
def owner_post(client, w, oid, action, **json_body):
    return client.post(
        f"{API}/owner/orders/{oid}/{action}", json=json_body or None, headers=w.owner_h
    )


def owner_status(client, w, oid, status):
    return client.patch(
        f"{API}/owner/orders/{oid}/status", json={"status": status}, headers=w.owner_h
    )


def test_happy_path_to_delivered_and_review(client, world, db_session):
    oid = place_paid_order(client, world)["id"]
    assert owner_post(client, world, oid, "accept").json()["status"] == "ACCEPTED"
    for step in ("PREPARING", "OUT_FOR_DELIVERY", "DELIVERED"):
        assert owner_status(client, world, oid, step).json()["status"] == step
    timeline = client.get(f"{API}/orders/{oid}", headers=world.customer_h).json()["history"]
    assert [h["to_status"] for h in timeline] == [
        "PENDING_PAYMENT", "PLACED", "ACCEPTED", "PREPARING", "OUT_FOR_DELIVERY", "DELIVERED",
    ]  # fmt: skip

    review = client.post(f"{API}/orders/{oid}/review", json={"rating": 4, "comment": "Tasty"},
                         headers=world.customer_h)  # fmt: skip
    assert review.status_code == 201 and review.json()["author_name"] == "Cara"
    db_session.refresh(world.restaurant)
    assert (world.restaurant.rating_count, str(world.restaurant.avg_rating)) == (1, "4.0")
    dup = client.post(f"{API}/orders/{oid}/review", json={"rating": 5}, headers=world.customer_h)
    assert dup.status_code == 409
    public = client.get(f"{API}/restaurants/{world.restaurant.id}/reviews").json()
    assert public["total"] == 1


def test_invalid_transitions_are_rejected(client, world):
    oid = place_paid_order(client, world)["id"]
    skip = owner_status(client, world, oid, "DELIVERED")  # PLACED -> DELIVERED
    assert skip.status_code == 400
    assert skip.json()["error"]["code"] == "ORDER_INVALID_TRANSITION"
    early = client.post(f"{API}/orders/{oid}/review", json={"rating": 5}, headers=world.customer_h)
    assert early.json()["error"]["code"] == "ORDER_NOT_DELIVERED"


def test_customer_cancel_rules_and_refund(client, world):
    oid = place_paid_order(client, world)["id"]
    cancel = client.post(f"{API}/orders/{oid}/cancel", json={"reason": "Changed my mind"},
                         headers=world.customer_h)  # fmt: skip
    assert cancel.json()["status"] == "CANCELLED"
    assert cancel.json()["payment_status"] == "refunded"  # paid -> refunded automatically

    oid2 = place_paid_order(client, world)["id"]
    owner_post(client, world, oid2, "accept")
    late = client.post(f"{API}/orders/{oid2}/cancel", headers=world.customer_h)
    # ACCEPTED -> CANCELLED exists, but only for admins: 403, not 400.
    assert late.status_code == 403
    assert late.json()["error"]["code"] == "ORDER_TRANSITION_FORBIDDEN"


def test_reject_requires_reason_and_refunds(client, world):
    oid = place_paid_order(client, world)["id"]
    assert owner_post(client, world, oid, "reject").status_code == 422
    res = owner_post(client, world, oid, "reject", reason="Out of stock")
    assert res.json()["status"] == "REJECTED"
    assert res.json()["rejection_reason"] == "Out of stock"
    assert res.json()["payment_status"] == "refunded"


def test_owner_isolation(client, world, db_session):
    from app.models.user import UserRole
    from tests.conftest import headers_for, make_user

    oid = place_paid_order(client, world)["id"]
    make_user(db_session, "rival@example.com", UserRole.RESTAURANT_OWNER)
    rival = headers_for(client, "rival@example.com")
    assert client.get(f"{API}/owner/orders/{oid}", headers=rival).status_code == 404
    assert client.post(f"{API}/owner/orders/{oid}/accept", headers=rival).status_code == 404
    # Other customers can't see the order either.
    assert client.get(f"{API}/orders/{oid}", headers=world.other_h).status_code == 404


def test_owner_does_not_see_unpaid_orders(client, world):
    add(client, world, 0, 2)
    oid = client.post(f"{API}/orders", json={"address_id": world.address.id},
                      headers=world.customer_h).json()["id"]  # fmt: skip
    listing = client.get(f"{API}/owner/restaurants/{world.restaurant.id}/orders",
                         headers=world.owner_h).json()  # fmt: skip
    assert listing["total"] == 0
    assert client.get(f"{API}/owner/orders/{oid}", headers=world.owner_h).status_code == 404


def test_customer_order_list_and_notifications(client, world):
    place_paid_order(client, world)
    orders = client.get(f"{API}/orders", headers=world.customer_h).json()
    assert orders["total"] == 1 and orders["items"][0]["item_count"] == 3
    notes = client.get(f"{API}/notifications", headers=world.customer_h).json()
    assert [n["type"] for n in notes["items"]] == ["order.placed"]
    nid = notes["items"][0]["id"]
    assert client.patch(f"{API}/notifications/{nid}/read", headers=world.customer_h).json()[
        "is_read"
    ]  # noqa: E501
    assert client.post(f"{API}/notifications/read-all", headers=world.customer_h).json() == {
        "updated": 0
    }  # noqa: E501


def test_average_rating_has_no_rounding_drift(client, world, db_session):
    """4 reviews of 5,5,5,4 must give exactly 4.8 (19/4 = 4.75 -> 4.8)."""
    from decimal import Decimal

    for rating in (5, 5, 5, 4):
        oid = place_paid_order(client, world)["id"]
        owner_post(client, world, oid, "accept")
        for step in ("PREPARING", "OUT_FOR_DELIVERY", "DELIVERED"):
            owner_status(client, world, oid, step)
        client.post(f"{API}/orders/{oid}/review", json={"rating": rating}, headers=world.customer_h)
    db_session.refresh(world.restaurant)
    assert world.restaurant.rating_count == 4
    assert world.restaurant.avg_rating == Decimal("4.8")
