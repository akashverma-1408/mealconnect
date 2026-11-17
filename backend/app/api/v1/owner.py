"""Restaurant-owner endpoints: restaurants, categories, menu items, orders, analytics.

Every endpoint checks the role (OwnerUser) and every service call checks ownership
(the restaurant/order must belong to this owner, otherwise 404).
"""

from datetime import date

from fastapi import APIRouter, Response, status

from app.api.deps import DbSession, OwnerUser, Pagination
from app.models.order import OrderStatus
from app.schemas.common import Page, errors
from app.schemas.engagement import RestaurantAnalytics
from app.schemas.order import OrderRead, OrderSummary, OwnerStatusUpdate, RejectRequest
from app.schemas.restaurant import (
    AvailabilityUpdate,
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    MenuItemCreate,
    MenuItemRead,
    MenuItemUpdate,
    MenuRead,
    OwnerRestaurantRead,
    RestaurantCreate,
    RestaurantUpdate,
)
from app.services import admin_service, order_service, restaurant_service

router = APIRouter(prefix="/owner", tags=["Restaurant owner"], responses=errors(401, 403))
R = "/restaurants/{restaurant_id}"


# ================================================================== restaurants
@router.post(
    "/restaurants",
    response_model=OwnerRestaurantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a restaurant (starts as pending until an admin approves)",
    responses=errors(422),
)
def create_restaurant(
    data: RestaurantCreate, owner: OwnerUser, db: DbSession
) -> OwnerRestaurantRead:
    return OwnerRestaurantRead.model_validate(restaurant_service.create_restaurant(db, owner, data))


@router.get("/restaurants", response_model=list[OwnerRestaurantRead], summary="My restaurants")
def my_restaurants(owner: OwnerUser, db: DbSession) -> list[OwnerRestaurantRead]:
    return restaurant_service.list_owned(db, owner)


@router.get(
    R, response_model=OwnerRestaurantRead, summary="One of my restaurants", responses=errors(404)
)
def get_restaurant(restaurant_id: int, owner: OwnerUser, db: DbSession) -> OwnerRestaurantRead:
    return OwnerRestaurantRead.model_validate(
        restaurant_service.get_owned(db, owner, restaurant_id)
    )


@router.patch(
    R,
    response_model=OwnerRestaurantRead,
    summary="Update profile, hours, fees, open/closed",
    responses=errors(400, 404, 422),
)
def update_restaurant(
    restaurant_id: int, data: RestaurantUpdate, owner: OwnerUser, db: DbSession
) -> OwnerRestaurantRead:
    restaurant = restaurant_service.update_restaurant(db, owner, restaurant_id, data)
    return OwnerRestaurantRead.model_validate(restaurant)


@router.get(
    f"{R}/menu",
    response_model=MenuRead,
    summary="Full menu as customers see it",
    responses=errors(404),
)
def get_menu(restaurant_id: int, owner: OwnerUser, db: DbSession) -> MenuRead:
    return restaurant_service.get_owner_menu(db, owner, restaurant_id)


# ================================================================== categories
@router.get(
    f"{R}/categories",
    response_model=list[CategoryRead],
    summary="List categories",
    responses=errors(404),
)
def list_categories(restaurant_id: int, owner: OwnerUser, db: DbSession) -> list[CategoryRead]:
    rows = restaurant_service.list_categories(db, owner, restaurant_id)
    return [CategoryRead.model_validate(c) for c in rows]


@router.post(
    f"{R}/categories",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
    responses=errors(404, 409, 422),
)
def create_category(
    restaurant_id: int, data: CategoryCreate, owner: OwnerUser, db: DbSession
) -> CategoryRead:
    return CategoryRead.model_validate(
        restaurant_service.create_category(db, owner, restaurant_id, data)
    )


@router.patch(
    f"{R}/categories/{{category_id}}",
    response_model=CategoryRead,
    summary="Rename / reorder a category",
    responses=errors(404, 409, 422),
)
def update_category(
    restaurant_id: int, category_id: int, data: CategoryUpdate, owner: OwnerUser, db: DbSession
) -> CategoryRead:
    return CategoryRead.model_validate(
        restaurant_service.update_category(db, owner, restaurant_id, category_id, data)
    )


@router.delete(
    f"{R}/categories/{{category_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a category (its items become uncategorized)",
    responses=errors(404),
)
def delete_category(
    restaurant_id: int, category_id: int, owner: OwnerUser, db: DbSession
) -> Response:
    restaurant_service.delete_category(db, owner, restaurant_id, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ================================================================== menu items
@router.get(
    f"{R}/menu-items",
    response_model=list[MenuItemRead],
    summary="List menu items",
    responses=errors(404),
)
def list_items(restaurant_id: int, owner: OwnerUser, db: DbSession) -> list[MenuItemRead]:
    return [
        MenuItemRead.model_validate(i)
        for i in restaurant_service.list_items(db, owner, restaurant_id)
    ]


@router.post(
    f"{R}/menu-items",
    response_model=MenuItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a menu item",
    responses=errors(404, 422),
)
def create_item(
    restaurant_id: int, data: MenuItemCreate, owner: OwnerUser, db: DbSession
) -> MenuItemRead:
    return MenuItemRead.model_validate(
        restaurant_service.create_item(db, owner, restaurant_id, data)
    )


@router.patch(
    f"{R}/menu-items/{{item_id}}",
    response_model=MenuItemRead,
    summary="Update a menu item",
    responses=errors(400, 404, 422),
)
def update_item(
    restaurant_id: int, item_id: int, data: MenuItemUpdate, owner: OwnerUser, db: DbSession
) -> MenuItemRead:
    return MenuItemRead.model_validate(
        restaurant_service.update_item(db, owner, restaurant_id, item_id, data)
    )


@router.patch(
    f"{R}/menu-items/{{item_id}}/availability",
    response_model=MenuItemRead,
    summary="Mark an item available / sold out",
    responses=errors(404),
)
def set_availability(
    restaurant_id: int, item_id: int, data: AvailabilityUpdate, owner: OwnerUser, db: DbSession
) -> MenuItemRead:
    return MenuItemRead.model_validate(
        restaurant_service.set_item_availability(
            db, owner, restaurant_id, item_id, data.is_available
        )
    )


@router.delete(
    f"{R}/menu-items/{{item_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a menu item (soft delete; order history is kept)",
    responses=errors(404),
)
def delete_item(restaurant_id: int, item_id: int, owner: OwnerUser, db: DbSession) -> Response:
    restaurant_service.delete_item(db, owner, restaurant_id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ================================================================== orders
@router.get(
    f"{R}/orders",
    response_model=Page[OrderSummary],
    summary="Incoming orders (paid only), newest first",
    responses=errors(404),
)
def list_orders(
    restaurant_id: int,
    owner: OwnerUser,
    db: DbSession,
    pagination: Pagination,
    status: OrderStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Page[OrderSummary]:
    return order_service.list_restaurant_orders(
        db, owner, restaurant_id, status, date_from, date_to, pagination.page, pagination.size
    )


@router.get(
    "/orders/{order_id}", response_model=OrderRead, summary="Order details", responses=errors(404)
)
def get_order(order_id: int, owner: OwnerUser, db: DbSession) -> OrderRead:
    return order_service.to_read(order_service.get_owner_order(db, owner, order_id))


@router.post(
    "/orders/{order_id}/accept",
    response_model=OrderRead,
    summary="Accept a PLACED order",
    responses=errors(400, 404),
)
def accept_order(order_id: int, owner: OwnerUser, db: DbSession) -> OrderRead:
    return order_service.to_read(
        order_service.owner_transition(db, owner, order_id, OrderStatus.ACCEPTED)
    )


@router.post(
    "/orders/{order_id}/reject",
    response_model=OrderRead,
    summary="Reject a PLACED order with a reason (customer is refunded)",
    responses=errors(400, 404, 422),
)
def reject_order(order_id: int, data: RejectRequest, owner: OwnerUser, db: DbSession) -> OrderRead:
    return order_service.to_read(
        order_service.owner_transition(db, owner, order_id, OrderStatus.REJECTED, data.reason)
    )


@router.patch(
    "/orders/{order_id}/status",
    response_model=OrderRead,
    summary="Advance an order: PREPARING -> OUT_FOR_DELIVERY -> DELIVERED",
    responses=errors(400, 404, 422),
)
def update_order_status(
    order_id: int, data: OwnerStatusUpdate, owner: OwnerUser, db: DbSession
) -> OrderRead:
    return order_service.to_read(
        order_service.owner_transition(db, owner, order_id, OrderStatus(data.status))
    )


# ================================================================== analytics
@router.get(
    f"{R}/analytics",
    response_model=RestaurantAnalytics,
    summary="Sales analytics for a date range (default: last 30 days)",
    responses=errors(400, 404),
)
def analytics(
    restaurant_id: int,
    owner: OwnerUser,
    db: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
) -> RestaurantAnalytics:
    return admin_service.restaurant_analytics(db, owner, restaurant_id, date_from, date_to)
