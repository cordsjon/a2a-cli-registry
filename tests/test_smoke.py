import hashlib
import json
import os
import shutil
import stat
import sys

import pytest

from core.models import Cli
from core.prober.smoke import run_smoke, smoke_result, smoke_rows


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


def test_fail_when_file_content_does_not_match(tmp_path):
    """A file that exists but holds the wrong result is the regression to catch."""
    tool = _script(tmp_path / "tool", "open('out.txt', 'w').write('total 41')")
    assert run_smoke(_spec([tool], expect_file="out.txt", expect_file_re="total 41"), timeout=10) == "pass"
    assert run_smoke(_spec([tool], expect_file="out.txt", expect_file_re="total 42"), timeout=10) == "fail"


@pytest.mark.skipif(shutil.which("sandbox-exec") is None, reason="needs the macOS sandbox")
def test_sandbox_blocks_writes_outside_the_cwd_and_the_network_unless_declared(tmp_path):
    outside = os.path.expanduser(f"~/.clireg-smoke-sandbox-probe-{os.getpid()}")
    write = _script(tmp_path / "write", f"open({outside!r}, 'w').close()")
    connect = _script(tmp_path / "connect", (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('127.0.0.1', 9), timeout=1)\n"
        "except ConnectionRefusedError:\n"
        "    print('reached the network stack')"))
    try:
        assert run_smoke(_spec([write]), timeout=10) == "fail"
        assert not os.path.exists(outside)
    finally:
        if os.path.exists(outside):
            os.unlink(outside)
    assert run_smoke(_spec([connect], expect_stdout_re="reached"), timeout=10) == "fail"
    assert run_smoke(_spec([connect], side_effects="network", expect_stdout_re="reached"),
                     timeout=10, allow_network=True) == "pass"


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


def test_a_fixture_with_a_dangling_symlink_fails_the_row_without_aborting_the_sweep(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "tool.py").symlink_to(tmp_path / "moved-away.py")
    tool = _script(tmp_path / "tool", "pass")
    assert run_smoke(_spec([tool], fixture=str(fixture)), timeout=10) == "fail"


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


@pytest.mark.parametrize("body, smoke, timeout, reason", [
    ("raise SystemExit(3)", {"expect_exit": 0}, 10, "exit 3, expected 0"),
    ("pass", {"expect_file": "out.pdf"}, 10, "expect_file out.pdf not written"),
    ("print('nothing')", {"expect_stdout_re": "wrote"}, 10, "stdout did not match expect_stdout_re"),
    ("open('out.txt', 'w').write('total 41')", {"expect_file": "out.txt", "expect_file_re": "total 42"}, 10,
     "out.txt did not match expect_file_re"),
    ("import time; time.sleep(30)", {}, 0.5, "timed out after 0.5s"),
])
def test_a_failure_says_which_check_failed(tmp_path, body, smoke, timeout, reason):
    tool = _script(tmp_path / "tool", body)
    assert smoke_result(_spec([tool], **smoke), timeout=timeout)[:2] == ("fail", reason)


def test_a_failure_that_never_ran_says_why(tmp_path):
    """A smoke with its own cwd is not sandboxed, so a missing command fails to start;
    under sandbox-exec it is an exit code instead, with the cause in the stderr tail."""
    unsandboxed = _spec([str(tmp_path / "absent")], cwd=str(tmp_path))
    assert smoke_result(unsandboxed, timeout=10)[1].startswith("did not start: ")
    assert smoke_result(_spec(["true"], fixture=str(tmp_path / "gone")), timeout=10)[1] == \
        f"fixture not copied: {tmp_path / 'gone'}"
    assert smoke_result({"smoke": {"side_effects": "none"}}, timeout=10)[1] == "smoke has no argv"


def test_a_failure_keeps_the_tails_of_stdout_and_stderr(tmp_path):
    """stderr is kept for the reader only: it still never satisfies expect_stdout_re."""
    tool = _script(tmp_path / "tool", "import sys; print('x' * 9000 + 'END-OUT'); "
                                      "sys.stderr.write('Traceback: boom'); raise SystemExit(1)")
    status, reason, tails = smoke_result(_spec([tool], expect_stdout_re="boom"), timeout=10)
    assert (status, reason) == ("fail", "exit 1, expected 0")
    assert tails["stdout"].rstrip().endswith("END-OUT") and len(tails["stdout"]) <= 2000
    assert tails["stderr"] == "Traceback: boom"


def test_a_pass_carries_no_reason(tmp_path):
    tool = _script(tmp_path / "tool", "print('ok')")
    assert smoke_result(_spec([tool]), timeout=10) == ("pass", "", {})


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
    assert summary["fail_detail"] == {"bad": {"reason": "exit 1, expected 0", "stdout": "", "stderr": ""}}


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
