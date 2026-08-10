"""FormField ORM model — one input in a widget's form.

Data layer only, created alongside Widget so the delete cascade covers the whole
tree described in docs/ERD.mmd.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FormField(Base):
    __tablename__ = "form_fields"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    widget_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # Reached transitively when a customer is deleted: customers -> widgets
        # -> form_fields. Postgres cascades the whole chain in one statement.
        ForeignKey("widgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[str] = mapped_column(String(50), nullable=False)
    placeholder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )

    widget: Mapped["Widget"] = relationship(back_populates="form_fields")  # noqa: F821

    def __repr__(self) -> str:
        return f"<FormField id={self.id} field_name={self.field_name!r}>"
