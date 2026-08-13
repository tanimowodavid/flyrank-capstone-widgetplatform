"""Submission business logic (PRD Path C - accept, validate, enrich, persist, notify).

Orchestrates the full submission pipeline:
  1. Validate the payload shape against the widget's form_fields (FR3.2)
  2. Check for spam via honeypot (FR4.2)
  3. Capture IP and User-Agent from request headers
  4. Enrich with geolocation using fallback chain (FR5.1-5.2)
  5. Store the submission atomically (FR3.3)
  6. Trigger side effect (email/webhook) without blocking success (FR5.3)

TODO: Implement SubmissionService for:
  - FR3.2: Validate payload size, field names, required fields, field types
  - FR4.2: Honeypot detection - check if honeypot_field is filled (mark is_spam=True, silently drop)
  - FR5.1: Geo enrichment with provider fallback (try Provider A, then Provider B)
  - FR5.2: If enrichment fails, store submission anyway without geo data
  - FR5.3: Queue side effects (email/webhook) after commit; if side effect fails, log but don't raise
  - Raise domain errors, not HTTPException; mapping to status codes belongs in endpoint layer
  
Key design decisions:
  - Like WidgetService: raise custom exceptions, let endpoint map to HTTP status
  - Submission success never depends on enrichment or side effects
  - Side effects are fire-and-forget (async task queue or background job recommended)
  - Honeypot submission is silently dropped (no error to visitor, just is_spam=True)
"""

from sqlalchemy.ext.asyncio import AsyncSession

# TODO: Implement SubmissionService class
class SubmissionNotCreatedError(Exception):
    """Submission could not be stored."""
