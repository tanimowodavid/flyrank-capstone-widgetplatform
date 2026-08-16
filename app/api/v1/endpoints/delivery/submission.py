"""Public submission endpoint (PRD Path C - collecting visitor form submissions)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.deps import DbSession
from app.repositories.submission import SubmissionRepository
from app.repositories.widget import WidgetRepository
from app.schemas.delivery import SubmissionCreate, SubmissionResponse
from app.schemas.submission import SubmissionData

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
async def submit_widget_response(
    widget_id: uuid.UUID,
    submission: SubmissionCreate,
    db: DbSession,
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

    This endpoint:
      1. Verifies the widget exists and is active
      2. Retrieves the widget's customer (tenant isolation)
      3. Stores the submission with best-effort enrichment data
      4. Returns a success response with submission ID

    Spam is flagged, not refused. A submission whose honeypot was filled is
    stored with is_spam=True and gets the same 201 and the same message as any
    other, because a distinguishable response is a signal a bot can tune
    against: tell it which attempts were caught and it learns to stop filling
    the trap (PRD FR4.2).

    Geolocation enrichment is best-effort; submission is stored
    even if enrichment fails.
    """
    # Get the widget and verify it's active
    widget_repo = WidgetRepository(db)
    widget = await widget_repo.get_by_id_public(widget_id)

    if widget is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Widget not found or inactive",
        )

    # Get the customer (widget.customer_id is set, but retrieved via relationship)
    customer_id = widget.customer_id

    # Extract IP address (prefer X-Forwarded-For for proxy scenarios)
    submitter_ip = None
    if x_forwarded_for:
        # X-Forwarded-For can be a comma-separated list; take the first (original client)
        submitter_ip = x_forwarded_for.split(",")[0].strip()

    # Create the submission. from_field_values takes the honeypot out of the
    # payload and turns it into the is_spam flag, so what the repository stores is
    # the widget's real fields and nothing else.
    submission_repo = SubmissionRepository(db)
    created_submission = await submission_repo.create(
        SubmissionData.from_field_values(
            widget_id=widget_id,
            customer_id=customer_id,
            field_values=submission.field_values,
            submitter_ip=submitter_ip,
            user_agent=user_agent or submission.user_agent,
        )
    )

    # Commit the transaction
    await db.commit()

    # Return success response
    response_data = {
        "id": str(created_submission.id),
        "created_at": created_submission.created_at.isoformat(),
        "message": "Thank you for your submission",
    }

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=response_data,
        headers={
            # Allow cross-origin submissions
            "Access-Control-Allow-Origin": "*",
            # POST submissions are not cached (only GET is)
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )
