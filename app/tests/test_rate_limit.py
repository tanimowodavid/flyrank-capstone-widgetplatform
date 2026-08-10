"""Tests for the rate limiting infrastructure, exercised through login.

Login is the first consumer; the same limiter will guard the public submission
endpoint (PRD FR4.1), so these tests target the shared machinery — the 429 body,
the Retry-After header, and per-IP keying — rather than anything login-specific.

Every test here takes the `rate_limited` fixture, which is what turns the limiter
on. Without it the suite-wide autouse fixture keeps it off.
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

SIGNUP_URL = "/api/v1/auth/signup"
LOGIN_URL = "/api/v1/auth/login"
HEALTH_URL = "/api/v1/health"

PASSWORD = "correct-horse-battery"
EMAIL = "owner@acme.example"

# One more than the configured allowance, so a burst is guaranteed to cross it.
LIMIT = int(settings.RATE_LIMIT_LOGIN.split("/")[0])
BURST = LIMIT + 3


def client_from(ip: str) -> AsyncClient:
    """An HTTP client whose requests appear to originate from `ip`.

    ASGITransport writes this into the ASGI scope's "client" entry, which is
    exactly what get_remote_address reads — so this exercises the real keying
    path rather than stubbing the key function.
    """
    return AsyncClient(
        transport=ASGITransport(app=app, client=(ip, 5000)),
        base_url="http://test",
    )


@pytest.fixture
async def registered(client: AsyncClient) -> AsyncGenerator[None, None]:
    """A customer to log in as, created before the limiter is armed."""
    response = await client.post(
        SIGNUP_URL,
        json={
            "organization_name": "Acme Widgets",
            "email": EMAIL,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201
    yield


def wrong_credentials() -> dict[str, str]:
    return {"email": EMAIL, "password": "not-my-password"}


def right_credentials() -> dict[str, str]:
    return {"email": EMAIL, "password": PASSWORD}


class TestLoginRateLimit:
    async def test_burst_of_failed_logins_is_throttled(
        self, registered: None, rate_limited: None
    ) -> None:
        statuses = []
        async with client_from("10.0.0.1") as caller:
            for _ in range(BURST):
                response = await caller.post(LOGIN_URL, json=wrong_credentials())
                statuses.append(response.status_code)

        # The allowance is spent on 401s, then the limiter takes over.
        assert statuses[:LIMIT] == [401] * LIMIT
        assert statuses[LIMIT:] == [429] * (BURST - LIMIT)

    async def test_throttled_response_carries_retry_after(
        self, registered: None, rate_limited: None
    ) -> None:
        async with client_from("10.0.0.2") as caller:
            for _ in range(LIMIT):
                await caller.post(LOGIN_URL, json=wrong_credentials())
            response = await caller.post(LOGIN_URL, json=wrong_credentials())

        assert response.status_code == 429

        retry_after = response.headers.get("Retry-After")
        assert retry_after is not None, "429 must tell the caller how long to wait"
        # Seconds, not an HTTP-date, and never zero — a zero would invite an
        # immediate retry that is still inside the window.
        assert retry_after.isdigit()
        assert 1 <= int(retry_after) <= 60

        assert response.json() == {
            "detail": "Too many requests. Please try again later."
        }

    async def test_a_different_ip_is_unaffected(
        self, registered: None, rate_limited: None
    ) -> None:
        """The limit is keyed per IP: one caller's burst must not block another."""
        async with client_from("10.0.0.3") as noisy:
            for _ in range(BURST):
                await noisy.post(LOGIN_URL, json=wrong_credentials())

            exhausted = await noisy.post(LOGIN_URL, json=wrong_credentials())

        assert exhausted.status_code == 429, "the noisy caller must be throttled"

        async with client_from("10.0.0.4") as innocent:
            response = await innocent.post(LOGIN_URL, json=right_credentials())

        assert response.status_code == 200
        assert response.json()["access_token"]

    async def test_successful_logins_count_toward_the_limit(
        self, registered: None, rate_limited: None
    ) -> None:
        """Otherwise a valid login would refill the attacker's budget."""
        statuses = []
        async with client_from("10.0.0.5") as caller:
            for _ in range(BURST):
                response = await caller.post(LOGIN_URL, json=right_credentials())
                statuses.append(response.status_code)

        assert statuses[:LIMIT] == [200] * LIMIT
        assert statuses[LIMIT:] == [429] * (BURST - LIMIT)

    async def test_throttling_login_does_not_throttle_other_endpoints(
        self, registered: None, rate_limited: None
    ) -> None:
        """The limit is scoped to the decorated route, not the whole API."""
        async with client_from("10.0.0.6") as caller:
            for _ in range(BURST):
                await caller.post(LOGIN_URL, json=wrong_credentials())

            throttled = await caller.post(LOGIN_URL, json=wrong_credentials())
            health = await caller.get(HEALTH_URL)

        assert throttled.status_code == 429
        assert health.status_code == 200

    async def test_rate_limit_headers_are_present_on_success(
        self, registered: None, rate_limited: None
    ) -> None:
        """A client should be able to back off before it is rejected."""
        async with client_from("10.0.0.7") as caller:
            response = await caller.post(LOGIN_URL, json=right_credentials())

        assert response.status_code == 200
        assert response.headers.get("x-ratelimit-limit") == str(LIMIT)
        assert response.headers.get("x-ratelimit-remaining") == str(LIMIT - 1)


class TestRateLimitDisabled:
    async def test_limiter_is_off_for_the_rest_of_the_suite(
        self, registered: None, client: AsyncClient
    ) -> None:
        """Guard on the autouse fixture: without it other tests fail by order."""
        statuses = []
        for _ in range(BURST):
            response = await client.post(LOGIN_URL, json=wrong_credentials())
            statuses.append(response.status_code)

        assert statuses == [401] * BURST
