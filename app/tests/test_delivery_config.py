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
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
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
        from app.models.form_field import FormField

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

        assert len(fields) == 2
        assert fields[0]["field_name"] == "email"
        assert fields[0]["label"] == "Email Address"
        assert fields[0]["field_type"] == "email"
        assert fields[0]["is_required"] is True
        assert "id" not in fields[0]  # No internal ID
        assert "display_order" not in fields[0]  # No display_order

        assert fields[1]["field_name"] == "name"
        assert fields[1]["label"] == "Full Name"

    async def test_widget_without_form_fields_returns_empty_list(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Widget with no form fields returns empty form_fields list."""
        customer, widget = await make_customer_and_widget(db_session)

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")

        assert response.status_code == 200
        payload = response.json()
        assert payload["form_fields"] == []

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
