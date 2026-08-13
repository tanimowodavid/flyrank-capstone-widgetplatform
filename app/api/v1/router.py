"""Aggregates every v1 endpoint module into a single router."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, widgets
from app.api.v1.endpoints.delivery import config, submission

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(widgets.router)
api_router.include_router(config.router)
api_router.include_router(config.static_router)
api_router.include_router(submission.router)
