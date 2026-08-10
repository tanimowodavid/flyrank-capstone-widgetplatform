"""Schema-level guarantees for the submissions foreign keys.

These assert database behaviour, not endpoint behaviour: the point of declaring
ON DELETE rules in the schema is that they hold for every writer — the ORM, a
migration, a seed script, or raw SQL — so they are tested directly.
"""

import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.models.form_field import FormField
from app.models.submission import Submission
from app.models.widget import Widget


async def make_customer(session: AsyncSession, email: str) -> Customer:
    customer = Customer(
        organization_name="Acme Widgets",
        email=email,
        password_hash="not-a-real-hash",
    )
    session.add(customer)
    await session.flush()
    return customer


async def make_widget_with_children(
    session: AsyncSession, customer: Customer
) -> tuple[Widget, FormField, Submission]:
    widget = Widget(
        customer_id=customer.id,
        widget_type="signup_form",
        title="Newsletter Signup",
    )
    session.add(widget)
    await session.flush()

    form_field = FormField(
        widget_id=widget.id,
        field_name="email",
        label="Email address",
        field_type="email",
    )
    submission = Submission(
        widget_id=widget.id,
        customer_id=customer.id,
        payload={"email": "visitor@example.com"},
    )
    session.add_all([form_field, submission])
    await session.commit()
    return widget, form_field, submission


class TestWidgetDeletePreservesSubmissions:
    async def test_deleting_a_widget_nulls_widget_id_but_keeps_the_submission(
        self, db_session: AsyncSession
    ) -> None:
        """ON DELETE SET NULL: the lead outlives the form it arrived through."""
        customer = await make_customer(db_session, "owner@acme.example")
        widget, _, submission = await make_widget_with_children(db_session, customer)
        submission_id = submission.id
        # Read before expire_all(): afterwards, touching customer.id would emit a
        # lazy refresh, which raises in an async session.
        customer_id = customer.id

        # Core DELETE rather than session.delete(widget) for the same reason the
        # repository uses one: it goes straight to the database instead of routing
        # through the ORM's relationship handling. Postgres enforces SET NULL
        # either way — this keeps the test measuring the schema, not the mapper.
        await db_session.execute(
            delete(Widget).where(Widget.id == widget.id)
        )
        await db_session.commit()

        # expire_all is load-bearing: Postgres nulls widget_id behind the ORM's
        # back, so the in-session copy still holds the old UUID. Without this the
        # assertion below would read a stale value and pass for the wrong reason.
        db_session.expire_all()

        surviving = await db_session.get(Submission, submission_id)
        assert surviving is not None, "submission must survive its widget"
        assert surviving.widget_id is None
        # The payload is the whole point of keeping the row.
        assert surviving.payload == {"email": "visitor@example.com"}
        assert surviving.customer_id == customer_id

    async def test_deleting_a_widget_still_removes_its_form_fields(
        self, db_session: AsyncSession
    ) -> None:
        """form_fields remain ON DELETE CASCADE — only submissions changed."""
        customer = await make_customer(db_session, "fields@acme.example")
        widget, form_field, _ = await make_widget_with_children(db_session, customer)
        form_field_id = form_field.id

        await db_session.execute(delete(Widget).where(Widget.id == widget.id))
        await db_session.commit()
        db_session.expire_all()

        assert await db_session.get(FormField, form_field_id) is None

    async def test_raw_sql_delete_also_preserves_the_submission(
        self, db_session: AsyncSession
    ) -> None:
        """The guarantee must not depend on going through the ORM."""
        customer = await make_customer(db_session, "rawsql@acme.example")
        widget, _, submission = await make_widget_with_children(db_session, customer)
        submission_id = submission.id

        await db_session.execute(
            text("DELETE FROM widgets WHERE id = :id"), {"id": widget.id}
        )
        await db_session.commit()
        db_session.expire_all()

        surviving = await db_session.get(Submission, submission_id)
        assert surviving is not None
        assert surviving.widget_id is None

    async def test_deleting_the_customer_still_removes_orphaned_submissions(
        self, db_session: AsyncSession
    ) -> None:
        """customer_id stays CASCADE, so an orphan cannot outlive its tenant."""
        customer = await make_customer(db_session, "orphan@acme.example")
        widget, _, submission = await make_widget_with_children(db_session, customer)
        submission_id = submission.id
        customer_id = customer.id

        await db_session.execute(delete(Widget).where(Widget.id == widget.id))
        await db_session.commit()
        db_session.expire_all()
        assert await db_session.get(Submission, submission_id) is not None

        await db_session.execute(
            text("DELETE FROM customers WHERE id = :id"), {"id": customer_id}
        )
        await db_session.commit()
        db_session.expire_all()

        assert await db_session.get(Submission, submission_id) is None

    async def test_a_submission_may_be_inserted_without_a_widget(
        self, db_session: AsyncSession
    ) -> None:
        """widget_id is nullable, so NOT NULL must no longer be enforced."""
        customer = await make_customer(db_session, "nullwidget@acme.example")
        await db_session.commit()

        db_session.add(
            Submission(
                widget_id=None,
                customer_id=customer.id,
                payload={"note": "arrived after the widget was deleted"},
            )
        )
        await db_session.commit()

        stored = (
            await db_session.execute(
                select(Submission).where(Submission.customer_id == customer.id)
            )
        ).scalar_one()
        assert stored.widget_id is None

    async def test_submission_cannot_reference_a_nonexistent_widget(
        self, db_session: AsyncSession
    ) -> None:
        """Nullable is not unvalidated: a bogus widget_id must still be rejected."""
        customer = await make_customer(db_session, "badfk@acme.example")
        await db_session.commit()

        db_session.add(
            Submission(
                widget_id=uuid.uuid4(),
                customer_id=customer.id,
                payload={"k": "v"},
            )
        )

        with pytest.raises(Exception) as exc_info:
            await db_session.commit()

        assert "foreign key" in str(exc_info.value).lower()
        await db_session.rollback()
