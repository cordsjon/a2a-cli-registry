"""US-CLIAUDIT-83 AC-03: re-evaluate every registry row's source file with the
ast classifier and set not_standalone + health_status='not_standalone' for the
two false-positive classes. Dry-run unless --apply. Backs up the DB on --apply.

NO pip install, NO edit to any target CLI — pure reclassification.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3

from bridge.standalone import classify_standalone

DB = os.path.expanduser("~/.hermes/cli-registry.db")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    # Precision guard (do-no-harm): NEVER demote a currently-healthy row. A
    # healthy probe is ground truth that the CLI actually runs standalone — it
    # outranks any static heuristic. AC-03 targets the false-positive UNHEALTHY/
    # unknown rows, not working CLIs. Scoping here, not in the classifier,
    # because the classifier is also used at feed-build where no probe exists.
    rows = con.execute(
        "SELECT slug, path, health_status FROM cli "
        "WHERE enabled = 1 AND health_status != 'healthy'"
    ).fetchall()

    to_flag = []
    for r in rows:
        path = r["path"]
        if not path:
            continue
        cls = classify_standalone(path)
        if cls != "standalone":
            to_flag.append((r["slug"], cls, r["health_status"]))

    print(f"{len(to_flag)} rows classify as not-standalone "
          f"(of {len(rows)} enabled):")
    by_class = {}
    for slug, cls, old in to_flag:
        by_class.setdefault(cls, 0)
        by_class[cls] += 1
    for cls, n in sorted(by_class.items()):
        print(f"  {cls}: {n}")

    if not args.apply:
        print("\nDRY RUN — re-run with --apply to write. Sample:")
        for slug, cls, old in to_flag[:15]:
            print(f"  {slug:40} {old:12} -> not_standalone ({cls})")
        return 0

    bak = f"{args.db}.bak-pre-reeval-notstandalone"
    shutil.copy2(args.db, bak)
    print(f"backed up -> {bak}")
    cur = con.cursor()
    for slug, cls, _old in to_flag:
        cur.execute(
            "UPDATE cli SET not_standalone = 1, health_status = 'not_standalone' WHERE slug = ?",
            (slug,),
        )
    con.commit()
    print(f"updated {len(to_flag)} rows.")
    # report the new distribution
    for hs, n in con.execute(
        "SELECT health_status, COUNT(*) FROM cli GROUP BY 1 ORDER BY 1"
    ):
        print(f"  {hs}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
