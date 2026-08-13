"""Submission data access layer (PRD Path C - persisting visitor submissions).

TODO: Implement SubmissionRepository for:
  - FR3.3: Create submission (store validated payload, IP, user_agent, widget_id, customer_id)
  - FR5.1-5.2: Store geo enrichment data (geo_country, geo_city, geo_provider)
  - FR4.2: Store is_spam flag (marked by spam detection service)
  - FR6.1-6.2: Query submissions for dashboard (by customer_id, by widget_id, with filtering/pagination)
  - Ensure all queries filter by customer_id for tenant isolation (FR1.4)
  
Key patterns:
  - Like WidgetRepository: async methods, scoped to customer
  - Submission can outlive its widget (widget_id SET NULL), but not its customer
  - All dashboard queries must include customer_id filter
"""

from sqlalchemy.ext.asyncio import AsyncSession

# TODO: Implement SubmissionRepository class
