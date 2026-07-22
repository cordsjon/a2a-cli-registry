from pathlib import Path
from core.store.db import init_db, get_session
from core.models import Cli, Capability
from core.playbooks import queries as q


def _seed_cli(s, slug):
    s.add(Cli(slug=slug, lang="python"))
    s.add(Capability(cli_slug=slug, input_types="a", output_types="x"))
    s.commit()


def _seed_pb(root: Path):
    d = root / "svg-pub"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\ndescription: Enrich SVGs and publish to Etsy\n"
        "tags: [svg, etsy]\nallowed-tools: [svg-enrich]\nstatus: verified\n---\n"
        "1. svg-enrich in: {raw: raw} out: EnrichedSvg\n"
    )


def test_suggest_ranks_matching_playbook(tmp_path, monkeypatch):
    _seed_pb(tmp_path)
    monkeypatch.setattr(q, "PLAYBOOKS_ROOT", str(tmp_path))
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed_cli(s, "svg-enrich")
        res = q.suggest_playbook(s, goal="publish svgs to etsy", limit=3)
        assert [c["slug"] for c in res["candidates"]] == ["svg-pub"]
        assert res["candidates"][0]["drift"]["status"] == "ok"
        assert len(res["candidates"][0]["steps"]) == 1


def test_list_returns_all_with_drift(tmp_path, monkeypatch):
    _seed_pb(tmp_path)
    monkeypatch.setattr(q, "PLAYBOOKS_ROOT", str(tmp_path))
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        # NOTE: svg-enrich NOT seeded -> drift should be "broken"
        res = q.list_playbooks(s)
        assert res["playbooks"][0]["slug"] == "svg-pub"
        assert res["playbooks"][0]["drift"]["status"] == "broken"


def test_get_playbook_includes_steps(tmp_path, monkeypatch):
    _seed_pb(tmp_path)
    monkeypatch.setattr(q, "PLAYBOOKS_ROOT", str(tmp_path))
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed_cli(s, "svg-enrich")
        pb = q.get_playbook(s, "svg-pub")
        assert pb["slug"] == "svg-pub"
        assert len(pb["steps"]) == 1
        assert pb["steps"][0]["cli"] == "svg-enrich"
        assert q.get_playbook(s, "ghost") is None
