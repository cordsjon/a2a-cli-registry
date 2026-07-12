# Producer Relevance Rank — `producer_terms` → `plan_chain` (US-CLIREG-PRODUCER-RELEVANCE-01)

**Date:** 2026-07-12
**Status:** Design — AC-01 brainstorm RESOLVED same day (user decision: **Approach A**,
relevance as a ranking input to `plan_chain`; E2E goal reworded, see Decision Log).
**Repos touched:** `a2a-cli-registry` (planner sort key, ops schema, catalog blob helper,
tests), `hermes-adapter` (tag inference 5th key, vocab-guard exemption, planner call,
logging, tests)

> NOTE (carried from the goal-actions spec): the `registry.db` in THIS repo is a DIFFERENT
> dataset than the live `~/.hermes/cli-registry.db` the adapter plans against. All claims
> below are grounded against the LIVE DB (probed 2026-07-12).

---

## 1. Incident and root cause (verified)

GOALACTIONS-01 AC-05 live E2E (2026-07-12 17:10): planning layers all passed — compound
tags inferred, 2-hop chain `['build', 'send_mail']` selected and dispatched — but hop-1
producer `build` (an SSG build script) was chosen for "generate a codename" purely by the
final slug tie-break of `Chain.sort_key` (`core/planner/search.py:20-23`):

```python
return (self.length, self.side_effect_count, self.min_confidence_rank, tuple(self.slugs))
```

~100 candidate chains were EQUAL on the first three keys (all 2-hop, same side-effect
count, same confidence), so `tuple(self.slugs)` ascending — alphabetical — IS the producer
pick. `build` sorts early; the gateway agent then invented a `--codename` flag (argparse
exit 2), fallbacks died on the approval gate, round_cap, no mail.

### 1.1 The truncation makes this worse than a tie-break
`plan_chain` sorts THEN truncates: `candidates.sort(...)` → `candidates[:max_candidate_chains]`
(search.py:216-217, default 100). The live probe returned exactly 100 candidates, i.e.
truncation was ACTIVE. Consequence: **any adapter-side re-rank operates on an
alphabetically-truncated window** — a semantically right producer sorting past the window
never reaches the adapter at all. Relevance must therefore score **before** the cap,
i.e. inside `plan_chain`. This is the structural argument that decided AC-01.

### 1.2 Live-DB grounding facts (probed 2026-07-12)
- `cli.description` is NOT semantic: it holds a repo-relative file path, and for broken
  CLIs literally an ImportError traceback. Do not design description-only matching.
- The usable signal is `slug` + `capability.intent_tags`. Live intent vocabulary (top):
  `generate`×131, `query`×56, `extract`×52, `lint`×45, `index`×40, `convert`×40 …
- Intent tags alone would NOT have fixed the incident: `build`'s capability row is
  `intent_tags=build,generate / output_types=file:json,text` — it legitimately carries
  `generate`. Only the artifact noun ("codename") discriminates.
- "codename" matches NOTHING in the live catalog (no slug/description hit). The honest
  outcome for the original E2E goal is "no relevance signal" → legacy tie-break. Hence
  the AC-03 goal reword (Decision Log #2).
- Healthy `generate`-intent text producers exist for the reworded E2E, e.g.
  `generate_content`, `create_handoff`, `governance_heatmap`, `governance_retro`.

## 2. Design

### 2.1 Registry: `producer_terms` parameter
`plan_chain(session, goal_inputs, goal_outputs, allow_side_effects=None, max_chain_depth=4,
max_candidate_chains=100, goal_actions=None, producer_terms=None)`.

- `producer_terms: list[str] | None` — free-text, lowercase artifact terms from the
  caller (e.g. `["codename"]`, `["cheatsheet"]`). NOT a vocabulary; never validated
  against `input_types`/`output_types`. Non-string elements are ignored (same tolerance
  as the adapter's other tag keys); the ops JSON schema types it as a string array.
- Ops exposure: `plan_cli_chain` op (`core/ops_registry.py:37-41`) gains optional
  `"producer_terms": _STR_ARRAY`. Not in `required`.

### 2.2 Registry: relevance rank in `sort_key`
`Chain` gains `relevance_rank: int` (0 = relevant, 1 = not). New sort key:

```python
return (self.length, self.side_effect_count, self.min_confidence_rank,
        self.relevance_rank, tuple(self.slugs))
```

- **Placement (decided):** between confidence and the slug tie-break. Every comparison
  the legacy tuple already DECIDED is preserved; only previously-ARBITRARY (slug-order)
  comparisons change. Named trade-off, user-accepted: a shorter irrelevant chain still
  beats a longer relevant one — length stays king.
- **Match rule:** a chain is relevant (rank 0) iff ANY producer hop's blob contains ANY
  term, case-insensitive substring. Blob = `slug + " " + description + " " + intent_tags
  + " " + input_types + " " + output_types` — the exact blob `search_clis`
  (`core/catalog/queries.py:70-86`) already matches against, extracted into a shared
  helper so the two cannot drift.
- **Producer hops:** `path[:-1]` when the chain's final hop is an action terminal
  (compound goal); ALL hops otherwise. Rationale: an action terminal is already matched
  by verb (§2.2 of the goal-actions spec); scoring it against artifact terms would let
  e.g. `send_mail`'s blob (`text`) fake relevance.
- **Legacy invariance (AC-02):** `producer_terms` absent, empty, or matching zero
  candidates ⇒ every chain has rank 1 ⇒ the 4-tuple ordering is byte-identical to
  legacy. The existing pinned legacy-path tests must stay green unmodified.
- **Rank-before-cap:** ranking happens in the same sort that precedes
  `candidates[:max_candidate_chains]`, so a relevant producer alphabetically past
  position 100 now survives (test (c) below).
- `relevance_rank` is serialized in each chain of the `plan_cli_chain` response for
  adapter logging and E2E evidence. Additive field — no consumer parses chains
  positionally (adapter reads dict keys).

### 2.3 Adapter: 5th inference key `producer_terms`
- `_TAG_INFER_SYSTEM` (cli_registry.py:487-499) gains: `producer_terms` = 1–3 short
  lowercase nouns naming the ARTIFACT the goal asks to produce (e.g. "codename",
  "cheatsheet", "poster"); `[]` when the goal names no artifact. Free text — explicitly
  NOT restricted to the registry vocabulary.
- `_infer_capability_tags` returns the key (string-filtered like `goal_actions`,
  cli_registry.py:536). Absence tolerated: missing/malformed ⇒ `[]`, never an error —
  the feature degrades to legacy ordering, it never blocks planning.
- **Vocab-guard exemption (load-bearing):** the step-3 vocabulary guard
  (cli_registry.py:922-930) validates `goal_inputs`/`goal_outputs` against the registry
  vocabulary and must NOT see `producer_terms` — they are fuzzy match hints, not
  reachability gates. A "codename" term is valid even though no vocab contains it.
- Step 4 forwards `producer_terms` on the `plan_cli_chain` MCP call (both the compound
  path and the plain planner path; the bypass path never calls the planner and is
  untouched). Corrective reinference (UnknownActionVerbError path) re-sends whatever the
  reinference returns — no special handling.
- `_select_chain` is UNTOUCHED: `sorted(healthy_chains, key=len)` is stable, so the
  planner's relevance ordering survives within equal lengths. No adapter re-rank exists
  or is added.
- Logging: the existing step-4 debug logs gain `producer_terms` (inference) and the
  selected chain's `relevance_rank` (selection).

### 2.4 Error handling
None new. A rank never raises; malformed terms are filtered; empty terms are legacy.
The §2.8 goal-actions error contract (ValueError → structured pass-through) is
unaffected — this feature adds no ValueErrors.

## 3. Test plan (RED-first, per AC-02)

Registry (`tests/test_planner.py`):
- (a) **Incident replica:** N equal text-producers where the semantically matching slug
  sorts alphabetically LAST; `producer_terms=["<term>"]` ⇒ selected chain's hop-1 is the
  match, not the alphabetical first. RED against current code.
- (b) **Legacy byte-identical:** same fixture, `producer_terms` omitted ⇒ ordering
  identical to legacy (and all existing pinned tests green, unmodified).
- (c) **Rank-before-cap:** >100 equal candidates, relevant producer past position 100
  alphabetically ⇒ it appears (first) in the returned list.
- (d) **No-match fallback:** `producer_terms=["zzz-nothing"]` ⇒ ordering identical to (b).
- (e) **Action-terminal exclusion:** compound goal; a term matching ONLY the action
  terminal's blob does not mark any chain relevant.
- (f) **Blob parity:** shared helper — a term that matches via `search_clis` matches in
  the planner and vice versa (guards drift).
- (g) **Non-string elements ignored;** ops schema accepts the optional array.

Adapter (unit, mocked MCP):
- (h) Inference emits `producer_terms`; missing key ⇒ `[]`.
- (i) Step-3 vocab guard does NOT reject an out-of-vocab producer term.
- (j) `plan_cli_chain` call payload contains `producer_terms` verbatim.
- Full suites green: registry (499 pass, 1 pre-existing unrelated `test_web_render`
  fail at base), adapter (182).

## 4. Deploy & AC-03 E2E
Deploy order per the GOALACTIONS handover (§8 hazard): registry FIRST, then adapter, then
ordered gateway restart — confirm `127.0.0.1:9113/mcp/` initialize before kicking the
gateway (Host `localhost` → 421).

AC-03: single-attempt live E2E (`--max-time 600`), goal REWORDED to name an artifact a
healthy catalog producer matches (picked at plan time from the live DB among §1.2's
candidates); pass = 2-hop chain executes end-to-end and the hop-1 runtime token lands in
the received mail body. Do NOT re-fire on failure (single-attempt rule stands).

## 5. Decision Log
1. **AC-01 (user, 2026-07-12): Approach A** — relevance lives in the registry planner as
   a ranking input (`producer_terms` → `relevance_rank` in `sort_key`), adapter supplies
   terms. Rejected: (B) adapter re-rank — unsound below the `[:100]` alphabetical
   truncation; (C) `restrict_slugs` hard filter — empty match kills all chains, forcing
   a double-plan fallback.
2. **E2E goal (user, 2026-07-12): reword** — "codename" matches nothing in the live
   catalog; the re-run goal must name a matchable artifact. Rejected: generic-generator
   matcher (scope creep), rerunning the unmatched goal (exercises only the fallback).
3. **Rank placement (user, 2026-07-12): after confidence, before slugs** — minimal
   ordering disruption; accepted that length still dominates relevance.

## 6. AC mapping
- AC-01 (design decision) — §5 Decision Log, this document.
- AC-02 (implementation + RED-first tests, legacy preserved) — §2, §3 (a)-(j).
- AC-03 (live E2E re-run) — §4.
