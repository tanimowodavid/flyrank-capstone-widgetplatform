"""Request and response schemas for widgets and their form fields."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.core.config import settings

# Literal rather than a database enum: the set is small, app-level, and changing
# it should be a code change with a migration-free deploy. Pydantic rejects
# anything outside it as a 422 before the request reaches the service layer.
WidgetType = Literal["signup_form", "contact_form", "cta_popover"]
FieldType = Literal["text", "email", "number", "textarea", "checkbox"]


class FormFieldCreate(BaseModel):
    """One input in a widget's form, as supplied by the owner."""

    field_name: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=255)
    field_type: FieldType
    placeholder: str | None = Field(default=None, max_length=255)
    is_required: bool = False
    # Defaults to 0 rather than the list index: an explicit value from the client
    # is authoritative, and the service fills in positions when it is omitted.
    display_order: int = Field(default=0, ge=0)

    @field_validator("field_name")
    @classmethod
    def field_name_must_be_an_identifier(cls, value: str) -> str:
        """Constrain to a form-safe key.

        field_name becomes a key in the submission payload JSON, so it has to
        survive being a form input name and a JSON object key. Rejecting the
        awkward characters here keeps that contract enforced at the edge.
        """
        candidate = value.strip()
        if not candidate.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "field_name may contain only letters, digits, underscores and hyphens"
            )
        return candidate


def _reject_duplicate_field_names(
    fields: list[FormFieldCreate] | None,
) -> list[FormFieldCreate] | None:
    """Reject duplicate field_names within one widget.

    Submission payloads are keyed by field_name, so two fields sharing a name
    would silently collapse into one value at submission time. Compared
    case-insensitively: "Email" and "email" would be two distinct JSON keys but
    are the same field to anyone reading the form.

    Shared by create and update because a full-replace update can introduce a
    collision just as easily as creation can.
    """
    if fields is None:
        return fields

    names = [field.field_name.lower() for field in fields]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(
            f"field_name must be unique within a widget; duplicated: "
            f"{', '.join(duplicates)}"
        )
    return fields


class WidgetCreate(BaseModel):
    """A new widget and the complete set of fields it collects.

    customer_id is deliberately absent: ownership comes from the access token,
    never from the request body.
    """

    widget_type: WidgetType
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    button_text: str | None = Field(default=None, max_length=100)
    theme_color: str | None = Field(default=None, max_length=20)
    is_active: bool = True
    # Empty list allowed: a cta_popover is a button, not a form, so requiring at
    # least one field would rule out a legitimate widget type.
    form_fields: list[FormFieldCreate] = Field(default_factory=list)

    @field_validator("form_fields")
    @classmethod
    def field_names_must_be_unique(
        cls, fields: list[FormFieldCreate]
    ) -> list[FormFieldCreate]:
        return _reject_duplicate_field_names(fields)


class WidgetUpdate(BaseModel):
    """Partial update of a widget, and optionally a full replacement of its fields.

    form_fields is all-or-nothing: omit the key and the existing fields are left
    untouched; send it and it replaces the entire set. There is no way to edit a
    single field in place — see WidgetService.update for why.
    """

    widget_type: WidgetType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    button_text: str | None = Field(default=None, max_length=100)
    theme_color: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None
    form_fields: list[FormFieldCreate] | None = None

    # Columns that are nullable in the database, so an explicit null on these is a
    # real instruction ("clear this"), not a malformed request.
    _CLEARABLE = frozenset({"description", "button_text", "theme_color"})

    @field_validator("form_fields")
    @classmethod
    def field_names_must_be_unique(
        cls, fields: list[FormFieldCreate] | None
    ) -> list[FormFieldCreate] | None:
        return _reject_duplicate_field_names(fields)

    @model_validator(mode="after")
    def reject_empty_and_invalid_nulls(self) -> "WidgetUpdate":
        """Require at least one field, and forbid nulls on non-nullable columns.

        Unknown keys are ignored by default, so without the first check a typo'd
        field name ("widgetType") would return 200 having changed nothing — a
        silent no-op the client reads as success.
        """
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")

        nulled = sorted(
            name
            for name in self.model_fields_set
            if getattr(self, name) is None and name not in self._CLEARABLE
        )
        if nulled:
            raise ValueError(f"Field(s) may not be null: {', '.join(nulled)}")

        return self


class FormFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    field_name: str
    label: str
    field_type: str
    placeholder: str | None
    is_required: bool
    display_order: int


class WidgetRead(BaseModel):
    """Widget as returned to its owner, without its fields.

    Used by the list endpoint, where loading every widget's fields would be a
    query per row for data the caller did not ask for.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    widget_type: str
    title: str
    description: str | None
    button_text: str | None
    theme_color: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WidgetReadDetail(WidgetRead):
    """Widget with its full field set and its embed snippet."""

    form_fields: list[FormFieldRead] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def embed_snippet(self) -> str:
        """The <script> tag the owner pastes into their site.

        Derived from id rather than stored: it is a formatting of data the
        response already carries, so persisting it would mean a column that can
        disagree with the id beside it, plus a migration every time the loader's
        URL changes.
        """
        return (
            f'<script src="{settings.WIDGET_EMBED_BASE_URL}'
            f'/widget.js?id={self.id}"></script>'
        )
