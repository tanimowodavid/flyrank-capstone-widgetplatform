# Product Requirements Document

## Embeddable Widget & Lead-Capture Platform

**Author:** Tanimowo David (with Claude)

---

## 1. Overview

### 1.1 What this is

A platform that lets a customer (a business) create a widget — a signup form, contact form, or call-to-action popover — and embed it on any website using a single line of HTML. When a visitor on that website fills out the widget, the submission is sent back to our system, checked for spam, protected from abuse, enriched with location data, safely stored, and shown to the customer in a dashboard.

### 1.2 The problem this solves

Businesses want a simple way to collect leads (potential customers) from their website without building custom form infrastructure. Today, they'd have to either pay for a third-party tool (Mailchimp, HubSpot, Intercom) or build this themselves — which is deceptively hard, because the moment your form is live on someone else's website, you're accepting traffic from the open internet: bots, spam, malicious payloads, and unpredictable load. This project builds that infrastructure from scratch.

### 1.3 Who this is for (in-story)

- **The Widget Owner** — a business that signs up, creates a widget, and wants to see the leads it collects.
- **The Website Visitor** — a random person on the internet who fills out the widget on the owner's website. They never log in; they just submit a form.

### 1.4 Why this project exists (real purpose)

This is a backend engineering capstone. Its job is to prove — with evidence, not just working code — that the system can survive real-world conditions: malicious input, traffic spikes, and third-party failures, without ever going down or losing data.

---

## 2. Goals and Non-Goals

### 2.1 Goals

1. A business can create, configure, and manage widgets through an authenticated API.
2. Each widget generates a single embeddable `<script>` snippet.
3. That snippet works when pasted into a completely different website (a different "origin") and renders a working form.
4. Visitor submissions are validated, protected from abuse, enriched with location data, and stored reliably.
5. A failure in any non-essential step (email notification, geo lookup) never causes a submission to be lost.
6. The widget owner can view submissions and basic analytics in a dashboard.
7. One customer can never see or affect another customer's widgets or data (multi-tenancy).

### 2.2 Non-Goals (explicitly out of scope)

- No real hosting, custom domain, or CDN — the "customer website" is just a plain HTML file running locally on a different port.
- No polished visual design for the widget itself — a functional form is enough; this is a backend project.
- No payment processing, billing, or subscription plans.
- No more than 1–2 widget types (e.g., signup form and CTA popover) — the platform proves the _pattern_, not a full form-builder product.
- No real email delivery — a logged/console email or a local mail catcher is sufficient.
- No CAPTCHA/bot-defense beyond a basic spam control (this is a stretch goal, not core).

---

## 3. User Stories

| #   | As a...                    | I want to...                                                                 | So that...                                                       |
| --- | -------------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| 1   | Widget Owner               | Sign up and log in                                                           | I can securely manage my own widgets                             |
| 2   | Widget Owner               | Create a widget with a type, title, and form fields                          | I can define what I want to collect from visitors                |
| 3   | Widget Owner               | Get a one-line embed snippet for my widget                                   | I can paste it into my website without writing custom code       |
| 4   | Widget Owner               | View submissions in a dashboard with basic stats                             | I can see and act on the leads I'm collecting                    |
| 5   | Widget Owner               | Be sure no other business can see my data                                    | I can trust the platform with customer information               |
| 6   | Website Visitor            | Submit a form on a site I'm browsing                                         | I can express interest without creating an account               |
| 7   | Website Visitor (implicit) | Have my submission rejected clearly if I fill it out wrong                   | (system integrity — visitor doesn't need to know this)           |
| 8   | System (self-interest)     | Keep working even if a rate-limit-breaking flood of requests hits one widget | Legitimate visitors aren't blocked by an attack on someone else  |
| 9   | System (self-interest)     | Keep working even if the geolocation provider or email service is down       | A visitor's submission is never lost due to a third-party outage |

---

## 4. Core Concepts (plain-language glossary)

| Term               | Meaning                                                                                                                                              |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Widget**         | A configurable form (signup, CTA, etc.) owned by one business                                                                                        |
| **Tenant**         | A business/customer account — each tenant's data is fully isolated from every other tenant's                                                         |
| **Embed snippet**  | The one-line `<script>` tag a business pastes into their website                                                                                     |
| **Origin**         | The domain + port a page is served from. `localhost:3000` and `localhost:5500` are different origins — this is how we simulate "a different website" |
| **CORS**           | Browser security rules that decide whether a page on one origin can call an API on another. Our public endpoints must explicitly allow this          |
| **Submission**     | A single form entry from a visitor                                                                                                                   |
| **Enrichment**     | Adding derived data (like country/city) to a submission based on the visitor's IP address                                                            |
| **Fallback chain** | Trying a backup provider if the primary one fails, so one dead dependency doesn't break the feature                                                  |
| **Rate limiting**  | Blocking excessive requests from one source so a flood can't take the system down                                                                    |
| **Honeypot**       | A hidden form field real humans never fill in, but bots do — used to silently catch spam                                                             |
| **Side effect**    | A secondary action after the main work (e.g., a confirmation email) that must never block the main action if it fails                                |

---

## 5. System Actors & Request Paths

There are exactly three distinct paths through this system. Keeping them mentally and architecturally separate is the single most important design decision in this project.

**Path A — Widget Owner (authenticated, trusted)**
Manages widgets and views the dashboard. Requires login. Full CRUD access to their own data only.

**Path B — Customer Website (public, semi-trusted)**
Loads the widget's JavaScript and configuration. No login. Must be fast and cacheable.

**Path C — Website Visitor (public, untrusted)**
Submits the form. No login. This is the most hostile-facing part of the system — every request must be treated as potentially malicious.

---

## 6. Functional Requirements

### 6.1 Widget Management (Path A)

- FR1.1: A business can register and authenticate (sign up / log in).
- FR1.2: An authenticated business can create a widget with: type, title, description, form fields, button text, display options.
- FR1.3: An authenticated business can view, update, and delete only their own widgets.
- FR1.4: Attempting to access another tenant's widget returns a clean "not found" or "forbidden" response — never a data leak.
- FR1.5: All inputs are validated; invalid requests return clean 4xx errors with a JSON error body, never a 500.

### 6.2 Embed Snippet & Delivery (Path B)

- FR2.1: Each widget has a generated embed snippet in the form `<script src=".../widget.js?id={widget_id}"></script>`.
- FR2.2: A public endpoint serves the widget's configuration (fields, labels, styling) as a small, cacheable JSON payload.
- FR2.3: The widget JavaScript bundle is served with a versioned URL so it can be cached long-term and safely updated later.
- FR2.4: The widget renders correctly when the snippet is pasted into an HTML page on a different origin than the API.

### 6.3 Public Submission (Path C)

- FR3.1: The submission endpoint accepts POST requests from any origin (CORS enabled), including handling the browser's preflight `OPTIONS` request correctly.
- FR3.2: Every field in the payload is validated before anything else happens. Malformed or oversized payloads are rejected with a 4xx response — never crash the server.
- FR3.3: Valid submissions are stored and linked to the correct widget and tenant.

### 6.4 Abuse Protection (Path C)

- FR4.1: Requests are rate-limited per IP address and/or per widget. Exceeding the limit returns HTTP 429, and legitimate traffic continues to be served normally.
- FR4.2: At least one spam-prevention technique is implemented (honeypot field is the recommended default). Detected spam is silently dropped or rejected.

### 6.5 Enrichment & Safe Side Effects (Path C)

- FR5.1: Each submission's IP address is enriched with geolocation data using Provider A. If Provider A fails, Provider B is tried automatically.
- FR5.2: If both providers fail, the submission is still stored successfully, simply without geo data. Enrichment failure never blocks storage.
- FR5.3: After a submission is stored, a confirmation email/webhook is triggered as a side effect. If this fails, the submission has already succeeded and remains stored — the failure is logged, not surfaced as an error to the visitor.

### 6.6 Owner Dashboard (Path A)

- FR6.1: An authenticated business can view all submissions for their own widgets.
- FR6.2: Basic analytics are available: submission counts over time, per-widget breakdown, geo breakdown.

---

## 7. Non-Functional Requirements

| Category        | Requirement                                                                                                                                                                                                 |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Security**    | Every query that touches widget or submission data must be scoped to the authenticated tenant. No secrets (API keys, credentials) are ever committed to source control — all live in environment variables. |
| **Resilience**  | No single third-party dependency failure (geo provider, email service) may cause a submission to be lost or the API to error out.                                                                           |
| **Performance** | Widget config and script delivery must be small and cache-friendly — a slow-loading widget is a widget a customer removes from their site.                                                                  |
| **Correctness** | The system must never return a 500 error for bad input — only clean, well-formed 4xx responses.                                                                                                             |
| **Testability** | Core failure scenarios (invalid payload, rate-limit burst, provider outage, side-effect failure, spam submission) must be covered by automated, deterministic tests — not manual checks.                    |
| **Portability** | The entire system must run locally with no paid service, no credit card, and no custom domain.                                                                                                              |

---

## 8. Success Criteria (Definition of Done)

The project is considered complete when all of the following are true and demonstrable:

1. A widget can be created, and its embed snippet works on a real, separate-origin HTML page.
2. A visitor can submit the widget and see the submission appear in the owner's dashboard, enriched with geo data.
3. Invalid and oversized submissions are cleanly rejected — never a server crash.
4. A burst of rapid submissions triggers rate limiting (429), while normal traffic continues to succeed.
5. Disabling the primary geo provider causes an automatic, transparent fallback to the secondary provider; disabling both still results in a successful, un-enriched submission.
6. A forced failure in the email/webhook side effect does not prevent the submission from being stored.
7. A honeypot-filled submission is identified and blocked as spam.
8. One tenant cannot read or modify another tenant's widgets or submissions, under any circumstance.
9. All of the above are covered by automated tests and documented with evidence (logs, test output, or request transcripts).

---

## 9. Risks & Open Questions

| Risk / Question                | Notes                                                                                                                                                                                                               |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CORS misconfiguration          | Historically the hardest part of projects like this — budget real debugging time, don't assume it'll "just work."                                                                                                   |
| Tenant isolation bugs          | A single missed `tenant_id` filter on one query is a real data-leak vulnerability, not just a missed checklist item. Worth solving once with a shared, reusable pattern rather than repeating the check everywhere. |
| Scope creep on widget types/UI | This is a backend proof, not a form-builder product — resist adding more widget types or visual polish than needed.                                                                                                 |
| Free-tier geo API limits       | Both providers have low free-tier request caps — enough for development and testing, but the fallback logic must be tested with mocked providers, not live calls, to stay deterministic.                            |
| What counts as "spam"          | Start with a honeypot field only; more sophisticated heuristics are a stretch goal, not core scope.                                                                                                                 |

---

## 10. What This Project Proves (portfolio framing)

This project is designed to demonstrate, with verifiable evidence rather than just claims:

- Clean, layered backend architecture (data / logic / HTTP separated)
- Multi-tenant data isolation done correctly
- Public-facing API hardening: CORS, validation, rate limiting, spam defense
- Graceful degradation under third-party failure (fallback chains, non-blocking side effects)
- Automated testing of adversarial and failure scenarios, not just happy paths

This is the "reliability infrastructure" half of the broader claim: _I build production backend systems — including the resilience layer that keeps them from breaking under real traffic._
