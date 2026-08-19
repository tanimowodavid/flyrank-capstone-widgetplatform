"""Dashboard business rules: tenant-scoped submission reads and analytics (PRD Path A).

Raises WidgetNotFoundError from the widget service when a filter references a
widget the caller does not own — the same 404 the widget endpoints produce, so a
dashboard request never confirms another tenant's widget exists.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.submission import SubmissionRepository
from app.repositories.widget import WidgetRepository
from app.schemas.submission import (
    DailyCount,
    SpamCount,
    SubmissionAnalytics,
    SubmissionPage,
    SubmissionRead,
)
from app.services.widget import WidgetNotFoundError

if TYPE_CHECKING:
    from app.models.submission import Submission

# Sentinel keys for aggregates whose grouping column is NULL: a deleted widget or
# a submission that failed geo enrichment. JSON object keys cannot be null, so
# the None is mapped to a stable label the frontend can render.
UNKNOWN_GROUP = "unknown"


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.submissions = SubmissionRepository(session)
        self.widgets = WidgetRepository(session)

    async def _require_owned_widget(
        self, widget_id: uuid.UUID | None, customer_id: uuid.UUID
    ) -> None:
        """404 (via WidgetNotFoundError) unless the filter targets the caller's widget."""
        if widget_id is None:
            return
        widget = await self.widgets.get_by_id_for_customer(widget_id, customer_id)
        if widget is None:
            raise WidgetNotFoundError(widget_id)

    async def _widget_titles(
        self, customer_id: uuid.UUID
    ) -> dict[uuid.UUID, str | None]:
        """Map every owned widget id to its title, for one title lookup per list."""
        widgets = await self.widgets.list_for_customer(customer_id)
        return {widget.id: widget.title for widget in widgets}

    @staticmethod
    def _to_read(submission: "Submission", title: str | None) -> SubmissionRead:
        """Turn a row into its response shape with its widget's title.

        widget_title lives outside the ORM row, so the service fills it in with a
        model_copy rather than asking Pydantic to resolve an attribute that does
        not exist on the model.
        """
        return SubmissionRead.model_validate(submission).model_copy(
            update={"widget_title": title}
        )

    async def list_submissions(
        self,
        *,
        customer_id: uuid.UUID,
        widget_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SubmissionPage:
        """One page of the customer's submissions, newest first.

        The total is counted in the same tenant scope as the page, so the two can
        never disagree about which rows exist.
        """
        await self._require_owned_widget(widget_id, customer_id)

        submissions = await self.submissions.list_by_customer(
            customer_id, limit=limit, offset=offset, widget_id=widget_id
        )
        total = await self.submissions.count_for_customer(
            customer_id, widget_id=widget_id
        )
        titles = await self._widget_titles(customer_id)

        items = [
            self._to_read(submission, titles.get(submission.widget_id))
            for submission in submissions
        ]
        return SubmissionPage(
            items=items, total=total, limit=limit, offset=offset
        )

    async def analytics(
        self,
        *,
        customer_id: uuid.UUID,
        widget_id: uuid.UUID | None = None,
    ) -> SubmissionAnalytics:
        """Aggregate the customer's submissions (PRD FR6.2)."""
        await self._require_owned_widget(widget_id, customer_id)

        total = await self.submissions.count_for_customer(
            customer_id, widget_id=widget_id
        )
        by_widget = {
            str(widget) if widget is not None else UNKNOWN_GROUP: count
            for widget, count in await self.submissions.counts_per_widget(
                customer_id, widget_id=widget_id
            )
        }
        by_country = {
            country or UNKNOWN_GROUP: count
            for country, count in await self.submissions.counts_per_country(
                customer_id, widget_id=widget_id
            )
        }
        by_spam = [
            SpamCount(is_spam=is_spam, count=count)
            for is_spam, count in await self.submissions.counts_per_spam(
                customer_id, widget_id=widget_id
            )
        ]
        over_time = [
            DailyCount(date=self._day_label(day), count=count)
            for day, count in await self.submissions.counts_per_day(
                customer_id, widget_id=widget_id
            )
        ]
        return SubmissionAnalytics(
            total=total,
            by_widget=by_widget,
            by_country=by_country,
            by_spam=by_spam,
            over_time=over_time,
        )

    @staticmethod
    def _day_label(day: object) -> str:
        """Normalise date_trunc's timestamp to an ISO calendar date string."""
        if isinstance(day, datetime):
            return day.date().isoformat()
        if isinstance(day, date):
            return day.isoformat()
        return str(day)