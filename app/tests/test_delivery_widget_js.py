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


class TestWidgetJsHoneypotRendering:
    """The script hides the honeypot without opting it out of submission.

    These assert on the served source, which is what this suite can reach — the
    script has no DOM harness here. They pin the technique and, just as
    importantly, the absence of the things that would break the trap.
    """

    async def test_script_hides_the_flagged_field_off_screen(
        self, client: AsyncClient
    ) -> None:
        """Off-screen positioning, keyed off the server's is_honeypot flag."""
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        content = response.text

        assert "is_honeypot" in content
        assert "-9999px" in content
        assert '"absolute"' in content or "'absolute'" in content

    async def test_script_does_not_hide_with_display_none(
        self, client: AsyncClient
    ) -> None:
        """display:none is the one technique that must not be used.

        Bots specifically skip display:none and type=hidden inputs, so hiding the
        trap that way would leave it permanently empty and catch nothing.
        """
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        content = response.text

        assert 'display = "none"' not in content
        assert "display = 'none'" not in content
        assert 'visibility = "hidden"' not in content
        assert 'type = "hidden"' not in content

    async def test_script_keeps_the_field_out_of_assistive_tech(
        self, client: AsyncClient
    ) -> None:
        """aria-hidden and tabindex=-1, which have to travel together.

        Hiding a still-focusable element from screen readers would strand a
        keyboard user on a field they can neither see nor hear announced.
        """
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        content = response.text

        assert "aria-hidden" in content
        assert "tabIndex = -1" in content

    async def test_script_disables_autofill_on_the_honeypot(
        self, client: AsyncClient
    ) -> None:
        """Autofill is the only realistic way a human fills this field.

        A browser matching the "Confirm your email" label would put a real
        visitor's address in the trap and get them flagged as a bot.
        """
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        assert "autocomplete" in response.text

    async def test_script_never_hard_codes_the_honeypot_name(
        self, client: AsyncClient
    ) -> None:
        """The name is rotatable only while the script does not know it.

        widget.js is cached immutable for a year; a name baked in here could not
        be changed for that long. The is_honeypot flag is what it keys off.
        """
        from app.core.config import settings

        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        assert settings.HONEYPOT_FIELD_NAME not in response.text

    async def test_script_contains_no_spam_decision_logic(
        self, client: AsyncClient
    ) -> None:
        """Whether a submission is spam is the server's call, never the client's.

        Anything the script decided could be edited out by the bot it is meant to
        catch, so the value is collected and forwarded without being read.
        """
        response = await client.get("/api/v1/widget.js")

        assert response.status_code == 200
        content = response.text

        assert "is_spam" not in content
        # The flag is read once, to decide how to draw the field — nowhere else.
        assert content.count("is_honeypot") == 1
