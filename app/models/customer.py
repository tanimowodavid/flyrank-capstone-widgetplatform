"""Customer ORM model — the tenant that owns widgets and their submissions."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Both modules import Customer, so these stay type-check only.
if TYPE_CHECKING:
    from app.models.submission import Submission
    from app.models.widget import Widget


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        # Generated in the database so rows inserted by migrations, seed scripts
        # or raw SQL get an id without going through the ORM.
        server_default=text("gen_random_uuid()"),
    )
    organization_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        # Signup and login both look up by email; the unique index serves both.
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        # Server-side default only fires on INSERT; onupdate keeps the column
        # honest on every ORM UPDATE.
        onupdate=func.now(),
    )

    # passive_deletes=True leaves the delete to the database's ON DELETE CASCADE.
    # Without it SQLAlchemy would load every child row and try to null its FK,
    # which fails against a NOT NULL column and defeats the point of the cascade.
    widgets: Mapped[list["Widget"]] = relationship(
        back_populates="customer",
        cascade="all, delete",
        passive_deletes=True,
    )
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="customer",
        cascade="all, delete",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Customer id={self.id} email={self.email!r}>"
