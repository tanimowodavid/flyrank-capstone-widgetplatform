"""Shared test fixtures.

The whole session runs against a throwaway database that is created, migrated
with Alembic, and dropped here. The development database is never touched: the
app's get_db dependency is overridden for the duration, and a guard aborts the
run outright if the test database name ever resolves to the development one.
"""

import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
import redis
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from limits.storage import storage_from_string
from limits.strategies import STRATEGIES
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.rate_limit import limiter
from app.db import get_db
from app.db.base import Base
from app.main import app
from app.models.customer import Customer
from app.models.widget import Widget

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


@pytest.fixture(autouse=True)
def disable_rate_limiting() -> Generator[None, None, None]:
    """Keep the limiter off for the suite at large.

    Rate limits are shared state keyed by client IP, and every test here logs in
    from the same address. Left on, one test's attempts would exhaust another
    test's budget and the failure would depend on execution order. The tests that
    prove limiting works re-enable it explicitly via the rate_limited fixture.
    """
    limiter.enabled = False
    yield
    limiter.enabled = False


@pytest.fixture
def rate_limited() -> Generator[None, None, None]:
    """Enable rate limiting for one test, against an isolated Redis database.

    Counters are flushed on both sides of the test: leftovers from a previous
    run would otherwise make the first request of this one arrive mid-window.
    """
    redis_client = redis.Redis.from_url(settings.REDIS_TEST_URL)
    try:
        redis_client.ping()
    except redis.RedisError:
        pytest.skip("Redis is not reachable — start it with `docker compose up -d redis`")

    original_storage_uri = limiter._storage_uri
    redis_client.flushdb()

    # Point the limiter at the test database and rebuild its storage, so counters
    # never land in the database the running app uses.
    limiter._storage_uri = settings.REDIS_TEST_URL
    limiter._storage = storage_from_string(settings.REDIS_TEST_URL)
    limiter._limiter = STRATEGIES[limiter._strategy or "fixed-window"](limiter._storage)
    limiter.enabled = True

    try:
        yield
    finally:
        limiter.enabled = False
        limiter._storage_uri = original_storage_uri
        limiter._storage = storage_from_string(original_storage_uri)
        limiter._limiter = STRATEGIES[limiter._strategy or "fixed-window"](
            limiter._storage
        )
        redis_client.flushdb()
        redis_client.close()


@pytest.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Direct database session for repository-level tests."""
    async with session_factory() as session:
        yield session


@pytest.fixture
async def db(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Alias for db_session, used by some tests."""
    async with session_factory() as session:
        yield session


@pytest.fixture
async def active_widget(
    db_session: AsyncSession,
) -> AsyncGenerator[Widget, None]:
    """Create an active widget with a customer for testing."""
    customer = Customer(
        organization_name="Test Org",
        email="owner@example.com",
        password_hash="not-a-real-hash",
    )
    db_session.add(customer)
    await db_session.flush()

    widget = Widget(
        customer_id=customer.id,
        widget_type="signup_form",
        title="Test Widget",
        description="Test widget description",
        button_text="Submit",
        theme_color="#0066cc",
        is_active=True,
    )
    db_session.add(widget)
    await db_session.commit()

    yield widget


@pytest.fixture
async def inactive_widget(
    db_session: AsyncSession,
) -> AsyncGenerator[Widget, None]:
    """Create an inactive widget with a customer for testing."""
    customer = Customer(
        organization_name="Test Org",
        email="owner@example.com",
        password_hash="not-a-real-hash",
    )
    db_session.add(customer)
    await db_session.flush()

    widget = Widget(
        customer_id=customer.id,
        widget_type="signup_form",
        title="Inactive Widget",
        description="Inactive widget description",
        button_text="Submit",
        theme_color="#0066cc",
        is_active=False,
    )
    db_session.add(widget)
    await db_session.commit()

    yield widget
