from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.rate_limit import init_rate_limiting
from app.db import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One client for the process, not one per request. Geo lookups are outbound
    # HTTPS, and a fresh client per submission would mean a fresh TLS handshake
    # per submission while the pooled connection it could have reused sits idle.
    async with httpx.AsyncClient() as http_client:
        app.state.http_client = http_client
        yield
    # Release pooled connections on shutdown. Reload mode restarts the process
    # frequently, and each restart would otherwise abandon an open pool.
    await engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# Before include_router: the exception handler must be registered on the app
# that ends up serving the limited routes.
# TODO: FR2.4 - Add CORS middleware for public endpoints (Path B and Path C)
# Public delivery endpoints and submission endpoint must accept requests from any origin
# Use fastapi.middleware.cors.CORSMiddleware with allow_origins=["*"]
# OR configure a whitelist of customer websites if known in advance
init_rate_limiting(app)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def read_root():
    return {"Hello": "World"}
