"""Derive launch_spec.smoke seeds from what a row's own --help offers.

Tier 'version': a healthy python row whose --help lists --version gets --version
as its smoke. That proves import plus entry, and the tier says so. Runs each row's
--help serially, then writes one seed per row for apply_smoke_seed.py --seed-dir.

Seeds are gitignored: they regenerate from the DB, and this repo is public while
their argv name private scripts (DECISIONS Q39). Rows under the Consigliere hold
are never selected, so they never run.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

from bridge.enrich_feed import _atomic_write_json
from core.prober.prober import _DEFAULT_MAX_OUTPUT_BYTES
from core.prober.smoke import _run

DB = os.path.expanduser("~/.hermes/cli-registry.db")
OUT = Path(__file__).resolve().parents[1] / "seed" / "smoke" / "derived"

# coalesce: a NULL project makes the LIKE NULL, and NOT NULL would drop the row.
_VERSION_ROWS = """
    SELECT slug, launch_spec FROM cli
    WHERE enabled = 1 AND health_status = 'healthy' AND json_valid(launch_spec)
      AND json_extract(launch_spec, '$.kind') = 'python_module'
      AND json_extract(launch_spec, '$.smoke') IS NULL
      AND NOT (coalesce(path, '') LIKE '%CONSIGLIERE%'
               OR lower(coalesce(project, '')) LIKE '%consigliere%')
    ORDER BY slug"""
# '[' for a usage-only line. The lookahead refuses '--version VERSION', a filter
# on list_nvidia_tools_downloads: one space then a metavar means it takes a value.
_VERSION_FLAG = re.compile(r"(^|[\s\[])--version(?=\]|[ \t]{2,}|[ \t]*$)", re.M)


def _offers_version(argv: list, timeout: float) -> bool:
    with tempfile.TemporaryDirectory(prefix="clireg-derive-") as cwd:
        code, stdout = _run([*argv, "--help"], cwd, timeout, _DEFAULT_MAX_OUTPUT_BYTES)
    return code == 0 and bool(_VERSION_FLAG.search(stdout))


def derive_version(con, out: Path, timeout: float) -> dict:
    counts = {"rows": 0, "seeded": 0}
    for slug, launch_spec in con.execute(_VERSION_ROWS).fetchall():
        counts["rows"] += 1
        argv = json.loads(launch_spec).get("argv")
        if not argv or not _offers_version(argv, timeout):
            continue
        _atomic_write_json(out / f"{slug}.json",
                           {"argv": [*argv, "--version"], "expect_exit": 0,
                            "side_effects": "none", "tier": "version", "timeout": 30})
        counts["seeded"] += 1
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", required=True, choices=["version"])
    ap.add_argument("--db", default=DB)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--timeout", type=float, default=15.0, help="seconds per --help")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    print(json.dumps(derive_version(con, args.out, args.timeout)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
