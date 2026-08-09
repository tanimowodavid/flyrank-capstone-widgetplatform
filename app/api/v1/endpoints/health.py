"""Liveness and readiness endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(tags=["health"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Report that the process is up. Deliberately does not touch the database:
    a liveness probe that fails on a database blip causes needless restarts."""
    return {"status": "ok"}


@router.get("/db-check", summary="Readiness probe")
async def db_check(db: DbSession) -> dict[str, str]:
    """Verify the database connection and container networking with SELECT 1."""
    try:
        result = await db.execute(text("SELECT 1"))
        result.scalar_one()
    except SQLAlchemyError as exc:
        # Surface an unreachable database as a clean JSON 503, never a bare 500.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
    return {"status": "ok", "database": "connected"}
