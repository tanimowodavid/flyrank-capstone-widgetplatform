"""Widget CRUD for the authenticated owner (PRD Path A)."""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.deps import CurrentCustomer, DbSession
from app.schemas.widget import (
    WidgetCreate,
    WidgetRead,
    WidgetReadDetail,
    WidgetUpdate,
)
from app.services.widget import WidgetNotFoundError, WidgetService

router = APIRouter(prefix="/widgets", tags=["widgets"])


def _not_found() -> HTTPException:
    """404 for both "no such widget" and "not yours".

    A 403 would confirm the widget exists, turning the endpoint into an oracle
    for ids owned by other tenants (PRD FR1.4).
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Widget not found",
    )


@router.post(
    "",
    response_model=WidgetReadDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a widget and its form fields",
)
async def create_widget(
    payload: WidgetCreate,
    customer: CurrentCustomer,
    db: DbSession,
) -> WidgetReadDetail:
    # TODO: FR2.1 - embed_snippet in response will work once delivery endpoints are implemented
    # The snippet points to /public/widgets/{widget_id}/config which is not yet implemented
    widget = await WidgetService(db).create(customer.id, payload)
    return WidgetReadDetail.model_validate(widget)


@router.get(
    "",
    response_model=list[WidgetRead],
    summary="List the authenticated customer's widgets",
)
async def list_widgets(
    customer: CurrentCustomer,
    db: DbSession,
) -> list[WidgetRead]:
    widgets = await WidgetService(db).list_for_customer(customer.id)
    return [WidgetRead.model_validate(widget) for widget in widgets]


@router.get(
    "/{widget_id}",
    response_model=WidgetReadDetail,
    summary="Retrieve one widget with its form fields",
)
async def read_widget(
    widget_id: uuid.UUID,
    customer: CurrentCustomer,
    db: DbSession,
) -> WidgetReadDetail:
    try:
        widget = await WidgetService(db).get_for_customer(widget_id, customer.id)
    except WidgetNotFoundError as exc:
        raise _not_found() from exc

    return WidgetReadDetail.model_validate(widget)


@router.patch(
    "/{widget_id}",
    response_model=WidgetReadDetail,
    summary="Update a widget, replacing its form fields",
)
async def update_widget(
    widget_id: uuid.UUID,
    payload: WidgetUpdate,
    customer: CurrentCustomer,
    db: DbSession,
) -> WidgetReadDetail:
    """Partial update. Sending form_fields replaces the whole set; omitting it
    leaves the existing fields untouched."""
    try:
        widget = await WidgetService(db).update(widget_id, customer.id, payload)
    except WidgetNotFoundError as exc:
        raise _not_found() from exc

    return WidgetReadDetail.model_validate(widget)


@router.delete(
    "/{widget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a widget, preserving its submissions",
)
async def delete_widget(
    widget_id: uuid.UUID,
    customer: CurrentCustomer,
    db: DbSession,
) -> None:
    """Removes the widget and its form fields. Submissions survive with a null
    widget_id — a captured lead outlives the form it arrived through."""
    try:
        await WidgetService(db).delete(widget_id, customer.id)
    except WidgetNotFoundError as exc:
        raise _not_found() from exc
