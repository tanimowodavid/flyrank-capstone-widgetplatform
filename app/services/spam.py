"""Spam detection service (PRD FR4.2 - honeypot defense).

Responsible for:
  - FR4.2: Detect spam submissions using honeypot field
  - Honeypot is a hidden form field that real humans never fill (only bots do)
  - If honeypot is filled, mark submission as is_spam=True
  - Honeypot submissions are silently stored (no error to visitor)

TODO: Implement SpamDetector with:
  - async detect_spam(payload: dict, widget: Widget) -> bool
    Returns True if spam detected (honeypot filled or other heuristics)
    
Honeypot strategy:
  - Widget.form_fields includes a hidden field with name from config (e.g., "website_url" or similar)
  - Visitor form renders this field as display:none or input type=hidden
  - Real users leave it blank; bots fill it
  - If the honeypot field has a non-empty value, is_spam=True
  
Note: Honeypot name can be configured per widget or globally. For MVP, a single global name is fine.

Stretch goal (not MVP):
  - Add heuristics: submission frequency spike, suspicious field patterns, etc.
  - For now, honeypot only is sufficient per PRD section 9 (Risks & Open Questions)
"""

# TODO: Implement SpamDetector class
