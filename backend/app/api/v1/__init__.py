"""Collects every v1 router under one APIRouter mounted at /api/v1."""

from fastapi import APIRouter

from app.api.v1 import admin, auth, catalogue, customer, health, notifications, owner, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(catalogue.router)
api_router.include_router(customer.cart)
api_router.include_router(customer.orders)
api_router.include_router(customer.payments)
api_router.include_router(customer.complaints)
api_router.include_router(notifications.router)
api_router.include_router(owner.router)
api_router.include_router(admin.router)
