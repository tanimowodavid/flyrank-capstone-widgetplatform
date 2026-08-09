"""Health and readiness endpoint tests."""

from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_db_check_connects_to_database(client: AsyncClient) -> None:
    """Exercises get_db end to end: a real SELECT 1 over asyncpg."""
    response = await client.get("/api/v1/db-check")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
