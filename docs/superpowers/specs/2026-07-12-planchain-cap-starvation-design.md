# `plan_chain`: Fix Candidate-Cap Starvation — Design

> **US-CLIREG-PLANCHAIN-CAP-STARVATION-01** (BACKLOG Ideation, P3/S). Root-cause
> fix for a planner correctness bug: a favorably-ranked start slug can be
> silently excluded from `plan_cli_chain`'s results because worse-ranked
> candidates from earlier-iterated starts fill the collection cap first.
>
> **Revision note (2026-07-12):** this spec's first draft proposed removing
> only the outer loop's early break. A Codex grounding review found — and
> live re-verification in this repo confirmed — that fix does not work: the
> inner `while` loop's cap check is gated on the *same* global candidate
> counter, not a per-start budget, so removing only the outer break leaves
> every later start's freshly-created queue permanently unconsumed once the
> cap fills. This revision corrects the fix, the reproduction test, and the
> "100+ CLIs" framing, all of which the first draft got wrong. See "What the
> first draft got wrong" below.

## Problem

`core/planner/search.py`'s `plan_chain()` (lines 81-126) has **two
collection-time candidate-cap checks that both read the same global
`len(candidates)` counter**, plus a final cap on the sorted return:

```python
for start in starts:
    if len(candidates) >= max_candidate_chains:      # outer gate (line 104-105)
        break
    q = deque([([start], {start}, [])])
    while q and len(candidates) < max_candidate_chains:  # inner gate (line 108)
        path, visited, hops = q.popleft()
        tail = path[-1]
        if _hop_excluded(caps[tail], allow_side_effects):
            continue
        if _slug_produces(caps[tail]) & goal_out:
            candidates.append(_finalize(path, caps, hops))
            continue
        if len(path) >= max_chain_depth:
            continue
        for (nxt, via) in adjacency.get(tail, []):
            if nxt in visited:
                continue
            q.append((path + [nxt], visited | {nxt},
                      hops + [{"from": tail, "to": nxt, "via_type": via}]))

candidates.sort(key=lambda c: c.sort_key())
return candidates[:max_candidate_chains]              # final slice (line 126)
```

Both the outer `break` and the inner `while` condition test
`len(candidates) < max_candidate_chains` — the same list, the same counter.
Once **any** combination of earlier starts has collectively appended
`max_candidate_chains` candidates, every subsequent start's BFS body never
executes even once (its `while q and len(candidates) < max_candidate_chains`
is `False` from the first check), and the outer loop keeps iterating over
starts doing nothing until it also hits its own now-redundant break. The
practical effect: `candidates.sort()` only ever sorts whichever candidates
happened to accumulate first in `starts`'s iteration order — never the truly
best-ranked ones, whenever total candidates generated before ranking exceeds
the cap.

**This is not about the number of valid start slugs.** A goal can have as
few as 32 valid starts (the live-measured count for `goal_inputs=['text']`
against the current registry) and still trigger starvation, because a single
start's BFS can itself produce many candidate chains via multi-hop fan-out.
Starvation is driven by **total candidates generated before a favorably-
ranked one is reached**, not by how many start slugs exist.

**Confirmed live** (2026-07-12, Codex grounding review + independent
reproduction in this repo): against the live registry (475 CLIs as of this
writing — the sibling `US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01` spec cited 474
a few hours earlier; registry count drifts and is not itself a defect),
`plan_chain(goal_inputs=['text'], goal_outputs=['text'],
allow_side_effects=set())` at the public default (`max_candidate_chains=100`)
returns exactly 100 candidates, none of which is `send_mail`. Raising the cap
to 1000 returns 449 candidates total, with `send_mail` present at zero-based
sorted index 18 (the 19th-ranked result) — proving it ranks well inside any
reasonable N once actually enumerated, and was purely starved by iteration
order, not by being poorly ranked.

**No caller currently overrides `max_candidate_chains`.** The only production
call site, `core/catalog/queries.py:165` (`plan_cli_chain`, the sole
production invocation confirmed by grep — the public MCP op registered at
`core/ops_registry.py:37` exposes only `goal_inputs`, `goal_outputs`,
`allow_side_effects` in its schema, with neither cap externally expressible),
calls `_plan(session, goal_inputs, goal_outputs, allow_side_effects or [])`
positionally, with no `max_candidate_chains`/`max_chain_depth` argument — so
every real caller is stuck on the hardcoded default of 100 with no way to
override it externally today.

### What the first draft got wrong

- **Proposed fix didn't work.** Removing only the outer break (line 104-105)
  and leaving the inner `while` condition intact: live-reproduced in this
  repo, `send_mail` remained absent from the cap=100 result — identical
  output to the unfixed code. The inner condition silently absorbs the same
  starvation effect the outer one was blamed for alone.
- **"100+ CLIs as valid start slugs" framing was wrong.** The live registry
  has only 32 valid starts for the `goal_inputs=['text']` probe; starvation
  is caused by candidate *fan-out* per start (a single start's BFS can
  generate dozens of chains through multi-hop adjacency), not by the number
  of starts.
- **Proposed AC-01 reproduction test didn't reproduce the bug.** A test with
  150 dead-end starts (each excluded or non-matching) plus 1 winning start
  never fills the candidate cap at all — the winner is never starved because
  nothing else is contending for cap space with it. A valid reproduction
  needs earlier starts that actually **do** produce competing candidates
  (see Testing section below).
- **Perf claim of ~330ms cited an experiment that didn't measure the
  proposed patch.** The pathological unsatisfiable-goal probe never
  increments `candidates` at all (nothing matches `goal_out`), so neither
  candidate cap ever activates in that scenario — it measured pre-existing
  full-BFS-exhaustion cost, not the marginal cost of the code change.
- **Test-count citation was stale/inaccurate relative to a differently-scoped
  full-suite run** (a Codex run in a network-restricted sandbox produced
  17 additional environment-specific failures — socket binds forbidden,
  network/pip e2e — not reproducible in this repo's normal dev environment;
  this spec's own fresh, non-sandboxed run reconfirmed 443 passed / 1
  pre-existing unrelated failure, matching the number now cited below).

## Fix

Remove **both** collection-time gates — the outer `break` and the inner
`while` loop's `len(candidates) < max_candidate_chains` condition — so every
reachable candidate chain (up to `max_chain_depth`, per existing behavior) is
enumerated before sorting. Cap only the final, sorted return:

```python
for start in starts:
    q = deque([([start], {start}, [])])
    while q:
        path, visited, hops = q.popleft()
        tail = path[-1]
        if _hop_excluded(caps[tail], allow_side_effects):
            continue
        if _slug_produces(caps[tail]) & goal_out:
            candidates.append(_finalize(path, caps, hops))
            continue
        if len(path) >= max_chain_depth:
            continue
        for (nxt, via) in adjacency.get(tail, []):
            if nxt in visited:
                continue
            q.append((path + [nxt], visited | {nxt},
                      hops + [{"from": tail, "to": nxt, "via_type": via}]))

candidates.sort(key=lambda c: c.sort_key())
return candidates[:max_candidate_chains]
```

`max_chain_depth` (line 117-118, `if len(path) >= max_chain_depth: continue`)
remains the only bound on BFS growth during collection — it already caps
path length per chain, independent of the candidate-count gates being
removed here. There is no unbounded-growth risk introduced: the search space
is inherently finite (bounded by chain depth × registry size), just not
artificially truncated mid-enumeration by an order-dependent counter
anymore.

**Live-verified this actually fixes the bug** (in-repo reproduction, not
just reasoning): with both gates removed and only the final slice retained,
the `winner`-vs-100-`worse` synthetic scenario in Testing below returns
`winner` at position 0 (correctly ranked first, since it has fewer side
effects) — where the original code and the outer-only-removed variant both
returned `winner` absent entirely.

### Perf trade-off (live-measured against the actual proposed patch)

Measured directly against the live registry (`~/.hermes/cli-registry.db`,
475 CLIs), 2026-07-12, using the corrected fix (both gates removed, final
slice only):

| Scenario | Result |
|---|---|
| `goal_inputs=['text'], goal_outputs=['text']`, current (buggy) code, cap=100 | 100 candidates, no `send_mail` |
| Same goal, **fixed** code, cap=100 | 100 candidates returned, `send_mail` present, ~19ms |
| Deliberately pathological: unsatisfiable goal (`goal_outputs=['nonexistent:type']`), every side-effect class allowed (forces full BFS exhaustion to `max_chain_depth` across every start slug, though this scenario never populates `candidates` either way since nothing matches `goal_out`), **fixed** code | 0 candidates, ~337ms |

The pathological-worst-case number (~337ms) is consistent with the first
draft's ~330ms citation, but for a different reason than originally claimed:
that scenario's cost comes from `max_chain_depth`-bounded BFS exhaustion
across all starts, which is unaffected by removing the candidate-count gates
(nothing in that scenario ever populates `candidates`, so those gates were
never the cost driver there in the first place). The realistic-case cost
(~19ms) is well within budget for an interactive/API-latency planning call
and not meaningfully different from today's ~15-20ms baseline. This fix does
not change `max_candidate_chains`'s default (still 100) — it changes what
that value bounds: the final sorted-and-returned result, not which
candidates get a chance to be ranked at all.

## Non-goals

- Changing `max_candidate_chains`'s default value (100) — out of scope; this
  fix corrects what the cap bounds, not its magnitude.
- Exposing `max_candidate_chains`/`max_chain_depth` as caller-overridable
  parameters on `plan_cli_chain` (`core/catalog/queries.py`) — grep confirms
  no caller currently passes these; adding that capability is a separate,
  unrequested concern from the starvation bug itself.
- Any change to `max_chain_depth`'s role, `_hop_excluded`, `_slug_side_effect`,
  or `Chain.sort_key()` — this fix touches exactly the two candidate-count
  gates and nothing else in the search's control flow.
- Any algorithmic change beyond removing the two order-dependent gates (e.g.
  a best-first/priority-queue search that could avoid full enumeration) —
  the measured cost of full enumeration at current registry scale (475 CLIs)
  is already acceptable; a smarter search is not justified by the numbers.

## Testing

`tests/test_planner.py` (currently 17 tests) gains 1 new case. The
reproduction must construct a scenario where a **favorably-ranked** chain is
excluded because **worse-ranked** chains from earlier-iterated starts
already filled the cap — not merely "many starts exist," which does not by
itself trigger starvation (verified: a 101-dead-end/1-tied-winner variant
does NOT reproduce the bug, since a slug tied on every sort key with the cap
boundary is legitimately excluded by fair ranking, not starved).

- `test_favorably_ranked_start_not_starved_by_worse_earlier_candidates` —
  100 synthetic start slugs (`worse000`..`worse099`), each declaring a
  single-hop chain to `goal_out` with `side_effect='writes-fs'`
  (`side_effect_count=1` once ranked), inserted before 1 additional slug
  (`winner`) with `side_effect='none'` (`side_effect_count=0` — strictly
  better per `Chain.sort_key()`'s second key). Call `plan_chain` with
  `max_candidate_chains=100` (the default). Before the fix: assert `winner`
  is MISSING from the results (the 100 `worse*` candidates fill the cap
  before `winner`'s start is ever visited — live-confirmed this reproduces
  against current code). After the fix: assert `winner` is present, and
  specifically at position 0 (correctly ranked first, not merely included
  somewhere) — live-confirmed against the corrected implementation.
  Directly satisfies AC-01/AC-03 below.

Full `a2a-cli-registry` suite must stay green: 443 passed / 1 pre-existing
unrelated failure (`test_web_render.py::test_render_binds_each_card_to_its_own_health_and_bucket`,
a Unicode-glyph render assertion) as of a fresh, full, non-sandboxed run
2026-07-12 immediately preceding this revision — matching the count found
during the sibling `US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01` work and confirmed
unrelated there via diff-scope and last-touched-commit checks. (A Codex
grounding-review run in a network-restricted sandbox additionally reported
17 environment-specific failures — forbidden local socket binds, a
real-network/pip e2e test — not reproducible in this repo's normal dev
environment and not counted here.)

**Live verification (AC-04):** re-run the exact probe from the Problem
section — `plan_cli_chain(goal_inputs=['text'], goal_outputs=['text'],
allow_side_effects=set())` against the live registry — and confirm `send_mail`
now appears in the result at the public default cap (100), not just under a
raised cap.

## Rollback

Two-line re-addition: restore `if len(candidates) >= max_candidate_chains:
break` at the top of the `for start in starts` loop, and restore `and
len(candidates) < max_candidate_chains` to the inner `while q` condition. No
data changes, no migration, no dependent code — this is a pure control-flow
fix in one function.

## Files touched

- Modify: `core/planner/search.py` (`plan_chain`, remove the outer loop's
  cap-check-and-break, and remove the inner while-loop's cap clause from its
  condition — 2 separate edits, not 1)
- Test: `tests/test_planner.py` (1 new case)

## Acceptance Criteria

(Mirrors the BACKLOG ticket's ACs, restated precisely against this
corrected design.)

- **AC-01** — A minimal reproduction test demonstrates a favorably-ranked
  candidate (fewer side effects, per `Chain.sort_key()`) is excluded from
  `plan_chain`'s results at today's (pre-fix) behavior, specifically because
  worse-ranked candidates from earlier-iterated starts already filled
  `max_candidate_chains` before the favorable one's start was reached — not
  merely "many start slugs exist."
- **AC-02** — Fix implemented: both the outer loop's early break AND the
  inner while-loop's candidate-count condition are removed; only the final
  `candidates.sort()` + `[:max_candidate_chains]` slice remains as a cap.
  `max_chain_depth` continues to bound BFS growth per chain, independent of
  this change. Perf trade-off documented above with live-measured numbers
  against the actual corrected implementation (not the unfixed code, and not
  a scenario that never exercises the changed code path).
- **AC-03** — The AC-01 reproduction test passes post-fix (specifically:
  `winner` present at position 0, not just "present somewhere"). Full
  `a2a-cli-registry` test suite green: 444 passed (443 current baseline + 1
  new planner test), the 1 pre-existing unrelated `test_web_render.py`
  failure untouched.
- **AC-04 (live)** — `plan_cli_chain(goal_inputs=['text'], goal_outputs=['text'],
  allow_side_effects=set())` against the live registry (475 CLIs as of this
  writing; `US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01`'s registry-enum fix has
  shipped, `a2a-cli-registry` commit `f856628`) includes `send_mail` as a
  candidate at the **public default** cap (100), not just under a raised
  cap. This is the AC that was explicitly NOT satisfiable by the sibling
  ticket alone — it closes that gap.

## Codex review — pre-implementation grounding pass

Grounding review performed 2026-07-12 against the first draft of this spec,
the live repository, and a disposable copy of the live registry:

- Confirmed the outer break's exact location (`core/planner/search.py:104-105`)
  and that the quoted code block in the first draft was schematic (elided
  lines, added annotations) rather than a literal excerpt — accurate in
  substance, imprecise in presentation.
- Confirmed `core/catalog/queries.py:165` is the only production call site
  (grep-verified), and that neither cap is externally overridable via the
  registered MCP op (`core/ops_registry.py:37`'s schema).
- **Found the first draft's proposed fix does not work.** Dynamically
  executed an in-memory variant with only the outer break removed: identical
  ranked output to the unfixed code, `send_mail` still absent at cap=100.
  Root cause: the inner `while` loop's condition
  (`len(candidates) < max_candidate_chains`) reads the same global counter,
  so a fresh-but-never-drained `deque` is created per later start but its
  body never executes once the cap has already filled from earlier starts.
- **Found the first draft's proposed AC-01 test does not reproduce the
  bug.** The proposed 150-dead-end-starts-plus-1-winner shape never fills
  the candidate cap (dead ends append nothing), so the winner is never
  contended for cap space and is returned successfully even in unfixed code.
- **Found the "100+ CLIs" framing incorrect.** Live probe has only 32 valid
  starts for the cited goal; starvation depends on total candidates
  generated (via multi-hop fan-out per start), not start-slug count.
- Reproduced the live cap=100/1000 probe results (100 candidates/no
  `send_mail` vs. 449 candidates/`send_mail` present) but could not
  reproduce the exact ~330ms pathological-latency figure in a 10-run
  benchmark (observed range 24.85-42.93ms) — attributed to that scenario
  never actually exercising the code path the fix changes, and to
  machine/load variance; not treated as a hard regression bar in this
  revision, only as directional evidence the marginal cost is small.
- Found the live registry had drifted from 474 to 475 CLIs since the sibling
  spec was written a few hours earlier (expected churn, corrected here) and
  that a broader full-suite run in a network-restricted sandbox surfaced
  17 additional environment-specific failures not present in this repo's
  normal dev environment (not counted in this spec's test-count citations).

**Disposition:** first draft's diagnosis (order-dependent enumeration
starves valid chains) was correct; its proposed patch, reproduction test,
and several supporting claims were not. This revision replaces the Fix,
Testing, and Acceptance Criteria sections with independently re-verified
versions (both the "removing only the outer break doesn't work" finding and
the corrected fix's effectiveness were reproduced live in this repo, not
just accepted from the review). Not yet re-reviewed post-revision — see
Resume/Review Gate.
