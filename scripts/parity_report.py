"""Grade each in-scope registry row against the five HiQual gates and summarize.

A row is in scope when it is enabled, its health_status is not not_standalone or
retired, and its launch_spec is a JSON object. The `install:<url>` placeholder
specs are not JSON, so they fall out of scope instead of crashing the run.

  H1 classified  health_status == 'healthy'
  H2 proven      work_status == 'pass', smoke.tier == 'hand', smoke has negative or negative_why
  H3 watched     work_checked_at is less than 8 days old
  H4 real work   a2a_invokable == 0, or smoke.proves is a non-empty string
  H5 wired       the consumer index lists a consumer, or launch_spec.operator_run is true

--consumers reads a JSON index {slug: [consumer file paths]}. A missing file means
no row has a consumer, so H5 holds only for operator_run rows.

The DB is opened read-only. --out writes the markdown report; it names slugs of
private scripts, so keep it out of this public repo (DECISIONS Q39).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

DB = os.path.expanduser("~/.hermes/cli-registry.db")
GATES = ("H1", "H2", "H3", "H4", "H5")
_OUT_OF_SCOPE = {"not_standalone", "retired"}
_FRESH_SECONDS = 8 * 86400


def _spec(row: dict) -> dict | None:
    try:
        spec = json.loads(row.get("launch_spec") or "")
    except json.JSONDecodeError:
        return None
    return spec if isinstance(spec, dict) else None


def in_scope(row: dict) -> bool:
    return (bool(row.get("enabled")) and row.get("health_status") not in _OUT_OF_SCOPE
            and _spec(row) is not None)


def grade(row: dict, consumers: list[str] | None, now: float) -> dict[str, bool]:
    spec = _spec(row) or {}
    smoke = spec.get("smoke")
    smoke = smoke if isinstance(smoke, dict) else {}
    proves = smoke.get("proves")
    checked = row.get("work_checked_at")
    return {
        "H1": row.get("health_status") == "healthy",
        "H2": (row.get("work_status") == "pass" and smoke.get("tier") == "hand"
               and bool(smoke.get("negative") or smoke.get("negative_why"))),
        "H3": checked is not None and now - float(checked) < _FRESH_SECONDS,
        "H4": not row.get("a2a_invokable") or (isinstance(proves, str) and bool(proves.strip())),
        "H5": bool(consumers) or spec.get("operator_run") is True,
    }


def summarize(rows: list[dict], consumers: dict[str, list[str]], now: float) -> dict:
    fails = dict.fromkeys(GATES, 0)
    failing: dict[str, list[str]] = {}
    scoped = [r for r in rows if in_scope(r)]
    for row in scoped:
        missed = [g for g, ok in grade(row, consumers.get(row["slug"]), now).items() if not ok]
        for gate in missed:
            fails[gate] += 1
        if missed:
            failing[row["slug"]] = missed
    return {"in_scope": len(scoped), "parity": len(scoped) - len(failing),
            "fails": fails, "failing": failing}


def markdown(summary: dict) -> str:
    totals = " · ".join(f"{g} {summary['fails'][g]}" for g in GATES)
    lines = [f"parity {summary['parity']}/{summary['in_scope']} · {totals}", "",
             "| slug | fails |", "|---|---|"]
    lines += [f"| {slug} | {', '.join(gates)} |" for slug, gates in sorted(summary["failing"].items())]
    return "\n".join(lines) + "\n"


def _rows(db: str) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM cli")]
    finally:
        con.close()


def _consumers(path: str | None) -> dict[str, list[str]]:
    if path is None or not Path(path).is_file():
        return {}
    return json.loads(Path(path).read_text())


def _write(out: Path, text: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    Path(tmp).replace(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--consumers", help="JSON index {slug: [consumer paths]}")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    ap.add_argument("--out", type=Path, help="write the markdown report here")
    args = ap.parse_args(argv)

    summary = summarize(_rows(args.db), _consumers(args.consumers), time.time())
    report = markdown(summary)
    if args.out:
        _write(args.out, report)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
