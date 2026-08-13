"""Aggregates every v1 endpoint module into a single router."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, widgets
from app.api.v1.endpoints.delivery import config

# TODO: Import submissions endpoint (Path C - public visitor submissions)
# from app.api.v1.endpoints import submissions  # When ready to implement

# TODO: Import dashboard endpoint (Path A - owner viewing submissions and analytics)
# from app.api.v1.endpoints import dashboard  # When ready to implement

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(widgets.router)
api_router.include_router(config.router)
api_router.include_router(config.static_router)

# TODO: Include submissions router when implemented
# api_router.include_router(submissions.router)

# TODO: Include dashboard router when implemented
# api_router.include_router(dashboard.router)
