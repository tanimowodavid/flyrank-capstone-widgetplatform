"""Submission request and response schemas (PRD Path C - Visitor Submissions).

TODO: Implement submission schemas for:
  - FR3.1: SubmissionCreate - public endpoint input (accepts any field name + value)
  - FR3.2: Input validation to reject oversized/malformed payloads
  - FR4.2: Add honeypot_field validation (silently mark submissions with honeypot filled)
  - Response schema for successful submission acknowledgment
  
Key design:
  - No customer_id in request (determined by widget_id)
  - No id in request (generated server-side)
  - Payload is dynamic JSON: shape defined by the widget's form_fields
  - Validation must reject payloads larger than MAX_SUBMISSION_SIZE (config)
"""

from pydantic import BaseModel

# TODO: Define MAX_SUBMISSION_SIZE in settings
