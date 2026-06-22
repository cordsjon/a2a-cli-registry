import json as _json
import os
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
# mass_removal config wiring — the value an operator sets must reach populate()
# ---------------------------------------------------------------------------

def _capture_mass_removal(monkeypatch):
    """Monkeypatch core.cli.main.populate to capture mass_removal_threshold.
    Returns the captured dict; populate is stubbed to a no-op summary."""
    captured = {}

    def fake_populate(session, source, adapters, vocab, clock,
                      mass_removal_threshold=0.30):
        captured["threshold"] = mass_removal_threshold
        return {"added": 0, "removed": 0}

    monkeypatch.setattr("core.cli.main.populate", fake_populate)
    return captured


def _write_fleet_and_cfg(tmp_path, extra=""):
    fleet = tmp_path / "fleet.json"
    fleet.write_text(_json.dumps({"clis": [
        {"slug": "pdf2text", "lang": "python", "path": "/x/pdf2text"},
    ]}))
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'cli_audit_path = "{fleet}"\n'
        f'{extra}'
        '[vocabulary]\nregistered = []\n[vocabulary.aliases]\n'
    )
    return cfg


def test_populate_passes_config_mass_removal(tmp_path, monkeypatch):
    """populate command threads [thresholds].mass_removal into populate()."""
    captured = _capture_mass_removal(monkeypatch)
    cfg = _write_fleet_and_cfg(tmp_path, extra="[thresholds]\nmass_removal = 0.01\n")
    rc = main(["populate", "--db", str(tmp_path / "r.db"), "--config", str(cfg)])
    assert rc == 0
    assert captured["threshold"] == 0.01


def test_discover_passes_config_mass_removal(tmp_path, monkeypatch):
    """discover (non-dry-run) also threads the config mass_removal into populate()."""
    captured = _capture_mass_removal(monkeypatch)
    cfg = _write_fleet_and_cfg(tmp_path, extra="[thresholds]\nmass_removal = 0.05\n")
    rc = main(["discover", "--db", str(tmp_path / "r.db"), "--config", str(cfg)])
    assert rc == 0
    assert captured["threshold"] == 0.05


def test_mass_removal_falls_back_to_default_when_absent(tmp_path, monkeypatch):
    """A config WITHOUT a [thresholds] section still runs populate, using the
    default 0.30 — config stays optional."""
    captured = _capture_mass_removal(monkeypatch)
    cfg = _write_fleet_and_cfg(tmp_path)  # no [thresholds]
    rc = main(["populate", "--db", str(tmp_path / "r.db"), "--config", str(cfg)])
    assert rc == 0
    assert captured["threshold"] == 0.30


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

    # SSRF guard must be bypassed so the test reaches httpx.post.
    monkeypatch.setattr("core.announcer.announcer._is_ssrf_target", lambda url: False)
    monkeypatch.setattr(httpx, "post", fake_post)
    result = announce(
        "http://example.com/agent.json",
        ["http://broker-a.example.com/register", "http://broker-b.example.com/register"],
    )
    assert result == [False, True]


def test_serve_builds_app_and_invokes_uvicorn(tmp_path, monkeypatch):
    captured = {}

    def _fake_run(app, host, port, **kw):
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    import uvicorn
    monkeypatch.setattr(uvicorn, "run", _fake_run)
    rc = main(["serve", "--db", str(tmp_path / "r.db"),
               "--host", "127.0.0.1", "--port", "9999"])
    assert rc == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9999
    assert captured["app"] is not None     # the FastAPI app was built


def test_serve_derives_base_url_from_host_port(tmp_path, monkeypatch):
    """When A2A_BASE_URL is unset, serve derives it from --host/--port so the
    agent card AND MCP allowed-hosts match the address we actually bind."""
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.delenv("A2A_BASE_URL", raising=False)
    rc = main(["serve", "--db", str(tmp_path / "r.db"),
               "--host", "127.0.0.1", "--port", "9999"])
    assert rc == 0
    assert os.environ["A2A_BASE_URL"] == "http://127.0.0.1:9999"


def test_serve_respects_preset_base_url(tmp_path, monkeypatch):
    """An explicit A2A_BASE_URL (operator override) must NOT be overwritten."""
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setenv("A2A_BASE_URL", "https://registry.example.com")
    rc = main(["serve", "--db", str(tmp_path / "r.db"),
               "--host", "127.0.0.1", "--port", "9999"])
    assert rc == 0
    assert os.environ["A2A_BASE_URL"] == "https://registry.example.com"


def test_serve_bind_all_host_derives_localhost(tmp_path, monkeypatch):
    """--host 0.0.0.0 is bind-all, not a reachable client address: the derived
    base_url substitutes localhost so the card/allowed-hosts stay usable."""
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.delenv("A2A_BASE_URL", raising=False)
    rc = main(["serve", "--db", str(tmp_path / "r.db"),
               "--host", "0.0.0.0", "--port", "9999"])
    assert rc == 0
    assert os.environ["A2A_BASE_URL"] == "http://localhost:9999"


def test_audit_does_not_create_db(tmp_path, capsys):
    """`audit` is unimplemented and must short-circuit BEFORE init_db, so it
    leaves no empty registry.db behind."""
    db = tmp_path / "r.db"
    rc = main(["audit", "--db", str(db)])
    assert rc == 2
    assert "not implemented" in capsys.readouterr().err
    assert not db.exists()


def test_announce_sets_no_follow_redirects(monkeypatch):
    """follow_redirects=False must be passed to httpx.post."""
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(status_code=200)

    # SSRF guard must be bypassed so the test reaches httpx.post.
    monkeypatch.setattr("core.announcer.announcer._is_ssrf_target", lambda url: False)
    monkeypatch.setattr(httpx, "post", fake_post)
    announce("http://example.com/agent.json", ["http://broker.example.com/register"])
    assert captured.get("follow_redirects") is False
