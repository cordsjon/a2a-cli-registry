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


# --- goal_actions dimension (spec 2026-07-12-goal-actions-dimension-design §2.2) ---
# Action verbs are matched to terminal intent tags. Map values are pairwise
# disjoint (necessary), but the real guard is the max-one-verb-per-live-terminal
# invariant enforced in _action_terminals (sufficient): a multi-tagged terminal
# matching >1 verb is a hard integrity error, never a silent pick.
_ACTION_REQUIRES_TAG = {
    "email":      {"send"},       # send_mail carries 'send' post-retag (§8 step 0)
    "notify":     {"notify"},     # a pure-notification terminal (none live today)
    "webhook":    {"webhook"},
    "file_write": {"persist"},
}


def _slug_intent_tags(caps_for_slug) -> set[str]:
    return {t for c in caps_for_slug for t in c.intent_tags.split(",") if t}


def _action_terminals(caps, goal_actions) -> set[str]:
    """Slugs satisfying a requested action verb (§2.2). Raises ValueError on an
    unknown verb (§2.8 structured-error contract) or on any slug whose intent
    tags match more than one map verb (max-one-verb-per-live-terminal)."""
    unknown = [a for a in goal_actions if a not in _ACTION_REQUIRES_TAG]
    if unknown:
        raise ValueError(
            f"unknown action verb: {unknown[0]}; known: {sorted(_ACTION_REQUIRES_TAG)}")
    terminals = set()
    for slug, caps_for_slug in caps.items():
        tags = _slug_intent_tags(caps_for_slug)
        verbs = [a for a in _ACTION_REQUIRES_TAG if _ACTION_REQUIRES_TAG[a] & tags]
        if len(verbs) > 1:
            raise ValueError(
                f"action verb integrity: terminal '{slug}' matches multiple verbs "
                f"{sorted(verbs)}")
        if verbs and verbs[0] in goal_actions:
            terminals.add(slug)
    return terminals


def plan_chain(session, goal_inputs, goal_outputs, allow_side_effects=None,
               max_chain_depth=4, max_candidate_chains=100, goal_actions=None):
    allow_side_effects = set(allow_side_effects or [])
    goal_actions = list(goal_actions or [])
    if len(goal_actions) > 1:
        # §7: one final action hop per goal; forward-compatible list, explicit cap
        raise ValueError(f"multiple action verbs not supported: {sorted(goal_actions)}")
    caps = _cap_index(session)
    # §2.2: validates verbs and enforces max-one-verb-per-live-terminal.
    action_terminals = _action_terminals(caps, goal_actions) if goal_actions else set()
    adjacency = {}
    for e in session.exec(select(CliEdge)).all():
        adjacency.setdefault(e.from_slug, []).append((e.to_slug, e.via_type))

    # §2.5: planning-time terminal edge synthesis — send_mail-class terminals
    # have zero persisted incoming edges (edges.py:30 down-weights bare hub
    # types). Synthesize (producer -> terminal, via H) IN MEMORY, scoped
    # strictly to terminals matching a requested action; the general hub
    # down-weight and the persisted CliEdge table are untouched.
    if goal_actions:
        for term in sorted(action_terminals):
            term_in = _slug_consumes(caps[term])
            for prod, prod_caps in caps.items():
                if prod == term:
                    continue
                for hub in sorted(_slug_produces(prod_caps) & term_in):
                    pairs = adjacency.setdefault(prod, [])
                    if (term, hub) not in pairs:
                        pairs.append((term, hub))

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
        # BFS state: (path, visited, hops). Cycle guard via visited set.
        q = deque([([start], {start}, [])])
        while q:
            path, visited, hops = q.popleft()
            tail = path[-1]
            if not goal_actions:
                # legacy path — byte-identical to the pre-goal_actions planner
                # (§2.3: "the new clauses are gated behind non-empty goal_actions")
                if _hop_excluded(caps[tail], allow_side_effects):
                    continue
                if _slug_produces(caps[tail]) & goal_out:
                    candidates.append(_finalize(path, caps, hops))
                    continue
            else:
                if _hop_excluded(caps[tail], allow_side_effects):
                    continue
                if tail in action_terminals:
                    # §2.3 terminal predicate: the final hop is the action; the
                    # artifact must come from an EARLIER hop (path[:-1]), so a
                    # dual-capable CLI never satisfies a compound goal in 1 hop.
                    artifact_met = (not goal_out) or any(
                        _slug_produces(caps[s]) & goal_out for s in path[:-1])
                    if artifact_met:
                        candidates.append(_finalize(path, caps, hops))
                    # action terminals are FINAL-position only (§2.6/§2.7):
                    # never expand through one — its confirmation output must
                    # not feed a later hop as a fake artifact.
                    continue
                # §2.4: a producer hop does NOT short-circuit when an action is
                # requested — fall through to neighbor expansion.
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
