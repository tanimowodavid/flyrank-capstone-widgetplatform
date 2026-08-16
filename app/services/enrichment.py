"""Geolocation enrichment with a provider fallback chain (PRD FR5.1-5.2).

Enrichment is decoration, not data capture. A submission is a lead someone's
business is waiting for; knowing which city it came from is a nice-to-have. So
every failure here resolves the same way — no country, no city, no provider, and
the submission stores fine without them. enrich() does not raise. That is the
whole contract, and the reason each provider attempt is wrapped to the point of
paranoia rather than left to a caller's try block.

The HTTP client is injected rather than built here so tests can hand over a fake
and never touch the network: real calls would burn a rate-limited free tier and
make the suite fail on a train.
"""

import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Which provider answered, recorded on the submission for audit. Short labels
# rather than hostnames because that is what the geo_provider column carries
# today; swapping in "ip-api.com" would be more use to whoever reads it later.
PRIMARY_LABEL = "A"
SECONDARY_LABEL = "B"


@dataclass(frozen=True, slots=True)
class GeoLocation:
    """What a lookup found, or an empty instance when nothing did.

    Frozen because it crosses a service boundary and nothing downstream has any
    business editing what a provider said.
    """

    country: str | None = None
    city: str | None = None
    provider: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.provider is None


class EnrichmentService:
    """Resolves an IP to a country and city, trying providers in order."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Takes an already-built client.

        Required, not optional. A default that constructed its own client would
        let a test silently make a real network call by forgetting to pass one.
        """
        self._client = client

    async def enrich(self, ip: str | None) -> GeoLocation:
        """Look up `ip`, falling back from the primary provider to the secondary.

        Never raises. Returns an empty GeoLocation if both providers fail, if the
        address is missing, or if anything else goes wrong.
        """
        # submitter_ip is None whenever the request arrived without the proxy
        # header the endpoint reads it from, which is the normal case in local
        # development. Calling a provider with an empty address would spend a
        # request to be told what we already know.
        if not ip:
            return GeoLocation()

        primary = await self._lookup_primary(ip)
        if not primary.is_empty:
            return primary

        secondary = await self._lookup_secondary(ip)
        if not secondary.is_empty:
            return secondary

        logger.warning("Geo lookup failed at both providers for %s", ip)
        return GeoLocation()

    async def _lookup_primary(self, ip: str) -> GeoLocation:
        """ip-api.com, which reports failure in the body as status: "fail"."""
        url = f"{settings.GEO_PROVIDER_PRIMARY.rstrip('/')}/{ip}"

        data = await self._get_json(url, PRIMARY_LABEL)
        if data is None:
            return GeoLocation()

        # A 200 carrying status "fail" is the documented response for a reserved
        # or unroutable address, so the HTTP status alone says nothing.
        if data.get("status") != "success":
            logger.info(
                "Primary geo provider declined %s: %s",
                ip,
                data.get("message", "no message"),
            )
            return GeoLocation()

        return self._build(
            country=data.get("country"),
            city=data.get("city"),
            provider=PRIMARY_LABEL,
        )

    async def _lookup_secondary(self, ip: str) -> GeoLocation:
        """ipapi.co, whose shape differs: error flag, and country under another key."""
        url = f"{settings.GEO_PROVIDER_SECONDARY.rstrip('/')}/{ip}/json/"

        data = await self._get_json(url, SECONDARY_LABEL)
        if data is None:
            return GeoLocation()

        # Also a 200 with an in-body error, but spelled differently to the
        # primary's. Two providers, two failure vocabularies, which is the reason
        # each one gets its own parser rather than a shared "is this ok" helper.
        if data.get("error"):
            logger.info(
                "Secondary geo provider declined %s: %s",
                ip,
                data.get("reason", "no reason"),
            )
            return GeoLocation()

        return self._build(
            country=data.get("country_name"),
            city=data.get("city"),
            provider=SECONDARY_LABEL,
        )

    async def _get_json(self, url: str, label: str) -> dict | None:
        """GET `url` and decode it, or return None if any part of that fails.

        Every failure mode is caught here so the parsers above deal only with a
        dict they can read. They are caught separately rather than as one
        `except Exception` because the distinction is what a log reader needs: a
        timeout means the provider is slow or unreachable, a decode error means it
        answered with something that is not the API we think it is.
        """
        try:
            # Timeout per request rather than set on the client: the client is the
            # caller's, and reaching in to reconfigure it would change the
            # behaviour of every other request they make with it.
            response = await self._client.get(
                url, timeout=settings.GEO_LOOKUP_TIMEOUT
            )
        except httpx.TimeoutException:
            logger.warning("Geo provider %s timed out", label)
            return None
        except httpx.RequestError as exc:
            # Connection refused, DNS failure, TLS problem: the request never
            # completed, so there is no response to inspect.
            logger.warning("Geo provider %s unreachable: %s", label, exc)
            return None
        except Exception:
            # Not reachable through any documented httpx path. It exists because
            # enrich() promises never to raise, and a promise resting on the
            # completeness of an exception hierarchy is not a promise.
            logger.exception("Geo provider %s raised unexpectedly", label)
            return None

        if response.status_code != 200:
            logger.warning(
                "Geo provider %s returned HTTP %s", label, response.status_code
            )
            return None

        try:
            data = response.json()
        except ValueError:
            # JSONDecodeError subclasses ValueError. An HTML error page or an
            # empty body both land here.
            logger.warning("Geo provider %s returned non-JSON", label)
            return None

        # A provider could answer 200 with a JSON list or string. Every parser
        # here calls .get(), which only a mapping has.
        if not isinstance(data, dict):
            logger.warning("Geo provider %s returned %s, not an object", label, type(data).__name__)
            return None

        return data

    @staticmethod
    def _build(
        country: object, city: object, provider: str
    ) -> GeoLocation:
        """Normalise a provider's values, or report nothing usable.

        Values are coerced to str and blanks dropped, because a provider can
        answer 200 with a success flag and empty strings for the fields we wanted.
        Treating that as a win would record "enriched by A" against no location
        and skip the provider that might actually have known.
        """
        clean_country = str(country).strip() if country else None
        clean_city = str(city).strip() if city else None

        if not clean_country and not clean_city:
            return GeoLocation()

        return GeoLocation(
            country=clean_country or None,
            city=clean_city or None,
            provider=provider,
        )
