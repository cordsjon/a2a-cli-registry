"""One-off: re-classify pip-unknown rows against the new module-mode check,
re-probe the ones that newly resolve to wrong-cwd, and flip to healthy only
the CLIs that demonstrably pass. Ticket: US-REMED-MODULEMODE-01 AC-02.

Usage: python3 tools/reclassify_modulemode.py [--db PATH] [--dry-run]
"""
import argparse
import sqlite3
import subprocess
import sys

from core.remediation.classify import classify_failure
from core.remediation.proposal import FailureClass


class _Row:
    def __init__(self, slug, description, path):
        self.slug = slug
        self.description = description
        self.path = path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="Path to registry DB (default: ~/.hermes/cli-registry.db)")
    ap.add_argument("--dry-run", action="store_true", help="Report only, do not write")
    args = ap.parse_args()

    import os
    db_path = args.db or os.path.expanduser("~/.hermes/cli-registry.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT slug, description, path FROM cli WHERE health_status != 'healthy'"
    ).fetchall()

    flips = []
    for r in rows:
        proposal = classify_failure(r["slug"], r["description"] or "", r["path"] or "")
        if proposal.failure_class != FailureClass.WRONG_CWD:
            continue
        if "python -m" not in (proposal.evidence or ""):
            continue  # only the new module-mode path, not the adjacent-file case
        # Extract the python -m invocation and re-probe.
        # evidence format: "... | proven module-mode: python -m <dotted> (from <root>)"
        ev = proposal.evidence
        marker = "python -m "
        idx = ev.find(marker)
        rest = ev[idx + len(marker):]
        dotted = rest.split(" (from ")[0].strip()
        root = rest.split(" (from ")[1].rstrip(")").strip() if " (from " in rest else None
        if not root:
            continue
        try:
            proc = subprocess.run(
                ["python3", "-m", dotted, "--help"],
                capture_output=True, text=True, timeout=5, cwd=root,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        if proc.returncode != 0:
            continue
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if (
            not out
            or "Traceback" in out
            or "ModuleNotFoundError" in out
            or "cannot be directly executed" in out
            or "No module named" in out
        ):
            continue
        flips.append(r["slug"])

    print(f"{len(flips)} CLIs proven to pass module-mode re-probe: {flips}")

    if args.dry_run or not flips:
        return

    conn.executemany(
        "UPDATE cli SET health_status = 'healthy' WHERE slug = ?",
        [(s,) for s in flips],
    )
    conn.commit()
    print(f"Flipped {len(flips)} rows to healthy.")


if __name__ == "__main__":
    sys.exit(main())
