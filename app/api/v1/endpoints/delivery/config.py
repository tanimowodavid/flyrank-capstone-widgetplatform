"""Public endpoints for widget delivery (PRD Path B - semi-trusted, cacheable).

Two endpoints under this module:
  1. GET /widgets/{id}/config - Widget configuration (form fields, labels, etc.)
     Returns WidgetConfig (from app/schemas/delivery.py)
     Cacheable: served with Cache-Control headers
     CORS enabled: accessible from any origin
     
  2. GET /widget.js - Embeddable widget JavaScript
     Vanilla JavaScript, no build step
     Cacheable: long-term cache with immutable flag
     CORS enabled: accessible from any origin
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, Response

from app.core.deps import DbSession
from app.repositories.widget import WidgetRepository
from app.schemas.delivery import WidgetConfig, honeypot_field_config

# Router for widget config and other widget-specific delivery endpoints (prefixed with /widgets)
router = APIRouter(prefix="/widgets", tags=["delivery"])

# Router for static assets like widget.js (no prefix, serves at /api/v1/widget.js)
static_router = APIRouter(tags=["delivery"])



@router.get(
    "/{widget_id}/config",
    response_model=WidgetConfig,
    summary="Get widget configuration (public endpoint, no auth required)",
)
async def get_widget_config(
    widget_id: uuid.UUID,
    db: DbSession,
) -> Response:
    """Fetch public widget configuration for rendering.

    Returns minimal payload: type, title, description, button_text, theme_color,
    and ordered form fields. Does not include customer_id, timestamps, or
    internal state.

    form_fields always carries one entry the widget's owner never defined: the
    honeypot, flagged is_honeypot=True for the renderer to hide (PRD FR4.2).

    Returns 404 if:
      - Widget does not exist
      - Widget exists but is_active=False (both indistinguishable to caller)

    Cacheable with short TTL (60s) since widget config can change when edited.
    Accessible from any origin (CORS enabled for third-party websites).
    """
    repo = WidgetRepository(db)
    widget = await repo.get_by_id_public(widget_id)

    if widget is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Widget not found",
        )

    # Serialize using WidgetConfig schema (filters out customer_id, is_active, timestamps)
    config = WidgetConfig.model_validate(widget)

    # Appended here rather than stored as a FormField row: the trap belongs to the
    # platform's spam defence, not to the owner's form definition, so it must not
    # appear in their dashboard or survive an edit to their fields. Last in the
    # list so the real fields keep the display_order they were given.
    config.form_fields.append(honeypot_field_config())

    # Cache-Control: public (cacheable by browsers and proxies), max-age=60 (1 minute)
    response = Response(
        content=config.model_dump_json(),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )
    response.headers["Cache-Control"] = "public, max-age=60"
    # CORS: allow any origin (widget.js may be loaded from any third-party site)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@static_router.get(
    "/widget.js",
    summary="Get embeddable widget JavaScript (public endpoint, no auth required)",
    response_class=FileResponse,
)
async def get_widget_script() -> FileResponse:
    """Serve the embeddable widget.js script.

    This is vanilla JavaScript (no build step, no dependencies) that can be loaded
    on any third-party website. It extracts the widget ID from the script tag's
    query parameter, fetches config, renders a form, and submits responses.

    Cacheable with very long TTL (1 year) and immutable flag because:
      - The script is identified by its URL, not by version
      - Widget ID and config are query-time fetches
      - Safe to aggressively cache this static asset

    CORS enabled for loading from any origin.
    """
    # Path: app/static/widget.js
    # From config.py (app/api/v1/endpoints/delivery/config.py), go up 5 levels to get to app/
    script_path = Path(__file__).parent.parent.parent.parent.parent / "static" / "widget.js"

    response = FileResponse(
        script_path,
        media_type="application/javascript",
        filename="widget.js",
    )
    # Cache-Control: max-age=31536000 (1 year), immutable (never changes)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    # CORS: allow any origin
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response
