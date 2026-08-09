# flyrank-capstone-widgetplatform

Let a customer define a widget, hand them one line of &lt;script>, and safely catch everything the public internet throws back at you — validated, spam-filtered, enriched, and dashboarded.

## Overview

A multi-tenant platform where a business creates a widget (signup form, contact form, or CTA popover) and embeds it on any website with a single `<script>` tag. Visitor submissions are validated, rate-limited, spam-filtered, enriched with geolocation, and stored — then surfaced to the owner in a dashboard.

The engineering goal is resilience: a submission is never lost because a third-party geo provider or email service went down, and no tenant can ever reach another tenant's data. See the [PRD](docs/PRD.md) for the full scope and success criteria.

### Tech stack

| Layer         | Choice                                |
| ------------- | ------------------------------------- |
| Language      | Python 3.12                           |
| Web framework | FastAPI                               |
| Database      | PostgreSQL 16                         |
| ORM           | SQLAlchemy 2.0 (async) with `asyncpg` |
| Migrations    | Alembic (async template)              |
| Config        | Pydantic `BaseSettings`               |
| Packaging     | uv                                    |
| Runtime       | Docker Compose                        |
| Tests         | pytest + pytest-asyncio               |

## Prerequisites

- [Docker Desktop](https://docs.docker.com/get-docker/) (running)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — only needed for host-side commands
- Python 3.12 — uv will fetch it if missing

## Installation

**1. Clone and enter the repo**

```bash
git clone <repository-url>
cd flyrank-capstone-widgetplatform
```

**2. Create your `.env`**

```bash
cp .env.example .env
```

Required before starting Docker — Compose reads `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` from this file to provision the database and run its health check. Edit the password before doing anything non-local. `.env` is gitignored and must stay that way.

**3. Build and start**

```bash
docker compose up -d --build
```

The `app` container waits for Postgres to pass `pg_isready` before it starts, so the first request won't hit a database that is still initialising.

**4. Verify**

```bash
docker compose ps                          # db should read (healthy)
curl -s localhost:8000/api/v1/health       # {"status":"ok"}
curl -s localhost:8000/api/v1/db-check     # {"status":"ok","database":"connected"}
```

| URL                                   | Purpose                                |
| ------------------------------------- | -------------------------------------- |
| http://localhost:8000                 | API root                               |
| http://localhost:8000/docs            | Swagger UI                             |
| http://localhost:8000/redoc           | ReDoc                                  |
| http://localhost:8000/api/v1/health   | Liveness — does not touch the database |
| http://localhost:8000/api/v1/db-check | Readiness — runs `SELECT 1`            |

Source is bind-mounted into the container and uvicorn runs with `--reload`, so edits apply without a rebuild. Rebuild only when dependencies change.

## Environment variables

| Variable            | Default                   | Notes                                                                                  |
| ------------------- | ------------------------- | -------------------------------------------------------------------------------------- |
| `PROJECT_NAME`      | `FlyRank Widget Platform` | Shown in the OpenAPI docs                                                              |
| `DEBUG`             | `false`                   |                                                                                        |
| `POSTGRES_USER`     | —                         | **Required**                                                                           |
| `POSTGRES_PASSWORD` | —                         | **Required**                                                                           |
| `POSTGRES_DB`       | —                         | **Required**                                                                           |
| `POSTGRES_HOST`     | `db`                      | `localhost` in `.env` for host-side runs; Compose overrides to `db` inside the network |
| `POSTGRES_PORT`     | `5432`                    | `5433` on the host to avoid clashing with a local Postgres                             |
| `DB_POOL_SIZE`      | `10`                      |                                                                                        |
| `DB_MAX_OVERFLOW`   | `5`                       | Extra connections allowed past the pool size                                           |
| `DB_POOL_TIMEOUT`   | `30`                      | Seconds to wait for a free connection                                                  |
| `DB_POOL_RECYCLE`   | `1800`                    | Recycle connections older than this, in seconds                                        |
| `DB_ECHO`           | `false`                   | Log every SQL statement                                                                |

Postgres is published on host port **5433**, not 5432. Connect with `psql -h localhost -p 5433 -U <user> -d <db>`.

## Running tests

Inside the container (recommended — the database is already reachable):

```bash
docker compose exec app pytest -v
```

From the host, with the stack running:

```bash
uv sync
uv run pytest -v
```

Host runs read `POSTGRES_HOST`/`POSTGRES_PORT` from `.env`, which point at `localhost:5433`. Tests that touch the database need `docker compose up -d db` first.

## Database migrations

Migrations run through Alembic's async template. The connection URL is injected at runtime from `app.core.config.settings`, so no credentials live in `alembic.ini`.

```bash
# Generate a migration from model changes
docker compose exec app alembic revision --autogenerate -m "add widgets table"

# Review the generated file in alembic/versions/ before applying it
docker compose exec app alembic upgrade head

# Inspect and roll back
docker compose exec app alembic current
docker compose exec app alembic downgrade -1
```

Autogenerate only sees models that have been imported. Every new model module must be imported in [app/models/\_\_init\_\_.py](app/models/__init__.py) — otherwise Alembic treats its table as nonexistent and will generate a migration that drops it.

## Common commands

```bash
docker compose logs -f app     # tail application logs
docker compose restart app     # restart just the API
docker compose down            # stop; database volume is preserved
docker compose down -v         # stop and DELETE all database data
```

## Project status

Implemented: configuration, async database layer, session dependency injection, containerisation, Alembic setup, and health/readiness endpoints.

Not yet built: ORM models for the [ERD](docs/ERD.mmd) entities, authentication, widget CRUD, the embed snippet, public submission handling, rate limiting, spam filtering, and geo enrichment.

## Documentation

- [Product Requirements Document (PRD)](docs/PRD.md)
- [Entity Relationship Diagram (ERD)](docs/ERD.mmd)
