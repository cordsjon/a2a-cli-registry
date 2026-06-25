# tests/test_remediation_cli.py  (orchestration half)
import json
import pytest
from sqlmodel import select
from core.models import Cli
from core.remediation.run import run_remediate, read_unhealthy, write_proposals


def _seed(db, slug, desc, status="unhealthy", path="/x/c.py"):
    db.add(Cli(slug=slug, lang="python", description=desc,
               health_status=status, path=path))
    db.commit()


class NoopPaperclip:
    def __init__(self):
        self.filed = None
    def file(self, proposals, *, dry_run=True):
        self.filed = (list(proposals), dry_run)
        return []


def test_read_unhealthy_only(db):
    _seed(db, "bad", "ModuleNotFoundError: No module named 'numpy'", "unhealthy")
    _seed(db, "good", "", "healthy")
    rows = read_unhealthy(db)
    assert [r.slug for r in rows] == ["bad"]


def test_run_classifies_and_writes_envelope(db, tmp_path):
    _seed(db, "bad", "ModuleNotFoundError: No module named 'numpy'")
    out = tmp_path / "proposals.json"
    pc = NoopPaperclip()
    summary = run_remediate(
        db, out_path=str(out), do_file=False, apply_safe=False,
        max_llm_calls=0, session_id="sid", generated_at="2026-06-25T20:00:00Z",
        paperclip=pc)
    env = json.loads(out.read_text())
    assert env["session_id"] == "sid"
    assert env["map_version"] == 1
    assert env["proposals"][0]["failure_class"] == "pip-3rd-party"
    assert env["proposals"][0]["target"] == "numpy"
    assert pc.filed[1] is True  # dry_run (do_file=False)


def test_run_skips_hermes_when_max_calls_zero(db, tmp_path):
    _seed(db, "u", "totally opaque failure")  # classifies to unknown
    out = tmp_path / "p.json"
    called = {"n": 0}

    class SpyHermes:
        def diagnose(self, unknowns, *, max_calls):
            called["n"] += 1
            return [], []
    run_remediate(db, out_path=str(out), do_file=False, apply_safe=False,
                  max_llm_calls=0, session_id="s", generated_at="t",
                  hermes=SpyHermes(), paperclip=NoopPaperclip())
    assert called["n"] == 0  # max_llm_calls=0 -> Hermes never invoked


def test_run_invokes_hermes_on_unknowns(db, tmp_path):
    _seed(db, "u", "totally opaque failure")
    _seed(db, "k", "ModuleNotFoundError: No module named 'numpy'")  # one known + one unknown
    out = tmp_path / "p.json"
    seen = {}

    class SpyHermes:
        def diagnose(self, unknowns, *, max_calls):
            seen["slugs"] = [r.slug for r in unknowns]
            seen["cap"] = max_calls
            return [], []
    run_remediate(db, out_path=str(out), do_file=False, apply_safe=False,
                  max_llm_calls=3, session_id="s", generated_at="t",
                  hermes=SpyHermes(), paperclip=NoopPaperclip())
    assert seen["slugs"] == ["u"]
    assert seen["cap"] == 3
    env = json.loads(out.read_text())
    assert len(env["proposals"]) == 2  # replace semantics: count unchanged


def test_apply_safe_requested_caught_and_still_writes(db, tmp_path):
    _seed(db, "n", "ModuleNotFoundError: No module named 'numpy'")
    out = tmp_path / "p.json"

    class StubFixer:
        def apply(self, proposals):
            raise NotImplementedError("stubbed")
    summary = run_remediate(
        db, out_path=str(out), do_file=False, apply_safe=True, max_llm_calls=0,
        session_id="s", generated_at="t", safe_fixer=StubFixer(),
        paperclip=NoopPaperclip())
    assert summary["apply_safe_requested"] is True
    assert out.exists()  # proposals.json written despite stubbed apply


def test_write_proposals_is_atomic_overwrite(tmp_path):
    out = tmp_path / "p.json"
    write_proposals({"a": 1}, str(out))
    write_proposals({"a": 2}, str(out))  # overwrite
    assert json.loads(out.read_text()) == {"a": 2}
    # no leftover temp files in the dir
    assert {p.name for p in tmp_path.iterdir()} == {"p.json"}
