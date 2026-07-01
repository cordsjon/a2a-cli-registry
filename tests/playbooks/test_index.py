from core.store.db import init_db, get_session
from core.models import Cli, Capability
from core.playbooks.skillmd import Playbook, PlaybookStep
from core.playbooks.index import rebuild_index, retrieve, stale_against_index


def _seed_cli(session, slug, in_t="a", out_t="x"):
    session.add(Cli(slug=slug, lang="python"))
    session.add(Capability(cli_slug=slug, input_types=in_t, output_types=out_t))
    session.commit()


def _pb(slug, desc, tags, clis):
    steps = tuple(PlaybookStep(id=f"s{i+1}", cli=c, inputs={}, out_type="T") for i, c in enumerate(clis))
    return Playbook(slug=slug, description=desc, tags=tuple(tags), allowed_tools=tuple(clis), steps=steps)


def test_rebuild_then_retrieve_by_keyword(tmp_path):
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed_cli(s, "svg-enrich")
        _seed_cli(s, "ledger")
        pbs = [
            _pb("svg-pub", "Enrich SVGs and publish to Etsy", ["svg", "etsy"], ["svg-enrich"]),
            _pb("acct", "Reconcile the ledger", ["finance"], ["ledger"]),
        ]
        assert rebuild_index(s, pbs) == 2
        assert retrieve(s, "etsy", limit=5) == ["svg-pub"]
        assert set(retrieve(s, "", limit=5)) == {"acct", "svg-pub"}


def test_stale_against_index_detects_signature_change(tmp_path):
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed_cli(s, "svg-enrich", in_t="a", out_t="x")
        pb = _pb("svg-pub", "Enrich", ["svg"], ["svg-enrich"])
        rebuild_index(s, [pb])
        assert stale_against_index(s, pb) == []
        # mutate the CLI's output type -> signature drifts
        from sqlmodel import select
        cap = s.exec(select(Capability).where(Capability.cli_slug == "svg-enrich")).first()
        cap.output_types = "x,y"
        s.add(cap); s.commit()
        assert stale_against_index(s, pb) == ["svg-enrich"]
