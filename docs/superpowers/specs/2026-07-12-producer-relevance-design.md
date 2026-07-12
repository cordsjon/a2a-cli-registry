# Producer Relevance Rank — `producer_terms` → `plan_chain` (US-CLIREG-PRODUCER-RELEVANCE-01)

**Date:** 2026-07-12
**Status:** Design — AC-01 brainstorm RESOLVED same day (user decision: **Approach A**,
relevance as a ranking input to `plan_chain`; E2E goal reworded, see Decision Log).
Codex pre-panel pass (2026-07-12, see end of file): 5 findings, ALL FOLDED same day —
wrapper integration point added (§2.1a), incident tie narrative corrected against Codex's
uncapped live probe (§1/§1.1), byte-identical claim reworded to order-invariance +
blank-term filter (§2.2), blob unified on the two-haystack `search_clis` predicate in a
leaf module (§2.2), test plan restructured (§3).
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

Within each group of chains tied on the first three keys, `tuple(self.slugs)` ascending —
alphabetical — IS the producer pick. Codex's uncapped live probe (incident-shaped call:
`goal_inputs=[]`, `goal_outputs=["text"]`, `goal_actions=["email"]`) found **7,174**
candidate paths; the legacy top-100 window comprises 76 two-hop chains (4 ranked
`(se=1, conf=0)`, 71 ranked `(1,1)`, 1 ranked `(2,0)`) plus 24 three-hop chains ranked
`(1,0)` — so `build` won alphabetically *within its tie group*, not across a flat ~100-way
tie as the ticket originally described. The gateway agent then invented a `--codename`
flag (argparse exit 2), fallbacks died on the approval gate, round_cap, no mail.

### 1.1 The truncation makes this worse than a tie-break
`plan_chain` sorts THEN truncates: `candidates.sort(...)` → `candidates[:max_candidate_chains]`
(search.py:216-217, default 100). With 7,174 uncapped candidates (Codex probe above),
truncation is ACTIVE: 7,074 chains never leave the planner. Consequence: **any
adapter-side re-rank operates on a window truncated by the complete legacy key** (and
alphabetically within tie groups) — a semantically right producer ranked past position
100 never reaches the adapter at all. Relevance must therefore score **before** the cap,
i.e. inside `plan_chain`. This is the structural argument that decided AC-01.

### 1.2 Live-DB grounding facts (probed 2026-07-12)
- `cli.description` is mixed/unreliable as a semantic field (Codex: 356/475 rows are
  path-like, several are ImportError tracebacks; some rows like `send_mail` DO carry
  semantic prose). Do not design description-ONLY matching; it stays in the blob as a
  secondary signal.
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
  `"producer_terms": _STR_ARRAY`. Not in `required`. NOTE (Codex): the repo's custom
  validator checks only the outer `array` type, not `_STR_ARRAY.items` — mixed arrays
  reach the handler, so the in-code filter (drop non-strings AND blank/whitespace-only
  strings) is the real guard, not the schema.

### 2.1a Registry: `catalog.queries.plan_cli_chain` wrapper (Codex finding 1)
The MCP op resolves to `core/catalog/queries.py:164-180` `plan_cli_chain`, which wraps
`planner.search.plan_chain` and serializes the response. BOTH halves change:
- accept + forward `producer_terms` (thread-only, same pattern as `goal_actions` — the
  wrapper owns no logic);
- serialize `relevance_rank` on each chain dict.
Changing only `planner.search.plan_chain` + the op schema would fail at the handler or
silently drop the evidence field.

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
- **Match rule:** a chain is relevant (rank 0) iff ANY producer hop matches ANY term
  under the **two-haystack predicate `search_clis` already uses**
  (`core/catalog/queries.py:70-87`): lowercase/strip the term, then test substring
  against `(slug + " " + description)` OR against the aggregated capability-vocab string
  (`intent_tags`,`input_types`,`output_types` over ALL capability rows of the slug). NOT
  a single five-field concatenation — that would permit synthetic matches spanning the
  description/vocab boundary that `search_clis` cannot produce (Codex finding 4). The
  predicate is extracted into a shared helper in a **leaf module** (e.g.
  `core/catalog/match.py`) so `catalog.queries → planner.search` doesn't go circular;
  both callers import it. The planner's `_cap_index` covers only `Capability` rows, so
  `plan_chain` additionally loads the `Cli` rows to obtain slugs' descriptions.
  Blank/whitespace-only terms are dropped before matching (`"" in blob` is always true
  and would mark every chain relevant).
- **Producer hops:** `path[:-1]` when the chain's final hop is an action terminal
  (compound goal); ALL hops otherwise. Rationale: an action terminal is already matched
  by verb (§2.2 of the goal-actions spec); scoring it against artifact terms would let
  e.g. `send_mail`'s blob (`text`) fake relevance.
- **Legacy invariance (AC-02, reworded per Codex finding 3):** `producer_terms` absent,
  empty, or matching zero candidates ⇒ every chain has the same constant rank ⇒ the
  induced ORDERING is identical to the legacy 4-tuple's. This is
  **order-and-existing-fields invariance, not byte identity** — the response universally
  gains the additive `relevance_rank` field. The existing pinned test
  (`test_empty_goal_actions_is_byte_identical_to_today`, tests/test_planner.py:376-383)
  compares only `slugs` + `hops` and stays green unmodified.
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

Registry — planner (`tests/test_planner.py`, in-memory `db` convention):
- (a) **Incident replica:** N rank-tied text-producers where the semantically matching
  slug sorts alphabetically LAST; `producer_terms=["<term>"]` ⇒ the FIRST RETURNED
  chain's hop-1 is the match, not the alphabetical first (`plan_chain` orders, it does
  not select). RED against current code.
- (b) **Legacy order invariance:** same fixture, `producer_terms` omitted ⇒ `slugs` +
  `hops` sequence identical to legacy (existing pinned tests green, unmodified).
- (c) **Rank-before-cap:** >100 rank-tied candidates, relevant producer past position
  100 alphabetically ⇒ it appears first in the returned list (fixture modeled on the
  existing 101-candidate starvation test, tests/test_planner.py:214-244).
- (d) **No-match fallback:** `producer_terms=["zzz-nothing"]` ⇒ ordering identical to (b).
- (e) **Action-terminal exclusion:** compound goal; a term matching ONLY the action
  terminal does not mark any chain relevant.
- (f) **Term hygiene in the planner:** non-string and blank/whitespace-only elements are
  dropped (the ops validator does not check item types — §2.1).

Registry — shared match helper (direct unit tests, new `tests/test_match.py` or in
`tests/test_catalog.py`): two-haystack semantics — a term matching only across the
description/vocab concatenation boundary does NOT match; slug/description hits and
vocab hits DO. `search_clis` keeps its existing catalog coverage; planner parity is
shown by both callers importing the one helper, not by comparing result sets (planner
visibility also depends on reachability/pruning — Codex finding 5).

Registry — wrapper + transport (`tests/test_ops_registry.py` / `tests/test_mcp.py`):
- (g1) op schema accepts optional `producer_terms`; (g2)
  `catalog.queries.plan_cli_chain` forwards terms to `planner.search.plan_chain`;
  (g3) response chains serialize `relevance_rank`.

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
- AC-02 (implementation + RED-first tests, legacy preserved) — §2, §2.1a, §3 (a)-(g3) + (h)-(j).
- AC-03 (live E2E re-run) — §4.

## Codex review — pre-panel

Reviewed against commit `94952a8` and the read-only live database
`~/.hermes/cli-registry.db` on 2026-07-12.

1. **The code citations are mostly accurate, with one minor range error and one
   omitted integration point.** `Chain.sort_key` is exactly at
   `core/planner/search.py:20-23`; sort then cap is exactly at `:216-217`; the
   `plan_cli_chain` op schema is at `core/ops_registry.py:37-41`. `search_clis`
   starts at `core/catalog/queries.py:70`, but its non-empty search expression
   closes on line 87, not 86. More importantly, the design must explicitly
   change `core/catalog/queries.py:164-180`: `plan_cli_chain` currently neither
   accepts nor forwards `producer_terms`, and its response serializer must add
   `relevance_rank`. Changing only `planner.search.plan_chain` and the op schema
   would make the MCP call fail at the handler or silently omit the evidence
   field, depending on which half was missed.

2. **Sort-before-truncate does make adapter-only re-ranking unsound, but the
   live-data explanation is overstated.** Once the planner returns only its
   legacy top 100, an adapter cannot recover a relevant chain ranked 101 or
   later; that structural conclusion is correct. “Alphabetically truncated” is
   precise only inside a group tied on length, side effects, and confidence;
   globally, the window is truncated by the complete legacy key. Also, merely
   observing 100 returned rows does not by itself prove truncation without an
   uncapped count. A read-only recursive SQLite probe of the incident-shaped
   call (`goal_inputs=[]`, `goal_outputs=["text"]`, `goal_actions=["email"]`)
   found 7,174 candidate paths, so truncation is in fact active. But the current
   live top 100 are not “~100 ... EQUAL” two-hop chains: they comprise 76
   two-hop chains (4 rank `(side_effect_count=1, confidence=0)`, 71 rank
   `(1,1)`, and 1 rank `(2,0)`) plus 24 three-hop chains ranked `(1,0)`.
   The incident narrative should distinguish the sound information-loss
   argument from this unsupported/evidently false equal-tie characterization.

3. **§2.2 preserves legacy relative ordering, not byte-identical output.** If
   all chains receive the same constant rank, inserting that constant before
   `slugs` induces the same ordering as the old key. The tuple itself changes
   from four elements to five, however, and §2.2 also requires every serialized
   chain to gain `relevance_rank`; therefore the `plan_cli_chain` response cannot
   be byte-identical. Existing conventions do not prove byte identity either:
   for example, `test_empty_goal_actions_is_byte_identical_to_today`
   (`tests/test_planner.py:376-383`) compares only `slugs` and `hops`. Reword
   AC-02/test (b) as order-and-existing-fields invariance, or conditionally omit
   the new response field when terms are absent if literal byte identity is a
   hard requirement. The same filter should discard blank/whitespace-only terms;
   otherwise `"" in blob` makes every chain rank 0 and breaks the stated
   empty-term degradation at the evidence-field level.

4. **The proposed blob is not currently the “exact blob `search_clis` already
   matches.”** `search_clis` lowercases and strips one query, then tests it
   against two separate haystacks: `(slug + " " + description)` and an
   aggregated capability-vocabulary string (`intent_tags`, `input_types`,
   `output_types`). A single concatenation of all five fields permits synthetic
   matches spanning the description/capability boundary that `search_clis`
   cannot produce. A shared helper should preserve the two-haystack predicate
   (or the spec should explicitly accept a small search-semantics change), live
   in a leaf module to avoid the existing `catalog.queries -> planner.search`
   import direction becoming circular, and account for all capability rows.
   The planner also currently indexes only `Capability` rows, so it must load
   the corresponding `Cli` rows to include descriptions. Live-DB checks do
   support the constituent-field claims: `codename` matches zero rows, `build`
   has `build,generate` and `file:json,text`, the cited intent counts are exact,
   and all four named healthy examples exist. “Description is NOT semantic” is
   too absolute: the column is mixed/unreliable (356/475 rows are path-like and
   several contain import errors, while rows such as `send_mail` have semantic
   prose).

5. **Tests (a), (c), (d), and (e) are feasible under the existing
   `tests/test_planner.py` in-memory `db` convention; test (c) closely matches
   the existing 101-candidate starvation fixture at lines 214-244.** Test (a)
   should say “first returned chain” rather than “selected chain,” because
   `plan_chain` orders candidates but does not select one. Test (f) cannot prove
   parity merely by comparing planner results with `search_clis`: planner
   visibility additionally depends on reachability, side-effect pruning, and
   terminal rules. Unit-test the shared match helper directly, then add one
   eligible planner fixture and retain/add catalog-query coverage in
   `tests/test_catalog.py`. Split (g): non-string filtering belongs in planner
   tests, while optional-schema acceptance/forwarding belongs in
   `tests/test_mcp.py` or `tests/test_ops_registry.py`. Note that the repository's
   custom validator checks only the outer `array` type, not `_STR_ARRAY.items`,
   so mixed arrays currently reach the handler and must be filtered safely.
   Finally, add explicit tests that `catalog.queries.plan_cli_chain` forwards the
   terms and serializes `relevance_rank`; neither behavior is covered by the
   listed registry tests as written.

## Codex review — confirm pass

**CONFIRM.** All five pre-panel findings are faithfully folded in the cited
sections. The folds introduce no new contradiction, including across §2.2's
order-invariance claim and test (b), the leaf-module helper import direction,
and §2.1's runtime filtering with §3(f).
