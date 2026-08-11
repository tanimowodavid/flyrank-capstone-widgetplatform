"""Widget ORM model — a configurable form owned by exactly one customer.

Data layer only: no endpoints or services target this table yet. It exists now so
the customer delete cascade is enforced by the schema rather than by application
code, and so a later widget feature inherits the shape from docs/ERD.mmd.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.customer import Customer
from app.models.form_field import FormField
from app.models.submission import Submission

from app.db.base import Base


class Widget(Base):
    __tablename__ = "widgets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # ondelete in the database, not cascade in the ORM: deleting a customer
        # must take their widgets with it even when the delete is issued by raw
        # SQL, a migration, or another service entirely.
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        # Every owner-scoped query filters on this column, so the index is not
        # optional — tenant isolation means it is on the hot path.
        index=True,
    )
    widget_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    button_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    theme_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # passive_deletes tells SQLAlchemy not to load children and null their FKs on
    # delete; without it the ORM would undo the ON DELETE CASCADE above.
    customer: Mapped["Customer"] = relationship(back_populates="widgets")  # noqa: F821
    form_fields: Mapped[list["FormField"]] = relationship(  # noqa: F821
        back_populates="widget",
        cascade="all, delete",
        passive_deletes=True,
        # Postgres returns rows in no guaranteed order, so without this the form
        # would render its inputs arbitrarily despite display_order being stored
        # correctly. Ordering here covers every load path, not just one query.
        order_by="FormField.display_order",
    )
    # No delete cascade, unlike form_fields: the FK is ON DELETE SET NULL, so
    # deleting a widget orphans its submissions rather than destroying them — a
    # captured lead outlives the form it arrived through. passive_deletes leaves
    # the nulling to Postgres instead of having the ORM rewrite each row.
    submissions: Mapped[list["Submission"]] = relationship(  # noqa: F821
        back_populates="widget",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Widget id={self.id} title={self.title!r}>"
