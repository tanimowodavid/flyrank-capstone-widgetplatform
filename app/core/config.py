"""Application configuration, loaded from the environment.

All settings come from environment variables (or a local .env file). Nothing that
varies per environment — and no secret — is hardcoded anywhere else in the app.
"""

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # Application
    PROJECT_NAME: str = "FlyRank Widget Platform"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # PostgreSQL connection
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    # Connection pool tuning
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    # JWT
    # No default: a fallback secret is the kind of thing that reaches production
    # unnoticed. Startup fails loudly instead if it is unset.
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Test database, created and dropped by the pytest session. Defaults to
    # "<POSTGRES_DB>_test" so it can never be the development database.
    POSTGRES_TEST_DB: str | None = None

    # Redis — backs rate limiting. Shared across processes, so a limit holds for
    # the whole deployment rather than per-worker as in-memory storage would.
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    # Database 0 is the app's; the test suite uses a different index so a test
    # run can flush its counters without touching development state.
    REDIS_DB: int = 0
    REDIS_TEST_DB: int = 15

    # Base URL the embed snippet points at. Its own setting rather than something
    # derived from the incoming request: widget.js is a static asset that may well
    # be served from a CDN, so the loader's host is not necessarily the API's.
    WIDGET_EMBED_BASE_URL: str = "https://your-domain.com"

    @field_validator("WIDGET_EMBED_BASE_URL")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        """Normalise once here so callers can always append "/widget.js"."""
        return value.rstrip("/")

    # Login rate limit, as a limits-library string ("5/minute", "100/hour").
    # Configurable so it can be tightened in production without a code change.
    RATE_LIMIT_LOGIN: str = "5/minute"
    # Turn limiting off wholesale. Most tests need it off; the ones that prove it
    # works turn it back on explicitly.
    RATE_LIMIT_ENABLED: bool = True

    def build_redis_url(self, db: int) -> str:
        """Redis DSN for `db` on the configured server.

        Password is percent-encoded for the same reason as the Postgres DSN: a
        credential containing "@" or "/" would otherwise split the URL wrongly.
        """
        auth = f":{quote_plus(self.REDIS_PASSWORD)}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{db}"

    @property
    def REDIS_URL(self) -> str:
        return self.build_redis_url(self.REDIS_DB)

    @property
    def REDIS_TEST_URL(self) -> str:
        return self.build_redis_url(self.REDIS_TEST_DB)

    def build_dsn(self, database: str) -> str:
        """Async SQLAlchemy DSN for `database` on the configured server.

        User and password are percent-encoded so credentials containing "@", ":"
        or "/" cannot break the URL into the wrong parts.
        """
        user = quote_plus(self.POSTGRES_USER)
        password = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{database}"
        )

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return self.build_dsn(self.POSTGRES_DB)

    # Plain properties, not computed_field: these are test-harness plumbing and
    # do not belong in a serialised settings dump.
    @property
    def TEST_DATABASE_NAME(self) -> str:
        return self.POSTGRES_TEST_DB or f"{self.POSTGRES_DB}_test"

    @property
    def TEST_DATABASE_URL(self) -> str:
        return self.build_dsn(self.TEST_DATABASE_NAME)

    @property
    def MAINTENANCE_DATABASE_URL(self) -> str:
        """DSN for the always-present "postgres" database.

        CREATE/DROP DATABASE cannot run while connected to the target, so the
        harness issues them from here.
        """
        return self.build_dsn("postgres")


@lru_cache
def get_settings() -> Settings:
    """Cached accessor, so the .env file is parsed once per process."""
    return Settings()


settings = get_settings()
