import json
import shlex
import sqlite3

from scripts.launch_measure import MAX_GATEWAY_ERRORS, main

_HELP = "usage: tool [-h]\n"


def _db(tmp_path, slugs, disabled=(), unhealthy=()):
    db = tmp_path / "registry.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cli (slug TEXT, launch_spec TEXT, enabled INT, health_status TEXT)")
    for slug in slugs:
        con.execute("INSERT INTO cli VALUES (?, ?, ?, ?)",
                    (slug, json.dumps({"argv": [f"/bin/{slug}"]}),
                     0 if slug in disabled else 1,
                     "stale" if slug in unhealthy else "healthy"))
    con.commit()
    con.close()
    return db


def _gateway(results):
    """A fake gateway: slug -> result in the shapes run_on_gateway returns. Records calls."""
    calls = []

    async def run(command):
        calls.append(command)
        return results[command.split("/bin/")[1].split()[0]]

    def compose(spec):
        return f"env {shlex.join(spec['argv'])}" if spec.get("argv") else None

    return calls, lambda: (run, compose)


def _ok(stdout=_HELP + "EXIT=0"):
    return {"status": "success", "stdout": stdout, "exit_code": 0}


def _args(db, out, *extra):
    return ["--db", str(db), "--out", str(out), *extra]


def test_only_exit_zero_passes_and_report_has_the_artefact_keys(tmp_path):
    db = _db(tmp_path, ["good", "exit1", "nomarker", "denied"])
    out = tmp_path / "report.json"
    calls, gateway = _gateway({
        "good": _ok(),
        # The gateway says success for a command that exited 1.
        "exit1": {"status": "success", "stdout": "Traceback\nEXIT=1", "exit_code": 1},
        "nomarker": {"status": "exit_unknown", "stdout": _HELP, "exit_code": None,
                     "error": "no marker"},
        "denied": {"status": "denied", "reason": "gateway requires approval"},
    })

    assert main(_args(db, out), gateway=gateway) == 1

    report = json.loads(out.read_text())
    assert {"date", "method", "sample_seed", "rows"} <= set(report)
    rows = {r["slug"]: r for r in report["rows"]}
    assert {s: r["passed"] for s, r in rows.items()} == {
        "good": True, "exit1": False, "nomarker": False, "denied": False}
    assert rows["good"]["usage_seen"] is True
    assert rows["denied"]["error"] == "gateway requires approval"
    assert all(c.endswith(" --help") for c in calls)


def test_only_healthy_enabled_rows_run_and_a_seed_repeats_the_sample(tmp_path):
    slugs = [f"s{i}" for i in range(20)]
    db = _db(tmp_path, slugs + ["off", "old"], disabled={"off"}, unhealthy={"old"})
    results = {s: _ok() for s in slugs}

    sampled = []
    for name in ("a.json", "b.json"):
        out = tmp_path / name
        assert main(_args(db, out, "--sample", "5", "--seed", "7"), gateway=_gateway(results)[1]) == 0
        report = json.loads(out.read_text())
        assert report["sample_seed"] == 7
        sampled.append([r["slug"] for r in report["rows"]])
    assert sampled[0] == sampled[1] and len(sampled[0]) == 5

    out = tmp_path / "all.json"
    assert main(_args(db, out), gateway=_gateway(results)[1]) == 0
    report = json.loads(out.read_text())
    assert sorted(r["slug"] for r in report["rows"]) == sorted(slugs)
    assert report["sample_seed"] is None


def test_gateway_outage_stops_the_run_without_scoring_the_remaining_rows(tmp_path):
    slugs = [f"s{i}" for i in range(10)]
    db = _db(tmp_path, slugs)
    out = tmp_path / "report.json"
    outage = {"status": "timeout", "error": "exec gateway breaker open"}
    calls, gateway = _gateway({"s0": _ok(), **{s: outage for s in slugs[1:]}})

    assert main(_args(db, out), gateway=gateway) == 2

    report = json.loads(out.read_text())
    assert len(calls) == 1 + MAX_GATEWAY_ERRORS
    assert "breaker open" in report["stopped"]
    assert len(report["rows"]) == 1 + MAX_GATEWAY_ERRORS


def test_a_gateway_error_between_row_answers_does_not_stop_the_run(tmp_path):
    slugs = [f"s{i}" for i in range(2 * MAX_GATEWAY_ERRORS)]
    db = _db(tmp_path, slugs)
    out = tmp_path / "report.json"
    outage = {"status": "timeout", "error": "did not reach a terminal state"}
    results = {s: (outage if i % 2 else _ok()) for i, s in enumerate(slugs)}

    assert main(_args(db, out), gateway=_gateway(results)[1]) == 1

    report = json.loads(out.read_text())
    assert report["stopped"] is None
    assert len(report["rows"]) == len(slugs)


def test_resume_keeps_answered_rows_and_retries_the_rest(tmp_path):
    slugs = ["a", "b", "c"]
    db = _db(tmp_path, slugs)
    out = tmp_path / "report.json"
    outage = {"status": "failed", "error": "gateway POST /v1/runs returned HTTP 429"}
    _, gateway = _gateway({"a": _ok(), "b": outage, "c": _ok()})
    assert main(_args(db, out), gateway=gateway) == 1

    calls, gateway = _gateway({"a": _ok(), "b": _ok(), "c": _ok()})
    assert main(_args(db, out, "--resume"), gateway=gateway) == 0

    assert [c.split("/bin/")[1].split()[0] for c in calls] == ["b"]
    rows = json.loads(out.read_text())["rows"]
    assert sorted(r["slug"] for r in rows) == slugs
    assert all(r["passed"] for r in rows)


def test_uncomposable_spec_fails_the_row_without_a_gateway_call(tmp_path):
    db = tmp_path / "registry.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cli (slug TEXT, launch_spec TEXT, enabled INT, health_status TEXT)")
    con.execute("INSERT INTO cli VALUES ('noargv', '{}', 1, 'healthy')")
    con.commit()
    con.close()
    out = tmp_path / "report.json"
    calls, gateway = _gateway({})

    assert main(_args(db, out), gateway=gateway) == 1

    assert calls == []
    row = json.loads(out.read_text())["rows"][0]
    assert (row["status"], row["passed"]) == ("uncomposable", False)


def test_a_slug_with_no_runnable_row_exits_2_and_measures_nothing(tmp_path):
    db = _db(tmp_path, ["good", "off"], disabled={"off"})
    out = tmp_path / "report.json"
    calls, gateway = _gateway({"good": _ok()})

    assert main(_args(db, out) + ["--slug", "good", "--slug", "typo"], gateway=gateway) == 2
    assert main(_args(db, out) + ["--slug", "off"], gateway=gateway) == 2

    assert calls == []
    assert not out.exists()
