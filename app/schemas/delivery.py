"""Public-facing schemas for widget delivery.

Deliberately separate types from app/schemas/widget.py rather than a subset or a
subclass of them. Those schemas answer "what does the owner see about their
widget"; these answer "what does an anonymous page on a site we have never heard
of need in order to draw it". The second question has a much smaller answer, and
keeping it a distinct type means a column added for the owner's dashboard cannot
reach a third-party page by inheritance.
"""

from pydantic import BaseModel, ConfigDict

from app.core.config import settings


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
    # False for every real FormField row, which is why it carries a default: the
    # model is validated straight off an ORM object that has no such column. Only
    # the trap below sets it, and it tells the renderer to draw that one
    # off-screen instead of in the visible form.
    is_honeypot: bool = False


def honeypot_field_config() -> FormFieldConfig:
    """The spam trap appended to every widget's fields (PRD FR4.2).

    Not a FormField row and not stored anywhere — it lives only in this response
    and in the form the renderer draws from it.

    Two of these values are load-bearing rather than arbitrary:

    is_required stays False because a required field a visitor cannot see is a
    form they can never submit.

    field_type is "text" rather than "email" despite the label, because an
    <input type="email"> makes the browser reject a junk value and refuse to
    submit the form. That would block precisely the submissions we want to
    receive and flag, turning a detector into a filter.
    """
    return FormFieldConfig(
        # Read from settings on every call rather than captured at import time,
        # so rotating the name takes effect without a restart.
        field_name=settings.HONEYPOT_FIELD_NAME,
        # Plausible enough that a bot filling fields by label will take the bait.
        label="Confirm your email",
        field_type="text",
        placeholder=None,
        is_required=False,
        is_honeypot=True,
    )


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


class SubmissionCreate(BaseModel):
    """Anonymous submission from an embedded form.

    The embed script collects form values keyed by field_name, and posts them
    directly with no server-side processing. The backend enriches this with
    geolocation, spam filtering, and timestamps.
    """

    model_config = ConfigDict(from_attributes=True)

    # Form field values, keyed by field_name from the form definition
    # e.g. {"email": "user@example.com", "name": "John"}
    field_values: dict[str, str | None]
    # Optional referrer URL (captures where the submission came from)
    referrer: str | None = None
    # Optional user agent (useful for spam analysis)
    user_agent: str | None = None


class SubmissionResponse(BaseModel):
    """Response after successful submission."""

    model_config = ConfigDict(from_attributes=True)

    # Submission ID for tracking/reference
    id: str
    # Timestamp of submission
    created_at: str
    # Message for the end user
    message: str
