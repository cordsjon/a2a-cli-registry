import hashlib
from core.store.db import init_db, get_session
from core.models import Cli, Capability
from core.playbooks.skillmd import Playbook, PlaybookStep
from core.playbooks.signature import cli_signature, playbook_drift


def _seed(session, slug, in_types, out_types):
    session.add(Cli(slug=slug, lang="python"))
    session.add(Capability(cli_slug=slug, input_types=in_types, output_types=out_types))
    session.commit()


def _pb(*clis):
    steps = tuple(PlaybookStep(id=f"s{i+1}", cli=c, inputs={}, out_type="T") for i, c in enumerate(clis))
    return Playbook(slug="pb", description="d", allowed_tools=tuple(clis), steps=steps)


def test_signature_is_order_independent(tmp_path):
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed(s, "foo", "b,a", "y,x")
        sig = cli_signature(s, "foo")
        expected = hashlib.sha256(b"a,b|x,y").hexdigest()
        assert sig == expected


def test_signature_none_for_missing(tmp_path):
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        assert cli_signature(s, "nope") is None


def test_drift_reports_missing_cli(tmp_path):
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed(s, "foo", "a", "x")
        d = playbook_drift(s, _pb("foo", "ghost"))
        assert d["status"] == "broken"
        assert d["missing_clis"] == ["ghost"]
