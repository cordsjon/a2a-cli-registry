# core/planner/search.py
from collections import deque
from dataclasses import dataclass, field
from sqlmodel import select
from core.models import Capability, CliEdge

# excluded-by-default side-effect classes (fail-UNSAFE): destructive + unknown
_UNSAFE_DEFAULT = {"destructive", "unknown"}
_CONFIDENCE_RANK = {"declared": 0, "inferred": 1}   # lower rank = higher confidence


@dataclass(order=False)
class Chain:
    slugs: list[str]
    length: int
    side_effect_count: int
    min_confidence_rank: int       # max over hops of _CONFIDENCE_RANK (worst hop)
    hops: list[dict] = field(default_factory=list)

    def sort_key(self):
        # length asc, side-effect count asc, min-confidence DESC (rank asc since
        # lower rank = higher confidence), slug-sequence asc (final tiebreak)
        return (self.length, self.side_effect_count, self.min_confidence_rank, tuple(self.slugs))


def _cap_index(session):
    idx = {}
    for c in session.exec(select(Capability)).all():
        idx.setdefault(c.cli_slug, []).append(c)
    return idx


def _slug_side_effect(caps_for_slug) -> str:
    order = ["destructive", "unknown", "network", "writes-fs", "none"]
    present = {c.side_effect for c in caps_for_slug}
    for level in order:
        if level in present:
            return level
    return "unknown"


def _slug_confidence_rank(caps_for_slug) -> int:
    return max(_CONFIDENCE_RANK.get(c.confidence, 1) for c in caps_for_slug)


def _slug_produces(caps_for_slug) -> set[str]:
    return {p for c in caps_for_slug for p in c.output_types.split(",") if p}


def _slug_consumes(caps_for_slug) -> set[str]:
    return {p for c in caps_for_slug for p in c.input_types.split(",") if p}


def plan_chain(session, goal_inputs, goal_outputs, allow_side_effects=None,
               max_chain_depth=4, max_candidate_chains=100):
    allow_side_effects = set(allow_side_effects or [])
    excluded = _UNSAFE_DEFAULT - allow_side_effects
    caps = _cap_index(session)
    adjacency = {}
    for e in session.exec(select(CliEdge)).all():
        adjacency.setdefault(e.from_slug, []).append((e.to_slug, e.via_type))

    goal_in, goal_out = set(goal_inputs), set(goal_outputs)
    starts = [s for s, c in caps.items() if _slug_consumes(c) & goal_in]
    candidates = []

    for start in starts:
        # BFS state: (path, visited, hops). Cycle guard via visited set.
        q = deque([([start], {start}, [])])
        while q and len(candidates) < max_candidate_chains:
            path, visited, hops = q.popleft()
            tail = path[-1]
            # excluded side-effect prunes the path entirely
            if _slug_side_effect(caps[tail]) in excluded:
                continue
            if _slug_produces(caps[tail]) & goal_out:
                candidates.append(_finalize(path, caps))
                continue
            if len(path) >= max_chain_depth:
                continue
            for (nxt, via) in adjacency.get(tail, []):
                if nxt in visited:
                    continue                       # cycle guard
                q.append((path + [nxt], visited | {nxt},
                          hops + [{"from": tail, "to": nxt, "via_type": via}]))

    candidates.sort(key=lambda c: c.sort_key())
    return candidates[:max_candidate_chains]


def _finalize(path, caps) -> Chain:
    se_count = sum(1 for s in path if _slug_side_effect(caps[s]) != "none")
    min_conf = max(_slug_confidence_rank(caps[s]) for s in path)
    hops = []
    for s in path:
        se = _slug_side_effect(caps[s])
        conf = "inferred" if _slug_confidence_rank(caps[s]) else "declared"
        prov = f"{se} ({conf}{', unverified' if conf == 'inferred' else ''})"
        hops.append({"slug": s, "side_effect": se, "provenance": prov})
    return Chain(slugs=path, length=len(path), side_effect_count=se_count,
                 min_confidence_rank=min_conf, hops=hops)
