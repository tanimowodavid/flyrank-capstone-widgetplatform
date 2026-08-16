"""Tests for public widget config endpoint (Stage 1 - widget delivery).

Tests verify:
  - Active widget returns correct minimal payload
  - Inactive widget returns 404
  - Nonexistent widget returns 404
  - Response does not leak customer_id or internal fields
  - Cache-Control and CORS headers are present
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.customer import Customer
from app.models.form_field import FormField
from app.models.widget import Widget


async def make_customer_and_widget(
    db_session: AsyncSession,
    email: str = "owner@example.com",
    is_active: bool = True,
) -> tuple[Customer, Widget]:
    """Helper: create a customer and an active widget."""
    customer = Customer(
        organization_name="Test Org",
        email=email,
        password_hash="not-a-real-hash",
    )
    db_session.add(customer)
    await db_session.flush()

    widget = Widget(
        customer_id=customer.id,
        widget_type="signup_form",
        title="Newsletter Signup",
        description="Sign up for our newsletter",
        button_text="Sign Me Up",
        theme_color="#0066cc",
        is_active=is_active,
    )
    db_session.add(widget)
    await db_session.commit()

    return customer, widget


class TestPublicWidgetConfigEndpoint:
    async def test_active_widget_returns_correct_config(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """GET /widgets/{id}/config returns minimal config for active widget."""
        customer, widget = await make_customer_and_widget(db_session)

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert response.status_code == 200
        payload = response.json()

        # Verify required fields are present
        assert payload["widget_type"] == "signup_form"
        assert payload["title"] == "Newsletter Signup"
        assert payload["description"] == "Sign up for our newsletter"
        assert payload["button_text"] == "Sign Me Up"
        assert payload["theme_color"] == "#0066cc"
        assert isinstance(payload["form_fields"], list)

    async def test_active_widget_does_not_leak_internal_fields(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Response must not include customer_id, timestamps, or internal state."""
        customer, widget = await make_customer_and_widget(db_session)

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert response.status_code == 200
        payload = response.json()

        # These must not appear in the response
        assert "customer_id" not in payload
        assert "id" not in payload
        assert "is_active" not in payload
        assert "created_at" not in payload
        assert "updated_at" not in payload

    async def test_inactive_widget_returns_404(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """GET /widgets/{id}/config returns 404 for inactive widget."""
        customer, widget = await make_customer_and_widget(
            db_session, is_active=False
        )

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert response.status_code == 404
        assert response.json()["detail"] == "Widget not found"

    async def test_nonexistent_widget_returns_404(
        self, client: AsyncClient
    ) -> None:
        """GET /widgets/{id}/config returns 404 for nonexistent widget."""
        fake_id = uuid.uuid4()

        response = await client.get(f"/api/v1/widgets/{fake_id}/config")

        assert response.status_code == 404
        assert response.json()["detail"] == "Widget not found"

    async def test_response_includes_cache_control_header(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Response includes Cache-Control: public, max-age=60."""
        customer, widget = await make_customer_and_widget(db_session)

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=60"

    async def test_response_includes_cors_header(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Response includes Access-Control-Allow-Origin: *."""
        customer, widget = await make_customer_and_widget(db_session)

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "*"

    async def test_form_fields_are_included_in_config(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Form fields appear in config in the correct order."""
        customer, widget = await make_customer_and_widget(db_session)

        # Add form fields
        field1 = FormField(
            widget_id=widget.id,
            field_name="email",
            label="Email Address",
            field_type="email",
            is_required=True,
            display_order=0,
        )
        field2 = FormField(
            widget_id=widget.id,
            field_name="name",
            label="Full Name",
            field_type="text",
            is_required=True,
            display_order=1,
        )
        db_session.add_all([field1, field2])
        await db_session.commit()

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert response.status_code == 200
        payload = response.json()
        fields = payload["form_fields"]

        # The appended honeypot is excluded here; the tests below cover it.
        real_fields = [field for field in fields if not field["is_honeypot"]]

        assert len(real_fields) == 2
        assert real_fields[0]["field_name"] == "email"
        assert real_fields[0]["label"] == "Email Address"
        assert real_fields[0]["field_type"] == "email"
        assert real_fields[0]["is_required"] is True
        assert "id" not in real_fields[0]  # No internal ID
        assert "display_order" not in real_fields[0]  # No display_order

        assert real_fields[1]["field_name"] == "name"
        assert real_fields[1]["label"] == "Full Name"

    async def test_widget_without_form_fields_returns_only_honeypot(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """A widget with no fields of its own still carries the honeypot."""
        customer, widget = await make_customer_and_widget(db_session)

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert response.status_code == 200
        payload = response.json()
        assert [field["field_name"] for field in payload["form_fields"]] == [
            settings.HONEYPOT_FIELD_NAME
        ]

    async def test_widget_with_null_optional_fields(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Widget with null description/button_text/theme_color returns null values."""
        customer = Customer(
            organization_name="Test Org",
            email="owner@example.com",
            password_hash="not-a-real-hash",
        )
        db_session.add(customer)
        await db_session.flush()

        # Create widget without optional fields
        widget = Widget(
            customer_id=customer.id,
            widget_type="cta_popover",
            title="Call to Action",
            description=None,
            button_text=None,
            theme_color=None,
            is_active=True,
        )
        db_session.add(widget)
        await db_session.commit()

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert response.status_code == 200
        payload = response.json()
        assert payload["description"] is None
        assert payload["button_text"] is None
        assert payload["theme_color"] is None


def honeypot_from(payload: dict) -> dict:
    """The single field in a config response flagged as the honeypot."""
    traps = [field for field in payload["form_fields"] if field["is_honeypot"]]
    assert len(traps) == 1, f"expected exactly one honeypot, got {len(traps)}"
    return traps[0]


class TestConfigHoneypotField:
    """The config response always carries a honeypot field (PRD FR4.2).

    Always, because a widget whose owner defined no fields, or whose fields
    change, must be defended the same as any other. These tests pin that the
    trap's presence does not depend on the widget's own field definitions.
    """

    async def test_honeypot_present_for_widget_with_no_fields(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        customer, widget = await make_customer_and_widget(db_session)

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert response.status_code == 200
        assert honeypot_from(response.json())["field_name"] == (
            settings.HONEYPOT_FIELD_NAME
        )

    async def test_honeypot_present_alongside_real_fields(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Real fields are returned untouched, with the trap added after them."""
        customer, widget = await make_customer_and_widget(db_session)
        db_session.add_all(
            [
                FormField(
                    widget_id=widget.id,
                    field_name="email",
                    label="Email Address",
                    field_type="email",
                    is_required=True,
                    display_order=0,
                ),
                FormField(
                    widget_id=widget.id,
                    field_name="name",
                    label="Full Name",
                    field_type="text",
                    is_required=True,
                    display_order=1,
                ),
            ]
        )
        await db_session.commit()

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert response.status_code == 200
        fields = response.json()["form_fields"]

        # Trap last, so a real field's position never shifts because of it.
        assert [field["field_name"] for field in fields] == [
            "email",
            "name",
            settings.HONEYPOT_FIELD_NAME,
        ]
        assert [field["is_honeypot"] for field in fields] == [False, False, True]

    @pytest.mark.parametrize("field_count", [0, 1, 5])
    async def test_honeypot_count_is_one_whatever_the_widget_defines(
        self, db_session: AsyncSession, client: AsyncClient, field_count: int
    ) -> None:
        """Exactly one trap, never zero and never duplicated."""
        customer, widget = await make_customer_and_widget(db_session)
        db_session.add_all(
            [
                FormField(
                    widget_id=widget.id,
                    field_name=f"field_{index}",
                    label=f"Field {index}",
                    field_type="text",
                    is_required=False,
                    display_order=index,
                )
                for index in range(field_count)
            ]
        )
        await db_session.commit()

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload["form_fields"]) == field_count + 1
        assert honeypot_from(payload)["field_name"] == settings.HONEYPOT_FIELD_NAME

    async def test_honeypot_is_not_required(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """A required invisible field would be a form no visitor could submit."""
        customer, widget = await make_customer_and_widget(db_session)

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert honeypot_from(response.json())["is_required"] is False

    async def test_honeypot_is_not_an_email_input(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """type=email would let the browser block the very submissions we want.

        A bot's junk value in an <input type="email"> fails browser validation and
        the form never posts, so the spam would go undetected instead of flagged.
        """
        customer, widget = await make_customer_and_widget(db_session)

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert honeypot_from(response.json())["field_type"] == "text"

    async def test_honeypot_is_never_persisted(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """The trap exists in the response only — no FormField row is created."""
        customer, widget = await make_customer_and_widget(db_session)

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")
        assert response.status_code == 200
        assert honeypot_from(response.json())

        stored = await db_session.execute(
            select(func.count())
            .select_from(FormField)
            .where(FormField.widget_id == widget.id)
        )
        assert stored.scalar_one() == 0

    async def test_real_fields_are_not_flagged_as_honeypot(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """is_honeypot defaults to False for rows loaded from the database.

        FormField has no such column, so this pins that the default rather than
        an accident is what keeps a real field from being hidden.
        """
        customer, widget = await make_customer_and_widget(db_session)
        db_session.add(
            FormField(
                widget_id=widget.id,
                field_name="email",
                label="Email Address",
                field_type="email",
                is_required=True,
                display_order=0,
            )
        )
        await db_session.commit()

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        fields = response.json()["form_fields"]
        real_field = next(f for f in fields if f["field_name"] == "email")
        assert real_field["is_honeypot"] is False
