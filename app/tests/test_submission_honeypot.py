"""Honeypot handling in the submission schema (PRD FR4.2).

Unit level and deliberately DB-free: split_honeypot is a pure function, and the
decision it makes is the one thing standing between a bot's submission and a
widget owner's dashboard. Testing it directly means these cases are pinned
independently of the endpoint that happens to call it.

The end-to-end pipeline is covered separately.
"""

import uuid

import pytest

from app.core.config import settings
from app.schemas.submission import SubmissionData, split_honeypot

HONEYPOT = settings.HONEYPOT_FIELD_NAME


class TestSplitHoneypot:
    def test_absent_honeypot_leaves_values_untouched(self) -> None:
        """A payload that never carried the trap is passed through unchanged."""
        values = {"email": "visitor@example.com", "name": "Jane"}

        payload, is_spam = split_honeypot(values)

        assert payload == {"email": "visitor@example.com", "name": "Jane"}
        assert is_spam is False

    def test_empty_honeypot_is_removed_and_not_spam(self) -> None:
        """What a real visitor's browser sends: the hidden input, submitted blank.

        Present-but-empty is the common case, not the edge case. The field is a
        real input inside the form, so every honest submission carries it as "".
        """
        values = {"email": "visitor@example.com", HONEYPOT: ""}

        payload, is_spam = split_honeypot(values)

        assert payload == {"email": "visitor@example.com"}
        assert is_spam is False

    def test_filled_honeypot_is_removed_and_flagged(self) -> None:
        values = {"email": "bot@example.com", HONEYPOT: "http://spam.example"}

        payload, is_spam = split_honeypot(values)

        assert payload == {"email": "bot@example.com"}
        assert is_spam is True

    @pytest.mark.parametrize("empty_value", [None, "", "   ", "\t", "\n"])
    def test_values_that_do_not_count_as_filled(self, empty_value: str | None) -> None:
        """Whitespace resolves in the visitor's favour.

        Missing a bot costs one spam row someone can delete. A false positive
        silently buries a real person's submission, and nobody finds out.
        """
        payload, is_spam = split_honeypot({"email": "a@b.example", HONEYPOT: empty_value})

        assert is_spam is False
        assert HONEYPOT not in payload

    @pytest.mark.parametrize(
        "filled_value", ["x", "0", "http://spam.example", " padded ", "false"]
    )
    def test_values_that_count_as_filled(self, filled_value: str) -> None:
        """Any real content is a bot. "0" and "false" are content, not falsiness."""
        _, is_spam = split_honeypot({HONEYPOT: filled_value})

        assert is_spam is True

    def test_honeypot_is_removed_even_when_it_is_the_only_field(self) -> None:
        payload, is_spam = split_honeypot({HONEYPOT: "filled"})

        assert payload == {}
        assert is_spam is True

    def test_empty_input_is_not_spam(self) -> None:
        payload, is_spam = split_honeypot({})

        assert payload == {}
        assert is_spam is False

    def test_caller_dict_is_not_mutated(self) -> None:
        """The split returns a new dict rather than editing the request's.

        Pydantic hands over the model's own attribute, so popping from it would
        alter the parsed request body underneath whatever reads it next.
        """
        values = {"email": "visitor@example.com", HONEYPOT: "filled"}

        split_honeypot(values)

        assert values == {"email": "visitor@example.com", HONEYPOT: "filled"}

    def test_a_field_merely_resembling_the_honeypot_is_kept(self) -> None:
        """Matching is exact, so a real field with a similar name is not eaten."""
        values = {HONEYPOT + "_2": "kept", "confirm_email": "also kept"}

        payload, is_spam = split_honeypot(values)

        assert payload == {HONEYPOT + "_2": "kept", "confirm_email": "also kept"}
        assert is_spam is False

    def test_rotating_the_configured_name_takes_effect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The name is read from settings per call, not captured at import.

        This is what makes the field rotatable without a redeploy, so it is worth
        pinning rather than assuming.
        """
        monkeypatch.setattr(settings, "HONEYPOT_FIELD_NAME", "rotated_trap")

        payload, is_spam = split_honeypot(
            {"email": "a@b.example", "rotated_trap": "filled", HONEYPOT: "now a field"}
        )

        assert is_spam is True
        assert "rotated_trap" not in payload
        # The old name is just an ordinary field once it is no longer configured.
        assert payload == {"email": "a@b.example", HONEYPOT: "now a field"}


class TestSubmissionDataFromFieldValues:
    def test_honeypot_never_reaches_the_stored_payload(self) -> None:
        data = SubmissionData.from_field_values(
            widget_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            field_values={"email": "bot@example.com", HONEYPOT: "gotcha"},
        )

        assert data.payload == {"email": "bot@example.com"}
        assert data.is_spam is True

    def test_clean_submission_is_not_flagged(self) -> None:
        data = SubmissionData.from_field_values(
            widget_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            field_values={"email": "visitor@example.com", HONEYPOT: ""},
        )

        assert data.payload == {"email": "visitor@example.com"}
        assert data.is_spam is False

    def test_request_context_is_carried_through(self) -> None:
        widget_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        data = SubmissionData.from_field_values(
            widget_id=widget_id,
            customer_id=customer_id,
            field_values={"email": "visitor@example.com"},
            submitter_ip="192.0.2.100",
            user_agent="TestAgent/1.0",
        )

        assert data.widget_id == widget_id
        assert data.customer_id == customer_id
        assert data.submitter_ip == "192.0.2.100"
        assert data.user_agent == "TestAgent/1.0"

    def test_geo_fields_are_left_unset(self) -> None:
        """Enrichment runs later and must never gate storing a submission."""
        data = SubmissionData.from_field_values(
            widget_id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            field_values={"email": "visitor@example.com"},
        )

        assert data.geo_country is None
        assert data.geo_city is None
        assert data.geo_provider is None
