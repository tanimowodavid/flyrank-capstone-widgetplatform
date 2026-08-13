"""Integration tests for widget.js with config endpoint (Stage 2).

Tests verify:
  - widget.js can fetch config from public endpoint
  - widget.js script behavior (simulated in Python)
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.models.form_field import FormField
from app.models.widget import Widget


async def make_customer_and_widget(
    db_session: AsyncSession,
    email: str = "owner@example.com",
) -> tuple[Customer, Widget]:
    """Helper: create a customer and a widget with form fields."""
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
        is_active=True,
    )
    db_session.add(widget)
    await db_session.flush()

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

    return customer, widget


class TestWidgetJsIntegration:
    async def test_widget_js_can_fetch_config_for_active_widget(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Simulate widget.js fetching config for an active widget."""
        customer, widget = await make_customer_and_widget(db_session)

        # First, get widget.js
        script_response = await client.get("/api/v1/widget.js")
        assert script_response.status_code == 200

        # Then, fetch config (what widget.js would do)
        config_response = await client.get(f"/api/v1/widgets/{widget.id}/config")
        assert config_response.status_code == 200

        config = config_response.json()
        assert config["widget_type"] == "signup_form"
        assert config["title"] == "Newsletter Signup"
        assert config["button_text"] == "Sign Me Up"
        assert config["theme_color"] == "#0066cc"
        assert len(config["form_fields"]) == 2

    async def test_widget_js_handles_404_for_inactive_widget(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Simulate widget.js receiving 404 for inactive widget."""
        customer = Customer(
            organization_name="Test Org",
            email="owner@example.com",
            password_hash="not-a-real-hash",
        )
        db_session.add(customer)
        await db_session.flush()

        widget = Widget(
            customer_id=customer.id,
            widget_type="signup_form",
            title="Inactive Widget",
            is_active=False,
        )
        db_session.add(widget)
        await db_session.commit()

        # widget.js would get 404 trying to fetch config
        config_response = await client.get(f"/api/v1/widgets/{widget.id}/config")
        assert config_response.status_code == 404

    async def test_widget_js_handles_404_for_missing_widget(
        self, client: AsyncClient
    ) -> None:
        """Simulate widget.js receiving 404 for nonexistent widget."""
        fake_id = uuid.uuid4()

        config_response = await client.get(f"/api/v1/widgets/{fake_id}/config")
        assert config_response.status_code == 404

    async def test_widget_js_cors_allows_cross_origin_fetch(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Config endpoint returns CORS headers allowing widget.js to fetch."""
        customer, widget = await make_customer_and_widget(db_session)

        # Simulate cross-origin request (from a different domain)
        response = await client.get(
            f"/api/v1/widgets/{widget.id}/config",
            headers={"Origin": "https://customer-website.example.com"},
        )

        assert response.status_code == 200
        # Should include CORS header
        assert response.headers.get("access-control-allow-origin") == "*"

    async def test_widget_js_script_with_color_validation(
        self, client: AsyncClient
    ) -> None:
        """Widget.js includes logic to validate and apply CSS color."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        content = response.text

        # Script should validate colors
        assert "isValidCssColor" in content
        # Script should default to skyblue
        assert "skyblue" in content

    async def test_widget_js_with_null_theme_color(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Config with null theme_color should work with widget.js default."""
        customer = Customer(
            organization_name="Test Org",
            email="owner@example.com",
            password_hash="not-a-real-hash",
        )
        db_session.add(customer)
        await db_session.flush()

        widget = Widget(
            customer_id=customer.id,
            widget_type="cta_popover",
            title="CTA",
            theme_color=None,
            is_active=True,
        )
        db_session.add(widget)
        await db_session.commit()

        # Fetch config
        response = await client.get(f"/api/v1/widgets/{widget.id}/config")
        assert response.status_code == 200

        config = response.json()
        assert config["theme_color"] is None

        # widget.js should handle this and default to skyblue
        script_response = await client.get("/api/v1/widget.js")
        script_content = script_response.text
        assert "getValidColor" in script_content
        assert "skyblue" in script_content

    async def test_widget_js_form_fields_order_preserved(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Form fields are returned in correct order for widget.js to render."""
        customer, widget = await make_customer_and_widget(db_session)

        response = await client.get(f"/api/v1/widgets/{widget.id}/config")
        assert response.status_code == 200

        config = response.json()
        fields = config["form_fields"]

        # Fields should be in order
        assert fields[0]["field_name"] == "email"
        assert fields[1]["field_name"] == "name"

    async def test_widget_js_endpoint_cache_headers_different_from_config(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """widget.js has longer cache than config endpoint."""
        customer, widget = await make_customer_and_widget(db_session)

        # Config endpoint has short cache
        config_response = await client.get(f"/api/v1/widgets/{widget.id}/config")
        assert config_response.status_code == 200
        config_cache = config_response.headers.get("cache-control", "")
        assert "max-age=60" in config_cache

        # widget.js has long cache
        script_response = await client.get("/api/v1/widget.js")
        assert script_response.status_code == 200
        script_cache = script_response.headers.get("cache-control", "")
        assert "max-age=31536000" in script_cache
        assert "immutable" in script_cache
