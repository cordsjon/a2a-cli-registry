import sqlite3

from scripts.disable_missing_path_rows import main


def _db(tmp_path, rows):
    db = tmp_path / "registry.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cli (slug TEXT, path TEXT, enabled INT, "
                "health_status TEXT, fixed_by TEXT)")
    con.executemany("INSERT INTO cli VALUES (?, ?, 1, 'unhealthy', NULL)", rows)
    con.commit()
    return db, con


def _fleet(tmp_path, n_live=4):
    rows = []
    for i in range(n_live):
        live = tmp_path / f"live{i}.py"
        live.write_text("")
        rows.append((f"live{i}", str(live)))
    return rows


def test_dry_run_writes_nothing(tmp_path):
    db, con = _db(tmp_path, _fleet(tmp_path) + [("gone", str(tmp_path / "gone.py"))])
    assert main(["--db", str(db)]) == 0
    assert con.execute("SELECT enabled FROM cli WHERE slug='gone'").fetchone() == (1,)
    assert list(tmp_path.glob("registry.db.bak-*")) == []


def test_apply_disables_only_missing_paths_with_provenance_and_backup(tmp_path):
    rows = _fleet(tmp_path) + [("gone", str(tmp_path / "gone.py")), ("module_form", "")]
    db, con = _db(tmp_path, rows)
    assert main(["--db", str(db), "--apply"]) == 0
    enabled, status, fixed_by = con.execute(
        "SELECT enabled, health_status, fixed_by FROM cli WHERE slug='gone'").fetchone()
    assert (enabled, status) == (0, "unknown")
    assert fixed_by.startswith("disabled:path-missing:")
    assert con.execute("SELECT COUNT(*) FROM cli WHERE enabled=1").fetchone() == (5,)
    assert len(list(tmp_path.glob("registry.db.bak-*"))) == 1


def test_refuses_when_too_many_paths_are_missing(tmp_path):
    rows = _fleet(tmp_path, n_live=1) + [("gone", str(tmp_path / "gone.py"))]
    db, con = _db(tmp_path, rows)
    assert main(["--db", str(db), "--apply"]) == 2
    assert con.execute("SELECT COUNT(*) FROM cli WHERE enabled=1").fetchone() == (2,)
