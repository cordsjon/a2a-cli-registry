## Findings — CODEX (GPT-5.2)

### CRITICAL — Recognition is incorrectly coupled to authorization
- What: The design fixes recognition but additionally makes declared `external` actions—including sending email—eligible with no explicit caller opt-in.
- Where: Fix §2, “a `declared` `external` hop … is always allowed regardless of `allow_side_effects`”; AC-02, “included … with `allow_side_effects=set()`.”
- Why it matters: Recognizing `external` instead of coercing it to `unknown` only requires allowing callers to opt in with `{'external'}`. Automatically admitting externally visible actions is a separate policy change and could cause plans to execute communications or other real-world effects unexpectedly.
- Suggested fix: Keep recognition and authorization separate: add `"external"` to `_slug_side_effect()` but require `allow_side_effects={'external'}` for both declared and inferred capabilities. Update AC-02 and its test accordingly; if no-opt-in behavior is an intentional product decision, require an explicit safety-policy decision rather than deriving it from the `writes-fs` precedent.
- Confidence: high

### IMPORTANT — The claimed sorting effect is unspecified and potentially false
- What: The spec says the position of `"external"` in `_slug_side_effect()`’s list feeds `Chain.sort_key()`’s `side_effect_count`, but does not explain how an ordered class becomes a count or weight.
- Where: Fix §2, “This rank feeds `Chain.sort_key()`’s `side_effect_count` tiebreak.”
- Why it matters: The list visibly establishes precedence only when aggregating multiple capability rows for one slug. If `side_effect_count` merely counts side-effecting hops, moving `"external"` within this list will not make external chains sort between network and filesystem chains, so the stated behavioral rationale and implementation may diverge.
- Suggested fix: Specify the exact class-to-sort-key transformation and add a test comparing otherwise equal chains containing `network`, `external`, and `writes-fs` hops. If sorting is unweighted, remove the claimed tiebreak behavior and justify the order solely as worst-case slug aggregation.
- Confidence: medium

### IMPORTANT — Tests do not cover the behavior actually changed by inserting into an ordered aggregator
- What: The proposed tests cover only an `external` capability in isolation, not its precedence when a slug has multiple capability rows.
- Where: Fix §2 changes `order` to `["destructive", "unknown", "network", "external", "writes-fs", "none"]`; Testing proposes three declared/inferred eligibility cases; AC-01 mentions only “a capability list containing a row with `side_effect='external'`.”
- Why it matters: `_slug_side_effect()` aggregates all rows for a slug, so boundary mistakes in the new ordering could pass every proposed test while producing the wrong worst-case classification for real multi-capability CLIs.
- Suggested fix: Add direct aggregation tests proving at least: `external + network → network`, `external + writes-fs → external`, and `external + unknown → unknown`. Clarify AC-01’s expected result when other classes are present.
- Confidence: high

### IMPORTANT — The target API names and test level are not grounded
- What: The problem and live AC target `plan_cli_chain`, while all proposed automated coverage targets `plan_chain`, without documenting their relationship.
- Where: Problem, “root-cause fix so `plan_cli_chain` can select”; Fix §3 repeatedly says `plan_chain`; AC-05 returns to `plan_cli_chain`.
- Why it matters: Unit tests could pass against an internal planner while the user-facing path still transforms, filters, or bypasses the result differently. The bundle explicitly says function names and call sites were not verified.
- Suggested fix: Identify which module owns each function and how `plan_cli_chain` reaches `plan_chain`. Add a test at the highest registry-owned entry point in scope, or explicitly state why the `plan_chain` tests fully exercise `plan_cli_chain`’s relevant behavior.
- Confidence: medium

### NIT — Rollback is not a single-file revert
- What: The rollback calls this a “Single-file revert” but immediately requires reverting two production files.
- Where: Rollback, “Single-file revert: remove `"external"` … and revert the `core/models.py` comment.”
- Why it matters: It gives an inaccurate operational summary and omits what should happen to the three added tests.
- Suggested fix: Describe it as a two-file production rollback and state whether the new tests are reverted or updated with the behavior.
- Confidence: high

### NIT — The adapter source reference is unresolved in the supplied grounding
- What: The spec cites `hermes-adapter/cli_registry.py`, but the bundle reports that path as missing and provides no external repository-qualified location.
- Where: Scope narrowing, “`hermes-adapter/cli_registry.py` `handle_run_cli_command`”; Non-goals also calls it a “separate repo.”
- Why it matters: Future readers cannot follow the cited cross-reference from this repository, weakening the justification for the deferred boundary.
- Suggested fix: Append a repository-qualified path, URL, or durable ticket identifier for the adapter bypass concern.
- Confidence: high

## Self-flagged uncertainty

- The bundle did not include `Chain.sort_key()` or `_hop_excluded()` contents, so the sorting finding is based on an unexplained claim in the spec rather than code verification.
- The bundle did not verify the `plan_chain`/`plan_cli_chain` symbols or their call relationship.
- The repository’s established authorization contract may deliberately trust all declared side effects. The bundle establishes a `writes-fs` precedent but contains no explicit safety-policy decision covering externally visible actions.
