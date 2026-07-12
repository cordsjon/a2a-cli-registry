# `plan_chain`: Fix Candidate-Cap Starvation — Design

> **US-CLIREG-PLANCHAIN-CAP-STARVATION-01** (BACKLOG Ideation, P3/S). Root-cause
> fix for a planner correctness bug: late-iterated start slugs can be silently
> excluded from `plan_cli_chain`'s results purely due to dict-iteration order.

## Problem

`core/planner/search.py`'s `plan_chain()` has two independent candidate-cap
checks:

```python
for start in starts:
    if len(candidates) >= max_candidate_chains:   # <-- outer break (THE BUG)
        break
    q = deque([([start], {start}, [])])
    while q and len(candidates) < max_candidate_chains:  # <-- inner cap (fine)
        ...
candidates.sort(key=lambda c: c.sort_key())
return candidates[:max_candidate_chains]           # <-- final slice (fine)
```

The **outer** break (line 104-105) exits the `for start in starts` loop
entirely once the cap is hit — **before** `candidates.sort()` ever runs. This
means the function returns "the first `max_candidate_chains` candidates found
in `starts`'s dict-iteration order," not "the `max_candidate_chains`
best-ranked candidates." A start slug late in iteration order that would sort
first (shortest chain, fewest side effects, per `Chain.sort_key()`) is
silently invisible to planning whenever 100+ other, worse-ranked start slugs
happen to iterate first.

**Confirmed live** (2026-07-12, during grounding review for the sibling
`US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01` fix): against the full 474-CLI live
registry, `plan_chain(goal_inputs=['text'], goal_outputs=['text'],
allow_side_effects=set())` at the public default (`max_candidate_chains=100`)
returns exactly 100 candidates, none of which is `send_mail`. Raising the cap
to 1000 returns 449 candidates total, with `send_mail` present at sorted
position 18 — proving it would have ranked well inside any reasonable N, had
it not been starved out by iteration order.

**No caller currently overrides `max_candidate_chains`.** The only production
call site, `core/catalog/queries.py:165` (`plan_cli_chain`, exposed as the MCP
op `plan_cli_chain`), calls `_plan(session, goal_inputs, goal_outputs,
allow_side_effects or [])` — positionally, with no `max_candidate_chains` or
`max_chain_depth` argument — so every real caller is stuck on the hardcoded
default of 100 with no way to override it externally today. This bug affects
every goal whose `goal_inputs` matches 100+ CLIs as valid start slugs, not
just the `send_mail` case it was found alongside.

## Fix

Remove the outer loop's early break. Leave the inner while-loop's cap and the
final sort-and-slice cap untouched:

```python
for start in starts:
    q = deque([([start], {start}, [])])
    while q and len(candidates) < max_candidate_chains:
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

**Why scope the fix to only the outer check:** the codebase has two distinct
cap mechanisms doing two distinct jobs. The inner `while` loop
(`while q and len(candidates) < max_candidate_chains`) is a per-start circuit
breaker — it bounds how much BFS work a *single* start slug's own subtree can
do before the loop moves on to the next start. It is not the starvation bug:
every start slug gets its own fresh `deque`, so one start's BFS exhausting the
inner cap does not prevent the *next* start from being visited — that's
purely the outer break's doing. Keeping the inner cap preserves a real safety
valve (bounding worst-case work if one single start's own subgraph is large
or densely connected) with zero change to its behavior. `candidates[:max_candidate_chains]`
at the end is unchanged — the cap continues to limit the *returned* result
size, just now correctly (best N after sorting, not first N found).

### Perf trade-off (live-measured, not assumed)

Measured directly against the live 474-CLI registry (`~/.hermes/cli-registry.db`),
2026-07-12:

| Scenario | Result |
|---|---|
| `goal_inputs=['text'], goal_outputs=['text']`, cap=100 (today's default) | 100 candidates, 16.4ms |
| Same goal, cap=1000 | 449 candidates, 14.5ms |
| Same goal, cap=10000 (effectively uncapped enumeration) | 449 candidates, 14.5ms |
| Deliberately pathological: unsatisfiable goal (`goal_outputs=['nonexistent:type']`), every side-effect class allowed (forces full BFS exhaustion to `max_chain_depth` across every start slug), cap=100000 | 0 candidates, 329.1ms |

Removing the outer cap costs **no measurable latency** in the realistic case
(the true candidate count, 449, is already reached well under today's
default cap once enumeration isn't gated) and costs **~330ms** in a
deliberately constructed worst case designed to force maximum BFS work with
zero early termination. Both are well within budget for an
interactive/API-latency planning call. This fix does not change the
`max_candidate_chains` default (still 100) — it only ensures that value
correctly bounds the *sorted, returned* result rather than gating which start
slugs are considered at all.

## Non-goals

- Changing `max_candidate_chains`'s default value (100) — out of scope; this
  fix corrects what the cap bounds, not its magnitude.
- Exposing `max_candidate_chains`/`max_chain_depth` as caller-overridable
  parameters on `plan_cli_chain` (`core/catalog/queries.py`) — no caller
  needs this today; a separate concern from the starvation bug itself.
- Any change to the inner while-loop's cap, `_hop_excluded`, `_slug_side_effect`,
  or `Chain.sort_key()` — this fix touches exactly one control-flow line.
- Performance work beyond measuring the existing implementation's live
  behavior — no algorithmic changes (e.g. early-terminate on provably-optimal
  chains) are proposed; the measured cost is already acceptable.

## Testing

`tests/test_planner.py` (currently 17 tests) gains 1 new case:

- `test_late_iterated_start_slug_not_starved_by_cap` — construct N (e.g. 150)
  synthetic start slugs, each satisfying `goal_in` and each a single-hop
  dead-end (side_effect that gets excluded, or a non-matching output) except
  for one, placed deliberately last by using a Python dict (insertion order
  preserved, matching `_cap_index`'s `dict.setdefault` construction), which
  is the only slug producing `goal_out`. Before the fix: assert this slug is
  MISSING from `plan_chain`'s results at the default `max_candidate_chains=100`
  (documents the bug — this assertion inverts once the fix lands, so the test
  itself changes from red to green rather than being written red-only against
  unfixed code and never re-checked). After the fix: assert the slug IS
  present. Directly satisfies AC-01/AC-03 of the BACKLOG ticket.

Full `a2a-cli-registry` suite must stay green (443 passed / 1 pre-existing
unrelated failure in `test_web_render.py`, reconfirmed by a fresh full run
2026-07-12 immediately before writing this spec — same result as the sibling
`US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01` work found, confirmed unrelated there
via diff-scope and last-touched-commit checks, not reintroduced or touched by
this fix).

**Live verification (AC-04):** re-run the exact probe from the Problem
section — `plan_cli_chain(goal_inputs=['text'], goal_outputs=['text'],
allow_side_effects=set())` against the live registry — and confirm `send_mail`
now appears in the result at the public default cap (100), not just the
raised-cap probe used to originally diagnose the bug.

## Rollback

Single-line revert: restore the two-line `if len(candidates) >=
max_candidate_chains: break` guard at the top of the `for start in starts`
loop. No data changes, no migration, no dependent code — this is a pure
control-flow fix in one function.

## Files touched

- Modify: `core/planner/search.py` (`plan_chain`, remove 2 lines: the outer
  loop's cap check and its `break`)
- Test: `tests/test_planner.py` (1 new case)

## Acceptance Criteria

(Mirrors the BACKLOG ticket's ACs, restated precisely against this design.)

- **AC-01** — A minimal reproduction test with N > `max_candidate_chains`
  synthetic start slugs, where only the last-iterated one produces
  `goal_out`, demonstrates the slug is excluded from `plan_chain`'s results
  at today's (pre-fix) behavior.
- **AC-02** — Fix implemented: outer loop's early break removed; inner
  while-loop cap and final sort+slice cap unchanged. Perf trade-off
  documented above with live-measured numbers (not estimated).
- **AC-03** — The AC-01 reproduction test passes post-fix. Full
  `a2a-cli-registry` test suite green: 444 passed (443 current baseline + 1
  new planner test), the 1 pre-existing unrelated `test_web_render.py`
  failure untouched.
- **AC-04 (live)** — `plan_cli_chain(goal_inputs=['text'], goal_outputs=['text'],
  allow_side_effects=set())` against the live registry (474 CLIs, assuming
  `US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01`'s registry-enum fix has shipped —
  confirmed shipped 2026-07-12, `a2a-cli-registry` commit `f856628`) includes
  `send_mail` as a candidate at the **public default** cap (100), not just
  under a raised cap. This is the AC that was explicitly NOT satisfiable by
  the sibling ticket alone — it closes that gap.
