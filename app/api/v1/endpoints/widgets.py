"""Widget CRUD for the authenticated owner (PRD Path A)."""

from fastapi import APIRouter, status

from app.core.deps import CurrentCustomer, DbSession
from app.schemas.widget import WidgetCreate, WidgetReadDetail
from app.services.widget import WidgetService

router = APIRouter(prefix="/widgets", tags=["widgets"])


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
    widget = await WidgetService(db).create(customer.id, payload)
    return WidgetReadDetail.model_validate(widget)
