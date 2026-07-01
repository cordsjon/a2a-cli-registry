# core/playbooks/skillmd.py
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PlaybookStep:
    id: str
    cli: str
    inputs: dict
    out_type: str


@dataclass(frozen=True)
class Playbook:
    slug: str
    description: str
    tags: tuple = ()
    allowed_tools: tuple = ()
    steps: tuple = ()
    status: str = "draft"


_FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
# matches: "1. svg-enrich  in: {raw: raw}   out: EnrichedSvg"
_STEP_RE = re.compile(
    r"^\s*\d+\.\s+(?P<cli>[\w-]+)\s+in:\s*\{(?P<inputs>[^}]*)\}\s+out:\s*(?P<out>\w+)\s*$"
)


def _parse_inline_list(value: str) -> tuple:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    items = [v.strip() for v in value.split(",") if v.strip()]
    return tuple(items)


def _parse_inputs(raw: str) -> dict:
    out = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        k, _, v = pair.partition(":")
        out[k.strip()] = v.strip()
    return out


def parse_skillmd(text: str, slug: str) -> Playbook:
    m = _FM_RE.match(text)
    if not m:
        raise ValueError(f"SKILL.md for {slug!r} has no YAML frontmatter")
    fm_block, body = m.group(1), m.group(2)

    fm = {}
    for line in fm_block.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip()

    steps = []
    for line in body.splitlines():
        sm = _STEP_RE.match(line)
        if not sm:
            continue
        steps.append(
            PlaybookStep(
                id=f"s{len(steps) + 1}",
                cli=sm.group("cli"),
                inputs=_parse_inputs(sm.group("inputs")),
                out_type=sm.group("out"),
            )
        )

    return Playbook(
        slug=slug,
        description=fm.get("description", ""),
        tags=_parse_inline_list(fm.get("tags", "")),
        allowed_tools=_parse_inline_list(fm.get("allowed-tools", "")),
        steps=tuple(steps),
        status=fm.get("status", "draft"),
    )
