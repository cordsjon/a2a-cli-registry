import hashlib
import json
import os
import stat
import sys

import pytest

from core.models import Cli
from core.prober.smoke import run_smoke, smoke_rows


def _script(path, body):
    path.write_text(f"#!{sys.executable}\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def _spec(argv, **smoke):
    return {"smoke": {"argv": argv, "side_effects": "none", "tier": "hand", **smoke}}


def test_pass_needs_exit_regex_and_file(tmp_path):
    tool = _script(tmp_path / "tool", "print('wrote out.pdf'); open('out.pdf', 'w').close()")
    spec = _spec([tool], expect_exit=0, expect_stdout_re=r"wrote out\.pdf", expect_file="out.pdf")
    assert run_smoke(spec, timeout=10) == "pass"


def test_fail_on_wrong_exit(tmp_path):
    tool = _script(tmp_path / "tool", "raise SystemExit(3)")
    assert run_smoke(_spec([tool], expect_exit=0), timeout=10) == "fail"


def test_fail_when_stdout_does_not_match(tmp_path):
    """stderr does not count: `expect_stdout_re` is a claim about the output."""
    tool = _script(tmp_path / "tool", "import sys; sys.stderr.write('wrote out.pdf')")
    assert run_smoke(_spec([tool], expect_stdout_re="wrote"), timeout=10) == "fail"


def test_fail_on_missing_file(tmp_path):
    tool = _script(tmp_path / "tool", "pass")
    assert run_smoke(_spec([tool], expect_file="out.pdf"), timeout=10) == "fail"


def test_fail_when_the_command_cannot_start(tmp_path):
    assert run_smoke(_spec([str(tmp_path / "absent")]), timeout=10) == "fail"


def test_fail_and_kill_on_timeout(tmp_path):
    tool = _script(tmp_path / "tool", "import time; time.sleep(30)")
    assert run_smoke(_spec([tool]), timeout=0.5) == "fail"


def test_spec_timeout_overrides_the_default(tmp_path):
    tool = _script(tmp_path / "tool", "import time; time.sleep(30)")
    assert run_smoke(_spec([tool], timeout=0.5), timeout=60) == "fail"


def test_unknown_without_a_smoke_key():
    assert run_smoke({"argv": ["x"]}, timeout=10) == "unknown"


@pytest.mark.parametrize("side_effects", ["network", "spend", None, "typo"])
def test_refuses_anything_not_declared_safe_unless_allowed(tmp_path, side_effects):
    ran = tmp_path / "ran"
    tool = _script(tmp_path / "tool", f"open({str(ran)!r}, 'w').close()")
    spec = _spec([tool], side_effects=side_effects)

    assert run_smoke(spec, timeout=10) == "unknown"
    assert not ran.exists()
    assert run_smoke(spec, timeout=10, allow_network=True) == "pass"
    assert ran.exists()


def test_fixture_is_copied_and_the_original_is_untouched(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    original = fixture / "in.txt"
    original.write_text("seed")
    before = (hashlib.sha256(original.read_bytes()).hexdigest(), original.stat().st_mtime_ns)
    tool = _script(tmp_path / "tool", "s = open('in.txt').read(); open('in.txt', 'w').write('x'); print(s)")

    status = run_smoke(_spec([tool], fixture=str(fixture), expect_stdout_re="seed"), timeout=10)

    assert status == "pass"
    assert (hashlib.sha256(original.read_bytes()).hexdigest(), original.stat().st_mtime_ns) == before


def test_fail_when_the_fixture_is_missing(tmp_path):
    tool = _script(tmp_path / "tool", "pass")
    assert run_smoke(_spec([tool], fixture=str(tmp_path / "absent")), timeout=10) == "fail"


def test_runs_in_a_throwaway_cwd_without_pythonpath(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/only/in/the/prober")
    caller = tmp_path / "caller"
    caller.mkdir()
    monkeypatch.chdir(caller)
    record = tmp_path / "seen.json"
    tool = _script(tmp_path / "tool", (
        "import json, os\n"
        f"json.dump([os.getcwd(), os.environ.get('PYTHONPATH')], open({str(record)!r}, 'w'))\n"
        "open('stray.txt', 'w').close()"))

    assert run_smoke(_spec([tool]), timeout=10) == "pass"

    cwd, pythonpath = json.loads(record.read_text())
    assert pythonpath is None
    assert os.path.realpath(cwd) != os.path.realpath(str(caller))
    assert not os.path.exists(cwd)
    assert list(caller.iterdir()) == []


def _row(db, slug, smoke=None, **fields):
    spec = {"kind": "x"}
    if smoke:
        spec["smoke"] = smoke
    db.add(Cli(slug=slug, lang="python", launch_spec=json.dumps(spec), **fields))
    db.commit()


def test_smoke_rows_writes_work_status_and_never_health(db, clock, tmp_path):
    tool = _script(tmp_path / "tool", "pass")
    bad = _script(tmp_path / "bad", "raise SystemExit(1)")
    _row(db, "good", {"argv": [tool], "side_effects": "none"}, health_status="healthy")
    _row(db, "bad", {"argv": [bad], "side_effects": "none"}, health_status="healthy")
    _row(db, "bare", health_status="healthy")

    summary = smoke_rows(db, clock)

    db.expire_all()
    good = db.get(Cli, "good")
    assert (good.work_status, good.work_checked_at) == ("pass", clock.now())
    assert db.get(Cli, "bad").work_status == "fail"
    assert (db.get(Cli, "bare").work_status, db.get(Cli, "bare").work_checked_at) == ("unknown", None)
    assert {db.get(Cli, s).health_status for s in ("good", "bad", "bare")} == {"healthy"}
    assert (summary["pass"], summary["fail"], summary["unknown"]) == (1, 1, 1)
    assert summary["fail_slugs"] == ["bad"]


def test_gated_row_keeps_a_recorded_pass(db, clock, tmp_path):
    """A dated operator pass on a network smoke must survive the next sweep that
    did not allow the network: not running it says nothing about it."""
    ran = tmp_path / "ran"
    tool = _script(tmp_path / "tool", f"open({str(ran)!r}, 'w').close()")
    _row(db, "net", {"argv": [tool], "side_effects": "network"},
         work_status="pass", work_checked_at=123.0)

    summary = smoke_rows(db, clock)

    assert not ran.exists()
    db.expire_all()
    net = db.get(Cli, "net")
    assert (net.work_status, net.work_checked_at) == ("pass", 123.0)
    assert summary["gated_network"] == ["net"]


def test_not_standalone_row_is_unknown_and_its_smoke_does_not_run(db, clock, tmp_path):
    """Its smoke can only prove a test file: no launcher can reach the row (Q45)."""
    ran = tmp_path / "ran"
    tool = _script(tmp_path / "tool", f"open({str(ran)!r}, 'w').close()")
    _row(db, "sub", {"argv": [tool], "side_effects": "project-tests"},
         not_standalone=True, health_status="not_standalone",
         work_status="pass", work_checked_at=123.0)

    summary = smoke_rows(db, clock)

    assert not ran.exists()
    db.expire_all()
    assert db.get(Cli, "sub").work_status == "unknown"
    assert (summary["unknown"], summary["gated_network"]) == (1, [])


def test_smoke_rows_dry_run_runs_but_writes_nothing(db, clock, tmp_path):
    tool = _script(tmp_path / "tool", "pass")
    _row(db, "good", {"argv": [tool], "side_effects": "none"})

    summary = smoke_rows(db, clock, dry_run=True)

    assert summary["pass"] == 1
    db.expire_all()
    assert db.get(Cli, "good").work_status == "unknown"


def test_smoke_rows_named_rows_only_and_reports_the_rest(db, clock, tmp_path):
    ran = tmp_path / "ran"
    tool = _script(tmp_path / "tool", f"open({str(ran)!r}, 'w').close()")
    ok = _script(tmp_path / "ok", "pass")
    _row(db, "other", {"argv": [tool], "side_effects": "none"})
    _row(db, "named", {"argv": [ok], "side_effects": "none"})

    summary = smoke_rows(db, clock, slugs=["named", "typo"])

    assert not ran.exists()
    assert summary["pass"] == 1
    assert summary["not_probed"] == ["typo"]
