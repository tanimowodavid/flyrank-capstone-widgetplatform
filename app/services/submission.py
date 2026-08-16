"""Submission business rules: accept, flag, enrich, persist (PRD Path C).

Raises domain errors rather than HTTPException — mapping to status codes belongs
in the endpoint layer, matching AuthService and WidgetService.

The ordering here is the design. A submission is a lead someone's business is
waiting for, so storing it is the one step allowed to fail the request. Spam
flagging is a pure decision made before any of it, enrichment is best-effort and
cannot block, and neither is permitted to turn a valid submission into an error.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.submission import Submission
from app.repositories.submission import SubmissionRepository
from app.repositories.widget import WidgetRepository
from app.schemas.delivery import SubmissionCreate
from app.schemas.submission import SubmissionData
from app.services.enrichment import EnrichmentService

logger = logging.getLogger(__name__)


class WidgetNotAvailableError(Exception):
    """No widget with this id is accepting submissions.

    Deliberately does not distinguish "never existed" from "deactivated": both
    must produce the same 404, or the public endpoint becomes a way to enumerate
    which widget ids exist.
    """


class SubmissionService:
    def __init__(
        self, session: AsyncSession, enrichment: EnrichmentService
    ) -> None:
        self.session = session
        self.submissions = SubmissionRepository(session)
        self.widgets = WidgetRepository(session)
        # Injected rather than constructed here, so a test can substitute a fake
        # and the suite never depends on a third-party provider being up.
        self.enrichment = enrichment

    async def record(
        self,
        *,
        widget_id: uuid.UUID,
        payload: SubmissionCreate,
        submitter_ip: str | None,
        user_agent: str | None,
    ) -> Submission:
        """Store one visitor's submission, flagged and enriched as far as possible.

        submitter_ip is the address the server observed, passed in by the endpoint
        that read it from the connection or proxy header. It is never taken from
        the request body: a client that could name its own IP could name someone
        else's, and every geo record after that would be fiction.
        """
        widget = await self.widgets.get_by_id_public(widget_id)
        if widget is None:
            raise WidgetNotAvailableError(widget_id)

        # Spam determination happens here, in the constructor: from_field_values
        # takes the honeypot out of the payload and turns it into the is_spam
        # flag. Flagged, not refused — a spam submission is stored like any other
        # so nothing bounces back to tell a bot which attempt was caught.
        data = SubmissionData.from_field_values(
            widget_id=widget_id,
            customer_id=widget.customer_id,
            field_values=payload.field_values,
            submitter_ip=submitter_ip,
            user_agent=user_agent,
        )

        data = await self._enriched(data)

        submission = await self.submissions.create(data)
        await self.session.commit()
        return submission

    async def _enriched(self, data: SubmissionData) -> SubmissionData:
        """Attach geolocation, or return `data` untouched if it cannot be found.

        EnrichmentService already promises not to raise, so this except clause
        should be unreachable. It is here anyway because the cost of being wrong
        is asymmetric: an unhandled error from a best-effort lookup would lose a
        submission that had already been validated and accepted, and no
        geolocation is worth that. Cheap insurance against a promise made in
        another file.
        """
        try:
            geo = await self.enrichment.enrich(data.submitter_ip)
        except Exception:
            logger.exception("Geo enrichment raised; storing without geo data")
            return data

        # model_copy rather than assignment: SubmissionData is built once, in one
        # place, and stays the object that was validated.
        return data.model_copy(
            update={
                "geo_country": geo.country,
                "geo_city": geo.city,
                "geo_provider": geo.provider,
            }
        )
