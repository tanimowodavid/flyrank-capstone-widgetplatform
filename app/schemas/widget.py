"""Request and response schemas for widgets and their form fields."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
        """Reject duplicate field_names within one widget.

        Submission payloads are keyed by field_name, so two fields sharing a name
        would silently collapse into one value at submission time. Compared
        case-insensitively: "Email" and "email" would be two distinct JSON keys
        but are the same field to anyone reading the form.
        """
        names = [field.field_name.lower() for field in fields]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(
                f"field_name must be unique within a widget; duplicated: "
                f"{', '.join(duplicates)}"
            )
        return fields


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
    """Widget with its full field set, for the retrieve endpoint."""

    form_fields: list[FormFieldRead] = Field(default_factory=list)
