"""Public-facing schemas for widget delivery.

Deliberately separate types from app/schemas/widget.py rather than a subset or a
subclass of them. Those schemas answer "what does the owner see about their
widget"; these answer "what does an anonymous page on a site we have never heard
of need in order to draw it". The second question has a much smaller answer, and
keeping it a distinct type means a column added for the owner's dashboard cannot
reach a third-party page by inheritance.
"""

from pydantic import BaseModel, ConfigDict


class FormFieldConfig(BaseModel):
    """One input, as the embed script needs to render it.

    No id and no display_order: the renderer submits values keyed by field_name,
    so the row's primary key is of no use to it, and order is already carried by
    this item's position in the list.
    """

    model_config = ConfigDict(from_attributes=True)

    field_name: str
    label: str
    field_type: str
    placeholder: str | None
    is_required: bool


class WidgetConfig(BaseModel):
    """Everything needed to draw one widget, and nothing else.

    Absent on purpose: customer_id (which organisation owns this), id and
    is_active (internal state the renderer cannot act on), created_at and
    updated_at (operational history). This response is served to any origin that
    asks, so every field here is a field published to the whole internet.
    """

    model_config = ConfigDict(from_attributes=True)

    widget_type: str
    title: str
    description: str | None
    button_text: str | None
    theme_color: str | None
    # Ordered by FormField.display_order, applied by the relationship itself so
    # every load path shares it rather than just one query.
    form_fields: list[FormFieldConfig]
