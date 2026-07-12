# US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01 — `goal_actions` Redesign

**Date:** 2026-07-12
**Status:** Design (Codex grounding-reviewed pre-write; findings folded in)
**Repos touched:** `a2a-cli-registry` (planner, edges, tests), `hermes-adapter` (tag inference, planner call, bypass guard)

---

## 1. Why this ticket was re-scoped

The ticket was filed on a premise that live inspection (2026-07-12) partly disproved. A
Codex grounding review confirmed the corrections and surfaced a deeper structural blocker
than originally understood. The evidence:

### Confirmed corrections to the original premise
- **AC-02 "email never matches external" is stale.** `send_mail`'s row is
  `notify,send | text | text | external | declared`. `core/planner/search.py::_hop_excluded`
  applies the side-effect-TERM gate only to **inferred** side-effects (the
  `_CONFIDENCE_RANK >= 1` loop, search.py:67-69); `send_mail` is `declared`, so no
  term mismatch excludes it. Live probe: `_hop_excluded(send_mail, {})` /
  `{'email'}` / `{'external'}` all return `False`. It's reachable whenever
  `goal_inputs` intersects its `input_types='text'`; the original AC-02 probe used
  `goal_inputs=[]`, which structurally selects only no-input CLIs (search.py:97-100)
  and so could never select it. (Codex: VERIFIED. Attribution nit — the planner
  mechanism landed in `3a78aa8`; `f856628` is documentation-only.)

- **`seed_anthropic_index` is not a text producer.** Real impl
  (`75_Coaching/10_Consulting/syllabus-2.0/seed/seed_anthropic_index.py`): consumes two
  `Path` args (`--v2-db`, `--task-pct-csv`), writes a SQLite table, and `main()`
  discards the `stats` dict returning 0 — **no stdout data**. Its true side_effect is
  `writes-fs`, not the DB's `none`. It cannot hand off to a downstream hop.

### The deeper blocker Codex surfaced (the real work)
A compound side-effect goal ("produce a report **and** email it") is unplannable today,
for two independent reasons:

1. **Term collapse.** Tag inference (`_TAG_INFER_SYSTEM`, cli_registry.py:490-494)
   instructs the model to put `text` in `goal_outputs` as a *confirmation placeholder*
   for action goals and the action term in `side_effects`. So the produce-hop and the
   action-hop share the single `goal_outputs='text'` term.

2. **Terminal short-circuit.** `plan_chain` accepts a path as terminal the moment
   `_slug_produces(tail) & goal_out` (search.py:112-115). With `goal_out={text}`, the
   first text producer terminates the chain; `send_mail` is never appended. Codex probe:
   an explicit `producer→send_mail` text edge still returned only `[['producer']]`.

3. **No incoming edges to `send_mail`.** Edge formation (edges.py:30) down-weights bare
   hub types (`text`,`json`) — a `text` edge forms only when `from_tags & to_tags` is
   non-empty. No text producer shares `send_mail`'s `notify`/`send` tags, so live
   `incoming_send_mail = 0`. Even without short-circuit, no chain *reaches* send_mail.

**Conclusion:** AC-04/AC-05 require a planner + edge-semantics change, not a config tweak.
Per user decision (2026-07-12), the full redesign lives in this one spec.

---

## 2. Design: the `goal_actions` dimension

Model the action as its own goal dimension, distinct from the produced artifact.

### 2.1 Data-flow change
Tag inference emits three lists instead of overloading two:
- `goal_inputs` — capability tags the user already has (unchanged).
- `goal_outputs` — the **produced artifact only** (e.g. the report `text`). For a pure
  action goal with no artifact, this MAY now be empty (see §2.4 back-compat).
- `goal_actions` — the terminal side-effect the goal demands (e.g. `email`). NEW.

### 2.2 Action → side_effect-enum map
A small explicit dict in the planner (single source of truth), bridging the inference
vocabulary to the registry enum:

```
_ACTION_TO_SIDE_EFFECT = {
    "email": "external", "notify": "external", "webhook": "external",
    "file_write": "writes-fs",
}
```

This is the "bridge" the original AC-02 named — now placed where it belongs (goal→enum
resolution), not in `_hop_excluded`.

### 2.3 `plan_chain` terminal rule
Signature gains `goal_actions: list[str] | None = None`. A path is terminal iff:
- some hop's output intersects `goal_out` **(unchanged)** when `goal_out` is non-empty, AND
- for each action `a` in `goal_actions`, the path's **final hop** is a terminal whose
  `_slug_side_effect(...) == _ACTION_TO_SIDE_EFFECT[a]`.

So a plain producer no longer short-circuits a compound goal — the search must extend to
a matching side-effect terminal. (A single CLI that BOTH produces `goal_out` AND carries
the action's side_effect satisfies this in one hop — the rule constrains the *final hop's*
side_effect, not the hop count. AC-05's 2-hop expectation is a property of the chosen test
scenario, not a planner constraint.) When `goal_actions` is empty, behavior is byte-identical
to today (the new clause is vacuously satisfied). `allow_side_effects` must contain the
resolved enum for the terminal hop to survive `_hop_excluded` — the caller opts in.

### 2.4 Edge formation for opted-in terminals
When planning a goal with a non-empty `goal_actions`, a producer→terminal edge on a hub
type (`text`) is allowed into a side-effect terminal matching a requested action **even
without shared intent tags** — scoped strictly to terminals whose side_effect enum is in
the requested action set. The general hub down-weight (edges.py:30) is unchanged for all
other pairs, so the 192-text-CLI explosion does not reopen. Mechanism: a planning-time
override in `plan_chain`'s adjacency expansion, NOT a change to the persisted edge table
(keeps the graph stable; the override is query-scoped and reversible).

### 2.5 Back-compat for `goal_outputs`
Today `goal_outputs` "must never be empty." Under the redesign, a pure action goal legit-
imately has no artifact. The tag-inference prompt is updated: for an action goal, put the
action in `goal_actions` and leave `goal_outputs` empty; `plan_chain` treats an empty
`goal_out` + non-empty `goal_actions` as "reach any terminal satisfying the actions."
The existing empty-goal_inputs handling (search.py:97-100) is the model to follow.

---

## 3. Components & boundaries

| Unit | Responsibility | Change |
|---|---|---|
| `hermes_adapter/tools/cli_registry.py::_TAG_INFER_SYSTEM` | goal → 3 tag lists | Add `goal_actions`; stop overloading `goal_outputs` for actions |
| `hermes_adapter/tools/cli_registry.py::_infer_capability_tags` | parse/validate model JSON | Parse+validate `goal_actions`; allow empty `goal_outputs` when `goal_actions` present |
| `hermes_adapter` planner call (cli_registry.py:899-903) | pass tags to planner | Forward `goal_actions`; keep `allow_side_effects` = resolved enums |
| `core/planner/search.py::plan_chain` | chain enumeration | `goal_actions` param, action-aware terminal rule, opted-in terminal edge override, `_ACTION_TO_SIDE_EFFECT` |
| `core/catalog/queries.py::plan_cli_chain` | public wrapper | Thread `goal_actions` through |
| `core/planner/search.py::_hop_excluded` | hop prune | **Unchanged** (declared terminals already pass) |
| `core/graph/edges.py` | persisted edges | **Unchanged** (override is planning-time only) |

---

## 4. Acceptance criteria (reconstituted)

- **AC-01** — DONE (`3a78aa8`): declared-`external` recognition + `send_mail.output_types`
  live backfill. Documents the enum-recognition mechanism. No further work.
- **AC-02** — Verification test: `send_mail` reachable at the DEFAULT cap. Codex flagged a
  tiny fixture insufficient — use either the exact live-row probe OR a fixture with 100+
  competing candidates, asserting presence at `max_candidate_chains=100`.
- **AC-03** — Backfill `seed_anthropic_index` in the live DB (backup first, atomic UPDATE):
  `side_effect='writes-fs'`, `input_types='path'`, `output_types=''`, `confidence='inferred'`.
  (Codex: `path` is real vocab per capability_repair.py:27; `declared` is NOT grounded —
  keep `inferred`.) Verify: exact affected-row count == 1, re-read matches, and
  `_hop_excluded(row, set())` == True (writes-fs excluded by default) / == False when
  `allow_side_effects={'writes-fs'}`.
- **AC-04** — Reproduce FIRST: a handler test showing a compound goal string handed to
  `run_cli_command` gets its producer sub-goal swallowed by the `len(healthy)==1` bypass
  (cli_registry.py:893). Then the guard: bypass defers to the planner when `goal_actions`
  is non-empty AND a produce artifact is also implied. RED-first.
- **AC-05** — Live E2E, single attempt, `--max-time 600`. A real producer→`send_mail`
  2-hop chain plans and executes. Codex-hardened verification: assert the exact ordered
  selected slugs (2 hops) AND a **unique token emitted by hop 1 appears in the received
  mail body** — inbox presence alone does not prove the handoff. No blind re-send on
  exit-124 (delivery-unknown; per prior handover, one test mail suffices).

---

## 5. Testing strategy

- **AC-02**: pure unit; 100+-contention fixture OR live-row probe. Deterministic.
- **AC-03**: no unit test (data fix). Verification = row-count + re-read + `_hop_excluded`
  assertions. Backup is rollback.
- **`goal_actions` planner logic**: RED-first unit tests in `tests/test_planner.py`:
  (a) compound goal (`goal_outputs=['text'], goal_actions=['email']`) plans a 2-hop
  producer→send_mail chain; (b) a plain producer does NOT short-circuit when
  `goal_actions` is set; (c) `goal_actions=[]` produces byte-identical output to today
  (regression guard); (d) the terminal-edge override does NOT create spurious chains for
  non-requested side-effect terminals.
- **AC-04**: RED-first handler test in hermes-adapter reproducing the swallow, then the guard.
- **AC-05**: live, single attempt, unique-token assertion.

## 6. Error handling
- Tag inference emitting an out-of-vocab action → existing one-retry-then-ValueError path
  (reuse `_infer_capability_tags`'s vocab-reject mechanism, extended to `goal_actions`).
- Empty `goal_outputs` AND empty `goal_actions` → hard-fail (no goal at all), as today.
- Mid-chain hop failure → existing abort-with-partial_output (already shipped `7bd49d5`).

## 7. Scope boundaries (YAGNI)
Explicitly OUT:
- No change to the persisted edge table or `compute_edges` (override is query-scoped).
- No priority-queue/best-first planner rewrite.
- No `max_candidate_chains` default change.
- No real Python I/O *inference* (the systemic `infer.py` gap that returns empty I/O for
  every Python CLI) — that is a separate ticket; here we only backfill the one row and
  correct the terminal/action semantics.
- No multi-action goals beyond what the terminal rule naturally supports (one terminal
  hop; N distinct actions on one terminal is fine, N sequential action hops is not).

## 8. Ordering (Codex-recommended)
1. `goal_actions` planner semantics + edge override (the enabling change).
2. AC-04 bypass guard.
3. AC-05 live E2E.
AC-02 and AC-03 are independent and can land first (they don't depend on the redesign).
