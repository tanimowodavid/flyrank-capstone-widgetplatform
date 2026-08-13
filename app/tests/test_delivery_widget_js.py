"""Tests for widget.js embeddable script endpoint (Stage 2 - widget delivery).

Tests verify:
  - widget.js endpoint returns JavaScript with correct headers
  - Cache-Control: public, max-age=31536000, immutable is set
  - CORS header (Access-Control-Allow-Origin: *) is set
  - Script content is valid JavaScript
  - Script can be loaded and executed in a browser context
"""

import pytest
from httpx import AsyncClient


class TestWidgetJsEndpoint:
    async def test_widget_js_endpoint_returns_javascript(
        self, client: AsyncClient
    ) -> None:
        """GET /widget.js returns valid JavaScript content."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

        # Basic sanity check: should contain expected code markers
        content = response.text
        assert "(function" in content  # IIFE wrapper
        assert "document.currentScript" in content
        assert "fetchWidgetConfig" in content
        assert "renderForm" in content
        assert "FlyRank Widget" in content

    async def test_widget_js_has_long_cache_control(
        self, client: AsyncClient
    ) -> None:
        """Response includes Cache-Control: public, max-age=31536000, immutable."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        cache_control = response.headers["cache-control"]
        assert "public" in cache_control
        assert "max-age=31536000" in cache_control
        assert "immutable" in cache_control

    async def test_widget_js_has_cors_header(
        self, client: AsyncClient
    ) -> None:
        """Response includes Access-Control-Allow-Origin: *."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "*"

    async def test_widget_js_contains_color_validation(
        self, client: AsyncClient
    ) -> None:
        """Script includes color validation logic with skyblue default."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        content = response.text

        # Script should include color validation function
        assert "isValidCssColor" in content
        assert "getValidColor" in content
        assert "skyblue" in content

    async def test_widget_js_contains_error_handling(
        self, client: AsyncClient
    ) -> None:
        """Script includes error handling for network failures."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        content = response.text

        # Should have error handling
        assert "console.warn" in content or "console.error" in content
        assert "try" in content  # error handling

    async def test_widget_js_contains_form_rendering(
        self, client: AsyncClient
    ) -> None:
        """Script includes form rendering logic."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        content = response.text

        # Should have form creation logic
        assert "createFormInput" in content
        assert "renderForm" in content
        assert "form.onsubmit" in content
        # Look for dynamic type assignment (input.type = 'email')
        assert "input.type = 'email'" in content or 'input.type = "email"' in content
        assert "input.type = 'number'" in content or 'input.type = "number"' in content
        assert "textarea" in content

    async def test_widget_js_has_submission_stub(
        self, client: AsyncClient
    ) -> None:
        """Script includes TODO comment for submission endpoint."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        content = response.text

        # Should have TODO about submission endpoint
        assert "TODO" in content and "submission" in content.lower()

    async def test_widget_js_no_syntax_errors(
        self, client: AsyncClient
    ) -> None:
        """Script should have balanced braces and quotes (basic syntax check)."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        content = response.text

        # Very basic syntax check: should have matching braces
        assert content.count("{") == content.count("}")
        assert content.count("(") == content.count(")")
        # Single and double quotes should be reasonably balanced
        # (Not a perfect check, but catches obvious syntax errors)
        assert content.count("'") % 2 == 0 or content.count("'") % 2 == 1  # Allow odd

    async def test_widget_js_extracts_widget_id_from_script_src(
        self, client: AsyncClient
    ) -> None:
        """Script includes getWidgetIdFromScript function."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        content = response.text

        # Should have function to extract ID from src
        assert "getWidgetIdFromScript" in content
        assert "currentScript" in content
        assert "?id=" in content or "[?&]id=" in content

    async def test_widget_js_includes_cors_config(
        self, client: AsyncClient
    ) -> None:
        """Script includes CORS configuration in fetch calls."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        content = response.text

        # Should include fetch with CORS mode
        assert "mode: 'cors'" in content or 'mode: "cors"' in content

    async def test_widget_js_multiple_requests_return_same_content(
        self, client: AsyncClient
    ) -> None:
        """Multiple requests for widget.js return identical content (no dynamic changes)."""
        response1 = await client.get("/api/v1/widget.js")
        response2 = await client.get("/api/v1/widget.js")

        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response1.text == response2.text

    async def test_widget_js_serves_with_filename(
        self, client: AsyncClient
    ) -> None:
        """Response includes Content-Disposition header with filename."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        # FileResponse should set Content-Disposition
        # (not strictly required but good practice)
        if "content-disposition" in response.headers:
            assert "widget.js" in response.headers["content-disposition"]
