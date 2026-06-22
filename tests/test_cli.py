import json as _json
import types

import httpx
from pathlib import Path

from core.cli.main import load_config, main
from core.announcer.announcer import announce


def test_load_config_reads_planner_bounds_and_vocab():
    cfg = load_config(str(Path(__file__).parent.parent / "examples/reference-fleet/config.toml"))
    assert cfg["planner"]["max_chain_depth"] == 4
    assert "file:pdf" in cfg["vocabulary"]["registered"]
    assert cfg["vocabulary"]["aliases"]["pdf"] == "file:pdf"


def test_main_graph_command_returns_zero(tmp_path, capsys):
    # graph on an empty db should succeed (exit 0), printing an empty graph
    rc = main(["graph", "--db", str(tmp_path / "r.db")])
    assert rc == 0


def test_unimplemented_subcommand_fails_loudly(tmp_path, capsys):
    """Unimplemented subcommands (audit, lifecycle) must return 2
    and must NOT print 'ok' (which would falsely imply success)."""
    rc = main(["audit", "--db", str(tmp_path / "r.db")])
    assert rc == 2
    captured = capsys.readouterr()
    assert "ok" not in captured.out
    assert "not implemented" in captured.err


def test_populate_command_writes_and_summarizes(tmp_path, capsys):
    # minimal cli-audit fixture
    fleet = tmp_path / "fleet.json"
    fleet.write_text(_json.dumps({"clis": [
        {"slug": "pdf2text", "lang": "python", "path": "/x/pdf2text",
         "capability": {"intent_tags": ["convert"], "input_types": ["file:pdf"],
                        "output_types": ["text:doc"], "side_effect": "none"}},
        {"slug": "summarize", "lang": "python", "path": "/x/summarize",
         "capability": {"intent_tags": ["summarize"], "input_types": ["text:doc"],
                        "output_types": ["text:summary"], "side_effect": "none"}},
    ]}))
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'cli_audit_path = "{fleet}"\n'
        '[vocabulary]\nregistered = ["file:pdf", "text:doc", "text:summary"]\n'
        '[vocabulary.aliases]\n'
    )
    rc = main(["populate", "--db", str(tmp_path / "r.db"), "--config", str(cfg)])
    assert rc == 0
    out = _json.loads(capsys.readouterr().out)
    assert out["added"] == 2
    assert out["edges"] >= 1   # pdf2text -> summarize via text:doc


def test_discover_dry_run_lists_without_writing(tmp_path, capsys):
    fleet = tmp_path / "fleet.json"
    fleet.write_text(_json.dumps({"clis": [
        {"slug": "pdf2text", "lang": "python", "path": "/x/pdf2text"},
    ]}))
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'cli_audit_path = "{fleet}"\n[vocabulary]\nregistered = []\n[vocabulary.aliases]\n')
    db = tmp_path / "r.db"
    rc = main(["discover", "--db", str(db), "--config", str(cfg), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "pdf2text" in out


def test_discover_without_dry_run_writes_db(tmp_path, capsys):
    fleet = tmp_path / "fleet.json"
    fleet.write_text(_json.dumps({"clis": [
        {"slug": "pdf2text", "lang": "python", "path": "/x/pdf2text",
         "capability": {"intent_tags": ["convert"], "input_types": ["file:pdf"],
                        "output_types": ["text:doc"], "side_effect": "none"}},
    ]}))
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'cli_audit_path = "{fleet}"\n'
        '[vocabulary]\nregistered = ["file:pdf", "text:doc"]\n[vocabulary.aliases]\n'
    )
    db = tmp_path / "r.db"
    rc = main(["discover", "--db", str(db), "--config", str(cfg)])
    assert rc == 0
    from core.store.db import init_db, get_session
    from core.catalog import queries
    engine = init_db(str(db))
    with get_session(engine) as session:
        rows = queries.search_clis(session)
    assert any(r["slug"] == "pdf2text" for r in rows)


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
