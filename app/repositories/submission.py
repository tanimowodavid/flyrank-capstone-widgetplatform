"""Submission data access layer (PRD Path C - persisting visitor submissions)."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.submission import Submission

if TYPE_CHECKING:
    pass


class SubmissionRepository:
    """Submission queries with automatic tenant isolation."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        widget_id: uuid.UUID,
        customer_id: uuid.UUID,
        payload: dict,
        submitter_ip: str | None = None,
        user_agent: str | None = None,
        geo_country: str | None = None,
        geo_city: str | None = None,
        geo_provider: str | None = None,
        is_spam: bool = False,
    ) -> Submission:
        """Create a new submission with automatic timestamp.

        Args:
            widget_id: ID of the widget this submission is for
            customer_id: ID of the customer who owns the widget
            payload: Form field values (dict keyed by field_name)
            submitter_ip: IP address of the submitter (best-effort)
            user_agent: User-Agent header from the request
            geo_country: Country code from geolocation enrichment
            geo_city: City name from geolocation enrichment
            geo_provider: Geolocation provider used
            is_spam: Whether the submission was flagged as spam

        Returns:
            The created Submission object
        """
        submission = Submission(
            widget_id=widget_id,
            customer_id=customer_id,
            payload=payload,
            submitter_ip=submitter_ip,
            user_agent=user_agent,
            geo_country=geo_country,
            geo_city=geo_city,
            geo_provider=geo_provider,
            is_spam=is_spam,
        )
        self.session.add(submission)
        await self.session.flush()
        return submission

    async def get_by_id(
        self, submission_id: uuid.UUID, customer_id: uuid.UUID
    ) -> Submission | None:
        """Get a submission by ID with tenant isolation.

        Args:
            submission_id: ID of the submission to retrieve
            customer_id: ID of the customer (for isolation)

        Returns:
            The Submission if it exists and belongs to the customer, else None
        """
        query = select(Submission).where(
            and_(
                Submission.id == submission_id,
                Submission.customer_id == customer_id,
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_customer(
        self, customer_id: uuid.UUID, limit: int = 100, offset: int = 0
    ) -> list[Submission]:
        """List submissions for a customer, ordered by most recent first.

        Args:
            customer_id: ID of the customer
            limit: Maximum number of results to return
            offset: Number of results to skip

        Returns:
            List of Submission objects, newest first
        """
        query = (
            select(Submission)
            .where(Submission.customer_id == customer_id)
            .order_by(Submission.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return result.scalars().all()

    async def list_by_widget(
        self,
        widget_id: uuid.UUID,
        customer_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Submission]:
        """List submissions for a specific widget with tenant isolation.

        Args:
            widget_id: ID of the widget
            customer_id: ID of the customer (for isolation)
            limit: Maximum number of results to return
            offset: Number of results to skip

        Returns:
            List of Submission objects for the widget, newest first
        """
        query = (
            select(Submission)
            .where(
                and_(
                    Submission.widget_id == widget_id,
                    Submission.customer_id == customer_id,
                )
            )
            .order_by(Submission.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return result.scalars().all()

    async def count_by_widget(
        self, widget_id: uuid.UUID, customer_id: uuid.UUID
    ) -> int:
        """Count submissions for a specific widget.

        Args:
            widget_id: ID of the widget
            customer_id: ID of the customer (for isolation)

        Returns:
            Number of submissions for the widget
        """
        query = select(Submission).where(
            and_(
                Submission.widget_id == widget_id,
                Submission.customer_id == customer_id,
            )
        )
        result = await self.session.execute(query)
        return len(result.scalars().all())
