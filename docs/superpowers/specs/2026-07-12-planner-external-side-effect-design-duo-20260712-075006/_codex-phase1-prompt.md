You are CODEX (GPT-5.2), an independent reviewer.

You are one of TWO reviewers performing an independent review of the spec.
You will NEVER see the other reviewer's findings — your report stands on its own.
Claude will read both reports and triage per-comment.

Phase: pre-panel
Spec: /Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/specs/2026-07-12-planner-external-side-effect-design.md

Use ONLY the bundle you are given (CONTEXT.md + SPEC.md). Do not re-explore the repo —
the context collector already did that and noted gaps in section 7. If something you
would want to verify is missing from the context, flag it explicitly rather than guess.

Output structure (markdown, to stdout):

## Findings — <your name>

For each finding:

### [SEVERITY] short title
- What: the issue in one sentence
- Where: spec section, line, or quoted phrase
- Why it matters: the consequence if shipped as-is
- Suggested fix: concrete change, not a vague direction
- Confidence: high | medium | low

SEVERITY in { CRITICAL, IMPORTANT, NIT }
- CRITICAL — wrong premise, broken cross-reference, will cause rework or incident
- IMPORTANT — design weakness, missing scope, ambiguous decision
- NIT — wording, typo, minor inconsistency

At the end:

## Self-flagged uncertainty
Bullet list of points where you have low confidence — Claude will weigh these against
the other reviewer's report if they cover overlapping ground.

Constraints:
- Append-only. Do not propose edits to the spec text directly.
- Cite line numbers or quoted phrases for every finding.
- If you have zero findings in a severity, write (none) — do not pad.
- Disagree freely with what you would expect a co-reviewer to say. Independence is
  the entire point of running two of you.

BUNDLE:

# DUO REVIEW BUNDLE

## CONTEXT.md (collected by gemini, phase 0)

# CONTEXT — 2026-07-12-planner-external-side-effect-design

_Generated procedurally by phase0-procedural.sh at 2026-07-12T05:50:06Z.
No LLM call — pure grep + stat. Reviewers can request deeper context on demand._

## 1. Spec under review

- **Path:** `/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/specs/2026-07-12-planner-external-side-effect-design.md`
- **Last modified:** 2026-07-12 07:49:12
- **Lines:** 167
- **Bytes:** 8170
- **Project root:** `/Users/jcords-macmini/projects/a2a-cli-registry`

### Section index

- Problem
- Scope narrowing (this session)
- Fix
- Non-goals
- Testing
- Rollback
- Files touched
- Acceptance Criteria

## 2. Cited artifacts — grounded existence checks

This is the **grounding layer**. Every citation extracted from the spec was checked
against the filesystem. `OK` = path exists, `MISSING` = does not exist, `GLOB` =
matches via shell glob (count > 0).

### 2.1 Tilde paths

| Path | Status | Size / kind |
|---|---|---|
| `~/.hermes/cli-registry.db` | OK | file, 589824B |

### 2.2 Backticked filenames

| Filename | Status | Locations (up to 3) |
|---|---|---|
| `capability_llm_fallback.py` | OK | ~/projects/a2a-cli-registry/tools/capability_llm_fallback.py |
| `core/models.py` | OK | ~/projects/a2a-cli-registry/core/models.py |
| `core/planner/search.py` | OK | ~/projects/a2a-cli-registry/core/planner/search.py |
| `hermes-adapter/cli_registry.py` | MISSING | — |
| `tests/test_planner.py` | OK | ~/projects/a2a-cli-registry/tests/test_planner.py |
| `tools/capability_llm_fallback.py` | OK | ~/projects/a2a-cli-registry/tools/capability_llm_fallback.py |

### 2.3 Slash-commands (skills)

| Command | Status | Path |
|---|---|---|

### 2.4 sh: panel skills

| Skill | Status | Path |
|---|---|---|

## 3-6. Surrounding code, prior decisions, open questions, repo conventions

**Procedurally deferred.** This collector intentionally does not synthesize these
sections — they require judgment the grounding layer alone cannot provide.
Reviewers should pull what they need:

- For *surrounding code* of a flagged path: open the path directly.
- For *prior decisions*: check sibling specs in `/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/specs` (see section index).
- For *open questions inherited*: search the spec for "Q1", "Q2", etc.
- For *repo conventions*: read `/Users/jcords-macmini/projects/a2a-cli-registry/CLAUDE.md` and `/Users/jcords-macmini/projects/a2a-cli-registry/KNOWN_PATTERNS.md`.

## 7. What this collector did NOT check

- Function names, CLI sub-commands, and config keys (`escalation.to`, `schema_version` etc.) — these are spec-internal JSON schema fields, not external artifacts; no existence check applies.
- External URLs and resources.
- Path placeholders containing `<...>` or `...` — filtered out as noise.
- Whether file *contents* match the spec's claims about them. Only file existence is verified.
- Imports / call sites of cited code paths (would require an LSP or wider grep).

If a reviewer needs any of these, they should request explicitly.

## SPEC.md (/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/specs/2026-07-12-planner-external-side-effect-design.md)

# Planner: Recognize `external` Side-Effect Class — Design

> **US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01** (BACKLOG Ideation, narrowed scope —
> see "Scope narrowing" below). Root-cause fix so `plan_cli_chain` can select
> `send_mail`-class CLIs at all.

## Problem

`send_mail`'s live capability row (`~/.hermes/cli-registry.db`) is correctly
hand-declared: `side_effect='external', confidence='declared'`. But
`core/planner/search.py`'s `_slug_side_effect()` only recognizes a closed
5-value order list:

```python
def _slug_side_effect(caps_for_slug) -> str:
    order = ["destructive", "unknown", "network", "writes-fs", "none"]
    present = {c.side_effect for c in caps_for_slug}
    for level in order:
        if level in present:
            return level
    return "unknown"          # <-- 'external' falls through to here
```

Any `side_effect` value not in `order` (including `'external'`) silently
degrades to `"unknown"`. `_hop_excluded()` then treats the hop as the
fail-unsafe `unknown` class, excluded by default regardless of what
`allow_side_effects` the caller passes. Net effect: `plan_cli_chain` can
**never** select `send_mail` as a chain hop — not a vocabulary-matching
problem at the `allow_side_effects` term level, but a silent value-coercion
bug one layer below it.

## Scope narrowing (this session)

The original ticket bundled three concerns. Live investigation
(2026-07-12) found part of its premise stale — `seed_anthropic_index` really
does still have empty `input_types`/`output_types` in the live DB, but
`send_mail`'s problem is NOT missing/empty capability data (it's fully
declared). Per user decision, this design covers **only** the `side_effect`
vocabulary-recognition bug. Deferred, separate tickets:

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
prompt risks reclassifying some subset of the 191 existing side-effect-bearing
capability rows. Minimal, reversible.

1. **`core/models.py:32`** — update the `Capability.side_effect` field
   comment from `# none/writes-fs/network/destructive/unknown` to
   `# none/writes-fs/network/external/destructive/unknown`, documenting the
   vocabulary is now 6-valued for hand-declared rows.

2. **`core/planner/search.py`** — `_slug_side_effect()`'s `order` list gains
   `"external"`, ranked between `network` and `writes-fs`:

   ```python
   order = ["destructive", "unknown", "network", "external", "writes-fs", "none"]
   ```

   Rationale for rank: `external` actions (e.g. sending one specific,
   declared email) are typically narrow-scope and single-purpose, less
   open-ended than generic `network` (arbitrary remote API access), but
   still leave the system boundary — more consequential than a local
   `writes-fs` side effect. This rank feeds `Chain.sort_key()`'s
   `side_effect_count` tiebreak (fewer/milder side effects sort first when
   multiple valid chains exist).

   `_hop_excluded()` needs **no structural change**. It already branches
   generically:
   - worst-case class in `_UNSAFE_DEFAULT = {destructive, unknown}` and not
     allowed → excluded
   - class in `allow_side_effects` → allowed
   - class carried only by an `inferred` (not `declared`) capability and
     not allowed → excluded

   Once `external` is a recognized non-`unknown` value, this logic treats it
   identically to `network`/`writes-fs` today: a `declared` `external` hop
   (like `send_mail`) is always allowed regardless of `allow_side_effects`;
   an `inferred` `external` hop would be excluded unless the caller opts in.
   No new code path — this is the payoff of `_hop_excluded` already being
   class-generic rather than hardcoding per-value checks beyond the `order`
   list and `_UNSAFE_DEFAULT` set.

3. **`tests/test_planner.py`** — new cases mirroring existing
   `writes-fs`/`network` coverage:
   - `test_declared_external_side_effect_always_allowed` — a `send_mail`-shaped
     capability (`side_effect='external', confidence='declared'`) is
     selectable by `plan_chain` with `allow_side_effects=set()` (no opt-in
     needed, matching how `declared writes-fs` behaves today per
     `test_declared_writes_fs_still_allowed_by_default`).
   - `test_inferred_external_side_effect_excluded_by_default` — an
     `inferred` `external` capability is excluded when `allow_side_effects`
     doesn't include `'external'`.
   - `test_inferred_external_side_effect_included_when_allowed` — same
     capability is selectable when `allow_side_effects={'external'}`.

## Non-goals

- Adapter-side `'email'` → `'external'` term mapping (deferred, see Scope
  narrowing).
- `seed_anthropic_index` I/O backfill (deferred, unrelated CLI/gap).
- Compound-goal bypass guard in `handle_run_cli_command` (deferred, separate
  mechanism, separate repo).
- Any change to `capability_llm_fallback.py`'s inferred-value vocabulary.
- Any change to `_UNSAFE_DEFAULT` — `external` is not added there; it
  follows the same allow-by-declared/exclude-by-inferred-unless-allowed
  path as `network`/`writes-fs`.

## Testing

Existing 116-test hermes-adapter suite is unaffected (no adapter changes).
`a2a-cli-registry`'s `tests/test_planner.py` gains 3 new cases; full suite
must stay green. No live DB migration — `'external'` already exists in the
data; only the code's recognition of it changes.

## Rollback

Single-file revert: remove `"external"` from the `order` list in
`core/planner/search.py` and revert the `core/models.py` comment. No data
migration, no adapter changes, no registry-service restart required beyond
picking up the code change.

## Files touched

- Modify: `core/models.py` (comment only, line 32)
- Modify: `core/planner/search.py` (`_slug_side_effect`'s `order` list)
- Test: `tests/test_planner.py` (3 new cases)

## Acceptance Criteria

- **AC-01** — `_slug_side_effect` returns `"external"` (not `"unknown"`) for
  a capability list containing a row with `side_effect='external'`.
- **AC-02** — A `declared`, `external`-side-effect capability (e.g.
  `send_mail`-shaped) is included in `plan_chain`'s candidate hops with
  `allow_side_effects=set()` (no opt-in required — matches `declared
  writes-fs` precedent).
- **AC-03** — An `inferred`, `external`-side-effect capability is excluded
  by default and included only when `allow_side_effects` contains
  `'external'`.
- **AC-04** — Full `a2a-cli-registry` test suite green, zero regressions in
  existing `writes-fs`/`network`/`destructive` planner tests.
- **AC-05 (live, informational)** — Post-deploy, `plan_cli_chain` called
  with `allow_side_effects=set()` and goal shapes that would previously
  exclude `send_mail` now includes it as a candidate hop when its
  `input_types`/`output_types` otherwise satisfy the chain. This does NOT by
  itself make the adapter's compound syllabus2 prompt succeed end-to-end —
  that requires the deferred adapter-side term-mapping and bypass-guard
  work (separate tickets).
