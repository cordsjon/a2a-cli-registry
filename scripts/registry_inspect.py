"""Read-only recon over a registry DB: coverage, schema drift, path resolution.

Replaces the `python3 - <<PY` blocks that got re-hand-rolled every design recon
against registry.db (profile tag/type coverage, diff the live schema against
core.models, check whether Cli.path rows still resolve on disk).

Three independent sections, selectable with --section:

  coverage  row counts + health/side-effect/confidence breakdowns and the
            capability/tag/type coverage ratios
  schema    live sqlite schema vs the SQLModel metadata in core.models
  paths     do Cli.path values still exist, and (for python CLIs) does a
            `python -m` project root + dotted module still derive from them

The DB is read through a RAW read-only sqlite3 connection, never the ORM. That
is deliberate: the whole point of the schema section is to report a DB missing a
column the model declares (e.g. a pre-migration DB without Cli.fixed_by), and a
`select(Cli)` against such a DB raises OperationalError before anything can be
printed. The inspector has to be able to inspect a DB it cannot ORM-load, so
every section works off PRAGMA/`SELECT` over the columns actually present.

Path math is NOT reimplemented here — it reuses core.paths.module_root, the same
derivation bridge/llm_infer.py and core/remediation/classify.py probe with.

Exit 0 = no findings; 1 = findings (schema drift and/or unresolvable paths) in
the sections that ran; 2 = the DB could not be opened or read.
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from sqlmodel import SQLModel

import core.models  # noqa: F401  (import for its side effect: registers tables)
from core.paths.module_root import _project_root, _dotted_module

SECTIONS = ("coverage", "schema", "paths")


def open_db(db_path: str) -> sqlite3.Connection:
    """Read-only connection. mode=ro so an inspect can never create or mutate.

    A missing file must fail here rather than being silently created as an empty
    DB, which is what a plain sqlite3.connect() would do and what would make an
    inspect of a typo'd path report a fleet of zero CLIs as if that were true.
    """
    if not Path(db_path).is_file():
        raise sqlite3.OperationalError(f"no such DB file: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def model_schema() -> dict[str, set[str]]:
    """{table: {column}} as core.models declares it."""
    return {name: {c.name for c in table.columns}
            for name, table in SQLModel.metadata.tables.items()}


def db_schema(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """{table: {column}} as the live DB actually has it."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'").fetchall()
    out = {}
    for row in rows:
        table = row["name"]
        # Identifier comes from sqlite_master, so it cannot be parameterized;
        # PRAGMA does not accept bind params anyway. Quote it defensively.
        cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        out[table] = {c["name"] for c in cols}
    return out


def schema_diff(live: dict[str, set[str]], model: dict[str, set[str]]) -> dict:
    """Drift between live DB and model, from the model's point of view.

    missing_* is what the model expects and the DB lacks (breaks reads);
    extra_* is what the DB carries and the model dropped (dead weight, and a
    hint that a migration was applied outside core/store/migrations.py).
    """
    diff = {
        "missing_tables": sorted(set(model) - set(live)),
        "extra_tables": sorted(set(live) - set(model)),
        "columns": {},
    }
    for table in sorted(set(model) & set(live)):
        missing = sorted(model[table] - live[table])
        extra = sorted(live[table] - model[table])
        if missing or extra:
            diff["columns"][table] = {"missing": missing, "extra": extra}
    return diff


def schema_has_drift(diff: dict) -> bool:
    return bool(diff["missing_tables"] or diff["extra_tables"] or diff["columns"])


def _breakdown(conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    """value -> count for one column, NULL folded into the literal '<null>'."""
    rows = conn.execute(
        f'SELECT COALESCE("{column}", \'<null>\') AS v, COUNT(*) AS n '
        f'FROM "{table}" GROUP BY v ORDER BY n DESC, v').fetchall()
    return {r["v"]: r["n"] for r in rows}


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def coverage_stats(conn: sqlite3.Connection) -> dict:
    """Fleet size, health/side-effect/confidence mix, and coverage ratios.

    Coverage denominators are the FULL cli count, not the capability-row count:
    a CLI with no capability row at all is the interesting gap, and dividing by
    capability rows would hide exactly those.
    """
    clis = _scalar(conn, "SELECT COUNT(*) FROM cli")
    with_cap = _scalar(conn, "SELECT COUNT(DISTINCT cli_slug) FROM capability")
    stats = {
        "clis": clis,
        "clis_enabled": _scalar(conn, "SELECT COUNT(*) FROM cli WHERE enabled"),
        "clis_not_standalone": _scalar(
            conn, "SELECT COUNT(*) FROM cli WHERE not_standalone"),
        "capability_rows": _scalar(conn, "SELECT COUNT(*) FROM capability"),
        "edges": _scalar(conn, "SELECT COUNT(*) FROM cliedge"),
        "health_status": _breakdown(conn, "cli", "health_status"),
        "lang": _breakdown(conn, "cli", "lang"),
        "side_effect": _breakdown(conn, "capability", "side_effect"),
        "confidence": _breakdown(conn, "capability", "confidence"),
        "coverage": {},
    }
    counts = {
        "capability": with_cap,
        "intent_tags": _scalar(
            conn, "SELECT COUNT(DISTINCT cli_slug) FROM capability "
                  "WHERE intent_tags IS NOT NULL AND intent_tags != ''"),
        "input_types": _scalar(
            conn, "SELECT COUNT(DISTINCT cli_slug) FROM capability "
                  "WHERE input_types IS NOT NULL AND input_types != ''"),
        "output_types": _scalar(
            conn, "SELECT COUNT(DISTINCT cli_slug) FROM capability "
                  "WHERE output_types IS NOT NULL AND output_types != ''"),
        "description": _scalar(
            conn, "SELECT COUNT(*) FROM cli "
                  "WHERE description IS NOT NULL AND description != ''"),
    }
    for key, n in counts.items():
        stats["coverage"][key] = {
            "clis": n,
            "pct": round(100.0 * n / clis, 1) if clis else 0.0,
        }
    return stats


def path_resolution(conn: sqlite3.Connection) -> dict:
    """Do Cli.path rows still point at real files, and still derive a module?

    `unresolved` is the actionable list: a path set but absent on disk. A NULL
    path is counted separately, not flagged — declared-only entries (the
    StubAdapter fleet) legitimately have none.
    """
    rows = conn.execute(
        "SELECT slug, lang, path FROM cli ORDER BY slug").fetchall()
    result = {
        "clis": len(rows),
        "path_null": 0,
        "path_relative": 0,
        "exists": 0,
        "unresolved": [],
        "module_mode_ok": 0,
        "module_mode_undecidable": [],
    }
    for row in rows:
        path = row["path"]
        if not path:
            result["path_null"] += 1
            continue
        if not os.path.isabs(path):
            result["path_relative"] += 1
        if not os.path.exists(path):
            result["unresolved"].append({"slug": row["slug"], "path": path})
            continue
        result["exists"] += 1
        if not path.endswith(".py"):
            continue
        root = _project_root(path)
        dotted = _dotted_module(path, root) if root else None
        if root and dotted:
            result["module_mode_ok"] += 1
        else:
            result["module_mode_undecidable"].append(
                {"slug": row["slug"], "path": path})
    return result


def _print_coverage(stats: dict) -> None:
    print(f"clis={stats['clis']} enabled={stats['clis_enabled']} "
          f"not_standalone={stats['clis_not_standalone']} "
          f"capability_rows={stats['capability_rows']} edges={stats['edges']}")
    for key, cov in stats["coverage"].items():
        print(f"  coverage {key:<13} {cov['clis']:>5} / {stats['clis']} "
              f"({cov['pct']}%)")
    for name in ("health_status", "lang", "side_effect", "confidence"):
        pairs = ", ".join(f"{k}={v}" for k, v in stats[name].items())
        print(f"  {name:<13} {pairs or '-'}")


def _print_schema(diff: dict) -> None:
    if not schema_has_drift(diff):
        print("schema: live DB matches core.models")
        return
    for table in diff["missing_tables"]:
        print(f"DRIFT missing table: {table}")
    for table in diff["extra_tables"]:
        print(f"DRIFT extra table:   {table}")
    for table, cols in diff["columns"].items():
        if cols["missing"]:
            print(f"DRIFT {table}: missing column(s) {', '.join(cols['missing'])}")
        if cols["extra"]:
            print(f"DRIFT {table}: extra column(s) {', '.join(cols['extra'])}")


def _print_paths(paths: dict) -> None:
    print(f"paths: exists={paths['exists']} unresolved={len(paths['unresolved'])} "
          f"null={paths['path_null']} relative={paths['path_relative']} "
          f"module_mode_ok={paths['module_mode_ok']} "
          f"module_mode_undecidable={len(paths['module_mode_undecidable'])}")
    for item in paths["unresolved"]:
        print(f"UNRESOLVED {item['slug']}: {item['path']}")
    for item in paths["module_mode_undecidable"]:
        print(f"NO-MODULE-ROOT {item['slug']}: {item['path']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="registry-inspect", description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="registry.db", help="registry DB to inspect")
    ap.add_argument("--section", action="append", choices=[*SECTIONS, "all"],
                    help="section to run; repeatable (default: all)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    wanted = set(args.section or ["all"])
    sections = SECTIONS if "all" in wanted else tuple(
        s for s in SECTIONS if s in wanted)

    try:
        conn = open_db(args.db)
    except sqlite3.Error as exc:
        print(f"ERROR: cannot open {args.db}: {exc}", file=sys.stderr)
        return 2

    report: dict = {"db": args.db}
    try:
        if "coverage" in sections:
            report["coverage"] = coverage_stats(conn)
        if "schema" in sections:
            report["schema"] = schema_diff(db_schema(conn), model_schema())
        if "paths" in sections:
            report["paths"] = path_resolution(conn)
    except sqlite3.Error as exc:
        # A drifted DB can break the coverage/paths SELECTs. Say which section
        # died instead of a traceback, and point at the section that explains it.
        print(f"ERROR: reading {args.db}: {exc}", file=sys.stderr)
        print("hint: run --section schema to see how the DB differs from the model",
              file=sys.stderr)
        return 2
    finally:
        conn.close()

    findings = 0
    if "schema" in report and schema_has_drift(report["schema"]):
        findings += 1
    if "paths" in report and report["paths"]["unresolved"]:
        findings += 1
    report["findings"] = findings

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if findings else 0

    print(f"registry-inspect: {args.db}")
    if "coverage" in report:
        _print_coverage(report["coverage"])
    if "schema" in report:
        _print_schema(report["schema"])
    if "paths" in report:
        _print_paths(report["paths"])
    print("OK: no findings" if not findings else f"FAIL: {findings} section(s) with findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
