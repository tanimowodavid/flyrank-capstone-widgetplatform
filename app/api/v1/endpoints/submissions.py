"""Public endpoint for visitor form submissions (PRD Path C - untrusted).

Single endpoint:
  POST /public/widgets/:widget_id/submit - Accept visitor form submissions
  
Handles:
  - FR3.1: CORS (accept from any origin, handle OPTIONS preflight)
  - FR3.2: Validate payload (reject oversized, malformed, missing required fields)
  - FR3.3: Store submission (call SubmissionService.create)
  - FR4.1: Rate limiting per IP and/or per widget
  - FR4.2: Spam detection (honeypot)
  - FR5.1-5.2: Geolocation enrichment with fallback
  - FR5.3: Trigger side effects (email/webhook) without blocking response
  
Key design:
  - Public: no authentication required
  - Hostile: assume every request is potentially malicious
  - Fast: client-side code waits for response, so latency matters
  - Resilient: geolocation or email failures never cause 5xx response
  - Rate limited: per IP to prevent flood attacks
  
HTTP status codes:
  - 201 Created: submission stored successfully
  - 400 Bad Request: validation failed (oversized, missing required field, wrong type, etc.)
  - 404 Not Found: widget not found or inactive
  - 429 Too Many Requests: rate limit exceeded (from rate_limit.py)
  - 500 Internal Server Error: only for true bugs, never for payload issues

TODO: Implement submission endpoint for:
  - FR3.1: Accept POST from any origin (CORS middleware handles this)
  - FR3.2: Validate payload shape/size; return 400 for any validation failure
    - Max payload size from settings
    - Validate field presence and types against widget.form_fields
    - Reject unknown fields (stricter) or ignore them (looser) - choose based on UX
    
  - FR3.3: Call SubmissionService to create submission
    - Pass widget_id, request.client.host (IP), request.headers.get('user-agent')
    - Service validates, detects spam, enriches, stores, triggers side effects
    
  - FR4.1: Rate limit decorator
    - Per IP: @limiter.limit(\"60/minute\") or similar
    - Optional: also rate limit per widget_id to prevent single-widget flooding other widgets
    
  - FR4.2: Spam detection (delegated to SubmissionService)
  - FR5.1-5.2: Enrichment with fallback (delegated to SubmissionService)
  - FR5.3: Side effects fire-and-forget after commit (delegated to SubmissionService)
  
Error responses must use app/schemas/submission.py (when created)
"""

from fastapi import APIRouter

# TODO: Implement public submission endpoint
router = APIRouter(prefix="/public/widgets", tags=["submissions"])
