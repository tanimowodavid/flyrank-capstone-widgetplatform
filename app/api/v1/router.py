"""Aggregates every v1 endpoint module into a single router."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, widgets

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(widgets.router)
