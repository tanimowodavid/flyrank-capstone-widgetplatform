"""Public endpoints for widget delivery (PRD Path B - semi-trusted, cacheable).

Two endpoints under this module:
  1. GET /widgets/{id}/config - Widget configuration (form fields, labels, etc.)
     Returns WidgetConfig (from app/schemas/delivery.py)
     Cacheable: served with Cache-Control headers
     CORS enabled: accessible from any origin
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from app.core.deps import DbSession
from app.repositories.widget import WidgetRepository
from app.schemas.delivery import WidgetConfig

router = APIRouter(prefix="/widgets", tags=["delivery"])


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
