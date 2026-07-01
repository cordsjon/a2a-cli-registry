import json
from pathlib import Path
from core.store.db import init_db, get_session
from core.models import Cli, Capability
from core.playbooks import resolve as r


def _seed_cli(s, slug, side="writes-fs", launch=None):
    s.add(Cli(slug=slug, lang="python",
              launch_spec=json.dumps(launch or {"kind": "python_module", "entrypoint": slug})))
    s.add(Capability(cli_slug=slug, input_types="a", output_types="x", side_effect=side))
    s.commit()


def _seed_pb(root: Path):
    d = root / "svg-pub"; d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\ndescription: Enrich SVGs and publish\ntags: [svg]\n"
        "allowed-tools: [svg-enrich]\nstatus: verified\n---\n"
        "1. svg-enrich in: {raw: raw} out: EnrichedSvg\n"
    )


def test_resolve_builds_runnable_plan(tmp_path, monkeypatch):
    _seed_pb(tmp_path)
    monkeypatch.setattr(r, "PLAYBOOKS_ROOT", str(tmp_path))
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed_cli(s, "svg-enrich", side="writes-fs")
        out = r.resolve_playbook(s, "svg-pub")
        assert out["runnable"] is True
        assert out["plan"][0]["cli"] == "svg-enrich"
        assert out["plan"][0]["launch_spec"]["kind"] == "python_module"
        assert out["plan"][0]["inputs"] == {"raw": "raw"}
        assert out["side_effects"] == ["writes-fs"]


def test_resolve_not_runnable_when_cli_missing(tmp_path, monkeypatch):
    _seed_pb(tmp_path)
    monkeypatch.setattr(r, "PLAYBOOKS_ROOT", str(tmp_path))
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        # svg-enrich NOT seeded
        out = r.resolve_playbook(s, "svg-pub")
        assert out["runnable"] is False
        assert out["drift"]["status"] == "broken"


def test_resolve_unknown_slug_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "PLAYBOOKS_ROOT", str(tmp_path))
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        assert r.resolve_playbook(s, "ghost") is None


def test_resolve_playbook_op_registered():
    # the client's `resolve-playbook` A2A skill must reach this handler
    from core.ops_registry import op_by_a2a_skill, validate_input
    op = op_by_a2a_skill("resolve-playbook")
    assert op.mcp_tool == "resolve_playbook"
    assert validate_input(op, {}) == "missing required input keys: ['slug']"
    assert validate_input(op, {"slug": "svg-pub"}) is None
