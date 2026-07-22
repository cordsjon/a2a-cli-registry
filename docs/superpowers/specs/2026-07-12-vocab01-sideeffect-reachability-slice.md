# US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01 — Side-effect Reachability Slice

**Date:** 2026-07-12
**Status:** Design — PLAN-READY. This is the §2.2-independent slice carved out of the original
VOCAB-01 spec after the `goal_actions` dimension (§2.2–§2.8) was spun out into its own ticket
(see `2026-07-12-goal-actions-dimension-design.md`). Both ACs below were Codex-CONFIRMED across
prior passes and carry NO dependency on the unresolved action→verb matching design.
**Repos touched:** `a2a-cli-registry` (tests), live registry DB (`~/.hermes/cli-registry.db`).

---

## 1. Scope

The parent ticket bundled two independent, already-verified fixes with a large planner
redesign. The redesign (compound side-effect goals via a `goal_actions` dimension) has an
open design question (§2.2 verb-matching, refuted twice) and is now a separate ticket. What
remains here is the plannable, low-risk slice:

- **AC-02** — a verification test proving `send_mail` is reachable at the default candidate cap.
- **AC-03** — a live-DB capability backfill for `seed_anthropic_index`.

Neither touches `goal_actions`, the planner's matching logic, or the adapter. AC-02 is a
pure planner-reachability assertion; AC-03 is a data fix following the capability-backfill
runbook.

## 2. Background (verified facts, carried from the parent spec)

- `send_mail`'s live row is `intent_tags='notify,send' | input_types='text' | output_types='text'
  | side_effect='external' | confidence='declared'` in `~/.hermes/cli-registry.db`. Its
  declared-`external` recognition + `output_types` backfill shipped as AC-01 (`3a78aa8`), and
  the planner cap-starvation fix (`16798e3`) means `send_mail` now appears at the default cap
  (verified: `plan_chain(goal_inputs=['text'], goal_outputs=['text'], allow_side_effects=set())`
  includes `send_mail` at sorted position 18/100). AC-02 pins that reachability with a test.
- `seed_anthropic_index` (syllabus-2.0) consumes two `Path` args, writes a SQLite table, emits
  NO stdout data. Its true capability is `side_effect='writes-fs'`, `input_types='path'`,
  `output_types=''`, `confidence='inferred'` — NOT the DB's current `none`/empty row. AC-03
  backfills it. (Codex: `path` is real vocab per `capability_repair.py:27`; `declared` is
  ungrounded, keep `inferred`.)

## 3. Acceptance criteria

- **AC-02** — Verification test: `send_mail` reachable at the DEFAULT cap
  (`max_candidate_chains=100`). Codex flagged a tiny fixture insufficient — use either the
  exact live-row probe OR a fixture with 100+ competing candidates, asserting `send_mail`'s
  presence at the default cap. Deterministic, pure unit (`tests/test_planner.py`).
- **AC-03** — Backfill `seed_anthropic_index` in the live DB (`~/.hermes/cli-registry.db`;
  backup first, atomic UPDATE): `side_effect='writes-fs'`, `input_types='path'`,
  `output_types=''`, `confidence='inferred'`. Verify: exact affected-row count == 1, re-read
  matches, and `_hop_excluded(row, set())` == True (writes-fs excluded by default) / == False
  when `allow_side_effects={'writes-fs'}`.

## 4. Testing strategy

- **AC-02**: pure unit; 100+-contention fixture OR live-row probe. Deterministic. RED-first is
  optional here (the fix already shipped via `16798e3`) — this is a regression pin, so a
  GREEN-confirming test that would FAIL if the cap-starvation regressed is sufficient; note in
  the test docstring that it guards `16798e3`.
- **AC-03**: no unit test (data fix). Verification = affected-row-count == 1 + re-read +
  `_hop_excluded` assertions both ways. Backup is the rollback path.

## 5. Ordering

AC-02 and AC-03 are independent of each other and of the spun-out `goal_actions` work; either
can land first. AC-03 mutates the live DB — take the backup and assert the row count before
and after. No cross-repo deploy, no schema change, no adapter change.

## 6. Scope boundaries (YAGNI)

Explicitly OUT (moved to `2026-07-12-goal-actions-dimension-design.md`):
- The `goal_actions` dimension, action→verb matching (§2.2), terminal-edge synthesis,
  start-selection gate, slug-scoped self-authorization, adapter decode + reinference.
- AC-04 (adapter compound-goal bypass guard) and AC-05 (live producer→send_mail E2E).
- No real Python I/O *inference* (systemic `infer.py` gap) — AC-03 backfills the ONE row only.
