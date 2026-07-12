# `plan_chain` Cap-Starvation Fix Implementation Plan

> **For agentic workers:** REQUIRED: Use `/sh:execute` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `plan_chain()` so a favorably-ranked candidate chain is never silently excluded just because worse-ranked chains from earlier-iterated start slugs already filled the collection cap — by removing both order-dependent, collection-time candidate-count gates and capping only the final sorted result.

**Architecture:** Single-function fix in `core/planner/search.py`. Both the outer `for start in starts` loop's early break and the inner `while q` loop's candidate-count condition currently read the same global `len(candidates)` counter, causing later start slugs' BFS queues to go completely unconsumed once the cap fills from earlier starts. Removing both gates lets every reachable chain (still bounded by `max_chain_depth` per chain, unchanged) get enumerated before `candidates.sort()` runs; the cap is then applied correctly, once, to the sorted result via the existing `candidates[:max_candidate_chains]` slice.

**Tech Stack:** Python 3.11+, SQLModel, pytest, sqlite3 (direct query for the live AC-04 verification).

**Spec:** [docs/superpowers/specs/2026-07-12-planchain-cap-starvation-design.md](../superpowers/specs/2026-07-12-planchain-cap-starvation-design.md) — revised after a Codex grounding review found the first-draft fix non-functional; both the bug in that first draft and the corrected fix were independently re-verified live in this repo (not just accepted from the review).

---

## Scope note

This plan implements only what the spec's Fix section covers: removing the two collection-time candidate-count gates in `plan_chain()`. It explicitly does **not**:
- Change `max_candidate_chains`'s default value (100)
- Expose `max_candidate_chains`/`max_chain_depth` as caller-overridable parameters on `plan_cli_chain` (`core/catalog/queries.py`)
- Touch `max_chain_depth`, `_hop_excluded`, `_slug_side_effect`, or `Chain.sort_key()`
- Introduce any algorithmic change beyond removing the two gates (e.g. a priority-queue/best-first search)

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `core/planner/search.py` | Chain-planning algorithm | `plan_chain()`: delete the outer loop's cap-check-and-break (lines 104-105), delete the inner while-loop's candidate-count clause from its condition (line 108) — 2 separate edits |
| `tests/test_planner.py` | Planner unit tests | 1 new test function appended, using a verified-working reproduction shape (100 worse-ranked candidates + 1 favorably-ranked winner, not the spec's-first-draft's broken dead-end-fleet shape) |

No new files. No file is large enough to warrant splitting.

---

## Chunk 1: Fix the cap-starvation bug (TDD)

### Task 1: Write the failing reproduction test

**Files:**
- Test: `tests/test_planner.py`

- [ ] **Step 1: Append the new test**

Append to `tests/test_planner.py`, after `test_terminates_on_cyclic_typegraph` (the file's last function, currently ending at line 211):

```python
def test_favorably_ranked_start_not_starved_by_worse_earlier_candidates(db):
    # 100 "worse" starts (writes-fs side effect -> side_effect_count=1) each
    # produce ONE matching candidate immediately. A 101st start, "winner"
    # (side_effect='none' -> side_effect_count=0, strictly better per
    # Chain.sort_key()), is inserted LAST. Before the fix: the 100 worse
    # candidates fill max_candidate_chains before winner's start is ever
    # visited, so winner is starved out entirely -- not merely ranked last,
    # ABSENT. After the fix: every start is enumerated before sorting, so
    # winner (fewest side effects) correctly sorts to position 0.
    #
    # This shape is deliberately NOT "N dead-end starts + 1 winner" (that
    # never fills the cap at all, since dead ends append nothing, and does
    # not reproduce the bug -- confirmed during spec review). Starvation
    # requires earlier starts that actually contend for cap space.
    for i in range(100):
        slug = f"worse{i:03d}"
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags="g", input_types="file:pdf",
                          output_types="text:goal", side_effect="writes-fs", confidence="declared"))
    db.add(Cli(slug="winner", lang="python"))
    db.add(Capability(cli_slug="winner", intent_tags="g", input_types="file:pdf",
                      output_types="text:goal", side_effect="none", confidence="declared"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"],
                        max_candidate_chains=100)
    assert chains, "expected at least 100 candidates"
    assert chains[0].slugs == ["winner"], (
        f"winner should rank first (fewest side effects) but got "
        f"{chains[0].slugs}; winner present at all: "
        f"{any(c.slugs == ['winner'] for c in chains)}"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && source .venv/bin/activate && python -m pytest tests/test_planner.py::test_favorably_ranked_start_not_starved_by_worse_earlier_candidates -v`

Expected: FAIL. The assertion `chains[0].slugs == ["winner"]` fails because `winner` is entirely absent from `chains` (starved out) — the failure message will show `winner present at all: False`. This confirms the test reproduces the bug (live-verified during spec-writing: unfixed code returns 100 candidates, none of which is `winner`).

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_planner.py
git commit -m "test: reproduce plan_chain cap-starvation bug (US-CLIREG-PLANCHAIN-CAP-STARVATION-01)" -- tests/test_planner.py
```

(Note: this repo's `cc-commit-guard` pre-commit hook blocks bare `git commit`/`-a` — always pass explicit paths on the `commit` command itself, as shown.)

### Task 2: Remove the outer loop's cap-check-and-break

**Files:**
- Modify: `core/planner/search.py:103-105`

- [ ] **Step 1: Locate and remove the outer gate**

Current (`core/planner/search.py:103-106`):
```python
    for start in starts:
        if len(candidates) >= max_candidate_chains:
            break
        # BFS state: (path, visited, hops). Cycle guard via visited set.
```

Change to:
```python
    for start in starts:
        # BFS state: (path, visited, hops). Cycle guard via visited set.
```

(Delete the `if len(candidates) >= max_candidate_chains: break` two-line block; keep the `# BFS state` comment line, which documents the `deque` tuple shape on the next line, not the cap logic.)

- [ ] **Step 2: Run the reproduction test — expect it still fails**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && source .venv/bin/activate && python -m pytest tests/test_planner.py::test_favorably_ranked_start_not_starved_by_worse_earlier_candidates -v`

Expected: **still FAILS**. This is intentional and matches the spec's live-verified finding — removing only the outer gate does not fix the bug, because the inner `while` loop's condition independently gates on the same global counter. Do not be alarmed; proceed to Task 3. (If this test unexpectedly PASSES here, something about the codebase has changed since the spec was written — stop and re-verify against the spec's "What the first draft got wrong" section before continuing.)

### Task 3: Remove the inner loop's candidate-count condition

**Files:**
- Modify: `core/planner/search.py:108` (line number after Task 2's 2-line deletion; originally line 108, now shifted up by 2 to line 106 — verify with `grep -n "while q" core/planner/search.py` before editing)

- [ ] **Step 1: Locate and fix the inner condition**

Current (post-Task-2):
```python
        while q and len(candidates) < max_candidate_chains:
```

Change to:
```python
        while q:
```

- [ ] **Step 2: Run the reproduction test — expect it now passes**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && source .venv/bin/activate && python -m pytest tests/test_planner.py::test_favorably_ranked_start_not_starved_by_worse_earlier_candidates -v`

Expected: PASS. `winner` now correctly appears at `chains[0]` (live-verified during spec-writing: fixed code returns `winner` at position 0).

- [ ] **Step 3: Run the full planner suite (regression check)**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && source .venv/bin/activate && python -m pytest tests/test_planner.py -v`

Expected: 18 PASS (17 existing + 1 new), 0 FAIL. Directly verifies AC-03's suite-green requirement for the planner file.

- [ ] **Step 4: Run the full repo test suite (broader regression check)**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && source .venv/bin/activate && python -m pytest tests/ -v 2>&1 | tail -20`

Expected: 444 passed, 1 failed (`test_web_render.py::test_render_binds_each_card_to_its_own_health_and_bucket` — pre-existing, unrelated, confirmed during the sibling `US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01` work via diff-scope and last-touched-commit checks; do not attempt to fix it here, out of scope). If the total or failure set differs from this, stop and diagnose before proceeding — do not assume drift is benign.

- [ ] **Step 5: Commit the fix**

```bash
git add core/planner/search.py
git commit -m "fix: remove both cap-starvation gates in plan_chain, sort before capping (AC-01/02/03)" -- core/planner/search.py
```

---

## Chunk 1 review

- Task 2 deliberately keeps the reproduction test RED after only the first edit — this mirrors the spec's own finding (Codex caught that "remove only the outer break" doesn't work) and gives the implementer the same live confirmation the spec author already verified, rather than asking them to trust the spec's narrative on faith.
- The reproduction test's shape (100 contending "worse" candidates + 1 late "winner") is the spec-corrected version, not the original broken "150 dead ends + 1 winner" design — using dead ends would silently pass even on unfixed code, since dead ends never fill the cap.
- Task 3's line-number caveat (verify with grep before editing) exists because Task 2's edit shifts every subsequent line number up by 2 — a plan that hardcoded "line 108" without that caveat could point an implementer at the wrong line after Task 2 lands.

Clean — proceeding to Chunk 2.

---

## Chunk 2: Live verification (AC-04)

### Task 4: Confirm `send_mail` is now reachable at the public default cap

**Files:**
- None (read-only verification against the live registry, not committed)

- [ ] **Step 1: Run the exact AC-04 probe from the spec**

```bash
cd /Users/jcords-macmini/projects/a2a-cli-registry && source .venv/bin/activate && python3 -c "
from sqlmodel import Session, create_engine
from core.planner.search import plan_chain

engine = create_engine('sqlite:////Users/jcords-macmini/.hermes/cli-registry.db')
with Session(engine) as db:
    chains = plan_chain(db, goal_inputs=['text'], goal_outputs=['text'], allow_side_effects=set())
    matches = [c for c in chains if 'send_mail' in c.slugs]
    print(f'public default cap: {len(chains)} candidates, send_mail present: {bool(matches)}')
    if matches:
        print('position:', chains.index(matches[0]))
"
```

Expected: `send_mail present: True` at the public default cap (100) — this is the specific gap the sibling `US-CLIREG-PLANNER-SIDEEFFECT-VOCAB-01` ticket could NOT close on its own (its own AC-05 explicitly documented this as a known, separately-filed limitation). This probe closing it is the actual point of this ticket.

- [ ] **Step 2: Also confirm via the public `plan_cli_chain` wrapper (not just the internal `plan_chain`)**

```bash
cd /Users/jcords-macmini/projects/a2a-cli-registry && source .venv/bin/activate && python3 -c "
from sqlmodel import Session, create_engine
from core.catalog.queries import plan_cli_chain

engine = create_engine('sqlite:////Users/jcords-macmini/.hermes/cli-registry.db')
with Session(engine) as db:
    chains = plan_cli_chain(db, goal_inputs=['text'], goal_outputs=['text'], allow_side_effects=set())
    matches = [c for c in chains if 'send_mail' in c['slugs']]
    print(f'{len(chains)} candidates via public wrapper, send_mail present: {bool(matches)}')
"
```

Expected: `send_mail present: True`. This confirms the fix reaches the actual production call path (`core/catalog/queries.py:165`), not just the internal function tested directly in Step 1 — the two have historically differed in shape (the wrapper adds `health_status` per hop) but should agree on presence/absence.

- [ ] **Step 3: Record the verification result**

No commit needed — this is evidence-gathering. Note both outcomes in the session's eventual handover: AC-04 satisfied at the public default cap via both the internal function and the production wrapper.

---

## Chunk 2 review

- Step 2 exists because the spec and Chunk 1's tests only ever exercise `plan_chain` directly — but the actual production surface (the MCP op `plan_cli_chain`, registered at `core/ops_registry.py:37`) goes through `core/catalog/queries.py:165`'s `plan_cli_chain` wrapper. Verifying only the internal function would leave a gap between "the function I tested works" and "the thing users actually call works" — this step closes that gap explicitly rather than assuming they're equivalent.

Clean — this is the last chunk.

---

## Definition of Done

- [ ] `core/planner/search.py`: outer loop's cap-check-and-break removed (was lines 104-105)
- [ ] `core/planner/search.py`: inner while-loop's condition is bare `while q:` (was `while q and len(candidates) < max_candidate_chains:`)
- [ ] `tests/test_planner.py` has 18 tests (17 existing + 1 new), all passing
- [ ] Full test suite: 444 passed, 1 pre-existing unrelated failure (`test_web_render.py`) — not a new count, not a new failure
- [ ] AC-04 live-verified via both `plan_chain` (internal) and `plan_cli_chain` (production wrapper): `send_mail` present at the public default cap (100)
- [ ] Two commits made: (1) failing reproduction test, (2) the fix — matching this plan's TDD sequencing, or squashed per your usual commit granularity preference
