"""Rate limiting infrastructure.

Shared by every endpoint that needs throttling, not just login: the public
submission endpoint (PRD FR4.1) will reuse this same limiter and handler.

Storage is Redis rather than in-memory on purpose. In-memory counters live per
worker process, so a limit of "5/minute" silently becomes "5 per minute per
worker" the moment the app runs more than one — and it resets on every reload.
"""

from typing import TYPE_CHECKING

import math
import time

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI


def client_ip(request: Request) -> str:
    """Key requests by client IP.

    slowapi's get_remote_address reads request.client.host directly. It does not
    consult X-Forwarded-For, which is the correct default here: that header is
    attacker-controlled, and trusting it unconditionally would let anyone bypass
    the limit by inventing an address. Behind a real proxy, terminate the header
    at the proxy and use ProxyHeadersMiddleware rather than parsing it here.
    """
    return get_remote_address(request)


limiter = Limiter(
    key_func=client_ip,
    # Sync storage URI, not "async+redis://". slowapi 0.1.10 builds its strategy
    # from limits.strategies (sync) and calls hit() without awaiting; handing it
    # an async backend raises AssertionError at construction.
    storage_uri=settings.REDIS_URL,
    # Emit X-RateLimit-* on every response, so a client can back off before it
    # is rejected rather than discovering the limit by hitting it.
    headers_enabled=True,
    enabled=settings.RATE_LIMIT_ENABLED,
)


def rate_limit_exceeded_handler(
    request: Request,
    exc: Exception,
) -> Response:
    """Return a clean 429 with Retry-After.

    Replaces slowapi's default handler to guarantee Retry-After is present and
    to keep the body shaped like every other error in the API ({"detail": ...}),
    rather than the plain-text default.

    Takes Exception rather than RateLimitExceeded because that is the signature
    Starlette's handler registry expects; only RateLimitExceeded is routed here.
    """
    retry_after = _retry_after_seconds(request)
    response = JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Too many requests. Please try again later."},
        # Seconds, not an HTTP-date: both are legal per RFC 9110, and a relative
        # value cannot be misread by a client whose clock is skewed.
        headers={"Retry-After": str(retry_after)},
    )
    # Re-attach X-RateLimit-* — headers_enabled only decorates successful
    # responses, and a rejected caller is precisely who needs them most.
    return request.app.state.limiter._inject_headers(response, request.state.view_rate_limit)


def _retry_after_seconds(request: Request) -> int:
    """Seconds until the offending window resets, floored at 1.

    Falls back to 60 if slowapi did not record which limit was hit — a caller
    that is being throttled must always be told how long to wait.
    """
    view_limit = getattr(request.state, "view_rate_limit", None)
    if view_limit is None:
        return 60

    limit_item, limit_args = view_limit
    try:
        stats = request.app.state.limiter.limiter.get_window_stats(
            limit_item, *limit_args
        )
    except Exception:  # noqa: BLE001 — a storage blip must not mask the 429
        return 60

    # Round up: truncating 0.4s to 0 would invite an immediate retry that is
    # still inside the window.
    return max(1, math.ceil(stats.reset_time - time.time()))


def init_rate_limiting(app: "FastAPI") -> None:
    """Attach the limiter and its 429 handler to the app."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
