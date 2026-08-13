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
| Cache / limits| Redis 7 (`slowapi` + `limits`)        |
| Auth          | JWT (`PyJWT`) + bcrypt via `passlib`  |
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
| `SECRET_KEY`        | —                         | **Required** — signs JWTs. Rotating it invalidates every issued token                  |
| `JWT_ALGORITHM`     | `HS256`                   |                                                                                        |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60`            |                                                                                        |
| `REDIS_HOST`        | `redis`                   | `localhost` in `.env` for host-side runs; Compose overrides to `redis`                 |
| `REDIS_PORT`        | `6379`                    | `6380` on the host to avoid clashing with a local Redis                                |
| `REDIS_PASSWORD`    | —                         | Optional; unset for local Docker                                                       |
| `REDIS_DB`          | `0`                       | Database used for rate limit counters                                                  |
| `REDIS_TEST_DB`     | `15`                      | Flushed by the test suite — must differ from `REDIS_DB`                                |
| `RATE_LIMIT_LOGIN`  | `5/minute`                | Any `limits` format, e.g. `100/hour`                                                   |
| `RATE_LIMIT_ENABLED`| `true`                    | Set `false` to disable limiting globally                                               |

Postgres is published on host port **5433**, not 5432. Connect with `psql -h localhost -p 5433 -U <user> -d <db>`.

Redis is published on host port **6380**, not 6379. Connect with `redis-cli -p 6380`.

## Rate limiting

Rate limits are enforced by [slowapi](https://github.com/laurentS/slowapi) with **Redis-backed** storage, configured in [app/core/rate_limit.py](app/core/rate_limit.py).

Redis rather than in-memory storage is a correctness requirement, not an optimisation: counters must be shared across worker processes. In-memory storage would give each uvicorn worker its own counter, silently turning `5/minute` into `5/minute per worker`.

| Endpoint           | Limit                     | Key       |
| ------------------ | ------------------------- | --------- |
| `POST /auth/login` | `RATE_LIMIT_LOGIN` (5/min) | Client IP |

Exceeding a limit returns `429` with a `Retry-After` header (seconds until the window resets) and a `{"detail": ...}` body matching every other API error. Successful responses carry `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` so a client can back off before being rejected.

Login counts **every** attempt, successful or not. Counting only failures would let an attacker reset their own budget with one valid login.

To limit a new endpoint, decorate it and give it a `Request` and `Response` parameter — slowapi reads the caller's IP from the former and writes headers onto the latter:

```python
@router.post("/submissions")
@limiter.limit(settings.RATE_LIMIT_SUBMISSION)
async def create_submission(request: Request, response: Response, ...): ...
```

Behind a proxy or load balancer, `get_remote_address` returns the proxy's IP, which collapses every visitor into one bucket. Before deploying, run uvicorn with `--proxy-headers` and key off the forwarded client address.

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

Host runs read `POSTGRES_HOST`/`POSTGRES_PORT` and `REDIS_HOST`/`REDIS_PORT` from `.env`, which point at `localhost:5433` and `localhost:6380`. Start both dependencies first:

```bash
docker compose up -d db redis
```

Tests run against a throwaway `<POSTGRES_DB>_test` database and Redis DB `REDIS_TEST_DB` (15), so a run never touches development data. Rate limit tests skip with a clear reason if Redis is unreachable rather than failing the suite.

Rate limiting is **disabled by default in tests** by an autouse fixture and enabled only inside the rate limit tests themselves. Without that, the shared per-IP counter would leak across tests — every test client shares one address, so the 40-plus login calls elsewhere in the suite would trip the limit and fail unrelated assertions.

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

## Testing the embeddable widget locally

To verify the widget loads and renders correctly on a different origin (required for CORS testing):

**1. Start the API server**
```bash
docker compose up -d
```

**2. Create a widget via the API**
```bash
# Sign up and get a token
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "TestPassword123!",
    "organization_name": "Test Org"
  }'

# Create a widget
curl -X POST http://localhost:8000/api/v1/widgets \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "widget_type": "signup_form",
    "title": "Newsletter Signup",
    "description": "Join our mailing list",
    "button_text": "Subscribe",
    "theme_color": "#0066cc",
    "form_fields": [
      {
        "field_name": "email",
        "label": "Email Address",
        "field_type": "email",
        "is_required": true
      }
    ]
  }'
```

Copy the `embed_snippet` from the response (e.g., `<script src="http://localhost:8000/widget.js?id=YOUR_WIDGET_ID"></script>`).

**3. Serve the test page on a different port**

Open a new terminal and run:
```bash
cd test-page/
python -m http.server 5500
```

This serves the test page on http://localhost:5500 (different origin than the API on http://localhost:8000).

**4. Edit the test page**

Edit [test-page/customer-site.html](test-page/customer-site.html) and replace:
```html
<!-- <script src="http://localhost:8000/widget.js?id=REPLACE_WITH_REAL_WIDGET_ID"></script> -->
```

with your actual embed snippet:
```html
<script src="http://localhost:8000/widget.js?id=YOUR_WIDGET_ID"></script>
```

**5. Verify**

Open http://localhost:5500 in your browser. You should see:
- The test page loads with the customer website content
- The widget appears on the right side (different origin, so CORS headers are tested)
- The widget renders with the title, description, form fields, and button from your config
- The button color matches the `theme_color` you configured (or defaults to skyblue if invalid)
- Console should show no CORS errors

## Common commands

```bash
docker compose logs -f app     # tail application logs
docker compose restart app     # restart just the API
docker compose down            # stop; database volume is preserved
docker compose down -v         # stop and DELETE all database data
```

## Project status

Implemented: configuration, async database layer, session dependency injection, containerisation, Alembic setup, health/readiness endpoints, the full [ERD](docs/ERD.mmd) schema (`Customer`, `Widget`, `FormField`, `Submission`) with `ON DELETE CASCADE`, JWT authentication (signup, login, `GET /me`, change password, `PATCH /me`, `DELETE /me` with cascade delete), and Redis-backed rate limiting on login.

Not yet built: widget CRUD, the embed snippet, public submission handling, spam filtering, and geo enrichment. The `Widget`, `FormField`, and `Submission` tables exist as data models only — no endpoints or services target them yet.

Known gap: JWTs are stateless with no revocation list, so a token issued before a password change stays valid until it expires (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 60). Closing it needs a token version column or a revocation store.

## Documentation

- [Product Requirements Document (PRD)](docs/PRD.md)
- [Entity Relationship Diagram (ERD)](docs/ERD.mmd)
