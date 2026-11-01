"""Refuse a hand smoke that could not catch a regression. Runs each seed for real.

A seed passes when it passes twice in a row, asserts something about the output
that neither --help nor empty output satisfies, and has a 'negative' case: keys
merged over the smoke so the tool still runs cleanly but gives a different answer,
which must fail. A seed that cannot have one states why in 'negative_why'.

Prints {"checked": n, "bad": {slug: [problems]}, "no_negative": [slugs]}. Exit 1 on
any problem. Seeds name private scripts, so they stay out of this public repo.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

from core.prober.prober import _DEFAULT_MAX_OUTPUT_BYTES
from core.prober.smoke import _copy_fixture, _run, _sandboxed, run_smoke

DB = os.path.expanduser("~/.hermes/cli-registry.db")
_DECLARED = {"none", "tmp", "network", "spend"}
_TIMEOUT = 120.0


def _ok(smoke: dict) -> bool:
    return run_smoke({"smoke": smoke}, timeout=_TIMEOUT, allow_network=True) == "pass"


def _help_text(con, slug: str) -> str:
    row = con.execute("SELECT launch_spec FROM cli WHERE slug = ?", (slug,)).fetchone()
    argv = json.loads(row[0] or "{}").get("argv") if row else None
    if not argv:
        return ""
    with tempfile.TemporaryDirectory(prefix="clireg-verify-") as cwd:
        return _run([*argv, "--help"], cwd, 30.0, _DEFAULT_MAX_OUTPUT_BYTES)[1]


def _evidence(smoke: dict) -> str:
    """What the command did, so a refused seed can be debugged without running it by hand."""
    with tempfile.TemporaryDirectory(prefix="clireg-verify-") as cwd:
        if not _copy_fixture(smoke.get("fixture"), cwd):
            return "the fixture could not be copied"
        code, stdout = _run(_sandboxed(smoke, smoke.get("argv") or [], cwd), smoke.get("cwd") or cwd,
                            smoke.get("timeout", _TIMEOUT), _DEFAULT_MAX_OUTPUT_BYTES)
    return f"exit {code}, stdout ends {stdout[-400:]!r}"


def problems(con, slug: str, smoke: dict) -> list:
    found = []
    if smoke.get("side_effects") not in _DECLARED:
        found.append(f"side_effects must be one of {sorted(_DECLARED)}")
    if smoke.get("tier") != "hand":
        found.append("tier must be hand")
    stdout_re, file_re = smoke.get("expect_stdout_re"), smoke.get("expect_file_re")
    if not stdout_re and not file_re:
        return [*found, "asserts no output: needs expect_stdout_re or expect_file_re"]
    for pattern in filter(None, (stdout_re, file_re)):
        try:
            if re.search(pattern, ""):
                found.append(f"regex {pattern!r} matches empty output")
            if re.search(pattern, _help_text(con, slug)):
                found.append(f"regex {pattern!r} matches --help")
        except re.error as exc:
            found.append(f"regex {pattern!r} does not compile: {exc}")
    if found:
        return found
    if not (_ok(smoke) and _ok(smoke)):
        return [f"did not pass twice in a row: {_evidence(smoke)}"]
    negative = smoke.get("negative")
    if not negative:
        if not smoke.get("negative_why"):
            found.append("has neither a negative case nor negative_why")
        return found
    case = {**smoke, **negative}
    bare = {k: v for k, v in case.items() if k not in ("expect_stdout_re", "expect_file_re")}
    if not _ok(bare):
        found.append("negative case did not run cleanly: a crash proves nothing about the regex")
    elif _ok(case):
        found.append("negative case still passes: the assertion does not depend on the answer")
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--seed-dir", type=Path, required=True)
    ap.add_argument("--slug", action="append", default=[], help="only this seed; repeatable")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    seeds = sorted(args.seed_dir.glob("*.json"))
    if args.slug:
        seeds = [s for s in seeds if s.stem in args.slug]
    report: dict = {"checked": len(seeds), "bad": {}, "no_negative": []}
    for seed in seeds:
        smoke = json.loads(seed.read_text())
        found = problems(con, seed.stem, smoke)
        if found:
            report["bad"][seed.stem] = found
        if not smoke.get("negative"):
            report["no_negative"].append(seed.stem)
    print(json.dumps(report, indent=2))
    return 1 if report["bad"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
