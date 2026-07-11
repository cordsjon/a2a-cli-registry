"""One-off: re-classify unhealthy CLIs whose failure is a genuinely missing
required env var / API key (classifier's ENV_MISSING verdict) into a distinct
'skipped-needs-env' health_status, instead of leaving them read as 'unhealthy'
(= broken code). Ticket: US-REMED-ENVDOC-01 AC-01/AC-02.

This never runs a subprocess and never provisions/guesses env values — env
provisioning is human/operator action (AC-03). It only reclassifies rows the
classifier already proved are ENV_MISSING from the failure note already
persisted in cli.description.

Usage: python3 -m tools.reclassify_envgated [--db PATH] [--dry-run]
"""
import argparse
import os
import sqlite3
import sys

from core.remediation.classify import classify_failure
from core.remediation.proposal import FailureClass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="Path to registry DB (default: ~/.hermes/cli-registry.db)")
    ap.add_argument("--dry-run", action="store_true", help="Report only, do not write")
    args = ap.parse_args()

    db_path = args.db or os.path.expanduser("~/.hermes/cli-registry.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT slug, description, path FROM cli WHERE health_status != 'healthy'"
    ).fetchall()

    flips = []
    for r in rows:
        proposal = classify_failure(r["slug"], r["description"] or "", r["path"] or "")
        if proposal.failure_class != FailureClass.ENV_MISSING:
            continue
        flips.append((r["slug"], proposal.target, proposal.evidence))

    print(f"{len(flips)} CLIs proven env-gated (ENV_MISSING), reclassifying to 'skipped-needs-env':")
    for slug, var, evidence in flips:
        print(f"  {slug}: var={var or '(unnamed)'} evidence={evidence!r}")

    if args.dry_run or not flips:
        return

    conn.executemany(
        "UPDATE cli SET health_status = 'skipped-needs-env' WHERE slug = ?",
        [(s,) for s, _, _ in flips],
    )
    conn.commit()
    print(f"\nReclassified {len(flips)} rows to 'skipped-needs-env'.")


if __name__ == "__main__":
    sys.exit(main())
