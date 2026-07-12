# US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01 — `goal_actions` Redesign

**Date:** 2026-07-12
**Status:** Design — revised after THREE Codex grounding passes. 3rd-pass fixes applied
(disjoint tag sets §2.2, compound-goal start gate §2.6, slug-scoped final-position auth
§2.7, shared-vocab contract §2.8). **A 4th Codex pass is the next action to confirm
PLAN-READY before writing-plans.**
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

### 2.2 Action → required-intent-tag map (tag-keyed, DISJOINT tag sets)
The action verbs are matched to terminal intent tags via a single shared dict. Codex's 3rd
pass found that overlapping tag sets re-introduce ambiguity: if `webhook` includes `notify`,
then `send_mail` (tagged `notify,send`) falsely satisfies `webhook`. **The tag sets must be
pairwise disjoint** so each live terminal satisfies at most one action verb:

```
_ACTION_REQUIRES_TAG = {
    "email":      {"send"},       # send_mail carries notify,send -> 'send' is its
                                  #   discriminating tag ('notify' is shared vocabulary)
    "notify":     {"notify"},     # a pure-notification terminal (none live today)
    "webhook":    {"webhook"},    # requires the specific 'webhook' tag, NOT 'notify'
    "file_write": {"persist"},    # a fs-writing terminal tagged 'persist' (none live today)
}
```

A terminal satisfies action `a` iff `_ACTION_REQUIRES_TAG[a] & terminal.intent_tags` is
non-empty. **Disjointness invariant** (asserted by a unit test over the map + validated
against live tags): no two values share a tag, so no terminal matches two verbs. Live check:
`email → {send}` matches only `send_mail`; `webhook → {webhook}` and `notify → {notify}`
match zero live terminals (correctly — none exist yet), so an `email` goal can never route
to a webhook/notify terminal. An action verb absent from the map is a **hard
inference-validation error** (one retry, then ValueError) — never silently dropped, never
routed to a wrong terminal.

> Trade-off: keying `email` on `send` alone (dropping `notify`) means a future
> notification-only mail CLI tagged `notify` but not `send` would not match `email`. That's
> the correct bias — an `email` goal should reach a *sending* terminal, and `notify` stays
> reserved for the distinct `notify` action. Revisit the map when a second `external`
> terminal is registered (the map is the single place to update).

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

### 2.6 Start-selection for pure-action goals (Codex VERIFIED gap; 3rd-pass narrowed)
A pure action with empty `goal_inputs` AND empty `goal_outputs` still cannot start at
`send_mail`: empty inputs select only no-input CLIs (search.py:97-100), but
`send_mail.input_types='text'`. Resolution: **only when `goal_outputs` is empty** (a pure
action with no artifact to produce first), the start set additionally includes any terminal
satisfying a requested action, regardless of its declared inputs.

**3rd-pass fix — gate on `not goal_out`, NOT merely `goal_actions` non-empty.** Codex found
that admitting action terminals as starts for a *compound* goal (non-empty `goal_outputs`)
is unsafe: with two matching terminals, terminal A's confirmation `text` output could be
consumed as the "artifact" feeding terminal B, falsely satisfying the compound predicate.
So for a compound goal the action terminal is reachable ONLY as a synthesized final hop
(§2.5) downstream of a real producer — never as a start. Pure-action (empty `goal_outputs`)
is the only case that admits an action terminal as a start.

### 2.7 Self-authorization — SLUG-scoped, final-position only (3rd-pass fix)
The adapter can't pre-resolve enums without duplicating the action map, so **the planner
owns resolution**: `plan_chain`/`plan_cli_chain` gain `goal_actions`; the adapter passes
`goal_actions` verbatim and does NOT pre-resolve enums.

**3rd-pass fix — do NOT union the terminal's enum into a class-wide `allow_side_effects`.**
Codex found that unioning e.g. `writes-fs` (a `file_write` terminal's enum) into
`allow_side_effects` would globally admit all 32 live inferred `writes-fs` CLIs as valid
mid-chain hops — a security regression. Instead, self-authorization is **slug-scoped and
final-position-only**:

- The planner computes `action_terminals: set[str]` = the exact slugs matched to a
  requested action (§2.2).
- `_hop_excluded` is consulted as today for every hop with the caller's (unmodified)
  `allow_side_effects`. The ONLY relaxation: a hop is additionally allowed if it is in
  `action_terminals` AND it is the FINAL hop of the path being evaluated. No other hop, and
  no other CLI of the same enum class, gains authorization.
- Mechanism: pass `action_terminals` + a `is_final` flag into the exclusion check at the
  terminal-evaluation site (search.py:110-116), rather than mutating the shared
  `allow_side_effects` set. `_hop_excluded`'s existing signature/logic is unchanged; the
  planner wraps it: `excluded = _hop_excluded(caps, allow) and not (is_final and slug in
  action_terminals)`.
- Explicit caller `allow_side_effects` remains class-wide (an operator opting into
  `writes-fs` accepts that blast radius knowingly) — only the *implicit action
  self-authorization* is slug-scoped.

### 2.8 Shared action-vocab contract — no cross-repo duplication (3rd-pass fix)
Codex flagged that the spec had the planner own `_ACTION_REQUIRES_TAG` while implying the
adapter must validate `goal_actions` against it and retry — with no mechanism, that forces
a duplicated map across two repos. Resolution: **the adapter does NOT own or duplicate the
map. Validation lives entirely in the registry.**

- The adapter's tag inference emits `goal_actions` and forwards them **verbatim** to
  `plan_cli_chain` (the existing MCP `_mcp_call` path). It performs no action-verb
  validation of its own.
- The registry's `plan_cli_chain` op validates each action verb against
  `_ACTION_REQUIRES_TAG` (the single owner). An unknown verb returns a **structured op
  error** (`{"error": "unknown action verb: <v>; known: [...]"}`) via the existing
  ops error channel (ops_registry already returns string errors, e.g. the unknown-key
  path at ops_registry.py:101).
- The adapter treats that structured error like any other planner failure: it surfaces it
  and (if it wants a retry) re-invokes tag inference with the rejected verb named — reusing
  the EXISTING vocab-reject retry loop pattern (`_infer_capability_tags`, cli_registry.py:
  ~545-566), which already round-trips "these tags were rejected" back to the model. The
  known-verbs list travels in the error payload, so the model gets the vocabulary without
  the adapter hardcoding it.
- Net: `_ACTION_REQUIRES_TAG` exists in exactly one place (the planner). The adapter learns
  the vocabulary at runtime from the registry's error payload. No duplication, no contract
  test needed beyond "adapter surfaces the structured error + retries."

---

## 3. Components & boundaries (all plumbing enumerated — Codex found 5 omissions)

| Unit | Responsibility | Change |
|---|---|---|
| `hermes_adapter/tools/cli_registry.py::_TAG_INFER_SYSTEM` | goal → 3 tag lists | Add `goal_actions` (intent-tag verbs); stop overloading `goal_outputs` for actions |
| `hermes_adapter/tools/cli_registry.py::_infer_capability_tags` | parse model JSON | Parse `goal_actions`; allow empty `goal_outputs` when `goal_actions` present. Does NOT validate action verbs against the map (§2.8 — registry owns validation; adapter surfaces the structured error + retries via the existing vocab-reject loop) |
| `hermes_adapter/tools/cli_registry.py` discovery (~843) | `output_term = goal_outputs[0]` | **Codex VERIFIED crash:** guard empty `goal_outputs`; when empty + `goal_actions` present, discover via the action term instead of `goal_outputs[0]`; restructure the logging/fallback/error branches that assume a non-empty output term |
| `hermes_adapter/tools/cli_registry.py` planner call (~899-903) | pass tags to planner | Forward `goal_actions`; STOP pre-resolving `allow_side_effects` from side_effects (planner owns resolution now) |
| `hermes_adapter/tools/cli_registry.py` tool schema (~387) | MCP tool input schema | **Codex VERIFIED omission:** add `goal_actions` to `plan_cli_chain` tool properties |
| `core/ops_registry.py` (~37, 101) | op input schema + unknown-key rejection | **Codex VERIFIED omission:** add `goal_actions` to the `plan_cli_chain` Op schema `properties`, else validation rejects it as an unknown key (ops_registry.py:101) |
| `core/planner/search.py::plan_chain` | chain enumeration | `goal_actions` param, `_ACTION_REQUIRES_TAG` (validate verbs, §2.8), disjoint tag-keyed matching (§2.2), tag-keyed terminal predicate (§2.3), short-circuit edit (§2.4), terminal edge synthesis (§2.5), action-terminal starts gated on empty `goal_outputs` (§2.6), slug-scoped final-position self-authorization (§2.7) |
| `core/catalog/queries.py::plan_cli_chain` | public wrapper | Thread `goal_actions` through; return structured error for unknown action verb (§2.8) |
| `core/planner/search.py::_hop_excluded` | hop prune | **Unchanged** signature/logic; the planner wraps its result with the slug-scoped final-position relaxation (§2.7) — it does NOT receive a widened allow-set |
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
  (f) an unknown action verb (not in `_ACTION_REQUIRES_TAG`) returns a structured error, not
      silently dropped (§2.8);
  (g) pure-action goal (empty goal_outputs, non-empty goal_actions) starts at and returns
      the action terminal (§2.6);
  (h) `_ACTION_REQUIRES_TAG` values are pairwise DISJOINT (§2.2 invariant) — assert over the
      map itself AND that no live terminal matches two verbs;
  (i) a compound goal does NOT admit an action terminal as a START (§2.6 gate) — only as a
      synthesized final hop after a producer;
  (j) slug-scoped final-position auth (§2.7): a `writes-fs` action terminal being the final
      hop does NOT admit other `writes-fs` CLIs as mid-chain hops (they stay excluded).
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
