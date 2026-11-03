import json
import sqlite3
import time

from scripts.parity_report import grade, in_scope, main, summarize

NOW = 1_800_000_000.0
_HAND = {"tier": "hand", "negative": {"argv": ["x", "--bad"]}, "proves": "converts a file"}


def _spec(smoke=None, **top):
    return json.dumps({"command": "x", "smoke": _HAND if smoke is None else smoke, **top})


def _at_parity(slug="good", **over):
    row = {"slug": slug, "enabled": 1, "health_status": "healthy", "launch_spec": _spec(),
           "work_status": "pass", "work_checked_at": NOW - 86400, "a2a_invokable": 1}
    row.update(over)
    return row


def _db(tmp_path, rows):
    db = tmp_path / f"registry-{len(list(tmp_path.glob('registry-*.db')))}.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cli (slug TEXT, enabled INT, health_status TEXT, launch_spec TEXT, "
                "work_status TEXT, work_checked_at REAL, a2a_invokable INT)")
    for r in rows:
        con.execute("INSERT INTO cli VALUES (:slug, :enabled, :health_status, :launch_spec, "
                    ":work_status, :work_checked_at, :a2a_invokable)", r)
    con.commit()
    con.close()
    return db


def _rows(tmp_path, rows):
    """Round-trip through sqlite so the rows carry the column types the live DB returns."""
    con = sqlite3.connect(_db(tmp_path, rows))
    con.row_factory = sqlite3.Row
    out = [dict(r) for r in con.execute("SELECT * FROM cli")]
    con.close()
    return out


def _one(tmp_path, **over):
    return _rows(tmp_path, [_at_parity(**over)])[0]


def test_invalid_json_spec_is_out_of_scope(tmp_path):
    rows = _rows(tmp_path, [_at_parity("placeholder", launch_spec="install:https://x"),
                            _at_parity("null", launch_spec=None)])
    assert not in_scope(rows[0])
    assert not in_scope(rows[1])
    assert summarize(rows, {}, NOW)["in_scope"] == 0


def test_not_standalone_is_out_of_scope(tmp_path):
    assert in_scope(_one(tmp_path))
    assert not in_scope(_one(tmp_path, health_status="not_standalone"))


def test_project_tests_tier_fails_h2(tmp_path):
    row = _one(tmp_path, launch_spec=_spec({**_HAND, "tier": "project-tests"}))
    assert grade(row, ["a.py"], NOW)["H2"] is False


def test_hand_without_negative_fails_h2(tmp_path):
    bare = {"tier": "hand", "proves": "converts a file"}
    assert grade(_one(tmp_path, launch_spec=_spec(bare)), ["a.py"], NOW)["H2"] is False
    why = {**bare, "negative_why": "no input makes it fail cleanly"}
    assert grade(_one(tmp_path, launch_spec=_spec(why)), ["a.py"], NOW)["H2"] is True


def test_check_older_than_8_days_fails_h3(tmp_path):
    assert grade(_one(tmp_path, work_checked_at=NOW - 9 * 86400), ["a.py"], NOW)["H3"] is False
    assert grade(_one(tmp_path, work_checked_at=None), ["a.py"], NOW)["H3"] is False
    assert grade(_one(tmp_path, work_checked_at=NOW - 7 * 86400), ["a.py"], NOW)["H3"] is True


def test_agent_callable_without_proves_fails_h4(tmp_path):
    smoke = {k: v for k, v in _HAND.items() if k != "proves"}
    assert grade(_one(tmp_path, launch_spec=_spec(smoke)), ["a.py"], NOW)["H4"] is False
    blank = {**_HAND, "proves": "  "}
    assert grade(_one(tmp_path, launch_spec=_spec(blank)), ["a.py"], NOW)["H4"] is False


def test_not_agent_callable_passes_h4(tmp_path):
    smoke = {k: v for k, v in _HAND.items() if k != "proves"}
    row = _one(tmp_path, a2a_invokable=0, launch_spec=_spec(smoke))
    assert grade(row, ["a.py"], NOW)["H4"] is True


def test_zero_consumers_fails_h5_unless_operator_run(tmp_path):
    row = _one(tmp_path)
    assert grade(row, None, NOW)["H5"] is False
    assert grade(row, [], NOW)["H5"] is False
    assert grade(row, ["a.py"], NOW)["H5"] is True
    run_by_hand = _one(tmp_path, launch_spec=_spec(operator_run=True))
    assert grade(run_by_hand, None, NOW)["H5"] is True


def test_summary_counts(tmp_path):
    rows = _rows(tmp_path, [_at_parity("good"),
                            _at_parity("unproven", launch_spec=_spec({**_HAND, "tier": "version"})),
                            _at_parity("library", health_status="not_standalone")])
    consumers = {"good": ["a.py"], "unproven": ["b.py"], "library": ["c.py"]}
    summary = summarize(rows, consumers, NOW)
    assert set(summary) == {"in_scope", "parity", "fails", "failing"}
    assert (summary["in_scope"], summary["parity"]) == (2, 1)
    assert summary["fails"] == {"H1": 0, "H2": 1, "H3": 0, "H4": 0, "H5": 0}
    assert summary["failing"] == {"unproven": ["H2"]}


def test_out_writes_markdown_totals_and_failing_rows(tmp_path, capsys):
    now = time.time()
    db = _db(tmp_path, [_at_parity("good", launch_spec=_spec(operator_run=True),
                                   work_checked_at=now - 86400),
                        _at_parity("stale", work_checked_at=now - 30 * 86400)])
    out = tmp_path / "parity.md"
    missing = tmp_path / "no-such-index.json"
    assert main(["--db", str(db), "--consumers", str(missing), "--out", str(out)]) == 0
    lines = out.read_text().splitlines()
    assert lines[0] == "parity 1/2 · H1 0 · H2 0 · H3 1 · H4 0 · H5 1"
    rows = [line for line in lines if line.startswith("| ") and "slug" not in line]
    assert rows == ["| stale | H3, H5 |"]
    assert list(tmp_path.glob(".parity.md.*")) == []
