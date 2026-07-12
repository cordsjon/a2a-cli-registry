# Planner: Recognize `external` Side-Effect Class + send_mail Output Type — Design

> **US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01** (BACKLOG Ideation, narrowed scope —
> see "Scope narrowing" below). Two-part fix so `plan_cli_chain` can actually
> select `send_mail` as a terminal chain hop.

## Problem

`send_mail`'s live capability row (`~/.hermes/cli-registry.db`) is
`side_effect='external', confidence='declared', output_types=''`. Two
independent bugs each separately block it from ever being selected by
`plan_chain`:

**Bug 1 — unrecognized side_effect value.** `core/planner/search.py`'s
`_slug_side_effect()` only recognizes a closed 5-value order list:

```python
def _slug_side_effect(caps_for_slug) -> str:
    order = ["destructive", "unknown", "network", "writes-fs", "none"]
    present = {c.side_effect for c in caps_for_slug}
    for level in order:
        if level in present:
            return level
    return "unknown"          # <-- 'external' falls through to here
```

A capability list whose only side-effect value is `external` falls through
to `"unknown"`. `_hop_excluded()` then excludes that hop under the default
empty allow-set (fail-UNSAFE). Note this is *not* absolute: allowing
`unknown` explicitly (`allow_side_effects={'unknown'}`) already admits the
coerced row today — but no legitimate caller does that, since `unknown` is
meant to gate genuinely unclassified capabilities, not stand in for
`external`.

**Bug 2 — empty output_types.** Independently of Bug 1, `plan_chain` only
ever accepts a hop as a *terminal* candidate when
`_slug_produces(caps[tail]) & goal_out` is nonempty
(`core/planner/search.py:114-116`). `send_mail`'s `output_types=''` means
`_slug_produces` always returns an empty set, so it can never intersect any
requested `goal_outputs` — it is structurally unreachable as a chain
terminus regardless of Bug 1. Fixing Bug 1 alone would not make `send_mail`
selectable for any real goal; both bugs must be fixed together for the
practical outcome (planner can route "email"-shaped goals to `send_mail`).

## Scope narrowing (this session)

The original ticket bundled three concerns. Live investigation
(2026-07-12) found part of its premise stale — `seed_anthropic_index` really
does still have empty `input_types`/`output_types` in the live DB, and
`send_mail`'s problem turned out to ALSO include an empty output type
(`output_types=''`), on top of its `side_effect` vocabulary gap — so this
design covers `send_mail`'s two blockers (Bug 1 + Bug 2 above) as one
tightly-coupled fix, since either alone is insufficient. `seed_anthropic_index`
remains a separate, unrelated CLI's gap. Deferred, separate tickets:

- Bridging hermes-adapter's free-form LLM-inferred `side_effects` terms
  (e.g. `'email'`) to the registry's closed `side_effect` enum — a
  different mechanism (adapter-side term vs. registry-side class), not
  addressed here.
- `seed_anthropic_index` capability I/O backfill — unrelated CLI, unrelated
  gap (empty type data vs. unrecognized value).
- The adapter's single-candidate bypass silently skipping a producer hop on
  compound goals — separate mechanism (`hermes-adapter/cli_registry.py`
  `handle_run_cli_command`), not a registry planner change.

**Related, not overlapping:** `US-CLIREG-SIDEEFFECT-GUARD-01` (BACKLOG,
State: Ready) is the inverse problem — the adapter's vocab guard doesn't
*reject* hallucinated/out-of-vocab side-effect tags before they reach
`plan_cli_chain`. That ticket is about rejecting bad values earlier; this
one is about correctly recognizing a good, already-declared value. Fixing
this design doesn't satisfy that ticket's ACs or vice versa.

## Fix

Hand-declared values only — do not touch the automated LLM-fallback
backfill's vocabulary (`tools/capability_llm_fallback.py`'s `_SIDE_EFFECTS`
stays 5-value). Rationale: no evidence yet that other CLIs need
auto-*inferred* `external` classification, and changing the LLM fallback's
prompt risks reclassifying some subset of existing inferred capability rows.
Minimal, reversible. `send_mail` is currently the only row in the live
registry with `side_effect='external'` — its exact provenance (which
process/tool set `confidence='declared'`) is not established by any tool
read during this investigation; `CliAuditSource`/`populate()` can persist an
arbitrary `side_effect` string with `confidence='declared'`, which is
consistent with the observed row, but the cited backfill tools
(`capability_llm_fallback.py`, `backfill_capabilities.py`) cannot have
produced it — they only ever emit `confidence='inferred'` from a closed
5-value list. Treat "hand-declared" as "declared via some feed/manual path,"
not as evidence a specific known tool wrote it.

### Part 1 — recognize `external` in the planner

1. **`core/models.py:32`** — update the `Capability.side_effect` field
   comment from `# none/writes-fs/network/destructive/unknown` to
   `# none/writes-fs/network/external/destructive/unknown`, documenting the
   vocabulary is now 6-valued for hand-declared rows.

2. **`core/planner/search.py`** — `_slug_side_effect()`'s `order` list gains
   `"external"`, placed between `network` and `writes-fs`:

   ```python
   order = ["destructive", "unknown", "network", "external", "writes-fs", "none"]
   ```

   This position only affects **which single value gets selected as the
   representative class** when a slug has multiple `Capability` rows with
   different `side_effect` values (first match in `order` wins) — it does
   **not** affect chain ranking. `Chain.sort_key()`'s `side_effect_count`
   (`_finalize()`) is a plain count of hops whose selected class is not
   `none`; it does not compare classes by severity, so `writes-fs`,
   `external`, and `network` all contribute the same weight of 1 once
   admitted. There is no severity-based tiebreak in this codebase today —
   an earlier draft of this section claimed otherwise and was wrong.

   `_hop_excluded()` needs **no structural change**. It already branches
   generically:
   - worst-case class in `_UNSAFE_DEFAULT = {destructive, unknown}` and not
     allowed → excluded
   - class in `allow_side_effects` → allowed
   - class carried only by an `inferred` (not `declared`) capability and
     not allowed → excluded

   Once `external` is a recognized non-`unknown` value, this logic treats it
   identically to `network`/`writes-fs` today: a **single-capability-row**
   slug with a `declared` `external` value is allowed by default regardless
   of `allow_side_effects`. Caveat: if a slug has *multiple* capability rows
   and another row's value precedes `external` in `order` (e.g. `unknown` or
   `destructive`), that worse value is selected instead — "always allowed"
   only holds for the single-row case the tests below cover. No new code
   path is needed in `_hop_excluded` itself — this is the payoff of it
   already being class-generic rather than hardcoding per-value checks
   beyond the `order` list and `_UNSAFE_DEFAULT` set.

3. **`tests/test_planner.py`** — new cases mirroring existing
   `writes-fs`/`network` coverage. Each test gives its synthetic capability
   a **nonempty `output_types`** (Bug 2 below means a real empty-output
   `external` row can never reach the terminal-acceptance check, so testing
   side-effect admission requires an output type independent of that gap):
   - `test_declared_external_side_effect_always_allowed` — a single-row
     `declared, external` capability (nonempty `output_types`) is selectable
     by `plan_chain` with `allow_side_effects=set()`, matching
     `test_declared_writes_fs_still_allowed_by_default`'s pattern.
   - `test_inferred_external_side_effect_excluded_by_default` — an
     `inferred, external` capability is excluded when `allow_side_effects`
     doesn't include `'external'`.
   - `test_inferred_external_side_effect_included_when_allowed` — same
     capability is selectable when `allow_side_effects={'external'}`.

### Part 2 — backfill `send_mail`'s `output_types`

`send_mail` is a pure side-effect/confirmation CLI: it sends an email and
returns a confirmation, not a file artifact. This matches
hermes-adapter's own tag-inference contract exactly —
`_TAG_INFER_SYSTEM` (`hermes_adapter/tools/cli_registry.py:490-494`)
explicitly instructs the model to use `goal_outputs=['text']` for
"ACTION goal[s] whose point is a side effect rather than a produced file
... the command returns a confirmation, not a file." So the adapter will
request `goal_outputs=['text']` for a "send an email" goal today — meaning
`output_types='text'` is not an arbitrary choice but the value the existing
adapter contract already assumes is there.

Direct, single-row DB update against the live registry
(`~/.hermes/cli-registry.db`), not routed through
`backfill_capabilities.py` (that pipeline only ever writes `inferred`-
confidence proposals and would not touch a `declared` row — see
`write_commit`'s provenance gating): set `send_mail`'s `output_types` from
`''` to `'text'`. This is a one-row, hand-authored correction, consistent
with how the row's `side_effect`/`confidence` were already set.

No other CLI in the live registry has `side_effect='external'`
(confirmed by direct query), so this backfill is scoped to exactly one row.

## Non-goals

- Adapter-side `'email'` → `'external'` term mapping (deferred, see Scope
  narrowing).
- `seed_anthropic_index` I/O backfill (deferred, unrelated CLI/gap — its
  empty types are a separate, still-open issue from `send_mail`'s).
- Compound-goal bypass guard in `handle_run_cli_command`
  (`hermes_adapter/tools/cli_registry.py:801`, deferred, separate mechanism,
  not this repo).
- Any change to `capability_llm_fallback.py`'s inferred-value vocabulary.
- Any change to `_UNSAFE_DEFAULT` — `external` is not added there; it
  follows the same allow-by-declared/exclude-by-inferred-unless-allowed
  path as `network`/`writes-fs`.
- Fixing `send_mail`'s `a2a_invokable=0` flag (live-confirmed via direct
  query) — a separate, orthogonal gate from whether the planner can select
  it as a candidate hop; out of scope here.

## Testing

`a2a-cli-registry`'s `tests/test_planner.py` (currently 14 tests) gains 3
new cases → 17. Full suite must stay green. hermes-adapter is untouched by
this spec (no adapter code changes) — its own suite (839 tests collected
via `pytest --collect-only -q`, not the narrower 116-count from
`test_cli_*.py` alone used in an earlier resume-checklist) is unaffected and
not part of this spec's verification surface. Part 2's DB update is a live,
single-row data change (not a schema/code change) — verify post-update with
a direct query, not a test.

## Rollback

Two-part, both reversible independently:
- Part 1 (code): remove `"external"` from the `order` list in
  `core/planner/search.py` and revert the `core/models.py` comment.
- Part 2 (data): revert `send_mail`'s `output_types` back to `''` via a
  direct DB update. No migration machinery either way — no
  `backfill_capabilities.py` involvement, no registry-service restart
  required beyond picking up the code change (Part 1) or the next read
  (Part 2, live data).

## Files touched

- Modify: `core/models.py` (comment only, line 32)
- Modify: `core/planner/search.py` (`_slug_side_effect`'s `order` list)
- Test: `tests/test_planner.py` (3 new cases)
- Data: `~/.hermes/cli-registry.db`, `send_mail`'s `capability.output_types`
  row (`'' → 'text'`) — live DB, not a repo file.

## Acceptance Criteria

- **AC-01** — `_slug_side_effect` returns `"external"` (not `"unknown"`) for
  a capability list whose only row has `side_effect='external'`.
- **AC-02** — A single-row, `declared`, `external`-side-effect capability
  (with nonempty `output_types`, per the Testing note on Bug 2) is included
  in `plan_chain`'s candidate hops when called with matching `goal_inputs`
  (nonempty, intersecting that capability's `input_types` — mirroring
  `test_declared_writes_fs_still_allowed_by_default`'s `goal_inputs=["file:pdf"]`
  pattern, not an empty `goal_inputs`) and `allow_side_effects=set()` (no
  opt-in required — matches `declared writes-fs` precedent for the
  single-row case).
- **AC-03** — An `inferred`, `external`-side-effect capability is excluded
  by default and included only when `allow_side_effects` contains
  `'external'`.
- **AC-04** — Full `a2a-cli-registry` test suite green, zero regressions in
  existing `writes-fs`/`network`/`destructive` planner tests.
- **AC-05 (live)** — Post-deploy (both Part 1 code change and Part 2 data
  update applied): `plan_cli_chain(goal_inputs=['text'], goal_outputs=['text'],
  allow_side_effects=set())` against the live registry includes `send_mail`
  as a candidate terminal hop. `goal_inputs` must be nonempty and match
  `send_mail`'s declared `input_types='text'` — an **empty** `goal_inputs`
  does NOT work even post-fix: `plan_chain`'s `starts` selection
  (`core/planner/search.py:96-98`) only admits no-declared-input CLIs when
  `goal_in` is empty, and `send_mail` has a nonempty declared `input_types`,
  so it is excluded from `starts` under `goal_inputs=[]` regardless of Bugs
  1/2. Verified live-simulated during spec-panel review: `goal_inputs=[]` →
  `[]`; `goal_inputs=['text']` → `[['send_mail']]` (with both fixes applied
  in the simulation). This is the concrete, previously-impossible outcome
  both parts of this fix are required to jointly produce — neither part
  alone achieves it (Part 1 alone: still unreachable, empty `output_types`;
  Part 2 alone: still `unknown`-coerced and excluded).
- **AC-06 (live, explicitly bounded)** — This AC set does NOT claim the
  adapter's compound syllabus2 prompt succeeds end-to-end. That additionally
  requires the deferred adapter-side `'email'`→`'external'` term mapping and
  the compound-goal bypass guard (separate tickets, not this spec).

## sh:spec-panel review

Experts: karl-wiegers, gojko-adzic, martin-fowler, lisa-crispin (default) +
charity-majors (auto-selected: `cli`/`external` keywords). AI-production
dimensions gate triggered (llm/prompt/model/pipeline keywords present).

**Findings (grounded + refute-stage survivors), both auto-fixed above:**
- Wiegers/testability: AC-05 as originally written used
  `goal_inputs=[]`, which live-simulation proved returns `[]` even with both
  fixes applied — `send_mail`'s nonempty declared `input_types` excludes it
  from `plan_chain`'s `starts` set when `goal_in` is empty
  (`core/planner/search.py:96-98`). Fixed: AC-05 and AC-02 now require
  `goal_inputs=['text']` (matching `send_mail`'s declared input), verified
  live-simulated to return `[['send_mail']]` post-fix.
- Adzic/concrete-examples: AC-02's original wording didn't state the test's
  required `goal_inputs` precondition explicitly. Fixed: AC-02 now names the
  nonempty, intersecting `goal_inputs` requirement and cites the existing
  `test_declared_writes_fs_still_allowed_by_default` pattern it mirrors.

No findings survived refutation from Fowler (interface boundaries —
`_hop_excluded` reuse confirmed clean, no new coupling), Crispin (test
strategy proportional to risk — 3 unit tests + 1 live AC judged adequate for
an S-effort planner change), or Majors (evidence-over-analogy — the spec
already commits to a live probe rather than an assumed behavior; the probe's
parameters were the only issue, now corrected and re-verified by live
simulation during this review).

**Scores:** clarity 8.5, completeness 7.5, testability 6.5→8.5 (post-fix),
consistency 8.0, public-readiness 8.0. AI-production dimensions: only
output-integrity meaningfully applies (8.0); isolation-enforcement and
security-boundaries are N/A (no multi-agent or read-only claims in this
spec) and excluded from the average.

**Overall (post-fix): 8.1 — PASS** (threshold 7.0).

PANEL-VERDICT: 8.1

## Codex review — pre-panel

Grounding review against the repository and the live DB referenced above,
performed 2026-07-12:

- **The quoted `_slug_side_effect()` implementation is exact.** In
  `core/planner/search.py:33-39`, the current order is exactly
  `['destructive', 'unknown', 'network', 'writes-fs', 'none']`, and a list
  whose only side-effect value is `external` falls through to `unknown`.
  `_hop_excluded()` then excludes that row with the default empty allow-set
  and also when only `external` is allowed. However, the Problem section's
  stronger “regardless of what `allow_side_effects` the caller passes” and
  “never” claims are not literally true: allowing `unknown` admits the
  currently coerced row. A direct call confirms
  `_hop_excluded(external_declared, {'unknown'}) is False`.

- **The proposed order does not rank chains by side-effect severity.** The
  order only chooses one representative (worst) class when a slug has
  multiple capability rows. `_finalize()` computes `side_effect_count` as
  one for every hop whose selected class is not `none`, and
  `Chain.sort_key()` compares that count; it never compares the selected
  class's position in `order`. Thus the claim at lines 83-85 that the rank
  feeds the tiebreak so “fewer/milder side effects sort first” is wrong:
  fewer sorts first, but `writes-fs`, `external`, `network`, `unknown`, and
  `destructive` each contribute the same count of one after admission.

- **AC-01 and “always allowed” need a single-class qualification.** Because
  `unknown` and `destructive` precede the proposed `external` entry, a
  capability list that merely *contains* an `external` row can still resolve
  to `unknown` or `destructive` when another row for the slug carries that
  value. Likewise, a declared `external` row is allowed by default only when
  `external` is the class selected for the slug. The intended tests appear
  to use one capability row and are valid for that narrower case.

- **`core/models.py:32` is grounded exactly.** The field is at line 32 and its
  current comment is
  `# none/writes-fs/network/destructive/unknown`, exactly as the Fix section
  says. This is documentation only: the SQLModel field is an unconstrained
  `str`, so the change does not enforce a six-value enum.

- **The live `send_mail` values exist, but the claimed provenance is not
  established by the cited backfill tools.** The referenced live DB currently
  has `send_mail` with `input_types='text'`, `output_types=''`,
  `intent_tags='notify,send'`, `side_effect='external'`, and
  `confidence='declared'`. That combination is plausible through the normal
  feed/populate path: `CliAuditSource` accepts arbitrary `side_effect` strings
  and defaults an omitted confidence to `declared`, and `populate()` persists
  the merged record. In contrast, `tools/capability_llm_fallback.py:18,84-92`
  cannot emit `external` and always emits `confidence='inferred'`; the static
  extractor also emits `inferred`; and `tools/backfill_capabilities.py:285-298`
  merely writes those proposal fields. Therefore those tools cannot have
  created the observed `external`/`declared` pair, and the live schema has no
  provenance columns from which “hand-declared” can be proven. The pair must
  have come from a feed/manual path or another process.

- **The live row is not “fully declared,” and the proposed fix is not by
  itself sufficient to select that actual row.** Its `output_types` is empty.
  `plan_chain()` only finalizes a candidate when
  `_slug_produces(caps[tail]) & goal_out` is nonempty
  (`core/planner/search.py:114-116`), so the current live `send_mail` cannot be
  returned as a terminal candidate for any requested output even after
  `external` is recognized. A new test that gives the external capability a
  synthetic nonempty output can verify side-effect admission, but should not
  be called literally `send_mail`-shaped. This also means the headline/root-
  cause wording and AC-05 overstate what this isolated change accomplishes
  for the live row; the empty-output modeling gap remains.

- **The three proposed test names and structures generally fit
  `tests/test_planner.py`.** The file uses module-level snake-case
  `test_<behavior>` functions with the `db` fixture, direct `Cli`/
  `Capability`/`CliEdge` setup, and `plan_chain()` assertions. It already has
  `_inferred_fleet(db, se=...)`,
  `test_inferred_side_effect_excluded_by_default`,
  `test_inferred_side_effect_included_when_allowed`, and
  `test_declared_writes_fs_still_allowed_by_default`, so the proposed cases
  fit naturally (with the “always” qualification above). There are currently
  14 tests in this file, so adding three means 17 planner tests.

- **Other factual drift:** the Rollback section says “Single-file revert” but
  immediately requires reverting both `core/planner/search.py` and the
  `core/models.py` comment; this is a two-file revert. The cited external
  adapter function exists, but its path is
  `hermes_adapter/tools/cli_registry.py:801`, not the stated
  `hermes-adapter/cli_registry.py`. The “existing 116-test hermes-adapter
  suite” count is stale for the currently installed checkout: `pytest
  --collect-only -q` reports 839 tests. Finally, the live DB currently has 79
  non-`none`/non-`unknown` side-effect rows (475 nonempty side-effect fields),
  so the unqualified “191 existing side-effect-bearing capability rows” is
  not reproducible from the referenced database and should define its filter
  and snapshot if retained.
