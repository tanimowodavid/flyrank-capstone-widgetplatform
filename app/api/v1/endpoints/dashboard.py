"""Dashboard endpoints for authenticated owners (PRD Path A - view submissions and analytics).

Two endpoints:
  1. GET /dashboard/submissions - List submissions for authenticated customer
     Filters by customer_id (from the token), optionally by widget_id
     Supports pagination (limit/offset), newest first
     
  2. GET /dashboard/analytics - Basic analytics for customer's widgets
     Submission counts: total, per-widget, per-country, spam split, over time

Tenant isolation is the repository's job: every query carries the caller's
customer_id. A widget_id filter that belongs to another tenant produces the same
404 as a widget that does not exist, matching the widget endpoints.
"""

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.core.deps import CurrentCustomer, DbSession
from app.schemas.submission import SubmissionAnalytics, SubmissionPage
from app.services.dashboard import DashboardService
from app.services.widget import WidgetNotFoundError

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _widget_not_found() -> HTTPException:
    """404 for both "no such widget" and "not yours" — see widgets.py's note."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Widget not found",
    )


@router.get(
    "/submissions",
    response_model=SubmissionPage,
    summary="List the authenticated customer's submissions",
)
async def list_submissions(
    customer: CurrentCustomer,
    db: DbSession,
    widget_id: uuid.UUID | None = Query(
        default=None, description="Restrict to one of the caller's widgets"
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SubmissionPage:
    """Paginated submissions, newest first, with the matching total.

    `limit` is capped so a single request cannot ask the database to materialise
    an unbounded result set; the frontend pages through with offset.
    """
    try:
        return await DashboardService(db).list_submissions(
            customer_id=customer.id,
            widget_id=widget_id,
            limit=limit,
            offset=offset,
        )
    except WidgetNotFoundError as exc:
        raise _widget_not_found() from exc


@router.get(
    "/analytics",
    response_model=SubmissionAnalytics,
    summary="Return analytics for the authenticated customer's submissions",
)
async def analytics(
    customer: CurrentCustomer,
    db: DbSession,
    widget_id: uuid.UUID | None = Query(
        default=None, description="Restrict to one of the caller's widgets"
    ),
) -> SubmissionAnalytics:
    """Totals and breakdowns across the customer's submissions (PRD FR6.2)."""
    try:
        return await DashboardService(db).analytics(
            customer_id=customer.id, widget_id=widget_id
        )
    except WidgetNotFoundError as exc:
        raise _widget_not_found() from exc