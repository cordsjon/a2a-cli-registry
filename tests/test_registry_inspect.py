import json
import sqlite3

import pytest
from sqlmodel import SQLModel, Session, create_engine

from core.models import Capability, Cli, CliEdge
from scripts.registry_inspect import (
    coverage_stats,
    db_schema,
    main as inspect_main,
    model_schema,
    open_db,
    path_resolution,
    schema_diff,
    schema_has_drift,
)


@pytest.fixture
def db_file(tmp_path):
    """A real on-disk registry DB. Not the in-memory `db` fixture: the inspector
    opens its own read-only sqlite3 connection by path, so the seam under test
    (a file the ORM wrote) has to actually be a file."""
    path = tmp_path / "registry.db"
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)

    def seed(*rows):
        with Session(engine) as session:
            for row in rows:
                session.add(row)
            session.commit()

    return path, seed


def test_open_db_refuses_a_missing_file(tmp_path):
    """A typo'd --db must fail, not be created as an empty DB and reported as a
    fleet of zero."""
    missing = tmp_path / "nope.db"
    with pytest.raises(sqlite3.OperationalError):
        open_db(str(missing))
    assert not missing.exists()


def test_open_db_is_read_only(db_file):
    path, _seed = db_file
    conn = open_db(str(path))
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM cli")
    conn.close()


def test_schema_diff_is_clean_for_a_freshly_created_db(db_file):
    path, _seed = db_file
    conn = open_db(str(path))
    diff = schema_diff(db_schema(conn), model_schema())
    conn.close()
    assert not schema_has_drift(diff), diff


def test_schema_diff_reports_a_column_the_model_added(tmp_path):
    """The real drift case: a pre-migration DB without Cli.fixed_by.

    This is also why the inspector must not read through the ORM — a select(Cli)
    against this DB raises before any diff could be printed.
    """
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE cli (slug TEXT PRIMARY KEY, lang TEXT)")
    conn.commit()
    conn.close()

    ro = open_db(str(path))
    diff = schema_diff(db_schema(ro), model_schema())
    ro.close()

    assert schema_has_drift(diff)
    assert "fixed_by" in diff["columns"]["cli"]["missing"]
    assert "capability" in diff["missing_tables"]


def test_schema_diff_reports_a_table_the_model_dropped(db_file):
    path, _seed = db_file
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE leftover (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    ro = open_db(str(path))
    diff = schema_diff(db_schema(ro), model_schema())
    ro.close()
    assert diff["extra_tables"] == ["leftover"]


def test_coverage_denominator_is_all_clis_not_capability_rows(db_file):
    """A CLI with no capability row at all is the gap worth seeing, so it has to
    stay in the denominator."""
    path, seed = db_file
    seed(
        Cli(slug="a", lang="python", description="does a thing"),
        Cli(slug="b", lang="python"),
        Capability(cli_slug="a", intent_tags="convert", input_types="pdf",
                   output_types="text", side_effect="writes-fs",
                   confidence="inferred"),
    )
    conn = open_db(str(path))
    stats = coverage_stats(conn)
    conn.close()

    assert stats["clis"] == 2
    assert stats["capability_rows"] == 1
    assert stats["coverage"]["capability"] == {"clis": 1, "pct": 50.0}
    assert stats["coverage"]["intent_tags"] == {"clis": 1, "pct": 50.0}
    assert stats["coverage"]["description"] == {"clis": 1, "pct": 50.0}
    assert stats["side_effect"] == {"writes-fs": 1}
    assert stats["confidence"] == {"inferred": 1}


def test_coverage_counts_empty_strings_as_uncovered(db_file):
    """intent_tags defaults to '' (not NULL), so an empty CSV must not count as
    coverage — the default value would otherwise report 100%."""
    path, seed = db_file
    seed(Cli(slug="a", lang="python"), Capability(cli_slug="a"))
    conn = open_db(str(path))
    stats = coverage_stats(conn)
    conn.close()
    assert stats["coverage"]["capability"]["clis"] == 1
    assert stats["coverage"]["intent_tags"]["clis"] == 0
    assert stats["coverage"]["output_types"]["clis"] == 0


def test_coverage_on_an_empty_db_does_not_divide_by_zero(db_file):
    path, _seed = db_file
    conn = open_db(str(path))
    stats = coverage_stats(conn)
    conn.close()
    assert stats["clis"] == 0
    assert stats["coverage"]["intent_tags"] == {"clis": 0, "pct": 0.0}


def test_coverage_counts_edges_and_health_breakdown(db_file):
    path, seed = db_file
    seed(
        Cli(slug="a", lang="python", health_status="healthy"),
        Cli(slug="b", lang="shell", health_status="unhealthy",
            not_standalone=True, enabled=False),
        CliEdge(from_slug="a", to_slug="b", via_type="text"),
    )
    conn = open_db(str(path))
    stats = coverage_stats(conn)
    conn.close()
    assert stats["edges"] == 1
    assert stats["clis_enabled"] == 1
    assert stats["clis_not_standalone"] == 1
    assert stats["health_status"] == {"healthy": 1, "unhealthy": 1}
    assert stats["lang"] == {"python": 1, "shell": 1}


def test_path_resolution_flags_only_paths_that_are_set_but_absent(db_file, tmp_path):
    """A NULL path is a declared-only entry, not a defect — it must not be
    flagged alongside a path that points at a file which is gone."""
    path, seed = db_file
    real = tmp_path / "real.py"
    real.write_text("print(1)\n")
    seed(
        Cli(slug="present", lang="python", path=str(real)),
        Cli(slug="gone", lang="python", path=str(tmp_path / "vanished.py")),
        Cli(slug="declared", lang="shell", path=None),
    )
    conn = open_db(str(path))
    result = path_resolution(conn)
    conn.close()

    assert result["exists"] == 1
    assert result["path_null"] == 1
    assert result["unresolved"] == [
        {"slug": "gone", "path": str(tmp_path / "vanished.py")}]


def test_path_resolution_reports_module_mode_from_the_shared_derivation(
        db_file, tmp_path):
    """module-mode is decidable only under a project-root sentinel; the check
    reuses core.paths.module_root rather than its own path math."""
    path, seed = db_file
    pkg = tmp_path / "proj" / "pkg"
    pkg.mkdir(parents=True)
    (tmp_path / "proj" / "pyproject.toml").write_text("")
    rooted = pkg / "tool.py"
    rooted.write_text("print(1)\n")

    orphan_dir = tmp_path / "orphan"
    orphan_dir.mkdir()
    orphan = orphan_dir / "loose.py"
    orphan.write_text("print(1)\n")

    seed(
        Cli(slug="rooted", lang="python", path=str(rooted)),
        Cli(slug="orphan", lang="python", path=str(orphan)),
    )
    conn = open_db(str(path))
    result = path_resolution(conn)
    conn.close()

    assert result["module_mode_ok"] == 1
    assert [i["slug"] for i in result["module_mode_undecidable"]] == ["orphan"]


def test_path_resolution_ignores_non_python_paths_for_module_mode(db_file, tmp_path):
    path, seed = db_file
    script = tmp_path / "run.sh"
    script.write_text("#!/bin/sh\n")
    seed(Cli(slug="sh", lang="shell", path=str(script)))
    conn = open_db(str(path))
    result = path_resolution(conn)
    conn.close()
    assert result["exists"] == 1
    assert result["module_mode_ok"] == 0
    assert result["module_mode_undecidable"] == []


def test_cli_exits_zero_on_a_clean_db(db_file, capsys):
    path, seed = db_file
    seed(Cli(slug="a", lang="python"))
    assert inspect_main(["--db", str(path)]) == 0
    out = capsys.readouterr().out
    assert "schema: live DB matches core.models" in out
    assert "OK: no findings" in out


def test_cli_exits_one_on_unresolved_paths(db_file, tmp_path, capsys):
    path, seed = db_file
    seed(Cli(slug="gone", lang="python", path=str(tmp_path / "vanished.py")))
    assert inspect_main(["--db", str(path)]) == 1
    assert "UNRESOLVED gone" in capsys.readouterr().out


def test_cli_missing_db_exits_two(tmp_path, capsys):
    assert inspect_main(["--db", str(tmp_path / "nope.db")]) == 2
    assert "cannot open" in capsys.readouterr().err


def test_cli_section_selection_runs_only_that_section(db_file, capsys):
    path, seed = db_file
    seed(Cli(slug="a", lang="python"))
    assert inspect_main(["--db", str(path), "--section", "coverage"]) == 0
    out = capsys.readouterr().out
    assert "coverage intent_tags" in out
    assert "schema:" not in out
    assert "paths:" not in out


def test_cli_json_mode_emits_the_whole_report(db_file, capsys):
    path, seed = db_file
    seed(Cli(slug="a", lang="python"))
    assert inspect_main(["--db", str(path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["findings"] == 0
    assert set(report) >= {"coverage", "schema", "paths", "db"}


def test_cli_on_a_drifted_db_reports_drift_instead_of_a_traceback(tmp_path, capsys):
    """The coverage SELECTs cannot survive a pre-migration DB; the tool must
    still exit cleanly and point at the section that explains why."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE cli (slug TEXT PRIMARY KEY, lang TEXT)")
    conn.commit()
    conn.close()

    assert inspect_main(["--db", str(path), "--section", "schema"]) == 1
    assert "DRIFT" in capsys.readouterr().out

    assert inspect_main(["--db", str(path), "--section", "coverage"]) == 2
    assert "hint: run --section schema" in capsys.readouterr().err
