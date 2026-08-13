"""Geolocation enrichment service with fallback chain (PRD FR5.1-5.2).

Responsible for:
  - FR5.1: Query geolocation provider A (primary)
  - If A fails or is unavailable, automatically try provider B (secondary)
  - FR5.2: If both fail, return None for geo data (submission still succeeds)
  - All calls are wrapped; exceptions never propagate to caller

TODO: Implement EnrichmentService with:
  - async get_geolocation(ip_address: str) -> dict | None
    Returns: {"country": str, "city": str, "provider": str} or None on total failure
  - Implement Provider A fallback to Provider B (e.g., IP-API -> GeoIP2 Mock, or similar)
  - All HTTP calls include timeout and retry logic
  - Exceptions are caught and logged; never raised to caller
  - Track which provider succeeded (store in geo_provider field for audit)
  
Recommended providers for local testing (free tier):
  - Primary: ip-api.com (free but rate-limited, ~45/min)
  - Secondary: ipstack.com or geoip-db.com (backup)
  - Mock provider for deterministic testing (configure via env)

Note: These are mocked in tests to avoid consuming free-tier quota and ensure determinism.
"""

# TODO: Implement EnrichmentService class
