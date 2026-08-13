"""Dashboard endpoints for authenticated owners (PRD Path A - view submissions and analytics).

Two main endpoints:
  1. GET /dashboard/submissions - List submissions for authenticated customer
     Filters by customer_id, optionally by widget_id
     Supports pagination, filtering, sorting
     
  2. GET /dashboard/analytics - Basic analytics for customer's widgets
     Submission counts, per-widget breakdown, geo breakdown
     
TODO: Implement dashboard endpoints for:
  - FR6.1: List submissions for authenticated customer
    - GET /dashboard/submissions?widget_id={widget_id}&limit=50&offset=0
    - Filter by widget_id if provided (optional)
    - Return paginated list of SubmissionRead (from app/schemas/submission.py)
    - Tenant isolation: only return submissions for customer's own widgets
    - Response: [SubmissionRead, ...] with pagination metadata
    
  - FR6.2: Analytics for customer's widgets
    - GET /dashboard/analytics
    - Return basic stats:
      * Total submission count
      * Per-widget breakdown: {widget_id: count}
      * Geo breakdown: {country: count, ...} (count by geo_country)
      * Spam breakdown: {is_spam: true/false, count: N}
      * Time series (optional): submissions over time by day/week
    - Only include submissions for this customer (tenant isolation)
    
Implementation notes:
  - Require authentication (@router.get with CurrentCustomer dependency)
  - All queries must filter by customer.id (FR1.4 - tenant isolation)
  - SubmissionRepository methods like list_for_customer, count_for_customer, etc.
  - Optional: add filtering by widget_id, date range, spam status
  - Return clean JSON structure for easy frontend consumption
"""

from fastapi import APIRouter

# TODO: Implement dashboard endpoints
router = APIRouter(prefix="/dashboard", tags=["dashboard"])
