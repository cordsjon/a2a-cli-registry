"""CLI wiring for `ard-resolve` (spec US-2, AC-2.1/2.4).

The dispatch block must never open the registry DB or its sidecar lock: these
tests pass no --db and assert on stdout/exit codes only, so a stray init_db
would leave a registry.db behind in the test CWD.
"""
import pytest

from core.cli.main import main


def test_ard_resolve_prints_endpoint(monkeypatch, capsys):
    import core.ard.resolve as R
    monkeypatch.setattr(R, "resolve", lambda base, t, deadline_s=10.0: "http://reg:9113/mcp")
    rc = main(["ard-resolve", "--base-url", "http://reg:9113", "--type", "mcp"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "http://reg:9113/mcp"


def test_ard_resolve_emit_claude(monkeypatch, capsys):
    import core.ard.resolve as R
    monkeypatch.setattr(R, "resolve", lambda base, t, deadline_s=10.0: "http://reg:9113/mcp")
    rc = main(["ard-resolve", "--base-url", "http://reg:9113", "--type", "mcp",
               "--emit", "claude"])
    assert rc == 0
    assert "claude mcp add" in capsys.readouterr().out


def test_emit_with_type_a2a_is_rejected(capsys):
    # AC-2.4: nonsense combo exits non-zero BEFORE any network I/O
    rc = main(["ard-resolve", "--base-url", "http://reg:9113", "--type", "a2a",
               "--emit", "claude"])
    assert rc == 2
    assert "only valid with --type mcp" in capsys.readouterr().err


def test_missing_base_url_is_rejected(capsys):
    rc = main(["ard-resolve"])
    assert rc == 2
    assert "--base-url" in capsys.readouterr().err


def test_ard_error_is_one_line_no_traceback(monkeypatch, capsys):
    import core.ard.resolve as R

    def boom(base, t, deadline_s=10.0):
        raise R.ArdError("GET http://reg:9113/... -> HTTP 404")

    monkeypatch.setattr(R, "resolve", boom)
    rc = main(["ard-resolve", "--base-url", "http://reg:9113", "--type", "mcp"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "HTTP 404" in err and "Traceback" not in err
