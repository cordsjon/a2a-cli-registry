"""US-CLIREG-HERMES-DISCOVERY-01 AC-05: disable registry rows whose script no
longer exists, with provenance in fixed_by. Dry-run unless --apply. Backs up the
DB on --apply.

Why not populate: populate from the current feed also removes rows the feed has
fallen behind on, including scripts that still exist (6 measured 2026-10-31).
Disabling is reversible, and the next populate with drop_missing_paths removes
these rows for good.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import time

DB = os.path.expanduser("~/.hermes/cli-registry.db")
MAX_FRACTION = 0.30     # same limit as populate's mass-removal breaker


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    total = con.execute("SELECT COUNT(*) FROM cli").fetchone()[0]
    rows = con.execute("SELECT slug, path FROM cli WHERE enabled = 1 AND path LIKE '/%'").fetchall()
    gone = [(slug, path) for slug, path in rows if not os.path.exists(path)]

    print(f"{len(gone)} enabled rows point at a missing path (of {total}):")
    for slug, path in gone:
        print(f"  {slug:40} {path}")

    # An unmounted volume reads as "everything deleted".
    if total and len(gone) / total >= MAX_FRACTION:
        print(f"refusing: {len(gone)}/{total} >= {MAX_FRACTION}; is a volume unmounted?")
        return 2

    if not args.apply:
        print("\nDRY RUN — re-run with --apply to write.")
        return 0

    bak = f"{args.db}.bak-{time.strftime('%Y%m%d-%H%M%S')}-pre-disable-missing"
    shutil.copy2(args.db, bak)
    print(f"backed up -> {bak}")
    provenance = f"disabled:path-missing:{time.strftime('%Y-%m-%d')}"
    con.executemany(
        "UPDATE cli SET enabled = 0, health_status = 'unknown', fixed_by = ? WHERE slug = ?",
        [(provenance, slug) for slug, _path in gone])
    con.commit()
    print(f"disabled {len(gone)} rows, fixed_by={provenance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
