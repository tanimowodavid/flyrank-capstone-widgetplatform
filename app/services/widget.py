"""Widget business rules: creation, owner-scoped lookup, update, deletion.

Raises domain errors rather than HTTPException — mapping to status codes belongs
in the endpoint layer, matching AuthService.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.widget import Widget
from app.repositories.widget import WidgetRepository
from app.schemas.widget import FormFieldCreate, WidgetCreate, WidgetUpdate


class WidgetNotFoundError(Exception):
    """No widget with this id belongs to this customer.

    Deliberately does not distinguish "does not exist" from "belongs to someone
    else": both must produce the same 404, or the endpoint becomes an oracle for
    which widget ids exist across tenants.
    """


class WidgetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.widgets = WidgetRepository(session)

    async def create(self, customer_id: uuid.UUID, payload: WidgetCreate) -> Widget:
        """Create a widget and its fields as one atomic unit.

        customer_id comes from the authenticated caller. WidgetCreate has no such
        field, so a client cannot supply one even by sending it.
        """
        attributes = payload.model_dump(exclude={"form_fields"})
        widget = await self.widgets.create(customer_id=customer_id, **attributes)

        self.widgets.add_form_fields(
            widget_id=widget.id,
            fields=self._ordered_field_rows(payload.form_fields),
        )

        # One commit for the widget and every field: a failure part-way through
        # leaves no half-built widget behind.
        await self.session.commit()

        # Re-read through the owner-scoped path so form_fields is eagerly loaded
        # for the response.
        return await self.get_for_customer(widget.id, customer_id)

    async def get_for_customer(
        self, widget_id: uuid.UUID, customer_id: uuid.UUID
    ) -> Widget:
        widget = await self.widgets.get_by_id_for_customer(widget_id, customer_id)
        if widget is None:
            raise WidgetNotFoundError(widget_id)
        return widget

    async def list_for_customer(self, customer_id: uuid.UUID) -> Sequence[Widget]:
        return await self.widgets.list_for_customer(customer_id)

    async def update(
        self, widget_id: uuid.UUID, customer_id: uuid.UUID, payload: WidgetUpdate
    ) -> Widget:
        """Apply a partial update, replacing form fields wholesale if given.

        Fields are replaced rather than diffed: the client sends the complete
        current set, the old rows are deleted, and new ones are inserted. Diffing
        would mean matching old rows to new ones by field_name — but field_name is
        itself editable, so a rename is indistinguishable from a delete plus an
        add. Replacing sidesteps that ambiguity entirely.

        Omitting form_fields leaves the existing set alone; sending [] clears it.
        """
        widget = await self.get_for_customer(widget_id, customer_id)

        attributes = payload.model_dump(
            exclude={"form_fields"}, exclude_unset=True
        )
        for name, value in attributes.items():
            setattr(widget, name, value)

        # Replacement is opt-in: `is None` distinguishes "key absent" from an
        # explicit [], which means "this widget now collects nothing".
        if payload.form_fields is not None:
            await self.widgets.delete_form_fields(widget.id)
            self.widgets.add_form_fields(
                widget_id=widget.id,
                fields=self._ordered_field_rows(payload.form_fields),
            )

        # One commit for the attribute changes, the deletes and the inserts: a
        # failure mid-way must not leave a widget with half its fields replaced.
        await self.session.commit()

        return await self.get_for_customer(widget.id, customer_id)

    async def delete(self, widget_id: uuid.UUID, customer_id: uuid.UUID) -> None:
        """Delete a widget the caller owns.

        Form fields go with it (ON DELETE CASCADE) but submissions do not: their
        widget_id is ON DELETE SET NULL, so a captured lead outlives the form it
        arrived through. Both behaviours are the database's, not this method's.
        """
        widget = await self.get_for_customer(widget_id, customer_id)
        await self.widgets.delete(widget)
        await self.session.commit()

    @staticmethod
    def _ordered_field_rows(fields: Sequence[FormFieldCreate]) -> list[dict]:
        """Turn field schemas into row kwargs, filling in display_order.

        A client that sends explicit display_order values keeps them. One that
        omits them gets list position instead of every field silently sharing the
        default of 0, which would leave the form's order undefined.
        """
        any_explicit = any(
            "display_order" in field.model_fields_set for field in fields
        )
        rows = []
        for position, field in enumerate(fields):
            row = field.model_dump()
            if not any_explicit:
                row["display_order"] = position
            rows.append(row)
        return rows
