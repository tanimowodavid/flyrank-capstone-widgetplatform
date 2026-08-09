"""Application configuration, loaded from the environment.

All settings come from environment variables (or a local .env file). Nothing that
varies per environment — and no secret — is hardcoded anywhere else in the app.
"""

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import computed_field
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
