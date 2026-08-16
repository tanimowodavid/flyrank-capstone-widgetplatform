"""Shared FastAPI dependencies."""

import uuid
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, decode_access_token
from app.db import get_db
from app.models.customer import Customer
from app.repositories.customer import CustomerRepository

DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_http_client(request: Request) -> httpx.AsyncClient:
    """The process-wide client opened by the lifespan handler.

    Handed out rather than constructed per request so outbound calls reuse pooled
    connections. Tests get the same object, which is what makes overriding this
    dependency enough to keep the suite off the network.
    """
    return request.app.state.http_client


HttpClient = Annotated[httpx.AsyncClient, Depends(get_http_client)]

# auto_error=False so a missing header reaches us as None and gets the same 401
# (with WWW-Authenticate) as a bad token, rather than HTTPBearer's bare 403.
bearer_scheme = HTTPBearer(auto_error=False)

BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_customer(
    credentials: BearerCredentials,
    db: DbSession,
) -> Customer:
    """Resolve the caller from the Authorization: Bearer header.

    Every failure — no header, wrong scheme, bad signature, expired, unparseable
    subject, or a customer since deleted — is the same 401 with the same body.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise _unauthorized() from exc

    try:
        customer_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise _unauthorized() from exc

    customer = await CustomerRepository(db).get_by_id(customer_id)
    if customer is None:
        raise _unauthorized()

    return customer


CurrentCustomer = Annotated[Customer, Depends(get_current_customer)]
