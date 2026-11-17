"""Public catalogue: browse, filter and search restaurants and dishes (no login needed)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, Pagination
from app.core.cache import cached_json, params_key
from app.core.config import settings
from app.schemas.common import Page, errors
from app.schemas.engagement import ReviewRead
from app.schemas.restaurant import (
    MenuItemSearchResult,
    MenuRead,
    RestaurantFilters,
    RestaurantRead,
    RestaurantSummary,
)
from app.services import engagement_service, restaurant_service

router = APIRouter(tags=["Catalogue"])


@router.get(
    "/restaurants",
    response_model=Page[RestaurantSummary],
    summary="List approved restaurants with search, filters, sorting and pagination",
)
def list_restaurants(
    db: DbSession, pagination: Pagination, filters: Annotated[RestaurantFilters, Depends()]
) -> Page[RestaurantSummary]:
    key = params_key(
        "restaurants", {**filters.model_dump(), "page": pagination.page, "size": pagination.size}
    )
    return cached_json(  # served from Redis for CACHE_TTL_SECONDS, invalidated on changes
        key,
        settings.CACHE_TTL_SECONDS,
        lambda: restaurant_service.list_public(
            db, filters, pagination.page, pagination.size
        ).model_dump(mode="json"),
        versioned=True,
    )


@router.get(
    "/restaurants/{restaurant_id}",
    response_model=RestaurantRead,
    summary="Restaurant details",
    responses=errors(404),
)
def get_restaurant(restaurant_id: int, db: DbSession) -> RestaurantRead:
    return cached_json(
        f"restaurant:{restaurant_id}",
        settings.MENU_CACHE_TTL_SECONDS,
        lambda: RestaurantRead.model_validate(
            restaurant_service.get_public(db, restaurant_id)
        ).model_dump(mode="json"),
    )


@router.get(
    "/restaurants/{restaurant_id}/menu",
    response_model=MenuRead,
    summary="Menu grouped by category (unavailable items included, flagged)",
    responses=errors(404),
)
def get_menu(restaurant_id: int, db: DbSession) -> MenuRead:
    return cached_json(
        f"menu:{restaurant_id}",
        settings.MENU_CACHE_TTL_SECONDS,
        lambda: restaurant_service.get_public_menu(db, restaurant_id).model_dump(mode="json"),
    )


@router.get(
    "/restaurants/{restaurant_id}/reviews",
    response_model=Page[ReviewRead],
    summary="Reviews, newest first",
    responses=errors(404),
)
def list_reviews(restaurant_id: int, db: DbSession, pagination: Pagination) -> Page[ReviewRead]:
    return engagement_service.list_reviews(db, restaurant_id, pagination.page, pagination.size)


@router.get(
    "/search/menu-items",
    response_model=Page[MenuItemSearchResult],
    summary="Search dishes across all restaurants",
)
def search_menu_items(
    db: DbSession,
    pagination: Pagination,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    city: Annotated[str | None, Query(max_length=80)] = None,
    is_veg: bool | None = None,
    max_price: Annotated[float | None, Query(gt=0)] = None,
) -> Page[MenuItemSearchResult]:
    params = {"q": q, "city": city, "is_veg": is_veg, "max_price": max_price}
    key = params_key("search", {**params, "page": pagination.page, "size": pagination.size})
    return cached_json(
        key,
        settings.CACHE_TTL_SECONDS,
        lambda: restaurant_service.search_menu_items(
            db, q, city, is_veg, max_price, pagination.page, pagination.size
        ).model_dump(mode="json"),
        versioned=True,
    )
