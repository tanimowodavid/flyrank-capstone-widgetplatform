"""Submission data access layer (PRD Path C - persisting visitor submissions)."""

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.submission import Submission
from app.schemas.submission import SubmissionData


class SubmissionRepository:
    """Submission queries with automatic tenant isolation."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: SubmissionData) -> Submission:
        """Persist a validated submission.

        Takes SubmissionData rather than a raw payload and a list of keyword
        arguments, so everything that reaches this layer has already been through
        validation: the honeypot removed, is_spam decided. This method persists a
        row; it does not decide what belongs in one.

        Args:
            data: The validated, storage-ready submission

        Returns:
            The created Submission object
        """
        submission = Submission(
            widget_id=data.widget_id,
            customer_id=data.customer_id,
            payload=data.payload,
            submitter_ip=data.submitter_ip,
            user_agent=data.user_agent,
            geo_country=data.geo_country,
            geo_city=data.geo_city,
            geo_provider=data.geo_provider,
            is_spam=data.is_spam,
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
        self,
        customer_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
        widget_id: uuid.UUID | None = None,
    ) -> list[Submission]:
        """List submissions for a customer, ordered by most recent first.

        Args:
            customer_id: ID of the customer
            limit: Maximum number of results to return
            offset: Number of results to skip
            widget_id: When given, restrict to one of the customer's widgets

        Returns:
            List of Submission objects, newest first
        """
        query = select(Submission).where(Submission.customer_id == customer_id)
        if widget_id is not None:
            query = query.where(Submission.widget_id == widget_id)
        query = query.order_by(Submission.created_at.desc()).limit(limit).offset(offset)
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

    def _customer_scoped(
        self,
        customer_id: uuid.UUID,
        widget_id: uuid.UUID | None = None,
    ):
        """Base WHERE clause for every owner-scoped aggregate query."""
        conditions = [Submission.customer_id == customer_id]
        if widget_id is not None:
            conditions.append(Submission.widget_id == widget_id)
        return conditions

    async def count_for_customer(
        self,
        customer_id: uuid.UUID,
        widget_id: uuid.UUID | None = None,
    ) -> int:
        """Total submissions for a customer, optionally for one widget.

        Uses COUNT(*) rather than loading rows: the dashboard list needs a total
        alongside the page, and the page itself already carries the data.
        """
        query = (
            select(func.count(Submission.id))
            .where(*self._customer_scoped(customer_id, widget_id))
        )
        result = await self.session.execute(query)
        return result.scalar_one()

    async def counts_per_widget(
        self,
        customer_id: uuid.UUID,
        widget_id: uuid.UUID | None = None,
    ) -> list[tuple[uuid.UUID | None, int]]:
        """Submission counts grouped by widget_id, newest widgets not implied."""
        query = (
            select(Submission.widget_id, func.count(Submission.id))
            .where(*self._customer_scoped(customer_id, widget_id))
            .group_by(Submission.widget_id)
        )
        return list((await self.session.execute(query)).all())

    async def counts_per_country(
        self,
        customer_id: uuid.UUID,
        widget_id: uuid.UUID | None = None,
    ) -> list[tuple[str | None, int]]:
        """Submission counts grouped by geo_country (None where not enriched)."""
        query = (
            select(Submission.geo_country, func.count(Submission.id))
            .where(*self._customer_scoped(customer_id, widget_id))
            .group_by(Submission.geo_country)
        )
        return list((await self.session.execute(query)).all())

    async def counts_per_spam(
        self,
        customer_id: uuid.UUID,
        widget_id: uuid.UUID | None = None,
    ) -> list[tuple[bool, int]]:
        """Submission counts split between spam and legitimate."""
        query = (
            select(Submission.is_spam, func.count(Submission.id))
            .where(*self._customer_scoped(customer_id, widget_id))
            .group_by(Submission.is_spam)
        )
        return list((await self.session.execute(query)).all())

    async def counts_per_day(
        self,
        customer_id: uuid.UUID,
        widget_id: uuid.UUID | None = None,
    ) -> list[tuple[object, int]]:
        """Submission counts by calendar day, oldest first (PRD FR6.2)."""
        day = func.date_trunc("day", Submission.created_at)
        query = (
            select(day.label("day"), func.count(Submission.id))
            .where(*self._customer_scoped(customer_id, widget_id))
            .group_by(day)
            .order_by(day)
        )
        return list((await self.session.execute(query)).all())
