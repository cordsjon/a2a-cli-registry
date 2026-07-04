import json
import sqlite3

import pytest

import tools.backfill_capabilities as backfill


def _make_drifted_db(path):
    """Mirrors the LIVE registry.db schema exactly, including the missing
    not_standalone column and missing provenance/description_provenance
    columns on capability -- built with raw sqlite3.executescript, NOT
    SQLModel.metadata.create_all, so this fixture reproduces the real
    production drift condition."""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE cli (
            slug VARCHAR NOT NULL,
            lang VARCHAR NOT NULL,
            bucket VARCHAR,
            project VARCHAR,
            path VARCHAR,
            launch_spec VARCHAR NOT NULL,
            description VARCHAR NOT NULL,
            source_class VARCHAR,
            health_cmd VARCHAR,
            health_status VARCHAR NOT NULL,
            health_checked_at FLOAT,
            fixed_by VARCHAR,
            enabled BOOLEAN NOT NULL,
            a2a_invokable BOOLEAN NOT NULL,
            source_run_id VARCHAR,
            last_seen_at FLOAT,
            updated_at FLOAT,
            PRIMARY KEY (slug)
        );
        CREATE TABLE capability (
            id INTEGER NOT NULL,
            cli_slug VARCHAR NOT NULL,
            intent_tags VARCHAR NOT NULL,
            input_types VARCHAR NOT NULL,
            output_types VARCHAR NOT NULL,
            side_effect VARCHAR NOT NULL,
            confidence VARCHAR NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(cli_slug) REFERENCES cli (slug)
        );
        """
    )
    con.execute(
        "INSERT INTO cli VALUES ('csv2json','python',NULL,NULL,'/tmp/csv2json.py','{}','30_x/csv2json.py',NULL,NULL,'unknown',NULL,NULL,1,0,NULL,NULL,NULL)"
    )
    con.execute(
        "INSERT INTO capability (cli_slug, intent_tags, input_types, output_types, side_effect, confidence) VALUES ('csv2json','','','','unknown','declared')"
    )
    con.execute(
        "INSERT INTO cli VALUES ('shellwrap','shell',NULL,NULL,'/usr/local/bin/shellwrap','{}','Traceback: crashed',NULL,NULL,'unknown',NULL,NULL,1,0,NULL,NULL,NULL)"
    )
    con.execute(
        "INSERT INTO capability (cli_slug, intent_tags, input_types, output_types, side_effect, confidence) VALUES ('shellwrap','','','','unknown','declared')"
    )
    con.commit()
    con.close()


@pytest.fixture
def drifted_db(tmp_path):
    db_path = str(tmp_path / "registry.db")
    _make_drifted_db(db_path)
    return db_path


def _patch_pipeline(monkeypatch, cap_result=None, desc_result="A test CLI that converts things.", sanity_ok=True):
    import tools.capability_extractor as extractor
    import tools.description_regenerator as regen
    import tools.sanity_check as sanity

    monkeypatch.setattr(regen, "regenerate_description", lambda slug, source: desc_result)
    monkeypatch.setattr(
        extractor, "extract_capability",
        lambda slug, description, source: cap_result or {
            "input_types": ["path"], "output_types": ["json"], "intent_tags": ["convert"],
            "side_effect": "none", "confidence": "inferred", "provenance": "static",
        },
    )
    monkeypatch.setattr(sanity, "check_row", lambda slug, description, capability: {"ok": sanity_ok, "reason": ""})


def test_dry_run_writes_proposals_and_zero_db_changes(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    summary = backfill.run_pipeline(drifted_db)
    assert (tmp_path / "backfill_proposals.jsonl").exists()
    assert (tmp_path / "sanity_report.jsonl").exists()
    con = sqlite3.connect(drifted_db)
    row = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    con.close()
    assert row[0] == "30_x/csv2json.py"  # unchanged -- dry-run never writes


def test_commit_updates_capability_and_description_and_creates_backup(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    backfill.main(["--db", drifted_db, "--commit"])
    con = sqlite3.connect(drifted_db)
    row = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    cap = con.execute("SELECT input_types, output_types, provenance FROM capability WHERE cli_slug='csv2json'").fetchone()
    con.close()
    assert row[0] == "A test CLI that converts things."
    assert cap[0] == "path"
    assert cap[1] == "json"
    assert cap[2] == "static"
    backups = list(tmp_path.glob("registry.db.bak-*")) + [p for p in __import__("pathlib").Path(drifted_db).parent.glob("*.bak-*")]
    assert backups


def test_manual_capability_provenance_protected_independently_of_description(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    backfill.ensure_provenance_columns(drifted_db)
    con = sqlite3.connect(drifted_db)
    con.execute("UPDATE capability SET provenance='manual', input_types='manual-path' WHERE cli_slug='csv2json'")
    con.commit()
    con.close()

    backfill.main(["--db", drifted_db, "--commit"])

    con = sqlite3.connect(drifted_db)
    cap = con.execute("SELECT input_types, provenance FROM capability WHERE cli_slug='csv2json'").fetchone()
    desc = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    con.close()
    assert cap[0] == "manual-path"  # capability protected
    assert cap[1] == "manual"
    assert desc[0] == "A test CLI that converts things."  # description still refreshed


def test_manual_description_provenance_protected_independently_of_capability(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    backfill.ensure_provenance_columns(drifted_db)
    con = sqlite3.connect(drifted_db)
    con.execute("UPDATE capability SET description_provenance='manual' WHERE cli_slug='csv2json'")
    con.execute("UPDATE cli SET description='Hand-written accurate description.' WHERE slug='csv2json'")
    con.commit()
    con.close()

    backfill.main(["--db", drifted_db, "--commit"])

    con = sqlite3.connect(drifted_db)
    desc = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    cap = con.execute("SELECT input_types FROM capability WHERE cli_slug='csv2json'").fetchone()
    con.close()
    assert desc[0] == "Hand-written accurate description."  # description protected
    assert cap[0] == "path"  # capability still refreshed


def test_backup_failure_aborts_write(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)

    def fail_backup(db_path):
        raise OSError("disk full")
    monkeypatch.setattr(backfill, "backup_db", fail_backup)

    with pytest.raises(OSError):
        backfill.main(["--db", drifted_db, "--commit"])

    con = sqlite3.connect(drifted_db)
    row = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    con.close()
    assert row[0] == "30_x/csv2json.py"  # unchanged -- abort must precede any write


def test_both_provenance_columns_auto_added_when_missing(drifted_db):
    con = sqlite3.connect(drifted_db)
    cols_before = {r[1] for r in con.execute("PRAGMA table_info(capability)")}
    con.close()
    assert "provenance" not in cols_before
    assert "description_provenance" not in cols_before

    backfill.ensure_provenance_columns(drifted_db)

    con = sqlite3.connect(drifted_db)
    cols_after = {r[1] for r in con.execute("PRAGMA table_info(capability)")}
    con.close()
    assert "provenance" in cols_after
    assert "description_provenance" in cols_after


def test_commit_refuses_when_sanity_failure_rate_exceeds_threshold(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, sanity_ok=False)  # 100% failure rate
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        backfill.main(["--db", drifted_db, "--commit"])
    con = sqlite3.connect(drifted_db)
    row = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    con.close()
    assert row[0] == "30_x/csv2json.py"  # refused -- no write happened


def test_commit_proceeds_when_failure_rate_under_threshold(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, sanity_ok=True)  # 0% failure rate
    monkeypatch.chdir(tmp_path)
    backfill.main(["--db", drifted_db, "--commit"])  # must not raise
    con = sqlite3.connect(drifted_db)
    row = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    con.close()
    assert row[0] == "A test CLI that converts things."


def test_all_474_rows_get_description_only_python_rows_get_capability(drifted_db, monkeypatch, tmp_path):
    # csv2json is python (lang='python'), shellwrap is lang='shell'
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    backfill.main(["--db", drifted_db, "--commit"])
    con = sqlite3.connect(drifted_db)
    shell_desc = con.execute("SELECT description FROM cli WHERE slug='shellwrap'").fetchone()
    shell_cap = con.execute("SELECT input_types, provenance FROM capability WHERE cli_slug='shellwrap'").fetchone()
    con.close()
    assert shell_desc[0] == "A test CLI that converts things."  # description regenerated for shell row too
    assert shell_cap[0] == ""  # capability fields NOT populated for shell row
    assert shell_cap[1] is None  # never touched by the static/llm extractor path


def test_no_module_imports_core_models_cli_for_reads():
    import ast
    import pathlib

    for path in pathlib.Path("tools").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "core.models":
                names = {alias.name for alias in node.names}
                assert "Cli" not in names, f"{path} imports core.models.Cli -- must use raw sqlite3"
