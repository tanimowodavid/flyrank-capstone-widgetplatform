## BUILDLOG.md

### Embeddable Widget & Lead-Capture Platform — AI Usage Log

AI (Claude, via agent and chat sessions) was used throughout this build. This log records where it helped, what it got wrong or oversimplified, and what I changed or decided myself.

### Auth (signup, login, JWT, password change, delete account)

**AI helped with:** bcrypt hashing setup, JWT create/verify functions, the get_current_customer dependency pattern, and the initial rate-limiting setup for login.

**What I changed:** the agent's first pass at rate limiting used in-memory storage. I required Redis-backed storage instead, since in-memory counters don't share state across multiple server instances — the whole point of rate limiting is protecting the system, not just one process.

**Decision I made, not AI:** account deletion cascades fully (widgets, fields, submissions) via a DB-level ON DELETE CASCADE, since no other tenant has a claim on that data once the account is gone.

### Widget CRUD + embed snippet

**AI helped with:** the CRUD endpoints, nested form-field creation, and generating the embed snippet string.

**Decision I made, not AI:** widget_type and field_type are constrained to explicit enums, not free strings — this was specified before any code was written, to keep the platform to the "prove the pattern, don't build a form-builder" scope in the brief.

**Decision I made, not AI:** widget deletion cascades to FormField but not to Submission — a widget being removed doesn't mean the customer wants to lose the leads it already collected. This required Submission.widget_id to be nullable (ON DELETE SET NULL), which I specified before the delete endpoint was built.

### Widget delivery (widget.js, public config endpoint)

**AI helped with:** the vanilla-JS embed script (self-locating via document.currentScript, config fetch, form rendering) and the public config endpoint.

### Submission validation, field-snapshotting

**AI helped with:** the validation logic checking incoming field_values against a widget's real FormField definitions, and the snapshot logic storing {field_name, label, field_type, value} per field rather than raw values.

**Decision I made:** submissions snapshot field metadata at submission time so historical submissions stay correctly labeled even after a widget's fields are later edited or replaced. I identified this as a real problem myself (a full-replace field edit would otherwise orphan or mislabel old submissions) before asking for an implementation.

### Honeypot spam detection

**Where I was initially wrong:** my first instinct was to have widget.js check the honeypot field client-side and report a spam verdict to the server. This is a real security flaw — an attacker can bypass client-side JavaScript entirely and POST straight to the API, so any spam decision made in the browser is trivially forgeable. I worked through this with AI assistance and corrected the design before any code was written: the client only renders and submits the field with zero interpretation; the server alone decides whether it's spam, based on the raw value it receives.

**Decision I made:** spam submissions are still stored, just flagged (is_spam=True), not silently dropped — this preserves the ability to prove the honeypot works and gives the dashboard future visibility into spam volume.

### Geolocation enrichment (provider fallback chain)

**AI helped with:** the EnrichmentService structure (injectable HTTP client for testability), the primary/secondary provider fallback logic, and provider-specific response parsing.

**What I changed:** my original config used ipstack.com as the secondary provider, which requires an API key even on its free tier — conflicting with the project's explicit no-cost, no-card requirement. Swapped to ipapi.co, matching what the brief actually specifies as free.

### General pattern across the build

The recurring theme in this log isn't "AI wrote bad code" — most of what it generated worked correctly on the first pass. The value of reviewing it carefully was catching places where an easy default (in-memory rate limiting, client-side spam verdicts, a paid geo provider) would have quietly violated a real requirement of the project — resilience, security, or the $0 constraint — without causing an obvious bug. Each of those was caught by checking AI output against the PRD and the project's own stated principles, not by assuming the first working version was the right version.
