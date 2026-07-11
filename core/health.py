"""Single source of truth for the CLI health-status vocabulary.

Both the data layer (core.catalog.queries) and the render layers
(core.web.overview_view, core.tui.overview) MUST import from here rather than
redefining the canonical set. The vocabulary was previously duplicated; a 5th
state added to the render layer alone was dead code because the data layer
normalized it away first (US-CLIAUDIT-83 distributed-enum smell).

States:
  healthy           — probe exited 0
  unhealthy         — probe exited non-zero
  stale             — no probeable command and last check older than the TTL
  unknown           — no probeable command, within TTL, or an unrecognized value
  not_standalone    — statically classified as a non-standalone CLI (Typer/click
                      sub-app or no-parser batch script); never probed
  skipped-needs-env — probe failed on a missing required env var / API key
                      (classifier's ENV_MISSING verdict); reading as "broken"
                      would be wrong — it is a human/operator provisioning gap,
                      not a code defect (US-REMED-ENVDOC-01)
"""
from __future__ import annotations

CANON_HEALTH = frozenset(
    {"healthy", "unhealthy", "stale", "unknown", "not_standalone", "skipped-needs-env"}
)


def norm_health(value) -> str:
    """Canonicalize a stored health_status to the lowercase canonical set,
    defaulting unrecognized/None values to 'unknown'. Defends consumers against
    legacy uppercase rows that predate the lowercase normalization."""
    state = (value or "unknown").lower()
    return state if state in CANON_HEALTH else "unknown"
