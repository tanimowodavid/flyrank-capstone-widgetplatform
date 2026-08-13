"""Public submission endpoint (PRD Path C - collecting visitor form submissions)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.deps import DbSession
from app.repositories.submission import SubmissionRepository
from app.repositories.widget import WidgetRepository
from app.schemas.delivery import SubmissionCreate, SubmissionResponse

# Router for submission endpoints
router = APIRouter(prefix="/widgets", tags=["submission"])


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

    Note: Spam detection (Stage 5) runs asynchronously after submission.
    Geolocation enrichment (Stage 6) is best-effort; submission is stored
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

    # Create the submission
    submission_repo = SubmissionRepository(db)
    created_submission = await submission_repo.create(
        widget_id=widget_id,
        customer_id=customer_id,
        payload=submission.field_values,
        submitter_ip=submitter_ip,
        user_agent=user_agent or submission.user_agent,
        # Geolocation enrichment will be added in Stage 6
        geo_country=None,
        geo_city=None,
        geo_provider=None,
        # Spam detection will be added in Stage 5
        is_spam=False,
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
