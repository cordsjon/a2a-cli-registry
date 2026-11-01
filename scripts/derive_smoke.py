"""Derive launch_spec.smoke seeds from what a row's own --help offers.

Tier 'version': a healthy python row whose --help lists --version gets --version
as its smoke. That proves import plus entry, and the tier says so. Runs each row's
--help serially, then writes one seed per row for apply_smoke_seed.py --seed-dir.

Tier 'project-tests': a row whose repo has a test file importing or naming its
script gets that file as its smoke. Collects but runs no test here. The seeds are
held behind --allow-network, and 15_belegfluss is left out (DECISIONS Q41).

Seeds are gitignored: they regenerate from the DB, and this repo is public while
their argv name private scripts (DECISIONS Q39).
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from bridge.enrich_feed import _atomic_write_json
from core.prober.prober import _DEFAULT_MAX_OUTPUT_BYTES
from core.prober.smoke import _run

DB = os.path.expanduser("~/.hermes/cli-registry.db")
OUT = Path(__file__).resolve().parents[1] / "seed" / "smoke" / "derived"

_ROWS = """
    SELECT slug, path, launch_spec FROM cli
    WHERE enabled = 1 AND health_status = 'healthy' AND json_valid(launch_spec)
      AND json_extract(launch_spec, '$.kind') = 'python_module'
      AND json_extract(launch_spec, '$.smoke') IS NULL
    ORDER BY slug"""
# '[' for a usage-only line. The lookahead refuses '--version VERSION', a filter
# on list_nvidia_tools_downloads: one space then a metavar means it takes a value.
_VERSION_FLAG = re.compile(r"(^|[\s\[])--version(?=\]|[ \t]{2,}|[ \t]*$)", re.M)
_FROZEN_REPOS = {"15_belegfluss"}
_PROJECT_TEST_TIMEOUT = 180


def _offers_version(argv: list, timeout: float) -> bool:
    with tempfile.TemporaryDirectory(prefix="clireg-derive-") as cwd:
        code, stdout = _run([*argv, "--help"], cwd, timeout, _DEFAULT_MAX_OUTPUT_BYTES)
    return code == 0 and bool(_VERSION_FLAG.search(stdout))


def derive_version(con, out: Path, timeout: float) -> dict:
    counts = {"rows": 0, "seeded": 0}
    for slug, _, launch_spec in con.execute(_ROWS).fetchall():
        counts["rows"] += 1
        argv = json.loads(launch_spec).get("argv")
        if not argv or not _offers_version(argv, timeout):
            continue
        _atomic_write_json(out / f"{slug}.json",
                           {"argv": [*argv, "--version"], "expect_exit": 0,
                            "side_effects": "none", "tier": "version", "timeout": 30})
        counts["seeded"] += 1
    return counts


def _git(cwd, *args) -> str:
    """stdout, empty when git refuses: not a repo, a gone cwd, or a grep with no hit."""
    try:
        proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                              timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _names_script(text: str, rel: Path, unique: bool) -> bool:
    """Does this test source import or name the script? A stem shared with another
    file in the repo says nothing, so only the full path or module counts then."""
    forms = [re.escape(rel.as_posix()), rf"\b{re.escape('.'.join(rel.with_suffix('').parts))}\b"]
    if unique:
        stem = re.escape(rel.stem)
        forms += [rf"^\s*(?:from|import)\s+{stem}\b",
                  rf"^\s*from\s+[\w.]+\s+import\s+.*\b{stem}\b",
                  rf"\b{stem}\.py\b"]
    return re.search("|".join(forms), text, re.M) is not None


def _test_file(root: Path, rel: Path):
    """The test file to run for this script, or None. test_<stem>.py wins."""
    hits = _git(root, "grep", "-l", "--fixed-strings", rel.stem, "--", "tests/**", "test/**")
    tests = [h for h in hits.splitlines()
             if Path(h).name.endswith("_test.py") or Path(h).name.startswith("test_")]
    unique = len(_git(root, "ls-files", "--", f":(glob)**/{rel.stem}.py").splitlines()) <= 1
    for test in sorted(tests, key=lambda h: (Path(h).name != f"test_{rel.stem}.py", h)):
        try:
            if _names_script((root / test).read_text(errors="replace"), rel, unique):
                return test
        except OSError:
            continue        # tracked, but gone from a checkout someone is editing
    return None


@functools.lru_cache(maxsize=None)
def _has_pytest(python: str, timeout: float) -> bool:
    with tempfile.TemporaryDirectory(prefix="clireg-derive-") as cwd:
        return _run([python, "-c", "import pytest"], cwd, timeout, _DEFAULT_MAX_OUTPUT_BYTES)[0] == 0


def _all_deselected(python: str, root: Path, test: str) -> bool:
    """pytest exit 5: the project's config selects nothing here, so the smoke would
    read as a broken row. A collection error stays a seed: that one is a real fail."""
    code, _ = _run([python, "-B", "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", test],
                   str(root), _PROJECT_TEST_TIMEOUT, _DEFAULT_MAX_OUTPUT_BYTES)
    return code == 5


def derive_project_tests(con, out: Path, timeout: float) -> dict:
    counts = {"rows": 0, "seeded": 0, "not_in_git": 0, "frozen": 0, "no_test": 0, "no_pytest": 0,
              "no_selected": 0}
    for slug, path, launch_spec in con.execute(_ROWS).fetchall():
        counts["rows"] += 1
        real = Path(path or "").resolve()
        top = _git(real.parent, "rev-parse", "--show-toplevel").strip()
        if not top:
            counts["not_in_git"] += 1
            continue
        root = Path(top).resolve()
        if root.name in _FROZEN_REPOS:
            counts["frozen"] += 1
            continue
        test = _test_file(root, real.relative_to(root))
        if not test:
            counts["no_test"] += 1
            continue
        argv = json.loads(launch_spec).get("argv")
        if not argv or not _has_pytest(argv[0], timeout):
            counts["no_pytest"] += 1
            continue
        if _all_deselected(argv[0], root, test):
            counts["no_selected"] += 1
            continue
        # -B and no cacheprovider: this runs in a checkout other sessions are editing.
        # The regex: pytest also exits 0 when every test is skipped.
        _atomic_write_json(out / f"{slug}.json",
                           {"argv": [argv[0], "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", test],
                            "cwd": str(root), "expect_exit": 0, "expect_stdout_re": r"\d+ passed",
                            "side_effects": "project-tests", "tier": "project-tests",
                            "timeout": _PROJECT_TEST_TIMEOUT})
        counts["seeded"] += 1
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", required=True, choices=["version", "project-tests"])
    ap.add_argument("--db", default=DB)
    ap.add_argument("--out", type=Path, help="default: seed/smoke/derived, project-tests in a subdirectory")
    ap.add_argument("--timeout", type=float, default=15.0, help="seconds per --help or pytest check")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    if args.tier == "version":
        counts = derive_version(con, args.out or OUT, args.timeout)
    else:
        counts = derive_project_tests(con, args.out or OUT / "project-tests", args.timeout)
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
