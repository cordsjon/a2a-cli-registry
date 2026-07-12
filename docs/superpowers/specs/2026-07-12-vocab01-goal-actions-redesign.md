# US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01 — `goal_actions` Redesign

**Date:** 2026-07-12
**Status:** Design (revised after two Codex grounding passes; findings folded in)
**Repos touched:** `a2a-cli-registry` (planner, ops schema, tests), `hermes-adapter` (tag inference, discovery, tool schema, planner call, bypass guard)

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

## 2. Design: the `goal_actions` dimension (tag-keyed, revised)

Model the action as its own goal dimension, distinct from the produced artifact, and
match action terminals by their **intent tags**, not their side_effect enum. The second
Codex pass refuted enum-based matching (`email`/`notify`/`webhook` all collapse to
`external`; `file_write` matches all 32 live `writes-fs` CLIs) — the side_effect enum
says *how dangerous* a hop is, not *what action* it performs. Intent tags carry the
action identity: live `send_mail` is uniquely tagged `notify,send`.

### 2.1 Data-flow change
Tag inference emits three lists instead of overloading two:
- `goal_inputs` — capability tags the user already has (unchanged).
- `goal_outputs` — the **produced artifact only** (e.g. the report `text`). For a pure
  action goal with no artifact, this MAY now be empty (see §2.5 back-compat + plumbing).
- `goal_actions` — the terminal action verb(s) the goal demands (e.g. `email`). NEW.
  These are **intent-tag terms**, matched against terminals' `intent_tags`.

### 2.2 Action → required-intent-tag map (tag-keyed, not enum-keyed)
A small explicit dict, the single source of truth, mapping an inference action verb to
the set of intent tags a terminal must carry to satisfy it:

```
_ACTION_REQUIRES_TAG = {
    "email":  {"notify", "send"},    # send_mail carries notify,send
    "notify": {"notify"},
    "webhook":{"webhook", "notify"},
    "file_write": {"write", "persist"},
}
```

A terminal satisfies action `a` iff `_ACTION_REQUIRES_TAG[a] & terminal.intent_tags` is
non-empty. An action verb absent from the map is a **hard inference-validation error**
(one retry, then ValueError) — never silently dropped, never routed to a wrong terminal.
This closes Codex's "email may route to a webhook terminal" hole: matching is on the
action tag, and `send_mail` (`notify,send`) vs a future webhook terminal (`webhook`) are
distinguishable.

### 2.3 Artifact-vs-confirmation resolution (Codex REFUTED the naive predicate)
Codex's fatal finding: `send_mail` both consumes AND outputs `text`, so a naive
`produces goal_out` test lets a one-hop `send_mail` satisfy `goal_out=text` even when
`text` meant the report artifact. Resolution: **the artifact hop and the action hop must
be distinct path positions.** The terminal predicate becomes:

- `artifact_met = (not goal_out) or any(hop BEFORE the final hop produces goal_out)`
- `action_met  = for every a in goal_actions, the FINAL hop's intent_tags satisfy a
                  (per §2.2) AND the final hop is NOT the sole artifact producer`
- A path is terminal iff `artifact_met AND action_met` (when `goal_actions` non-empty).
- When `goal_actions` is empty, the rule is exactly today's (`any hop produces goal_out`),
  byte-identical — the new clauses are gated behind non-empty `goal_actions`.

So a compound goal REQUIRES ≥2 distinct hops: a producer emits `goal_out`, then a
tag-matched terminal acts. A single dual-capable CLI does NOT short-circuit a compound
goal (the artifact must come from an earlier hop). This removes the §2.3 ambiguity the
first draft's "one CLI both produces and acts" clause created.

### 2.4 Terminal short-circuit edit (search.py:112-116)
The current unconditional `continue` after appending a candidate (search.py:114) prevents
expansion from any hop producing `goal_out`. Change: when `goal_actions` is non-empty and
`action_met` is FALSE for the current path, do **not** append-and-`continue` — fall
through to neighbor expansion so the producer's edges (including the synthesized terminal
edge, §2.5) are followed. Append-as-candidate only when `artifact_met AND action_met`.
This is a localized predicate + control-flow edit, not a BFS rewrite (Codex: VERIFIED
feasible).

### 2.5 Planning-time terminal edge synthesis (no persisted-table change)
`plan_chain` builds `adjacency` from the persisted `CliEdge` table (search.py:84-87) —
Codex VERIFIED. To reach `send_mail` (which has zero persisted incoming edges), synthesize
adjacency entries **in-memory, at plan time**, before BFS: for each producer P whose
outputs intersect a hub type H, and each terminal T satisfying some `goal_action` (§2.2),
add `(P, T, H)` to `adjacency[P]` if `H ∈ P.outputs ∩ T.inputs`. Scoped strictly to
terminals matching a requested action — the general hub down-weight (edges.py:30) is
untouched for all other pairs, so the 192-text-CLI explosion does not reopen. `via_type`
is preserved (= H) for hop tracing. The persisted `CliEdge` table and `compute_edges` are
**not** modified.

### 2.6 Start-selection for pure-action goals (Codex VERIFIED gap)
A pure action with empty `goal_inputs` AND empty `goal_outputs` still cannot start at
`send_mail`: empty inputs select only no-input CLIs (search.py:97-100), but
`send_mail.input_types='text'`. Resolution: when `goal_actions` is non-empty, the start
set additionally includes any terminal satisfying a requested action, regardless of its
declared inputs — an action terminal is a valid 1-hop chain when there is no artifact to
produce first. (This is the "explicitly admit matching action terminals as starts" option
Codex named.)

### 2.7 Enum resolution — single source of truth (Codex REFUTED duplication)
Codex: the planner can't own the action map while the adapter also passes resolved
`allow_side_effects` enums — one side duplicates it. Resolution: **the planner owns
everything.** `plan_chain`/`plan_cli_chain` gain `goal_actions`; the planner resolves each
action's matched terminal, reads that terminal's actual `side_effect`, and unions those
enums into the effective `allow_side_effects` for `_hop_excluded` internally. The adapter
passes `goal_actions` through verbatim and does NOT pre-resolve enums. `allow_side_effects`
remains a caller-overridable input for explicit opt-in, but action terminals self-authorize
their own declared side_effect (a declared terminal the user explicitly asked to act with
is, by request, allowed).

---

## 3. Components & boundaries (all plumbing enumerated — Codex found 5 omissions)

| Unit | Responsibility | Change |
|---|---|---|
| `hermes_adapter/tools/cli_registry.py::_TAG_INFER_SYSTEM` | goal → 3 tag lists | Add `goal_actions` (intent-tag verbs); stop overloading `goal_outputs` for actions |
| `hermes_adapter/tools/cli_registry.py::_infer_capability_tags` | parse/validate model JSON | Parse+validate `goal_actions` (reject verbs not in `_ACTION_REQUIRES_TAG`, one retry); allow empty `goal_outputs` when `goal_actions` present |
| `hermes_adapter/tools/cli_registry.py` discovery (~843) | `output_term = goal_outputs[0]` | **Codex VERIFIED crash:** guard empty `goal_outputs`; when empty + `goal_actions` present, discover via the action term instead of `goal_outputs[0]`; restructure the logging/fallback/error branches that assume a non-empty output term |
| `hermes_adapter/tools/cli_registry.py` planner call (~899-903) | pass tags to planner | Forward `goal_actions`; STOP pre-resolving `allow_side_effects` from side_effects (planner owns resolution now) |
| `hermes_adapter/tools/cli_registry.py` tool schema (~387) | MCP tool input schema | **Codex VERIFIED omission:** add `goal_actions` to `plan_cli_chain` tool properties |
| `core/ops_registry.py` (~37, 101) | op input schema + unknown-key rejection | **Codex VERIFIED omission:** add `goal_actions` to the `plan_cli_chain` Op schema `properties`, else validation rejects it as an unknown key (ops_registry.py:101) |
| `core/planner/search.py::plan_chain` | chain enumeration | `goal_actions` param, `_ACTION_REQUIRES_TAG`, tag-keyed terminal predicate (§2.3), short-circuit edit (§2.4), terminal edge synthesis (§2.5), action-terminal starts (§2.6), internal enum union (§2.7) |
| `core/catalog/queries.py::plan_cli_chain` | public wrapper | Thread `goal_actions` through |
| `core/planner/search.py::_hop_excluded` | hop prune | **Unchanged** logic; the planner feeds it the action-unioned allow-set |
| `core/graph/edges.py` | persisted edges | **Unchanged** (synthesis is planning-time only) |

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
  is non-empty AND a produce artifact (`goal_outputs`) is also present. Assert the exact
  planner arguments (`goal_actions` forwarded) AND the exact selected chain (producer
  retained), not merely that the bypass didn't fire (Codex UNCERTAIN otherwise). RED-first.
- **AC-05** — Live E2E, single attempt, `--max-time 600`. A real producer→`send_mail`
  2-hop chain plans and executes. Codex-hardened proof of handoff: because every hop is
  injected with the ORIGINAL goal (cli_registry.py:944) independent of prior stdout, the
  unique token MUST be one **generated by hop 1 at runtime and absent from the goal
  string** — its appearance in the received mail body is the only proof hop-1 output
  actually reached hop-2. Assert exact ordered selected slugs via explicit instrumentation
  (the success response returns stdout/exit code, not the chain — cli_registry.py:964 — so
  the plan step must log or return the selected slug order for the test to observe). No
  blind re-send on exit-124.

---

## 5. Testing strategy

- **AC-02**: pure unit; 100+-contention fixture OR live-row probe. Deterministic.
- **AC-03**: no unit test (data fix). Verification = row-count + re-read + `_hop_excluded`
  assertions. Backup is rollback.
- **`goal_actions` planner logic**: RED-first unit tests in `tests/test_planner.py`:
  (a) compound goal (`goal_outputs=['text'], goal_actions=['email']`) plans a 2-hop
  producer→send_mail chain, producer strictly before send_mail;
  (b) a plain producer does NOT short-circuit when `goal_actions` is set;
  (c) `goal_actions=[]` produces byte-identical output to today (regression guard);
  (d) the terminal-edge synthesis does NOT create chains into non-requested side-effect
      terminals (e.g. a `network` terminal when only `email` was requested);
  (e) a dual-capable CLI (produces goal_out AND has the action tag) does NOT satisfy a
      compound goal in ONE hop (artifact must precede action, §2.3);
  (f) an unknown action verb (not in `_ACTION_REQUIRES_TAG`) raises, not silently drops;
  (g) pure-action goal (empty goal_outputs, non-empty goal_actions) starts at and returns
      the action terminal (§2.6).
- **AC-04**: RED-first handler test in hermes-adapter reproducing the swallow, then the
  guard; assert forwarded `goal_actions` + retained producer.
- **AC-05**: live, single attempt, runtime-token-in-mail-body assertion.

## 6. Error handling
- Tag inference emitting an out-of-map action verb → one-retry-then-ValueError (reuse
  `_infer_capability_tags`'s vocab-reject mechanism, extended to `goal_actions`).
- Empty `goal_outputs` AND empty `goal_actions` → hard-fail (no goal at all), as today.
- Empty `goal_outputs` WITH non-empty `goal_actions` → valid pure-action goal; discovery
  uses the action term (§3 discovery row).
- Mid-chain hop failure → existing abort-with-partial_output (already shipped `7bd49d5`).

## 7. Scope boundaries (YAGNI)
Explicitly OUT:
- No change to the persisted edge table or `compute_edges` (synthesis is query-scoped).
- No priority-queue/best-first planner rewrite.
- No `max_candidate_chains` default change.
- No real Python I/O *inference* (the systemic `infer.py` gap that returns empty I/O for
  every Python CLI) — separate ticket; here we backfill the one row and fix planner semantics.
- **Multi-action-per-goal is OUT** (Codex REFUTED the first draft's "N actions on one
  terminal is fine"): one final action hop satisfying ONE action verb. A goal with two
  distinct actions ("email me AND post a webhook") is not supported this ticket — it needs
  multiple terminal hops, a separate design. `goal_actions` accepts a list for forward
  compatibility, but the planner asserts len ≤ 1 and errors otherwise (explicit, not silent).

## 8. Ordering (Codex-corrected — atomic cross-repo deploy)
Registry-side schema must deploy BEFORE the adapter forwards the new key, or
`goal_actions` is rejected as an unknown input key (ops_registry.py:101):
1. **Registry first:** `plan_chain` semantics + `core/ops_registry.py` schema + wrapper.
   Land + test in isolation (planner unit tests a–g green).
2. **Adapter atomically:** tag inference + empty-output discovery restructure + tool
   schema + planner call + bypass guard — all together (partial deploy = unknown-key
   rejection or discovery crash).
3. AC-05 live E2E last.
AC-02 and AC-03 are independent and can land first (they don't depend on the redesign).
