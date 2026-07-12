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
    order = ["destructive", "unknown", "network", "external", "writes-fs", "none"]
    present = {c.side_effect for c in caps_for_slug}
    for level in order:
        if level in present:
            return level
    return "unknown"


def _slug_confidence_rank(caps_for_slug) -> int:
    return max(_CONFIDENCE_RANK.get(c.confidence, 1) for c in caps_for_slug)


def _hop_excluded(caps_for_slug, allow_side_effects) -> bool:
    """Fail-UNSAFE prune decision for a single hop (slug). A hop is excluded if:
      - its worst side_effect is in {destructive, unknown} and that class is NOT
        allowed, OR
      - it carries an INFERRED side_effect with real blast radius (non-"none")
        that is NOT in allow_side_effects. An inferred side_effect is unverified,
        so it must fail UNSAFE (spec §8, lines 34/228). An inferred "none" hop
        has no blast radius and is always allowed (confidence alone never excludes).
    The operator override is unified on allow_side_effects: opting into a
    side-effect CLASS accepts that blast radius whether declared or inferred.
    """
    se = _slug_side_effect(caps_for_slug)
    if se == "none":
        return False
    excluded = _UNSAFE_DEFAULT - allow_side_effects
    if se in excluded:
        return True
    # writes-fs / network: excluded by default only when INFERRED and not allowed.
    if se in allow_side_effects:
        return False
    # is the (non-none, non-unsafe-default) side_effect carried by an inferred cap?
    for c in caps_for_slug:
        if c.side_effect == se and _CONFIDENCE_RANK.get(c.confidence, 1) >= 1:
            return True
    return False


def _slug_produces(caps_for_slug) -> set[str]:
    return {p for c in caps_for_slug for p in c.output_types.split(",") if p}


def _slug_consumes(caps_for_slug) -> set[str]:
    return {p for c in caps_for_slug for p in c.input_types.split(",") if p}


def plan_chain(session, goal_inputs, goal_outputs, allow_side_effects=None,
               max_chain_depth=4, max_candidate_chains=100):
    allow_side_effects = set(allow_side_effects or [])
    caps = _cap_index(session)
    adjacency = {}
    for e in session.exec(select(CliEdge)).all():
        adjacency.setdefault(e.from_slug, []).append((e.to_slug, e.via_type))

    goal_in, goal_out = set(goal_inputs), set(goal_outputs)
    # An empty goal_in means "no input constraint" (a query-only goal like
    # "list files" or "check status"). `_slug_consumes(c) & goal_in` is always
    # empty/falsy when goal_in is empty, which used to make EVERY CLI —
    # including the ones with input_types="" that exist specifically for this
    # case — permanently unreachable. Only match no-declared-input CLIs when
    # goal_in is empty; a CLI with a real declared input type still requires
    # the caller to name it (goal_in non-empty and intersecting).
    if goal_in:
        starts = [s for s, c in caps.items() if _slug_consumes(c) & goal_in]
    else:
        starts = [s for s, c in caps.items() if not _slug_consumes(c)]
    candidates = []

    for start in starts:
        if len(candidates) >= max_candidate_chains:
            break
        # BFS state: (path, visited, hops). Cycle guard via visited set.
        q = deque([([start], {start}, [])])
        while q and len(candidates) < max_candidate_chains:
            path, visited, hops = q.popleft()
            tail = path[-1]
            # fail-UNSAFE prune: destructive/unknown OR inferred-side-effect
            if _hop_excluded(caps[tail], allow_side_effects):
                continue
            if _slug_produces(caps[tail]) & goal_out:
                candidates.append(_finalize(path, caps, hops))
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


def _finalize(path, caps, hop_trace) -> Chain:
    se_count = sum(1 for s in path if _slug_side_effect(caps[s]) != "none")
    min_conf = max(_slug_confidence_rank(caps[s]) for s in path)
    hops = []
    for i, s in enumerate(path):
        se = _slug_side_effect(caps[s])
        conf = "inferred" if _slug_confidence_rank(caps[s]) else "declared"
        prov = f"{se} ({conf}{', unverified' if conf == 'inferred' else ''})"
        hop = {"slug": s, "side_effect": se, "provenance": prov}
        if i > 0:
            edge = hop_trace[i - 1]
            hop["from"] = edge["from"]
            hop["to"] = edge["to"]
            hop["via_type"] = edge["via_type"]
        hops.append(hop)
    return Chain(slugs=path, length=len(path), side_effect_count=se_count,
                 min_confidence_rank=min_conf, hops=hops)
