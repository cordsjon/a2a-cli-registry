from pathlib import Path
from core.playbooks.loader import load_playbooks


def _write(root: Path, slug: str, body: str):
    d = root / slug
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body)


def test_loads_all_skillmd_sorted(tmp_path):
    _write(tmp_path, "b-pb", "---\ndescription: B\ntags: [x]\nallowed-tools: [foo]\n---\n1. foo in: {a: raw} out: T\n")
    _write(tmp_path, "a-pb", "---\ndescription: A\ntags: [y]\nallowed-tools: [bar]\n---\n1. bar in: {a: raw} out: T\n")
    (tmp_path / "not-a-playbook").mkdir()   # no SKILL.md -> skipped
    pbs = load_playbooks(str(tmp_path))
    assert [p.slug for p in pbs] == ["a-pb", "b-pb"]
    assert pbs[0].description == "A"


def test_empty_root_returns_empty(tmp_path):
    assert load_playbooks(str(tmp_path)) == []
