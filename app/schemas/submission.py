"""Internal submission schemas (PRD Path C - Visitor Submissions).

The wire shapes a visitor's browser posts and receives live in
app/schemas/delivery.py, alongside the other public types. What lives here is the
step after: the validated, storage-ready form of a submission, which is the only
thing SubmissionRepository.create accepts.

Splitting it this way means the repository never sees a raw dict off the network.
Anything reaching it has already been through validation, and the honeypot has
already been taken out.

Deferred, deliberately:
  - FR3.2 payload size limit (settings.MAX_SUBMISSION_SIZE). Its own concern with
    its own rejection path, so it is not folded in here.
  - FR3.2 unknown-field rejection against the widget's FormField rows. When it
    lands it belongs after split_honeypot, which is what keeps the trap out of it
    without needing a special case: the honeypot is expected input, not an error,
    but it is also not one of the widget's fields, so a check that ran before the
    split would reject every honest submission.
"""

import uuid
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from app.core.config import settings


def split_honeypot(
    field_values: Mapping[str, str | None],
) -> tuple[dict[str, str | None], bool]:
    """Separate the spam trap from the real form values (PRD FR4.2).

    Returns the values with the honeypot removed, and whether it was filled.

    The trap is stripped rather than stored because it is not one of the widget's
    FormField rows. Left in, it would show the owner a column in their dashboard
    for a field they never created and cannot delete.

    A whitespace-only value counts as empty. That direction is chosen on
    consequence rather than principle: missing a bot costs one spam row, while a
    false positive silently buries a real person's submission, so the ambiguous
    case resolves in the visitor's favour.
    """
    real_values = {
        name: value
        for name, value in field_values.items()
        if name != settings.HONEYPOT_FIELD_NAME
    }

    # Absent and empty are both "not filled": a real visitor's browser submits the
    # hidden input as "", so absence is not what distinguishes a human here.
    trap_value = field_values.get(settings.HONEYPOT_FIELD_NAME)
    honeypot_filled = bool(trap_value and trap_value.strip())

    return real_values, honeypot_filled


class SubmissionData(BaseModel):
    """A submission that has passed validation and is ready to be stored.

    One argument for SubmissionRepository.create, in place of the loose keyword
    arguments it used to take. The repository's job is to persist a row, not to
    decide what belongs in one.

    Build it with from_field_values rather than the constructor when the values
    came from a request: that path is what removes the honeypot and sets is_spam,
    so a caller cannot forget to do either.
    """

    model_config = ConfigDict(from_attributes=True)

    widget_id: uuid.UUID
    customer_id: uuid.UUID
    # The honeypot is already gone from this. Only real form fields remain.
    payload: dict[str, str | None]
    submitter_ip: str | None = None
    user_agent: str | None = None
    # Enrichment is best-effort and runs later, so all three stay unset here
    # rather than blocking a submission on a geo provider being reachable.
    geo_country: str | None = None
    geo_city: str | None = None
    geo_provider: str | None = None
    is_spam: bool = False

    @classmethod
    def from_field_values(
        cls,
        *,
        widget_id: uuid.UUID,
        customer_id: uuid.UUID,
        field_values: Mapping[str, str | None],
        submitter_ip: str | None = None,
        user_agent: str | None = None,
    ) -> "SubmissionData":
        """Build from the raw values a visitor posted.

        Splits the honeypot on the way in, so the payload that comes out is
        storable and is_spam already reflects the trap. Flagged is not rejected:
        a spam submission is stored like any other, just marked, because the
        alternative tells a bot which of its attempts got through.
        """
        payload, honeypot_filled = split_honeypot(field_values)

        return cls(
            widget_id=widget_id,
            customer_id=customer_id,
            payload=payload,
            submitter_ip=submitter_ip,
            user_agent=user_agent,
            is_spam=honeypot_filled,
        )
