"""Per project, the healthy rows no smoke proves yet: a table, or --json with the
fields backlog_add.py add takes. One story at 10 or more unknown rows, a TODO line
below that.

A not_standalone row is left out: it has no parser, so it can never carry a smoke.
A failing row is listed but not counted: it has a smoke, and it needs a fix.

Prints slugs of private scripts, so the output stays out of this public repo
(DECISIONS Q39).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3

DB = os.path.expanduser("~/.hermes/cli-registry.db")
STORY_THRESHOLD = 10
_NO_PROJECT = "(none)"

_ROWS = """
    SELECT coalesce(project, ?), slug, work_status FROM cli
    WHERE enabled = 1 AND health_status = 'healthy' AND work_status IN ('unknown', 'fail')
    ORDER BY 1, 2"""


def gaps(con) -> dict:
    report: dict = {}
    for project, slug, work in con.execute(_ROWS, (_NO_PROJECT,)):
        report.setdefault(project, {"unknown": [], "fail": []})[work].append(slug)
    return report


def _story(project: str, unknown: list, fail: list) -> dict:
    ac = ["every row in the list has a smoke with tier hand"]
    if fail:
        ac.append(f"these rows pass or carry a named cause: {', '.join(fail)}")
    return {"project": project, "fail": fail,
            "title": f"[{project}] {len(unknown)} registry rows have no smoke",
            "role": "agent choosing a CLI from the registry",
            "want": f"a hand smoke for each of these rows: {', '.join(unknown)}",
            "so_that": "a green row predicts a working call", "ac": ac}


def _todo(project: str, unknown: list, fail: list) -> dict:
    line = f"- TODO: hand smokes for registry rows: {', '.join(unknown) or 'none'}"
    if fail:
        line += f"; fix the failing rows: {', '.join(fail)}"
    return {"project": project, "fail": fail, "line": line}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--json", action="store_true", help="story and TODO fields, not the table")
    args = ap.parse_args(argv)

    report = gaps(sqlite3.connect(args.db))
    if args.json:
        stories, todos = [], []
        for project, rows in report.items():
            if len(rows["unknown"]) >= STORY_THRESHOLD:
                stories.append(_story(project, rows["unknown"], rows["fail"]))
            else:
                todos.append(_todo(project, rows["unknown"], rows["fail"]))
        print(json.dumps({"stories": stories, "todos": todos}, indent=2))
        return 0
    print(f"{'project':32} unknown fail")
    for project, rows in sorted(report.items(), key=lambda kv: -len(kv[1]["unknown"])):
        print(f"{project:32} {len(rows['unknown']):7} {len(rows['fail']):4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
