"""Shared test fixtures.

The whole session runs against a throwaway database that is created, migrated
with Alembic, and dropped here. The development database is never touched: the
app's get_db dependency is overridden for the duration, and a guard aborts the
run outright if the test database name ever resolves to the development one.
"""

import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db import get_db
from app.db.base import Base
from app.main import app

TEST_DB_NAME = settings.TEST_DATABASE_NAME


def _run_alembic_upgrade() -> None:
    """Migrate the test database to head.

    Runs in a worker thread: alembic/env.py calls asyncio.run(), which explodes
    if a loop is already running in the current thread. The URL is handed over
    through config.attributes so env.py targets the test database rather than
    the one in settings.
    """
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.attributes["sqlalchemy_url"] = settings.TEST_DATABASE_URL
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session", autouse=True)
async def test_database() -> AsyncGenerator[AsyncEngine, None]:
    """Create, migrate, and finally drop the test database."""
    if TEST_DB_NAME == settings.POSTGRES_DB:
        pytest.exit(
            f"Refusing to run: test database name {TEST_DB_NAME!r} is the same as "
            "POSTGRES_DB. Set POSTGRES_TEST_DB to something else.",
            returncode=1,
        )

    # CREATE/DROP DATABASE cannot run inside a transaction, nor while connected
    # to the target, so both are issued against "postgres" in AUTOCOMMIT.
    admin_engine = create_async_engine(
        settings.MAINTENANCE_DATABASE_URL,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    async with admin_engine.begin() as conn:
        # FORCE (Postgres 13+) evicts leftover connections from an interrupted
        # previous run, which would otherwise make the DROP hang.
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))

    await asyncio.to_thread(_run_alembic_upgrade)

    engine = create_async_engine(settings.TEST_DATABASE_URL, poolclass=NullPool)
    try:
        yield engine
    finally:
        # Drop the pool before the database: an open connection blocks the DROP.
        await engine.dispose()
        async with admin_engine.begin() as conn:
            await conn.execute(
                text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
            )
        await admin_engine.dispose()


@pytest.fixture(scope="session")
def session_factory(test_database: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=test_database,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest.fixture(autouse=True)
def override_get_db(
    session_factory: async_sessionmaker[AsyncSession],
) -> Generator[None, None, None]:
    """Point the app at the test database for every test."""

    async def _get_test_db() -> AsyncGenerator[AsyncSession, None]:
        session = session_factory()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
async def clean_tables(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[None, None]:
    """Empty every table after each test, so order and reruns cannot matter."""
    yield
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    if not tables:
        return
    async with session_factory() as session:
        # One statement so foreign keys never see a half-empty schema.
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client that drives the app in-process, without a live server."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Direct database session for repository-level tests."""
    async with session_factory() as session:
        yield session
