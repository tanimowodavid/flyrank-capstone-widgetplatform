"""Guards on the test harness itself.

If these fail, every other test's isolation claim is void — they would be
mutating the development database.
"""

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


async def test_session_is_bound_to_the_test_database(
    db_session: AsyncSession,
) -> None:
    current = (await db_session.execute(text("select current_database()"))).scalar_one()

    assert current == settings.TEST_DATABASE_NAME
    assert current != settings.POSTGRES_DB


async def test_app_requests_hit_the_test_database(client: AsyncClient) -> None:
    """The get_db override must apply to requests, not just direct fixtures."""
    response = await client.get("/api/v1/db-check")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


async def test_migrations_ran_against_the_test_database(
    db_session: AsyncSession,
) -> None:
    """The customers table exists because Alembic migrated this database."""
    version = (
        await db_session.execute(text("select version_num from alembic_version"))
    ).scalar_one()
    assert version

    exists = (
        await db_session.execute(text("select to_regclass('public.customers')"))
    ).scalar_one()
    assert exists == "customers"
