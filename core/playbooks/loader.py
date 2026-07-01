# core/playbooks/loader.py
from pathlib import Path
from core.playbooks.skillmd import parse_skillmd, Playbook


def load_playbooks(root: str = "playbooks") -> list[Playbook]:
    base = Path(root)
    if not base.is_dir():
        return []
    out: list[Playbook] = []
    for child in sorted(base.iterdir()):
        skill = child / "SKILL.md"
        if not skill.is_file():
            continue
        out.append(parse_skillmd(skill.read_text(), slug=child.name))
    out.sort(key=lambda p: p.slug)
    return out
