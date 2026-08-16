"""Geolocation enrichment and its fallback chain (PRD FR5.1-5.2).

Every test here drives a fake HTTP client. Nothing touches the network, which is
not only about speed: both providers are rate-limited free tiers, so a suite that
called them for real would start failing once it ran often enough, and the
failure would look like a bug in this code.

Responses are built as real httpx.Response objects rather than stubs with a
.json() method, so status_code handling and JSON decoding behave exactly as they
will in production — including the decode error an HTML error page produces.
"""

import uuid

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_http_client
from app.main import app
from app.models.widget import Widget
from app.repositories.submission import SubmissionRepository
from app.services.enrichment import (
    PRIMARY_LABEL,
    SECONDARY_LABEL,
    EnrichmentService,
    GeoLocation,
)

# Response bodies as each provider actually documents them. The two shapes are
# the reason the service parses them separately: different success markers,
# different failure markers, and the country under a different key.
PRIMARY_SUCCESS = {
    "status": "success",
    "country": "United States",
    "countryCode": "US",
    "city": "Ashburn",
}
PRIMARY_FAIL = {"status": "fail", "message": "reserved range", "query": "127.0.0.1"}
SECONDARY_SUCCESS = {"ip": "8.8.8.8", "city": "Berlin", "country_name": "Germany"}
SECONDARY_FAIL = {"error": True, "reason": "RateLimited"}

IP = "8.8.8.8"


class FakeHttpClient:
    """Stands in for httpx.AsyncClient, replaying queued outcomes in order.

    An outcome is either a Response to return or an Exception to raise, which is
    what lets one fake cover both "the provider answered badly" and "the request
    never completed". Records every URL so a test can assert which providers were
    reached — and, just as importantly, which were not.
    """

    def __init__(self, *outcomes: httpx.Response | Exception) -> None:
        self._outcomes = list(outcomes)
        self.requested_urls: list[str] = []
        self.timeouts: list[object] = []

    async def get(self, url: str, *, timeout: object = None, **kwargs: object) -> httpx.Response:
        self.requested_urls.append(url)
        self.timeouts.append(timeout)

        if not self._outcomes:
            # Louder than returning a default: an unqueued request means the
            # service called a provider the test did not expect it to.
            raise AssertionError(f"unexpected request to {url}")

        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def json_response(body: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=body)


def text_response(body: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status_code, text=body)


class TestPrimaryProviderSucceeds:
    async def test_returns_primary_data_labelled_a(self) -> None:
        fake = FakeHttpClient(json_response(PRIMARY_SUCCESS))

        result = await EnrichmentService(fake).enrich(IP)

        assert result == GeoLocation(
            country="United States", city="Ashburn", provider=PRIMARY_LABEL
        )

    async def test_secondary_is_not_called(self) -> None:
        """The fallback exists to be skipped when it is not needed.

        Calling it anyway would spend a request from a rate-limited free tier for
        an answer already in hand.
        """
        fake = FakeHttpClient(json_response(PRIMARY_SUCCESS))

        await EnrichmentService(fake).enrich(IP)

        assert len(fake.requested_urls) == 1
        assert "ip-api.com" in fake.requested_urls[0]

    async def test_url_is_built_from_configuration(self) -> None:
        fake = FakeHttpClient(json_response(PRIMARY_SUCCESS))

        await EnrichmentService(fake).enrich(IP)

        assert fake.requested_urls[0] == f"{settings.GEO_PROVIDER_PRIMARY.rstrip('/')}/{IP}"

    async def test_configured_timeout_is_applied(self) -> None:
        """A lookup that hangs must not hold a visitor's submission open."""
        fake = FakeHttpClient(json_response(PRIMARY_SUCCESS))

        await EnrichmentService(fake).enrich(IP)

        assert fake.timeouts == [settings.GEO_LOOKUP_TIMEOUT]

    async def test_partial_data_is_still_a_success(self) -> None:
        """A city with no country is worth recording, and is not a failure."""
        fake = FakeHttpClient(json_response({"status": "success", "city": "Ashburn"}))

        result = await EnrichmentService(fake).enrich(IP)

        assert result == GeoLocation(country=None, city="Ashburn", provider=PRIMARY_LABEL)


class TestFallsBackToSecondary:
    """Every way the primary can let us down, and the same recovery from each."""

    @pytest.mark.parametrize(
        "primary_outcome",
        [
            pytest.param(json_response(PRIMARY_FAIL), id="in-body status fail"),
            pytest.param(httpx.TimeoutException("timed out"), id="timeout"),
            pytest.param(httpx.ConnectError("refused"), id="connection refused"),
            pytest.param(json_response(PRIMARY_SUCCESS, status_code=500), id="http 500"),
            pytest.param(json_response(PRIMARY_SUCCESS, status_code=429), id="http 429"),
            pytest.param(text_response("<html>gateway error</html>"), id="non-JSON body"),
            pytest.param(text_response(""), id="empty body"),
            pytest.param(json_response([1, 2, 3]), id="JSON list, not an object"),
            pytest.param(
                json_response({"status": "success", "country": "", "city": ""}),
                id="success with blank fields",
            ),
            pytest.param(RuntimeError("something unforeseen"), id="unexpected exception"),
        ],
    )
    async def test_secondary_answers_when_primary_does_not(
        self, primary_outcome: httpx.Response | Exception
    ) -> None:
        fake = FakeHttpClient(primary_outcome, json_response(SECONDARY_SUCCESS))

        result = await EnrichmentService(fake).enrich(IP)

        assert result == GeoLocation(
            country="Germany", city="Berlin", provider=SECONDARY_LABEL
        )

    async def test_both_providers_are_tried_in_order(self) -> None:
        fake = FakeHttpClient(
            json_response(PRIMARY_FAIL), json_response(SECONDARY_SUCCESS)
        )

        await EnrichmentService(fake).enrich(IP)

        assert fake.requested_urls == [
            f"{settings.GEO_PROVIDER_PRIMARY.rstrip('/')}/{IP}",
            f"{settings.GEO_PROVIDER_SECONDARY.rstrip('/')}/{IP}/json/",
        ]


class TestBothProvidersFail:
    """The contract that matters most: no geo data, and no exception."""

    @pytest.mark.parametrize(
        ("primary_outcome", "secondary_outcome"),
        [
            pytest.param(
                json_response(PRIMARY_FAIL), json_response(SECONDARY_FAIL), id="both decline"
            ),
            pytest.param(
                httpx.TimeoutException("t"), httpx.TimeoutException("t"), id="both time out"
            ),
            pytest.param(
                httpx.ConnectError("c"), httpx.ConnectError("c"), id="both unreachable"
            ),
            pytest.param(
                json_response(PRIMARY_FAIL),
                json_response(SECONDARY_SUCCESS, status_code=503),
                id="decline then http 503",
            ),
            pytest.param(
                text_response("<html>"), text_response("<html>"), id="both non-JSON"
            ),
            pytest.param(
                RuntimeError("boom"), RuntimeError("boom"), id="both raise unexpectedly"
            ),
        ],
    )
    async def test_returns_empty_without_raising(
        self,
        primary_outcome: httpx.Response | Exception,
        secondary_outcome: httpx.Response | Exception,
    ) -> None:
        fake = FakeHttpClient(primary_outcome, secondary_outcome)

        result = await EnrichmentService(fake).enrich(IP)

        assert result == GeoLocation(country=None, city=None, provider=None)
        assert result.country is None
        assert result.city is None
        assert result.provider is None

    async def test_secondary_in_body_error_is_recognised(self) -> None:
        """ipapi.co reports failure as error/reason, not as the primary's status."""
        fake = FakeHttpClient(json_response(PRIMARY_FAIL), json_response(SECONDARY_FAIL))

        result = await EnrichmentService(fake).enrich(IP)

        assert result.provider is None


class TestNoAddressToLookUp:
    @pytest.mark.parametrize("missing", [None, ""])
    async def test_no_provider_is_called(self, missing: str | None) -> None:
        """submitter_ip is None whenever no proxy header was present.

        Calling a provider with an empty address spends a request to be told what
        is already known.
        """
        fake = FakeHttpClient()

        result = await EnrichmentService(fake).enrich(missing)

        assert result == GeoLocation()
        assert fake.requested_urls == []


@pytest.fixture
def geo_responses():
    """Install a fake HTTP client for the running app to use.

    Replaces the autouse offline stub for one test, so an endpoint test can
    decide what the providers say.
    """
    installed: list[FakeHttpClient] = []

    def install(*outcomes: httpx.Response | Exception) -> FakeHttpClient:
        fake = FakeHttpClient(*outcomes)
        app.dependency_overrides[get_http_client] = lambda: fake
        installed.append(fake)
        return fake

    yield install
    app.dependency_overrides.pop(get_http_client, None)


class TestSubmissionSurvivesEnrichmentFailure:
    """FR5.2 end to end: a dead provider chain must not cost a submission."""

    async def test_submission_is_stored_when_both_providers_fail(
        self,
        client: AsyncClient,
        active_widget: Widget,
        db: AsyncSession,
        geo_responses,
    ) -> None:
        fake = geo_responses(
            json_response(PRIMARY_FAIL), json_response(SECONDARY_FAIL)
        )

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json={"field_values": {"email": "visitor@example.com", "name": "Jane"}},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )

        assert response.status_code == 201

        submission = await SubmissionRepository(db).get_by_id(
            uuid.UUID(response.json()["id"]), active_widget.customer_id
        )
        assert submission is not None
        # The lead itself is intact. That is the whole point of FR5.2.
        assert submission.payload == {"email": "visitor@example.com", "name": "Jane"}
        assert submission.geo_country is None
        assert submission.geo_city is None
        assert submission.geo_provider is None

        # Both providers really were attempted, so this passes for the right
        # reason rather than because enrichment was never reached.
        assert len(fake.requested_urls) == 2
        assert "ip-api.com" in fake.requested_urls[0]
        assert "ipapi.co" in fake.requested_urls[1]

    async def test_submission_survives_a_transport_failure(
        self,
        client: AsyncClient,
        active_widget: Widget,
        offline_http_client,
    ) -> None:
        """The autouse offline stub raises ConnectError, the harshest case."""
        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json={"field_values": {"email": "visitor@example.com"}},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )

        assert response.status_code == 201
        assert len(offline_http_client.attempted_urls) == 2

    async def test_geo_data_is_stored_when_a_provider_answers(
        self,
        client: AsyncClient,
        active_widget: Widget,
        db: AsyncSession,
        geo_responses,
    ) -> None:
        """The success path, end to end: what a provider says reaches the row."""
        geo_responses(json_response(PRIMARY_SUCCESS))

        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json={"field_values": {"email": "visitor@example.com"}},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )

        assert response.status_code == 201

        submission = await SubmissionRepository(db).get_by_id(
            uuid.UUID(response.json()["id"]), active_widget.customer_id
        )
        assert submission is not None
        assert submission.geo_country == "United States"
        assert submission.geo_city == "Ashburn"
        assert submission.geo_provider == PRIMARY_LABEL
        assert submission.submitter_ip == "203.0.113.10"

    async def test_no_geo_lookup_without_a_forwarded_address(
        self,
        client: AsyncClient,
        active_widget: Widget,
        offline_http_client,
    ) -> None:
        """No address means no provider call, so no quota spent on nothing."""
        response = await client.post(
            f"/api/v1/widgets/{active_widget.id}/submit",
            json={"field_values": {"email": "visitor@example.com"}},
        )

        assert response.status_code == 201
        assert offline_http_client.attempted_urls == []
