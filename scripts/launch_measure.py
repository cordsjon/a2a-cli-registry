"""Send `<command> --help` for healthy rows through the live gateway, one at a time,
and report which of them launch. Every row is one model call.

Scores on the agent's EXIT= marker, never on gateway status, which says success for
exit 1. The marker is self-reported, so usage_seen records whether the output also
reads like help text. A pass means the row launches, not that it does real work:
that is work_status.

An outage is not a row failure. run_on_gateway never raises, so an open breaker
arrives as status timeout. After MAX_GATEWAY_ERRORS in a row the run stops and the
remaining rows stay unmeasured. The report is rewritten after every row; --resume
keeps the rows that answered and retries the others.

Imports hermes_adapter, so run it with that project's interpreter. The report holds
slugs and output of private scripts, so it stays out of this public repo (DECISIONS Q39).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import random
import re
import sqlite3
import tempfile
import time
from pathlib import Path

DB = os.path.expanduser("~/.hermes/cli-registry.db")
REPORTS = os.path.expanduser("~/.hermes/reports")
METHOD = "_run_step(execute_and_report(env <argv> --help)), serial, EXIT=0"
MAX_GATEWAY_ERRORS = 3
_TAIL_CHARS = 1000
# The row's command was answered for. Anything else says nothing about the row.
_ANSWERED = {"success", "exit_unknown", "denied", "uncomposable"}
_USAGE_RE = re.compile(r"\b(usage|options|commands)\b", re.IGNORECASE)

_ROWS = """
    SELECT slug, launch_spec FROM cli
    WHERE enabled = 1 AND health_status = 'healthy'
    ORDER BY slug"""


def _gateway():
    from hermes_adapter.playbook_routes import _run_step, compose_command
    from hermes_adapter.tools.cli_registry import execute_and_report

    async def run(command: str) -> dict:
        return await _run_step(execute_and_report(command))

    return run, compose_command


def _select(rows: list, slugs: list | None, sample: int | None, seed: int) -> list:
    if slugs:
        return [r for r in rows if r[0] in slugs]
    if sample:
        return random.Random(seed).sample(rows, min(sample, len(rows)))
    return rows


def _row(slug: str, command: str | None, result: dict, seconds: float) -> dict:
    stdout = result.get("stdout") or ""
    return {"slug": slug, "command": command, "status": result.get("status"),
            "exit_code": result.get("exit_code"),
            "passed": result.get("status") == "success" and result.get("exit_code") == 0,
            "usage_seen": bool(_USAGE_RE.search(stdout)),
            "seconds": round(seconds, 1), "tail": stdout[-_TAIL_CHARS:],
            "error": result.get("error") or result.get("reason")}


def _write(out: Path, report: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.")
    with os.fdopen(fd, "w") as f:
        json.dump(report, f, indent=1)
    Path(tmp).replace(out)


async def _measure(rows: list, report: dict, out: Path, run, compose) -> None:
    errors = 0
    for slug, spec in rows:
        started = time.monotonic()
        command = compose(json.loads(spec))
        if command is None:
            result = {"status": "uncomposable", "error": "launch_spec composes no command"}
        else:
            command += " --help"
            result = await run(command)
        row = _row(slug, command, result, time.monotonic() - started)
        report["rows"].append(row)
        print(f"{'pass' if row['passed'] else 'FAIL'} {row['status']} {row['seconds']}s {slug}",
              flush=True)
        errors = 0 if row["status"] in _ANSWERED else errors + 1
        if errors >= MAX_GATEWAY_ERRORS:
            report["stopped"] = f"{errors} gateway errors in a row, last: {row['error']}"
        _write(out, report)
        if report["stopped"]:
            return


def main(argv: list | None = None, gateway=_gateway) -> int:
    today = datetime.date.today().isoformat()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=DB)
    parser.add_argument("--out", default=os.path.join(REPORTS, f"cli-registry-launch-{today}.json"))
    parser.add_argument("--sample", type=int, help="measure this many rows, drawn by --seed")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--slug", action="append", help="measure this row; repeatable")
    parser.add_argument("--resume", action="store_true",
                        help="keep the rows in --out that answered, retry the others")
    args = parser.parse_args(argv)

    con = sqlite3.connect(args.db)
    try:
        rows = _select(con.execute(_ROWS).fetchall(), args.slug, args.sample, args.seed)
    finally:
        con.close()

    out = Path(args.out)
    report = {"date": today, "method": METHOD, "sample_seed": args.seed if args.sample else None,
              "stopped": None, "rows": []}
    if args.resume and out.exists():
        kept = json.loads(out.read_text())["rows"]
        report["rows"] = [r for r in kept if r["status"] in _ANSWERED]
        done = {r["slug"] for r in report["rows"]}
        rows = [r for r in rows if r[0] not in done]

    run, compose = gateway()
    asyncio.run(_measure(rows, report, out, run, compose))
    _write(out, report)

    passed = sum(r["passed"] for r in report["rows"])
    print(f"{passed} of {len(report['rows'])} passed; report: {out}")
    if report["stopped"]:
        print(f"STOPPED: {report['stopped']}")
        return 2
    return 0 if passed == len(report["rows"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
