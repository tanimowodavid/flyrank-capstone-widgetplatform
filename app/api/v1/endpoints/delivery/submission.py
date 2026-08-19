"""Public submission endpoint (PRD Path C - collecting visitor form submissions)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.deps import DbSession, HttpClient
from app.core.rate_limit import limiter
from app.schemas.delivery import SubmissionCreate, SubmissionResponse
from app.services.enrichment import EnrichmentService
from app.services.submission import SubmissionService, WidgetNotAvailableError

# Router for submission endpoints
router = APIRouter(prefix="/widgets", tags=["submission"])



@router.options("/{widget_id}/submit", include_in_schema=False)
async def options_submit_widget_response() -> JSONResponse:
    """Handle CORS preflight OPTIONS request from third-party sites."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ok"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "86400",
        },
    )


@router.post(
    "/{widget_id}/submit",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit form response (public endpoint, no auth required)",
)
@limiter.limit(settings.RATE_LIMIT_SUBMIT)
async def submit_widget_response(
    request: Request,
    response: Response,
    widget_id: uuid.UUID,
    submission: SubmissionCreate,
    db: DbSession,
    http_client: HttpClient,
    user_agent: Annotated[str | None, Header()] = None,
    x_forwarded_for: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Accept an anonymous form submission from an embedded widget.

    The client (embed script) submits:
      - field_values: dict of field_name → value pairs from the rendered form
      - referrer: optional referrer URL (where the form was loaded from)
      - user_agent: optional user-agent (redundant if trusting HTTP header)

    Returns:
      - 201 Created with submission ID and timestamp if accepted
      - 404 if widget doesn't exist or is inactive
      - 422 if submission payload is invalid (missing required fields)

    This endpoint reads what only it can see — the forwarded address and the
    User-Agent header — and hands the rest to SubmissionService, which verifies
    the widget, flags spam, enriches, and stores. Everything here is HTTP:
    header extraction, mapping a domain error to 404, and the CORS and
    cache headers a cross-origin POST needs.

    Spam is flagged, not refused. A submission whose honeypot was filled is
    stored with is_spam=True and gets the same 201 and the same message as any
    other, because a distinguishable response is a signal a bot can tune
    against: tell it which attempts were caught and it learns to stop filling
    the trap (PRD FR4.2).

    Geolocation enrichment is best-effort; submission is stored
    even if enrichment fails.
    """
    # Extract IP address (prefer X-Forwarded-For for proxy scenarios)
    submitter_ip = None
    if x_forwarded_for:
        # X-Forwarded-For can be a comma-separated list; take the first (original client)
        submitter_ip = x_forwarded_for.split(",")[0].strip()

    service = SubmissionService(db, EnrichmentService(http_client))

    try:
        created_submission = await service.record(
            widget_id=widget_id,
            payload=submission,
            submitter_ip=submitter_ip,
            # The header wins over the body's copy: a client can claim any
            # user_agent it likes, but only one of the two was observed.
            user_agent=user_agent or submission.user_agent,
        )
    except WidgetNotAvailableError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Widget not found or inactive",
        ) from None

    # Return success response
    response_data = {
        "id": str(created_submission.id),
        "created_at": created_submission.created_at.isoformat(),
        "message": "Thank you for your submission",
    }

    # Allow cross-origin submissions
    response.headers["Access-Control-Allow-Origin"] = "*"
    # POST submissions are not cached (only GET is)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

    return response_data
