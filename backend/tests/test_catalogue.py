"""Public catalogue: listing, filters, sorting, pagination, menu, dish search."""

from decimal import Decimal

from app.models.restaurant import MenuItem, Restaurant, RestaurantStatus
from tests.conftest import API


def add_restaurant(db, owner, name, **kw):
    defaults = dict(
        cuisine="Italian", city="Mumbai", address="9 Some Road", status=RestaurantStatus.APPROVED
    )
    r = Restaurant(owner_id=owner.id, name=name, slug=name.lower().replace(" ", "-"),
                   **{**defaults, **kw})  # fmt: skip
    db.add(r)
    db.commit()
    return r


def test_list_only_shows_approved_restaurants(client, world, db_session):
    add_restaurant(db_session, world.owner, "Hidden Pending", status=RestaurantStatus.PENDING)
    add_restaurant(db_session, world.owner, "Hidden Suspended", status=RestaurantStatus.SUSPENDED)
    res = client.get(f"{API}/restaurants")
    assert res.status_code == 200
    body = res.json()
    assert [r["name"] for r in body["items"]] == ["Spice Route"]
    assert body["total"] == 1 and body["page"] == 1 and body["pages"] == 1
    assert body["items"][0]["delivery_fee"] == "30.00"  # money as a 2-decimal string


def test_filters_and_search(client, world, db_session):
    add_restaurant(db_session, world.owner, "Pizza Piazza", avg_rating=Decimal("4.5"))
    add_restaurant(db_session, world.owner, "Green Bowl", cuisine="Healthy", city="Pune",
                   is_veg_only=True, avg_rating=Decimal("3.9"))  # fmt: skip

    def names(**params):
        return [r["name"] for r in client.get(f"{API}/restaurants", params=params).json()["items"]]

    assert names(city="pune", sort="name") == ["Green Bowl", "Spice Route"]  # case-insensitive
    assert names(is_veg=True) == ["Green Bowl"]
    assert names(min_rating=4) == ["Pizza Piazza"]
    assert names(q="piz") == ["Pizza Piazza"]  # partial match on name
    assert names(q="healthy") == ["Green Bowl"]  # ...or cuisine
    assert names(q="100%_") == []  # % and _ are matched literally, not as wildcards
    assert names(sort="-avg_rating")[0] == "Pizza Piazza"


def test_pagination(client, world, db_session):
    for i in range(5):
        add_restaurant(db_session, world.owner, f"Place {i}")
    page2 = client.get(f"{API}/restaurants", params={"size": 2, "page": 2, "sort": "name"}).json()
    assert page2["total"] == 6 and page2["pages"] == 3 and len(page2["items"]) == 2
    assert client.get(f"{API}/restaurants", params={"size": 101}).status_code == 422


def test_restaurant_detail_and_hidden_restaurant(client, world, db_session):
    assert client.get(f"{API}/restaurants/{world.restaurant.id}").status_code == 200
    pending = add_restaurant(db_session, world.owner, "Secret", status=RestaurantStatus.PENDING)
    res = client.get(f"{API}/restaurants/{pending.id}")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESTAURANT_NOT_FOUND"


def test_menu_groups_by_category_and_flags_unavailable(client, world, db_session):
    world.items[1].is_available = False
    db_session.commit()
    menu = client.get(f"{API}/restaurants/{world.restaurant.id}/menu").json()
    sections = {(s["category"] or {}).get("name"): s["items"] for s in menu["sections"]}
    assert set(sections) == {"Mains", None}  # None = uncategorized
    mains = {i["name"]: i["is_available"] for i in sections["Mains"]}
    assert mains == {"Butter Chicken": False, "Paneer Tikka": True}
    assert sections[None][0]["name"] == "Garlic Naan"


def test_deleted_items_are_hidden_from_menu(client, world, db_session):
    from datetime import UTC, datetime

    world.items[0].deleted_at = datetime.now(UTC)
    db_session.commit()
    menu = client.get(f"{API}/restaurants/{world.restaurant.id}/menu").json()
    names = [i["name"] for s in menu["sections"] for i in s["items"]]
    assert "Paneer Tikka" not in names


def test_dish_search(client, world, db_session):
    other = add_restaurant(db_session, world.owner, "Pizza Piazza")
    db_session.add(MenuItem(restaurant_id=other.id, name="Paneer Pizza", price=Decimal("299"),
                            is_veg=True))  # fmt: skip
    db_session.commit()
    res = client.get(f"{API}/search/menu-items", params={"q": "paneer"}).json()
    assert {(i["name"], i["restaurant"]["name"]) for i in res["items"]} == {
        ("Paneer Tikka", "Spice Route"),
        ("Paneer Pizza", "Pizza Piazza"),
    }
    cheap = client.get(f"{API}/search/menu-items", params={"q": "paneer", "max_price": 250}).json()
    assert [i["name"] for i in cheap["items"]] == ["Paneer Tikka"]
    assert client.get(f"{API}/search/menu-items", params={"q": "p"}).status_code == 422
