# FlyRank Widget Platform — API Reference

REST API for the FlyRank Widget Platform: a multi-tenant service where businesses create embeddable widgets (signup forms, contact forms, CTA popovers), collect anonymous visitor submissions, and manage their account and widgets.

**Base URL (local development):** `http://localhost:8000`

**API prefix:** `/api/v1`

**Full API base:** `http://localhost:8000/api/v1`

---

## Table of contents

1. [Quick start](#quick-start)
2. [Interactive documentation](#interactive-documentation)
3. [Authentication](#authentication)
4. [Error handling](#error-handling)
5. [Rate limiting](#rate-limiting)
6. [Endpoints overview](#endpoints-overview)
7. [Health](#health)
8. [Authentication & account](#authentication--account)
9. [Widgets (owner CRUD)](#widgets-owner-crud)
10. [Public delivery](#public-delivery)
11. [Public submission](#public-submission)
12. [Widget embedding guide](#widget-embedding-guide)
13. [Data types reference](#data-types-reference)
14. [Planned endpoints](#planned-endpoints)
15. [Security & tenant isolation](#security--tenant-isolation)

---

## Quick start

```bash
# 1. Check the API is running
curl -s http://localhost:8000/api/v1/health
# → {"status":"ok"}

# 2. Register a customer account
curl -s -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "organization_name": "Acme Corp",
    "email": "owner@acme.com",
    "password": "SecurePass123!"
  }'
# → {"access_token":"<jwt>","token_type":"bearer"}

# 3. Create a widget (replace TOKEN with the access_token above)
curl -s -X POST http://localhost:8000/api/v1/widgets \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "widget_type": "contact_form",
    "title": "Contact Us",
    "form_fields": [
      {
        "field_name": "email",
        "label": "Email",
        "field_type": "email",
        "is_required": true
      }
    ]
  }'
```

Store the `access_token` from signup or login and send it on every authenticated request:

```
Authorization: Bearer <access_token>
```

---

## Interactive documentation

FastAPI auto-generates an OpenAPI schema. No static spec file is checked into the repository.

| URL | Description |
| --- | --- |
| `http://localhost:8000/docs` | Swagger UI |
| `http://localhost:8000/redoc` | ReDoc |
| `http://localhost:8000/openapi.json` | OpenAPI 3 JSON schema |

---

## Authentication

The API uses **stateless JWT Bearer tokens**. There is no refresh token flow; when a token expires, the client must log in again.

### Obtaining a token

Call `POST /api/v1/auth/signup` or `POST /api/v1/auth/login`. Both return:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

### Using a token

Include the token in the `Authorization` header on protected routes:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

### Token details

| Property | Value |
| --- | --- |
| Algorithm | HS256 (`JWT_ALGORITHM`) |
| Signing key | `SECRET_KEY` environment variable (required) |
| Default lifetime | 60 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`) |
| Payload claims | `sub` (customer UUID), `iat`, `exp`, `type` (`"access"`) |

### Token lifecycle notes

- Tokens are **not revocable**. A token issued before a password change remains valid until it expires.
- Deleting an account (`DELETE /auth/me`) invalidates future requests because the customer row no longer exists.
- All authentication failures return the same **401** response to avoid leaking whether a token is malformed, expired, or belongs to a deleted account.

---

## Error handling

All errors use FastAPI's standard JSON envelope.

### Application errors

```json
{
  "detail": "Human-readable error message"
}
```

| Status | Typical cause |
| --- | --- |
| **400** | Bad request (e.g. incorrect current password) |
| **401** | Missing or invalid Bearer token; invalid login credentials |
| **404** | Resource not found (includes cross-tenant widget access) |
| **409** | Conflict (e.g. duplicate email on signup or profile update) |
| **422** | Request body or query failed Pydantic validation |
| **429** | Rate limit exceeded |
| **503** | Database unavailable (`/db-check`) |

401 responses include `WWW-Authenticate: Bearer`.

### Validation errors (422)

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "password"],
      "msg": "String should have at least 8 characters",
      "input": "short"
    }
  ]
}
```

---

## Rate limiting

Rate limiting is enforced by [slowapi](https://github.com/laurentS/slowapi) with **Redis-backed** storage so limits are shared across all worker processes.

| Setting | Default | Description |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | `true` | Global toggle (disabled in tests) |
| `RATE_LIMIT_LOGIN` | `5/minute` | Login endpoint limit per client IP |
| `RATE_LIMIT_SUBMIT` | `60/minute` | Configured but **not yet applied** to submission |

### Currently rate-limited endpoints

| Endpoint | Limit | Key |
| --- | --- | --- |
| `POST /api/v1/auth/login` | `RATE_LIMIT_LOGIN` | Client IP |

Login counts **every** attempt, successful or not.

### 429 response

```json
{
  "detail": "Too many requests. Please try again later."
}
```

Headers:

| Header | Description |
| --- | --- |
| `Retry-After` | Seconds until the rate-limit window resets |
| `X-RateLimit-Limit` | Maximum requests allowed in the window |
| `X-RateLimit-Remaining` | Requests remaining in the current window |
| `X-RateLimit-Reset` | Unix timestamp when the window resets |

Successful responses on rate-limited endpoints also include the `X-RateLimit-*` headers so clients can back off proactively.

---

## Endpoints overview

| Method | Path | Auth | Status |
| --- | --- | --- | --- |
| `GET` | `/` | No | Live |
| `GET` | `/api/v1/health` | No | Live |
| `GET` | `/api/v1/db-check` | No | Live |
| `POST` | `/api/v1/auth/signup` | No | Live |
| `POST` | `/api/v1/auth/login` | No | Live (rate limited) |
| `GET` | `/api/v1/auth/me` | Bearer | Live |
| `PATCH` | `/api/v1/auth/me` | Bearer | Live |
| `DELETE` | `/api/v1/auth/me` | Bearer | Live |
| `POST` | `/api/v1/auth/change-password` | Bearer | Live |
| `POST` | `/api/v1/widgets` | Bearer | Live |
| `GET` | `/api/v1/widgets` | Bearer | Live |
| `GET` | `/api/v1/widgets/{widget_id}` | Bearer | Live |
| `PATCH` | `/api/v1/widgets/{widget_id}` | Bearer | Live |
| `DELETE` | `/api/v1/widgets/{widget_id}` | Bearer | Live |
| `GET` | `/api/v1/widgets/{widget_id}/config` | No | Live |
| `GET` | `/api/v1/widget.js` | No | Live |
| `POST` | `/api/v1/widgets/{widget_id}/submit` | No | Live |
| `GET` | `/api/v1/dashboard/submissions` | Bearer | Planned |
| `GET` | `/api/v1/dashboard/analytics` | Bearer | Planned |

---

## Health

### `GET /api/v1/health`

Liveness probe. Confirms the process is running. Does **not** check the database.

**Auth:** None

**Response `200 OK`**

```json
{
  "status": "ok"
}
```

---

### `GET /api/v1/db-check`

Readiness probe. Runs `SELECT 1` against PostgreSQL to verify database connectivity.

**Auth:** None

**Response `200 OK`**

```json
{
  "status": "ok",
  "database": "connected"
}
```

**Response `503 Service Unavailable`**

```json
{
  "detail": "Database unavailable"
}
```

---

## Authentication & account

All routes in this section are prefixed with `/api/v1/auth`.

---

### `POST /auth/signup`

Register a new customer account and receive a JWT in one step.

**Auth:** None

**Request body:** [`CustomerSignup`](#customersignup)

**Response `201 Created`:** [`Token`](#token)

**Errors**

| Status | Detail |
| --- | --- |
| 409 | `"Email already registered"` |
| 422 | Validation failure (password too short, invalid email, etc.) |

**Example**

```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "organization_name": "Acme Corp",
    "email": "owner@acme.com",
    "password": "SecurePass123!"
  }'
```

---

### `POST /auth/login`

Exchange email and password for a JWT.

**Auth:** None

**Rate limit:** `RATE_LIMIT_LOGIN` (default 5/minute per IP)

**Request body:** [`CustomerLogin`](#customerlogin)

**Response `200 OK`:** [`Token`](#token)

**Errors**

| Status | Detail |
| --- | --- |
| 401 | `"Invalid credentials"` (same message for unknown email and wrong password) |
| 429 | Rate limit exceeded |

**Example**

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "owner@acme.com",
    "password": "SecurePass123!"
  }'
```

---

### `GET /auth/me`

Return the authenticated customer's profile.

**Auth:** Bearer required

**Response `200 OK`:** [`CustomerRead`](#customerread)

**Errors**

| Status | Detail |
| --- | --- |
| 401 | `"Could not validate credentials"` |

---

### `PATCH /auth/me`

Partially update the authenticated customer's profile. At least one field must be provided. Explicit `null` values are rejected.

**Auth:** Bearer required

**Request body:** [`CustomerUpdate`](#customerupdate)

**Response `200 OK`:** [`CustomerRead`](#customerread)

**Errors**

| Status | Detail |
| --- | --- |
| 401 | Unauthenticated |
| 409 | `"Email already registered"` |
| 422 | Empty body, explicit nulls, or invalid email |

**Example**

```bash
curl -X PATCH http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"organization_name": "Acme International"}'
```

---

### `DELETE /auth/me`

Permanently delete the authenticated customer's account. Cascades to all widgets, form fields, and submissions owned by the customer.

**Auth:** Bearer required

**Response `204 No Content`** — empty body

**Errors**

| Status | Detail |
| --- | --- |
| 401 | Unauthenticated |

---

### `POST /auth/change-password`

Change the authenticated customer's password. The current password must be provided and verified.

**Auth:** Bearer required

**Request body:** [`CustomerPasswordChange`](#customerpasswordchange)

**Response `200 OK`:** [`CustomerRead`](#customerread)

**Errors**

| Status | Detail |
| --- | --- |
| 400 | `"Current password is incorrect"` |
| 401 | Unauthenticated |
| 422 | New password too short or exceeds 72 bytes |

---

## Widgets (owner CRUD)

All routes in this section are prefixed with `/api/v1/widgets` and require **Bearer authentication**. Widget ownership is determined from the JWT — `customer_id` is never accepted in the request body.

Cross-tenant access (requesting another customer's widget by ID) returns **404 Not Found**, not 403, to prevent widget ID enumeration.

---

### `POST /widgets`

Create a new widget with its form fields.

**Auth:** Bearer required

**Request body:** [`WidgetCreate`](#widgetcreate)

**Response `201 Created`:** [`WidgetReadDetail`](#widgetreaddetail)

Includes `form_fields` and a computed `embed_snippet` for pasting into a website.

**Errors**

| Status | Detail |
| --- | --- |
| 401 | Unauthenticated |
| 422 | Validation failure (duplicate `field_name`, invalid widget type, etc.) |

**Example**

```bash
curl -X POST http://localhost:8000/api/v1/widgets \
  -H "Authorization: Bearer TOKEN" \
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
        "placeholder": "you@example.com",
        "is_required": true,
        "display_order": 0
      },
      {
        "field_name": "name",
        "label": "Full Name",
        "field_type": "text",
        "is_required": false,
        "display_order": 1
      }
    ]
  }'
```

---

### `GET /widgets`

List all widgets belonging to the authenticated customer, ordered newest first.

**Auth:** Bearer required

**Response `200 OK`:** Array of [`WidgetRead`](#widgetread)

Does not include `form_fields` or `embed_snippet` (use `GET /widgets/{id}` for those).

---

### `GET /widgets/{widget_id}`

Retrieve a single widget with its full form field set and embed snippet.

**Auth:** Bearer required

**Path parameters**

| Name | Type | Description |
| --- | --- | --- |
| `widget_id` | UUID | Widget identifier |

**Response `200 OK`:** [`WidgetReadDetail`](#widgetreaddetail)

**Errors**

| Status | Detail |
| --- | --- |
| 401 | Unauthenticated |
| 404 | `"Widget not found"` |
| 422 | Malformed UUID |

---

### `PATCH /widgets/{widget_id}`

Partially update a widget. Sending `form_fields` **replaces the entire field set**; omitting it leaves existing fields untouched. Sending `form_fields: []` clears all fields.

Nullable fields (`description`, `button_text`, `theme_color`) may be set to `null` to clear them.

**Auth:** Bearer required

**Path parameters**

| Name | Type | Description |
| --- | --- | --- |
| `widget_id` | UUID | Widget identifier |

**Request body:** [`WidgetUpdate`](#widgetupdate)

**Response `200 OK`:** [`WidgetReadDetail`](#widgetreaddetail)

**Errors**

| Status | Detail |
| --- | --- |
| 401 | Unauthenticated |
| 404 | `"Widget not found"` |
| 422 | Validation failure |

**Example — deactivate a widget**

```bash
curl -X PATCH http://localhost:8000/api/v1/widgets/WIDGET_ID \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'
```

---

### `DELETE /widgets/{widget_id}`

Delete a widget and its form fields. Existing submissions are preserved with `widget_id` set to `null`.

**Auth:** Bearer required

**Path parameters**

| Name | Type | Description |
| --- | --- | --- |
| `widget_id` | UUID | Widget identifier |

**Response `204 No Content`** — empty body

**Errors**

| Status | Detail |
| --- | --- |
| 401 | Unauthenticated |
| 404 | `"Widget not found"` |

---

## Public delivery

These endpoints require **no authentication**. They are designed to be called from third-party websites embedding the widget. Individual responses set `Access-Control-Allow-Origin: *`. Global CORS middleware is not yet configured — see [Widget embedding guide](#widget-embedding-guide).

---

### `GET /widgets/{widget_id}/config`

Return the public configuration needed to render a widget. Excludes internal fields (`id`, `customer_id`, `is_active`, timestamps, field IDs, and display order).

**Auth:** None

**Path parameters**

| Name | Type | Description |
| --- | --- | --- |
| `widget_id` | UUID | Widget identifier |

**Response `200 OK`:** [`WidgetConfig`](#widgetconfig)

**Response headers**

| Header | Value |
| --- | --- |
| `Cache-Control` | `public, max-age=60` |
| `Access-Control-Allow-Origin` | `*` |

**Errors**

| Status | Detail |
| --- | --- |
| 404 | `"Widget not found"` (nonexistent widget or `is_active=false`) |

**Example**

```bash
curl -s http://localhost:8000/api/v1/widgets/WIDGET_ID/config
```

```json
{
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
      "placeholder": "you@example.com",
      "is_required": true
    }
  ]
}
```

---

### `GET /widget.js`

Serve the embeddable vanilla JavaScript loader. No build step, no dependencies.

**Auth:** None

**Full path:** `/api/v1/widget.js`

**Query parameters**

| Name | Type | Description |
| --- | --- | --- |
| `id` | UUID | Widget ID (read by the script at runtime, not validated at serve time) |

**Response `200 OK`:** JavaScript file (`application/javascript`)

**Response headers**

| Header | Value |
| --- | --- |
| `Cache-Control` | `public, max-age=31536000, immutable` |
| `Access-Control-Allow-Origin` | `*` |

**Example embed snippet**

The `embed_snippet` field on widget detail responses is computed from `WIDGET_EMBED_BASE_URL`:

```html
<script src="https://your-domain.com/api/v1/widget.js?id=WIDGET_ID"></script>
```

Set `WIDGET_EMBED_BASE_URL` to your public API host (e.g. `http://localhost:8000/api/v1` for local development).

---

## Public submission

---

### `POST /widgets/{widget_id}/submit`

Accept an anonymous form submission from an embedded widget.

**Auth:** None

**Path parameters**

| Name | Type | Description |
| --- | --- | --- |
| `widget_id` | UUID | Widget identifier |

**Request body:** [`SubmissionCreate`](#submissioncreate)

**Request headers (optional, used for enrichment)**

| Header | Description |
| --- | --- |
| `User-Agent` | Browser user agent (preferred over body field) |
| `X-Forwarded-For` | Client IP when behind a proxy (first IP in the list is used) |

**Response `201 Created`:** [`SubmissionResponse`](#submissionresponse)

**Response headers**

| Header | Value |
| --- | --- |
| `Access-Control-Allow-Origin` | `*` |
| `Cache-Control` | `no-cache, no-store, must-revalidate` |

**Errors**

| Status | Detail |
| --- | --- |
| 404 | `"Widget not found or inactive"` |
| 422 | Invalid payload shape |

**Example**

```bash
curl -X POST http://localhost:8000/api/v1/widgets/WIDGET_ID/submit \
  -H "Content-Type: application/json" \
  -d '{
    "field_values": {
      "email": "visitor@example.com",
      "name": "Jane Doe"
    },
    "referrer": "https://customer-site.com/contact",
    "user_agent": "Mozilla/5.0 ..."
  }'
```

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "created_at": "2026-08-14T12:00:00+00:00",
  "message": "Thank you for your submission"
}
```

### Current submission limitations

The following features are configured but **not yet implemented**:

| Feature | Config / status |
| --- | --- |
| Field validation against widget form definition | Not enforced |
| Payload size limit | `MAX_SUBMISSION_SIZE` (10 KB) configured, not enforced |
| Spam / honeypot detection | `HONEYPOT_FIELD_NAME` configured; `is_spam` always `false` |
| Geolocation enrichment | Columns exist; always stored as `null` |
| Rate limiting | `RATE_LIMIT_SUBMIT` configured, not applied |
| Referrer storage | Accepted in body but not persisted |
| Email / webhook side effects | `WEBHOOK_*` and `SMTP_*` configured, not wired |

---

## Widget embedding guide

### Supported widget types

| Value | Description |
| --- | --- |
| `signup_form` | Email/name collection form |
| `contact_form` | General contact form |
| `cta_popover` | Call-to-action button (may have zero form fields) |

### Supported field types

| Value | Renders as |
| --- | --- |
| `text` | Single-line text input |
| `email` | Email input |
| `number` | Number input |
| `textarea` | Multi-line text area |

### Embed flow

```mermaid
sequenceDiagram
    participant Site as Customer website
    participant JS as widget.js
    participant API as FlyRank API

    Site->>JS: Load script tag with ?id=WIDGET_ID
    JS->>API: GET /api/v1/widgets/{id}/config
    API-->>JS: WidgetConfig JSON
    JS->>Site: Render form inline
    Site->>JS: User submits form
    JS->>API: POST /api/v1/widgets/{id}/submit
    API-->>JS: SubmissionResponse
    JS->>Site: Show success message
```

### Integration steps

1. Create a widget via `POST /api/v1/widgets` and copy the `embed_snippet` from the response.
2. Paste the snippet into the customer's HTML where the widget should appear.
3. Ensure `WIDGET_EMBED_BASE_URL` points to the publicly reachable API host including the `/api/v1` prefix.

**Local development example:**

```html
<script src="http://localhost:8000/api/v1/widget.js?id=YOUR_WIDGET_ID"></script>
```

### Field naming rules

- `field_name` must contain only letters, digits, underscores, and hyphens.
- `field_name` values must be unique within a widget (case-insensitive).
- `field_name` becomes the key in submission `field_values`.

---

## Data types reference

### CustomerSignup

| Field | Type | Constraints |
| --- | --- | --- |
| `organization_name` | string | Required, 1–255 characters |
| `email` | string (email) | Required, max 255 characters |
| `password` | string | Required, 8–72 characters |

### CustomerLogin

| Field | Type | Constraints |
| --- | --- | --- |
| `email` | string (email) | Required |
| `password` | string | Required (no minimum length on login) |

### CustomerUpdate

| Field | Type | Constraints |
| --- | --- | --- |
| `organization_name` | string | Optional, 1–255 characters |
| `email` | string (email) | Optional, max 255 characters |

At least one field required. Explicit `null` values rejected.

### CustomerPasswordChange

| Field | Type | Constraints |
| --- | --- | --- |
| `current_password` | string | Required |
| `new_password` | string | Required, 8–72 characters |

### CustomerRead

| Field | Type | Description |
| --- | --- | --- |
| `id` | UUID | Customer identifier |
| `organization_name` | string | Organization name |
| `email` | string (email) | Email address |
| `created_at` | datetime (ISO 8601) | Account creation timestamp |
| `updated_at` | datetime (ISO 8601) | Last update timestamp |

### Token

| Field | Type | Description |
| --- | --- | --- |
| `access_token` | string | JWT access token |
| `token_type` | string | Always `"bearer"` |

### FormFieldCreate

| Field | Type | Constraints | Default |
| --- | --- | --- | --- |
| `field_name` | string | Required, 1–100 chars, alphanumeric + `_` + `-` | — |
| `label` | string | Required, 1–255 characters | — |
| `field_type` | enum | `text`, `email`, `number`, `textarea` | — |
| `placeholder` | string \| null | Max 255 characters | `null` |
| `is_required` | boolean | — | `false` |
| `display_order` | integer | ≥ 0 | `0` |

### WidgetCreate

| Field | Type | Constraints | Default |
| --- | --- | --- | --- |
| `widget_type` | enum | `signup_form`, `contact_form`, `cta_popover` | — |
| `title` | string | Required, 1–255 characters | — |
| `description` | string \| null | — | `null` |
| `button_text` | string \| null | Max 100 characters | `null` |
| `theme_color` | string \| null | Max 20 characters | `null` |
| `is_active` | boolean | — | `true` |
| `form_fields` | FormFieldCreate[] | May be empty | `[]` |

### WidgetUpdate

Same fields as `WidgetCreate`, all optional. At least one field required. Nullable string fields (`description`, `button_text`, `theme_color`) may be set to `null` to clear.

### WidgetRead

| Field | Type | Description |
| --- | --- | --- |
| `id` | UUID | Widget identifier |
| `customer_id` | UUID | Owning customer |
| `widget_type` | string | Widget type |
| `title` | string | Display title |
| `description` | string \| null | Optional description |
| `button_text` | string \| null | Submit button label |
| `theme_color` | string \| null | CSS color for the button |
| `is_active` | boolean | Whether the widget accepts public traffic |
| `created_at` | datetime (ISO 8601) | Creation timestamp |
| `updated_at` | datetime (ISO 8601) | Last update timestamp |

### WidgetReadDetail

Extends `WidgetRead` with:

| Field | Type | Description |
| --- | --- | --- |
| `form_fields` | FormFieldRead[] | Ordered form field definitions |
| `embed_snippet` | string (computed) | HTML script tag for embedding |

### FormFieldRead

| Field | Type | Description |
| --- | --- | --- |
| `id` | UUID | Field identifier |
| `field_name` | string | Submission payload key |
| `label` | string | Display label |
| `field_type` | string | Input type |
| `placeholder` | string \| null | Placeholder text |
| `is_required` | boolean | Whether the field is required |
| `display_order` | integer | Render order |

### WidgetConfig

Public-facing widget configuration (no internal IDs or timestamps).

| Field | Type | Description |
| --- | --- | --- |
| `widget_type` | string | Widget type |
| `title` | string | Display title |
| `description` | string \| null | Optional description |
| `button_text` | string \| null | Submit button label |
| `theme_color` | string \| null | CSS color for the button |
| `form_fields` | FormFieldConfig[] | Ordered public field definitions |

### FormFieldConfig

| Field | Type | Description |
| --- | --- | --- |
| `field_name` | string | Submission payload key |
| `label` | string | Display label |
| `field_type` | string | Input type |
| `placeholder` | string \| null | Placeholder text |
| `is_required` | boolean | Whether the field is required |

### SubmissionCreate

| Field | Type | Description |
| --- | --- | --- |
| `field_values` | object | Map of `field_name` → string value (or `null`) |
| `referrer` | string \| null | Page URL where the form was submitted (not yet stored) |
| `user_agent` | string \| null | Browser user agent (overridden by `User-Agent` header if present) |

### SubmissionResponse

| Field | Type | Description |
| --- | --- | --- |
| `id` | string (UUID) | Submission identifier |
| `created_at` | string (ISO 8601) | Submission timestamp |
| `message` | string | User-facing confirmation message |

---

## Planned endpoints

The following endpoints have stub router modules but are **not registered** in the application. They are documented here for reference against the [PRD](PRD.md).

### Dashboard — `GET /api/v1/dashboard/submissions`

List submissions for the authenticated customer with pagination.

**Planned query parameters:** `widget_id` (optional filter), `limit`, `offset`

**Auth:** Bearer required

### Dashboard — `GET /api/v1/dashboard/analytics`

Return submission analytics: total count, per-widget breakdown, geo breakdown, spam breakdown.

**Auth:** Bearer required

### Alternate submission path — `POST /api/v1/public/widgets/{widget_id}/submit`

Planned alternate public submission URL. The live endpoint is `POST /api/v1/widgets/{widget_id}/submit`.

---

## Security & tenant isolation

### Ownership model

- Every widget belongs to exactly one customer (`customer_id`).
- Authenticated widget operations are scoped to the customer in the JWT `sub` claim.
- Submissions store both `widget_id` and `customer_id` for efficient tenant-scoped dashboard queries.

### Information hiding

- Requesting another tenant's widget by UUID returns **404**, not **403**.
- Login returns a single `"Invalid credentials"` message regardless of whether the email exists.
- All JWT validation failures return the same **401** message.

### Public endpoint exposure

Public delivery and submission endpoints intentionally expose minimal data:

- Config responses omit customer IDs, internal state, and timestamps.
- Inactive widgets (`is_active=false`) are indistinguishable from nonexistent widgets (both return 404).

### CORS

Public endpoints set `Access-Control-Allow-Origin: *` on individual responses. Global CORS middleware with OPTIONS preflight support is planned but not yet implemented. For cross-origin embedding from a different host than the API, ensure the browser can reach the API endpoints directly.

### Password policy

- Signup and password change require 8–72 characters (bcrypt's 72-byte limit).
- Passwords are hashed with bcrypt; hashes are never returned in API responses.

---

## Root endpoint

### `GET /`

Simple health check outside the versioned API prefix.

**Response `200 OK`**

```json
{
  "Hello": "World"
}
```
