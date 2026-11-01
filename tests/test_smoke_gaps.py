import json
import sqlite3

from scripts.smoke_gaps import main


def _db(tmp_path, rows):
    """rows: (slug, project, work_status, overrides for enabled and health_status)."""
    db = tmp_path / "registry.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cli (slug TEXT, project TEXT, enabled INT, health_status TEXT, "
                "work_status TEXT)")
    for slug, project, work, over in rows:
        con.execute("INSERT INTO cli VALUES (?, ?, ?, ?, ?)",
                    (slug, project, over.get("enabled", 1), over.get("health", "healthy"), work))
    con.commit()
    con.close()
    return db


def _report(tmp_path, capsys, rows):
    assert main(["--db", str(_db(tmp_path, rows)), "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def _unknown(project, count):
    return [(f"{project}-{i}", project, "unknown", {}) for i in range(count)]


def test_ten_unknown_rows_are_a_story_and_nine_are_a_todo(tmp_path, capsys):
    report = _report(tmp_path, capsys, _unknown("big", 10) + _unknown("small", 9))
    assert [s["project"] for s in report["stories"]] == ["big"]
    assert [t["project"] for t in report["todos"]] == ["small"]
    story = report["stories"][0]
    assert story["ac"][0] == "every row in the list has a smoke with tier hand"
    assert all(f"big-{i}" in story["want"] for i in range(10))
    assert "small-8" in report["todos"][0]["line"]


def test_only_healthy_enabled_unproven_rows_count(tmp_path, capsys):
    rows = [("proven", "p", "pass", {}), ("off", "p", "unknown", {"enabled": 0}),
            ("library", "p", "unknown", {"health": "not_standalone"}),
            ("gap", "p", "unknown", {})]
    report = _report(tmp_path, capsys, rows)
    assert len(report["todos"]) == 1
    assert "gap" in report["todos"][0]["line"]
    for gone in ("proven", "off", "library"):
        assert gone not in report["todos"][0]["line"]


def test_a_failing_row_stays_visible_and_does_not_count_towards_the_threshold(tmp_path, capsys):
    rows = _unknown("p", 9) + [("broken", "p", "fail", {})]
    report = _report(tmp_path, capsys, rows)
    assert report["stories"] == []
    assert report["todos"][0]["fail"] == ["broken"]
    assert "broken" in report["todos"][0]["line"]


def test_a_story_carries_its_failing_rows_in_an_ac(tmp_path, capsys):
    report = _report(tmp_path, capsys, _unknown("q", 10) + [("broken", "q", "fail", {})])
    assert any("broken" in ac for ac in report["stories"][0]["ac"])


def test_a_null_project_is_not_silently_dropped(tmp_path, capsys):
    report = _report(tmp_path, capsys, [("orphan", None, "unknown", {})])
    assert report["todos"][0]["project"] == "(none)"


def test_the_table_prints_a_row_per_project_with_its_counts(tmp_path, capsys):
    db = _db(tmp_path, _unknown("big", 10) + [("broken", "small", "fail", {})])
    assert main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert any(line.split() == ["big", "10", "0"] for line in out.splitlines())
    assert any(line.split() == ["small", "0", "1"] for line in out.splitlines())
