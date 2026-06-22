import types

import httpx
from pathlib import Path

from core.cli.main import load_config, main
from core.announcer.announcer import announce


def test_load_config_reads_planner_bounds_and_vocab():
    cfg = load_config(str(Path(__file__).parent.parent / "examples/jonas-fleet/config.toml"))
    assert cfg["planner"]["max_chain_depth"] == 4
    assert "file:pdf" in cfg["vocabulary"]["registered"]
    assert cfg["vocabulary"]["aliases"]["pdf"] == "file:pdf"


def test_main_graph_command_returns_zero(tmp_path, capsys):
    # graph on an empty db should succeed (exit 0), printing an empty graph
    rc = main(["graph", "--db", str(tmp_path / "r.db")])
    assert rc == 0


def test_unimplemented_subcommand_fails_loudly(tmp_path, capsys):
    """Unimplemented subcommands (populate, audit, discover, lifecycle) must return 2
    and must NOT print 'ok' (which would falsely imply success)."""
    rc = main(["populate", "--db", str(tmp_path / "r.db")])
    assert rc == 2
    captured = capsys.readouterr()
    assert "ok" not in captured.out
    assert "not implemented" in captured.err


# ---------------------------------------------------------------------------
# announce — network-free tests (monkeypatched httpx.post)
# ---------------------------------------------------------------------------

def test_announce_empty_brokers_returns_empty():
    result = announce("http://example.com/agent.json", [])
    assert result == []


def test_announce_isolates_failing_broker(monkeypatch):
    """One broker raising Exception must not abort the loop — bulkhead check."""
    call_count = {"n": 0}

    def fake_post(url, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("connection refused")
        return types.SimpleNamespace(status_code=200)

    monkeypatch.setattr(httpx, "post", fake_post)
    result = announce(
        "http://example.com/agent.json",
        ["http://broker-a.example.com/register", "http://broker-b.example.com/register"],
    )
    assert result == [False, True]


def test_announce_sets_no_follow_redirects(monkeypatch):
    """follow_redirects=False must be passed to httpx.post."""
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(status_code=200)

    monkeypatch.setattr(httpx, "post", fake_post)
    announce("http://example.com/agent.json", ["http://broker.example.com/register"])
    assert captured.get("follow_redirects") is False
