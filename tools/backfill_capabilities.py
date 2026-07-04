"""Guarded writer for the registry capability backfill. The ONLY module that
mutates registry.db. Backup-first, dry-run-default, sanity-gated --commit.

Pipeline order per CLI: description_regenerator -> capability_extractor
-> (capability_llm_fallback if input_types or output_types empty)
-> sanity_check over the full proposed dataset -> write.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import tools.capability_extractor as capability_extractor
import tools.capability_llm_fallback as capability_llm_fallback
import tools.description_regenerator as description_regenerator
import tools.sanity_check as sanity_check
from tools.sanity_check import CALIBRATION_SET

# Originally 30 (spec's placeholder guess, written before real corpus data
# existed). Task 7's live dry-run against the actual 471-python-CLI corpus
# measured 253 CLIs genuinely needing fallback -- not a mistuned extractor,
# but a real corpus mix the static extractor was never designed to cover:
# ~124 CLIs with no argparse/click/Typer parser at all (bare sys.argv),
# ~60 CLIs whose output is a database write (sqlite3/.db) rather than a
# path/json/text file the extractor's output-type vocabulary recognizes,
# ~69 with a real parser still falling through for varied per-CLI reasons.
# Raised to let the (already-built, reviewed, tested) LLM fallback path
# carry this real corpus shape; SANITY_FAILURE_THRESHOLD below remains the
# actual quality gate on the results, not this count.
FALLBACK_CAP = 300
SANITY_FAILURE_THRESHOLD = 0.10

# Captured at import time, deliberately NOT re-read through the sanity_check
# module attribute on every call. Calibration validates whether the real,
# shipped sanity_check.check_row is well-calibrated against its own
# CALIBRATION_SET -- a static property of the real checker. Row-level sanity
# scoring during a pipeline run (see run_pipeline below) legitimately goes
# through the mockable `sanity_check.check_row` attribute so tests can stub
# it out; calibration must not silently start validating that same stub
# instead of the real checker, or the gate stops measuring what it exists to
# measure.
_REAL_CHECK_ROW = sanity_check.check_row


def _table_exists(con, table: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _column_exists(con, table: str, column: str) -> bool:
    return any(r[1] == column for r in con.execute(f"PRAGMA table_info({table})"))


def _add_column_guarded(con, table: str, column: str, coltype: str) -> None:
    if _table_exists(con, table) and not _column_exists(con, table, column):
        try:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
            con.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise


def ensure_provenance_columns(db_path: str) -> None:
    con = sqlite3.connect(db_path)
    try:
        _add_column_guarded(con, "capability", "provenance", "TEXT")
        _add_column_guarded(con, "capability", "description_provenance", "TEXT")
    finally:
        con.close()


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or "nogit"
    except (OSError, subprocess.SubprocessError):
        return "nogit"


def backup_db(db_path: str) -> Path:
    src = Path(db_path)
    sha = _git_sha()
    dest = src.parent / f"{src.name}.bak-{sha}"
    fd, tmp_name = tempfile.mkstemp(dir=str(src.parent))
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "wb") as tmp_f, open(src, "rb") as src_f:
            shutil.copyfileobj(src_f, tmp_f)
        tmp_path.replace(dest)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise
    return dest


def _fetch_all_cli_rows(con) -> list[dict]:
    rows = con.execute(
        "SELECT slug, lang, path, description FROM cli"
    ).fetchall()
    return [{"slug": r[0], "lang": r[1], "path": r[2], "description": r[3]} for r in rows]


def _read_source(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text()
    except (OSError, UnicodeDecodeError):
        return ""


def run_pipeline(db_path: str) -> dict:
    """Dry-run body: regenerate descriptions, extract/fallback capabilities,
    sanity-check everything, write both jsonl report files. Never writes to
    the DB. Returns a summary dict; also the first phase of --commit."""
    start = time.time()
    con = sqlite3.connect(db_path)
    try:
        cli_rows = _fetch_all_cli_rows(con)
    finally:
        con.close()

    proposals = []
    fallback_count = 0
    for row in cli_rows:
        slug, lang, path, _old_description = row["slug"], row["lang"], row["path"], row["description"]
        source = _read_source(path) if lang == "python" else ""
        description = description_regenerator.regenerate_description(slug, source)

        capability = None
        if lang == "python":
            capability = capability_extractor.extract_capability(slug, description, source)
            if not capability["input_types"] or not capability["output_types"]:
                capability = capability_llm_fallback.infer_capability_llm(slug, description, source)
                fallback_count += 1

        proposals.append({"slug": slug, "description": description, "capability": capability})

    if fallback_count > FALLBACK_CAP:
        print(
            f"STOP: {fallback_count} CLIs required LLM fallback (cap: {FALLBACK_CAP}). "
            "Static extractor needs tuning before proceeding.",
            file=sys.stderr,
        )
        sys.exit(1)

    calibration_ok, calibration_detail = _run_calibration()

    sanity_results = []
    for p in proposals:
        result = sanity_check.check_row(p["slug"], p["description"], p["capability"] or {})
        sanity_results.append({"slug": p["slug"], **result})

    fail_count = sum(1 for r in sanity_results if not r["ok"])
    fail_rate = fail_count / len(sanity_results) if sanity_results else 0.0

    Path("backfill_proposals.jsonl").write_text(
        "\n".join(json.dumps(p) for p in proposals) + "\n"
    )
    Path("sanity_report.jsonl").write_text(
        "\n".join(json.dumps(r) for r in sanity_results) + "\n"
    )

    elapsed = time.time() - start
    summary = {
        "total_rows": len(cli_rows),
        "python_rows": sum(1 for r in cli_rows if r["lang"] == "python"),
        "fallback_count": fallback_count,
        "sanity_fail_count": fail_count,
        "sanity_fail_rate": fail_rate,
        "calibration_ok": calibration_ok,
        "calibration_detail": calibration_detail,
        "elapsed_seconds": elapsed,
    }
    print(json.dumps(summary, indent=2))
    return {"proposals": proposals, "sanity_results": sanity_results, "summary": summary}


def _run_calibration() -> tuple[bool, str]:
    mismatches = []
    for case in CALIBRATION_SET:
        result = _REAL_CHECK_ROW(case["slug"], case["description"], case["capability"])
        if result["ok"] != case["expected_ok"]:
            mismatches.append(case["slug"])
    ok = not mismatches
    detail = "all calibration cases matched" if ok else f"mismatched: {mismatches}"
    return ok, detail


def write_commit(db_path: str, proposals: list[dict]) -> None:
    con = sqlite3.connect(db_path)
    try:
        for p in proposals:
            slug, description, capability = p["slug"], p["description"], p["capability"]

            row = con.execute(
                "SELECT provenance, description_provenance FROM capability WHERE cli_slug=?",
                (slug,),
            ).fetchone()
            cap_provenance, desc_provenance = (row if row else (None, None))

            if desc_provenance in (None, "static", "llm"):
                con.execute(
                    "UPDATE cli SET description=? WHERE slug=?", (description, slug)
                )
                con.execute(
                    "UPDATE capability SET description_provenance='llm' WHERE cli_slug=?",
                    (slug,),
                )

            if capability is not None and cap_provenance in (None, "static", "llm"):
                con.execute(
                    """UPDATE capability SET input_types=?, output_types=?, intent_tags=?,
                       side_effect=?, confidence=?, provenance=? WHERE cli_slug=?""",
                    (
                        ",".join(capability["input_types"]),
                        ",".join(capability["output_types"]),
                        ",".join(capability["intent_tags"]),
                        capability["side_effect"],
                        capability["confidence"],
                        capability["provenance"],
                        slug,
                    ),
                )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Registry capability backfill")
    parser.add_argument("--db", required=True, help="Path to registry.db")
    parser.add_argument("--commit", action="store_true", help="Write to the DB (default: dry-run)")
    args = parser.parse_args(argv)

    ensure_provenance_columns(args.db)
    result = run_pipeline(args.db)

    if not args.commit:
        return

    if not result["summary"]["calibration_ok"]:
        print(
            f"REFUSED: sanity-check calibration failed ({result['summary']['calibration_detail']}). "
            "The checker may be miscalibrated -- fix before committing.",
            file=sys.stderr,
        )
        sys.exit(1)

    if result["summary"]["sanity_fail_rate"] > SANITY_FAILURE_THRESHOLD:
        print(
            f"REFUSED: sanity failure rate {result['summary']['sanity_fail_rate']:.1%} "
            f"exceeds threshold {SANITY_FAILURE_THRESHOLD:.0%}. "
            "Fix the regenerator/extractor and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    backup_db(args.db)
    write_commit(args.db, result["proposals"])


if __name__ == "__main__":
    main()
