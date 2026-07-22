"""One-off: re-probe the 28 CLIs left unresolved by reclassify_modulemode.py
after correct classification (WRONG_CWD, module-mode-fixable) but a live
--help probe on the error-text-derived dotted path failed structurally
(package has no __main__.py). Ticket: US-REMED-MODULEMODE-FOLLOWUP-01 AC-02.

Instead of the error text's dotted name (usually just the top-level package),
derives the dotted module from the CLI's OWN recorded `path` relative to its
project root (core.paths.module_root._dotted_module) and re-probes THAT.
Flips to healthy only rows with a genuine passing `--help` invocation that
also produces non-empty output — a clean exit with empty stdout/stderr means
the module imported but has no __main__ entry point, which is not proof of a
working CLI (see AC-01: ComfyUI's app/frontend_management.py to see it fail
that exact way).

Usage: python3 -m tools.reclassify_modulemode_v2 [--db PATH] [--dry-run]
"""
import argparse
import os
import sqlite3
import subprocess
import sys

from core.paths.module_root import _project_root, _dotted_module
from core.remediation.classify import classify_failure
from core.remediation.proposal import FailureClass


def _probe(path: str):
    """Returns (verdict, detail). verdict in {"pass", "fail", "no-root"}."""
    root = _project_root(path)
    if not root:
        return "no-root", "no project-root sentinel found"
    dotted = _dotted_module(path, root)
    if not dotted:
        return "no-root", "path not relative to its own derived root"
    try:
        proc = subprocess.run(
            ["python3", "-m", dotted, "--help"],
            capture_output=True, text=True, timeout=8, cwd=root,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return "fail", f"{dotted}: {e}"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return "fail", f"{dotted}: rc={proc.returncode} {out.splitlines()[-1] if out else ''}"
    if not out:
        return "fail", f"{dotted}: rc=0 but empty output (no __main__ entry point — not a real CLI)"
    if "Traceback" in out or "ModuleNotFoundError" in out or "cannot be directly executed" in out:
        return "fail", f"{dotted}: rc=0 but error text in output: {out.splitlines()[-1]}"
    return "pass", f"python -m {dotted} --help (from {root})"


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

    # Scope to exactly the same candidate set the parent ticket (US-REMED-
    # MODULEMODE-01) already proved WRONG_CWD/module-mode-fixable via the
    # error-text-derived dotted name. Do NOT run the path-derived probe
    # against the whole unhealthy fleet — most rows fail for unrelated
    # reasons (missing 3rd-party deps, code bugs, stateful CLIs) and are out
    # of this ticket's scope.
    candidates = []
    for r in rows:
        path = r["path"] or ""
        if not path:
            continue
        proposal = classify_failure(r["slug"], r["description"] or "", path)
        if proposal.failure_class == FailureClass.WRONG_CWD and "python -m" in (proposal.evidence or ""):
            candidates.append(r)

    flips, still_failing, no_root = [], [], []
    for r in candidates:
        path = r["path"] or ""
        verdict, detail = _probe(path)
        if verdict == "pass":
            flips.append((r["slug"], detail))
        elif verdict == "fail":
            still_failing.append((r["slug"], detail))
        else:
            no_root.append((r["slug"], detail))

    print(f"{len(flips)} CLIs proven to pass path-derived module-mode re-probe:")
    for slug, detail in flips:
        print(f"  PASS  {slug}: {detail}")
    print(f"\n{len(still_failing)} still failing (not this fix's problem — real missing dep, code bug, etc.):")
    for slug, detail in still_failing:
        print(f"  FAIL  {slug}: {detail}")
    if no_root:
        print(f"\n{len(no_root)} skipped, no derivable root/dotted path:")
        for slug, detail in no_root:
            print(f"  SKIP  {slug}: {detail}")

    if args.dry_run or not flips:
        return

    conn.executemany(
        "UPDATE cli SET health_status = 'healthy' WHERE slug = ?",
        [(s,) for s, _ in flips],
    )
    conn.commit()
    print(f"\nFlipped {len(flips)} rows to healthy.")


if __name__ == "__main__":
    sys.exit(main())
