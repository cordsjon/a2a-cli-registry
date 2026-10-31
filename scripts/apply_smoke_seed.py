"""Upsert launch_spec.smoke from seed/smoke/<slug>.json. Dry-run unless --apply.

All or nothing: one seed naming a slug the DB does not have, or a row with no
JSON spec to merge into, refuses the whole run. See docs/launch-spec.md.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

DB = os.path.expanduser("~/.hermes/cli-registry.db")
SEED_DIR = Path(__file__).resolve().parents[1] / "seed" / "smoke"


def _merged(con, seed: Path):
    """The row's new launch_spec, or None when it must be refused."""
    row = con.execute("SELECT launch_spec FROM cli WHERE slug = ?", (seed.stem,)).fetchone()
    if row is None:
        print(f"refused {seed.stem}: no such slug", file=sys.stderr)
        return None
    try:
        spec = json.loads(row[0] or "{}")
    except ValueError:
        spec = None
    if not isinstance(spec, dict):
        print(f"refused {seed.stem}: launch_spec is not a JSON object", file=sys.stderr)
        return None
    return {**spec, "smoke": json.loads(seed.read_text())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--seed-dir", type=Path, default=SEED_DIR)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    specs = {seed.stem: _merged(con, seed) for seed in sorted(args.seed_dir.glob("*.json"))}
    if None in specs.values():
        return 1
    for slug, spec in specs.items():
        print(f"{slug:24} {' '.join(spec['smoke']['argv'][1:])}")
    if not args.apply:
        print(f"\nDRY RUN: {len(specs)} seeds, re-run with --apply to write.")
        return 0

    bak = f"{args.db}.bak-pre-smoke-seed"
    shutil.copy2(args.db, bak)
    print(f"backed up -> {bak}")
    with con:
        con.executemany("UPDATE cli SET launch_spec = ? WHERE slug = ?",
                        [(json.dumps(spec), slug) for slug, spec in specs.items()])
    print(f"updated {len(specs)} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
