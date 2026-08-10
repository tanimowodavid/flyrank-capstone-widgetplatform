"""Data access for widgets and their form fields. Owns queries; owns no rules.

Every read here takes customer_id and filters on it. Tenant isolation is a
property of the query, not of a check the caller is expected to remember: an
owner-scoped lookup that misses returns None, which the service turns into the
same 404 an absent widget produces.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.form_field import FormField
from app.models.widget import Widget


class WidgetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id_for_customer(
        self, widget_id: uuid.UUID, customer_id: uuid.UUID
    ) -> Widget | None:
        """Fetch one widget with its fields, scoped to its owner."""
        result = await self.session.execute(
            select(Widget)
            .where(Widget.id == widget_id, Widget.customer_id == customer_id)
            # selectinload, not lazy access: form_fields is read while rendering
            # the response, and a lazy load there raises in an async session.
            .options(selectinload(Widget.form_fields))
        )
        return result.scalar_one_or_none()

    async def list_for_customer(self, customer_id: uuid.UUID) -> Sequence[Widget]:
        """List a customer's widgets, newest first, without their fields."""
        result = await self.session.execute(
            select(Widget)
            .where(Widget.customer_id == customer_id)
            .order_by(Widget.created_at.desc())
        )
        return result.scalars().all()

    async def create(self, *, customer_id: uuid.UUID, **attributes) -> Widget:
        widget = Widget(customer_id=customer_id, **attributes)
        self.session.add(widget)
        await self.session.flush()
        return widget

    def add_form_fields(
        self, *, widget_id: uuid.UUID, fields: Sequence[dict]
    ) -> list[FormField]:
        """Stage field rows for `widget_id`. Not flushed — the caller commits."""
        rows = [FormField(widget_id=widget_id, **field) for field in fields]
        self.session.add_all(rows)
        return rows

    async def delete_form_fields(self, widget_id: uuid.UUID) -> None:
        """Remove every field belonging to a widget.

        Used by the full-replace update: fields are recreated from the request
        rather than diffed, so the old set is cleared first.
        """
        await self.session.execute(
            delete(FormField).where(FormField.widget_id == widget_id)
        )

    async def delete(self, widget: Widget) -> None:
        """Delete a widget row.

        Core DELETE rather than session.delete(widget): the database's ON DELETE
        rules are what remove form_fields (CASCADE) and null submissions.widget_id
        (SET NULL), so the guarantee does not depend on the ORM's relationship
        handling.
        """
        await self.session.execute(delete(Widget).where(Widget.id == widget.id))
