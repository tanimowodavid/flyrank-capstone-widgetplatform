"""Submission ORM model — one visitor's form entry.

Data layer only. Carries both widget_id and customer_id per docs/ERD.mmd: the
denormalised customer_id is what lets the owner dashboard list a tenant's
submissions without joining through widgets on every query.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.customer import Customer
from app.models.widget import Widget

from app.db.base import Base


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    widget_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # SET NULL rather than CASCADE: a submission must outlive the widget it
        # was created against. The stored payload and its snapshot keep the
        # historical record meaningful even after the widget is deleted.
        ForeignKey("widgets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # Cascades independently of widget_id. Both paths lead here when a
        # customer is deleted, and either one alone is enough — so a submission
        # can never outlive the tenant it belongs to.
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # JSONB rather than JSON: the payload shape is defined per widget, and JSONB
    # is what makes it queryable later without a migration per field.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # String, not INET: values arrive from proxy headers and are not guaranteed
    # to parse as an address. Storing the raw value keeps a malformed one from
    # rejecting an otherwise valid submission.
    submitter_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # All three geo columns stay nullable: enrichment is best-effort, and a dead
    # provider must never block storage (PRD FR5.2).
    geo_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    geo_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    geo_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_spam: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    widget: Mapped["Widget"] = relationship(back_populates="submissions")  # noqa: F821
    customer: Mapped["Customer"] = relationship(  # noqa: F821
        back_populates="submissions"
    )

    def __repr__(self) -> str:
        return f"<Submission id={self.id} widget_id={self.widget_id}>"
