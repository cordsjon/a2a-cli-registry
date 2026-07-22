# Planner: Recognize `external` Side-Effect + `send_mail` Output Type — Implementation Plan

> **For agentic workers:** REQUIRED: Use `/sh:execute` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `send_mail` selectable by `plan_chain()` as a terminal chain hop by (1) teaching `_slug_side_effect()` to recognize `side_effect='external'` instead of coercing it to `unknown`, and (2) backfilling `send_mail`'s empty `output_types` to `'text'` in the live registry.

**Architecture:** Two independent, additive changes to `core/planner/search.py` and `core/models.py` (a one-value vocabulary extension that reuses `_hop_excluded()`'s existing class-generic logic unchanged), plus one hand-authored data correction to a single live DB row. No schema migration, no new code paths, no change to the LLM-inferred side-effect vocabulary.

**Tech Stack:** Python 3.11+, SQLModel, pytest, sqlite3 (direct query for the live data step).

**Spec:** [docs/superpowers/specs/2026-07-12-planner-external-side-effect-design.md](../superpowers/specs/2026-07-12-planner-external-side-effect-design.md) — spec-panel 8.1/10 PASS, 2 Codex grounding passes, all findings triaged.

---

## Scope note

This plan implements **only** what `US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01`'s narrowed spec covers: the `external` vocabulary gap (Bug 1) and `send_mail`'s empty `output_types` (Bug 2). It explicitly does **not** touch:
- `capability_llm_fallback.py`'s inferred-value vocabulary (stays 5-value)
- `seed_anthropic_index`'s I/O backfill (separate CLI, separate ticket)
- The adapter-side `'email'`→`'external'` term mapping or compound-goal bypass guard (separate repo, separate tickets)
- `plan_chain`'s candidate-cap starvation bug (filed as `US-CLIREG-PLANCHAIN-CAP-STARVATION-01`) — AC-05 below is deliberately scoped to NOT require fixing this.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `core/models.py` | `Capability` SQLModel definition | Comment-only update at line 32 (documents 6-value vocabulary) |
| `core/planner/search.py` | Chain-planning algorithm | `_slug_side_effect()`'s `order` list gains `"external"` (1-line change, line 34) |
| `tests/test_planner.py` | Planner unit tests | 3 new test functions appended, mirroring existing `writes-fs`/`inferred` patterns |
| `~/.hermes/cli-registry.db` | Live SQLite registry (not a repo file) | Single-row `UPDATE`: `send_mail.output_types` `'' → 'text'` |

No new files. No file is large enough to warrant splitting.

---

## Chunk 1: Code fix — recognize `external` in the planner

### Task 1: Update `Capability.side_effect` field comment

**Files:**
- Modify: `core/models.py:32`

- [ ] **Step 1: Edit the comment**

Current (line 32):
```python
    side_effect: str = "unknown"                    # none/writes-fs/network/destructive/unknown
```

New:
```python
    side_effect: str = "unknown"                    # none/writes-fs/network/external/destructive/unknown
```

This is documentation only — the field is an unconstrained `str`, so no validation logic changes.

- [ ] **Step 2: Commit**

```bash
git add core/models.py
git commit -m "docs: note external in Capability.side_effect vocabulary comment"
```

---

### Task 2: Teach `_slug_side_effect()` to recognize `external` (TDD)

**Files:**
- Modify: `core/planner/search.py:34`
- Test: `tests/test_planner.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_planner.py` (after `test_declared_writes_fs_still_allowed_by_default`, before `test_terminates_on_cyclic_typegraph`):

```python
def test_declared_external_side_effect_always_allowed(db):
    # a DECLARED external hop must be included by default, mirroring the
    # writes-fs precedent above. Nonempty output_types on the synthetic
    # capability is required — Bug 2 (empty output_types) is a separate,
    # independently-tested gap; this test isolates Bug 1 only.
    db.add(Cli(slug="src", lang="python"))
    db.add(Capability(cli_slug="src", intent_tags="g", input_types="file:pdf",
                      output_types="text:x", side_effect="none", confidence="declared"))
    db.add(Cli(slug="emid", lang="python"))
    db.add(Capability(cli_slug="emid", intent_tags="g", input_types="text:x",
                      output_types="text:goal", side_effect="external", confidence="declared"))
    db.add(CliEdge(from_slug="src", to_slug="emid", via_type="text:x"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"])
    assert any("emid" in c.slugs for c in chains)


def test_inferred_external_side_effect_excluded_by_default(db):
    # inferred (unverified) external side-effect must fail UNSAFE by default,
    # same rule as inferred writes-fs/network above.
    _inferred_fleet(db, se="external")
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"])
    assert chains == []


def test_inferred_external_side_effect_included_when_allowed(db):
    # same goal, operator opts into the external blast-radius class -> included
    _inferred_fleet(db, se="external")
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"],
                        allow_side_effects=["external"])
    assert any("mid" in c.slugs for c in chains)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_planner.py -k external -v`

Expected: 3 FAIL. `test_declared_external_side_effect_always_allowed` and `test_inferred_external_side_effect_included_when_allowed` fail because `external` currently falls through to `unknown` and gets excluded by `_UNSAFE_DEFAULT` (chains come back empty). `test_inferred_external_side_effect_excluded_by_default` fails for the wrong reason (currently excluded regardless, since `unknown` is also in `_UNSAFE_DEFAULT`) — confirm by reading the failure, not just the pass/fail count, since this specific test may show a passing false-positive before the fix. Note it and proceed; it will still be correctly exercised once `external` is a distinct recognized value.

- [ ] **Step 3: Implement the minimal fix**

`core/planner/search.py:34`, change:
```python
    order = ["destructive", "unknown", "network", "writes-fs", "none"]
```
to:
```python
    order = ["destructive", "unknown", "network", "external", "writes-fs", "none"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_planner.py -k external -v`

Expected: 3 PASS.

- [ ] **Step 5: Run the full planner suite (regression check)**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_planner.py -v`

Expected: 17 PASS (14 existing + 3 new), 0 FAIL. This directly verifies AC-04 (no regressions in `writes-fs`/`network`/`destructive` planner tests).

- [ ] **Step 6: Commit**

```bash
git add core/planner/search.py tests/test_planner.py
git commit -m "feat: recognize external side-effect class in planner (AC-01/02/03)"
```

---

## Chunk 1 review

- `_hop_excluded()` required zero code changes — confirmed by the spec's grounding review: it's already class-generic (checks membership in `order`, `_UNSAFE_DEFAULT`, and `allow_side_effects` rather than hardcoding per-value branches). The plan's Task 2 only touches the `order` list, matching that finding.
- The 3 new tests use synthetic `emid`/`mid` slugs with nonempty `output_types`, not `send_mail` itself — this correctly isolates Bug 1 (side-effect recognition) from Bug 2 (empty output_types), per the spec's Testing section. Chunk 2 handles the real `send_mail` row.
- Step 2's note about the "wrong reason" pass is intentional — flagging it prevents a worker from mis-diagnosing later if that specific assertion doesn't visibly change between red/green.

Clean — proceeding to Chunk 2.

---

## Chunk 2: Data fix — backfill `send_mail`'s `output_types`

### Task 3: Verify the live row before touching it

**Files:**
- None (read-only verification against `~/.hermes/cli-registry.db`)

- [ ] **Step 1: Confirm current state**

Run:
```bash
sqlite3 ~/.hermes/cli-registry.db "SELECT cli_slug, input_types, output_types, side_effect, confidence FROM capability WHERE cli_slug='send_mail';"
```

Expected output: `send_mail|text||external|declared` (empty `output_types` field between the two `|` characters). If this doesn't match — STOP, the live data has drifted since the spec was written; re-verify against current spec assumptions before proceeding.

- [ ] **Step 2: Confirm no other row already has `side_effect='external'`**

Run:
```bash
sqlite3 ~/.hermes/cli-registry.db "SELECT cli_slug FROM capability WHERE side_effect='external';"
```

Expected: exactly one row, `send_mail`. This confirms the spec's "scoped to exactly one row" claim still holds.

### Task 4: Apply the backfill

**Files:**
- Data: `~/.hermes/cli-registry.db` (live, not a repo file — no git commit for this step)

- [ ] **Step 1: Back up the live DB first**

```bash
cp ~/.hermes/cli-registry.db ~/.hermes/cli-registry.db.bak-$(date +%s)
```

(Reversibility per the spec's Rollback section — this is a live production DB, not a throwaway test fixture.)

- [ ] **Step 2: Apply the single-row update**

```bash
sqlite3 ~/.hermes/cli-registry.db "UPDATE capability SET output_types='text' WHERE cli_slug='send_mail' AND output_types='';"
```

- [ ] **Step 3: Verify exactly one row changed**

```bash
sqlite3 ~/.hermes/cli-registry.db "SELECT changes();"
```

Expected: `1`. If `0`, the `WHERE` clause matched nothing (row already changed or slug/condition mismatch) — investigate before re-running. If `>1` — STOP immediately, this should be impossible given `cli_slug` is not unique-constrained but the live registry should have at most one `send_mail` capability row; investigate before proceeding further.

- [ ] **Step 4: Verify the new state**

```bash
sqlite3 ~/.hermes/cli-registry.db "SELECT cli_slug, input_types, output_types, side_effect, confidence FROM capability WHERE cli_slug='send_mail';"
```

Expected: `send_mail|text|text|external|declared`.

No git commit for this task — it's a live data change, not a repo file.

---

## Chunk 2 review

- Task 3 is a read-before-write guard: the spec was written against a live-data snapshot, and live data can drift between spec-approval and execution. Verifying first avoids silently corrupting an already-changed row.
- The backup in Task 4 Step 1 makes the data half of the Rollback section's promise concrete and executable, not just documented.
- The `WHERE output_types=''` clause (not just `WHERE cli_slug='send_mail'`) makes the UPDATE idempotent-safe — re-running it after success is a no-op (`changes()` → 0), not a silent overwrite of some other manual edit.

Clean — proceeding to Chunk 3.

---

## Chunk 3: Live verification (AC-05)

### Task 5: Prove `send_mail` is selectable in an isolated/scoped simulation

**Files:**
- None (verification script, not committed — run and discard, or keep as a scratch file outside the repo)

- [ ] **Step 1: Run an isolated-DB simulation against the real send_mail row**

This reproduces the spec's own post-panel Codex verification. Use a throwaway copy of the live DB filtered to just the `send_mail` row plus its dependencies, or run against the full live DB with `max_candidate_chains` raised (per AC-05's explicit allowance for either isolated-subset OR raised-cap verification):

```bash
cd /Users/jcords-macmini/projects/a2a-cli-registry && python3 -c "
from sqlmodel import Session, create_engine
from core.planner.search import plan_chain

engine = create_engine('sqlite:////Users/jcords-macmini/.hermes/cli-registry.db')
with Session(engine) as db:
    chains = plan_chain(db, goal_inputs=['text'], goal_outputs=['text'],
                        allow_side_effects=set(), max_candidate_chains=1000)
    matches = [c for c in chains if 'send_mail' in c.slugs]
    print(f'{len(chains)} total candidates, send_mail present: {bool(matches)}')
    if matches:
        print('position:', chains.index(matches[0]), 'slugs:', matches[0].slugs)
"
```

Expected: `send_mail present: True`, at some sorted position (spec's own pre-execution probe found position 18 with `max_candidate_chains=1000`; exact position may shift slightly as the live registry has grown since, this is not a regression signal by itself).

- [ ] **Step 2: Confirm the public-default call still does NOT include send_mail (documents the known, separately-filed gap — not a regression)**

```bash
cd /Users/jcords-macmini/projects/a2a-cli-registry && python3 -c "
from sqlmodel import Session, create_engine
from core.planner.search import plan_chain

engine = create_engine('sqlite:////Users/jcords-macmini/.hermes/cli-registry.db')
with Session(engine) as db:
    chains = plan_chain(db, goal_inputs=['text'], goal_outputs=['text'], allow_side_effects=set())
    matches = [c for c in chains if 'send_mail' in c.slugs]
    print(f'default cap: {len(chains)} candidates, send_mail present: {bool(matches)}')
"
```

Expected: `send_mail present: False` at the public default (`max_candidate_chains=100`). This is the expected, spec-acknowledged outcome — AC-05 explicitly does NOT claim this call surfaces `send_mail` (that requires the separately-filed `US-CLIREG-PLANCHAIN-CAP-STARVATION-01`). If this instead prints `True`, the cap-starvation bug may have been independently fixed since the spec was written — note it, don't treat as a failure.

- [ ] **Step 3: Record the verification result**

No commit needed (this is evidence-gathering, not a code/data change). Note the two outcomes (isolated/raised-cap: found; public-default: not found, expected) in the session's eventual handover or PR description.

---

## Chunk 3 review

- This task doesn't change any code or data — it's the AC-05 evidence step, kept as its own chunk so "did the fix actually work end-to-end" is a distinct, visible checkpoint rather than folded into the code-change commit.
- Step 2 is included deliberately to prevent future confusion: without it, someone re-running verification later might mistake "send_mail still absent from default output" for a regression in Chunk 1/2's fixes, when it's actually the known, separately-ticketed cap-starvation gap.

Clean — this is the last chunk.

---

## Definition of Done

- [ ] `core/models.py:32` comment updated
- [ ] `core/planner/search.py:34` `order` list includes `"external"`
- [ ] `tests/test_planner.py` has 17 tests (14 existing + 3 new), all passing
- [ ] Full test suite green: `python -m pytest tests/ -v`
- [ ] Live DB: `send_mail.output_types` = `'text'` (verified via direct query)
- [ ] Live DB backup exists (`~/.hermes/cli-registry.db.bak-*`)
- [ ] AC-05 isolated/raised-cap simulation confirms `send_mail` is selectable
- [ ] Two commits made: (1) models.py comment, (2) search.py fix + tests — or squashed per user's usual commit granularity preference
