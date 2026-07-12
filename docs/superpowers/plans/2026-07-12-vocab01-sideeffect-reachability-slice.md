# VOCAB-01 Side-effect Reachability Slice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin `send_mail`'s planner reachability with a regression test (AC-02) and backfill `seed_anthropic_index`'s capability row in the live registry DB (AC-03).

**Architecture:** Two independent tasks. AC-02 is a pure-unit regression pin in `tests/test_planner.py` guarding the already-shipped cap-starvation fix (`16798e3`). AC-03 is a one-row live-DB `UPDATE` (backup-gated, row-count-asserted) plus a `_hop_excluded` verification test. Neither touches `goal_actions` or the planner's matching logic — that redesign lives in US-CLIREG-GOALACTIONS-01.

**Tech Stack:** Python 3.11+, SQLModel/SQLite, pytest. Repo `.venv` (`.venv/bin/python3`, `.venv/bin/pytest`).

## Global Constraints

- The LIVE registry DB is `~/.hermes/cli-registry.db`. This repo's `./registry.db` is a DIFFERENT dataset (474 CLIs, no `send_mail`) — do NOT confuse them. AC-03's mutation targets the LIVE DB only.
- `_hop_excluded(caps_for_slug, allow_side_effects)` takes `caps_for_slug` = a **list of `Capability` objects** (not a dict, not a single row) and `allow_side_effects` = a set of side-effect strings. Verified `core/planner/search.py:46`.
- `plan_chain(session, goal_inputs, goal_outputs, allow_side_effects=None, max_chain_depth=4, max_candidate_chains=100)` returns a list of `Chain`; each `Chain` has a `.slugs` list. Verified `core/planner/search.py:81`.
- `_slug_side_effect` reads `{c.side_effect for c in caps_for_slug}` and ranks `destructive > unknown > network > external > writes-fs > none`. So a `writes-fs` cap is excluded by default (returns True) unless `writes-fs` is in `allow_side_effects`.
- Atomic DB writes only: backup the DB file BEFORE the UPDATE; assert the affected-row count == 1; keep the backup as the rollback path.
- Commit messages end with the trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Commit with explicit paths (`git commit -- <path>`), never a bare whole-index commit (repo commit guard blocks it).

---

### Task 1: AC-02 — pin `send_mail` reachability at the default cap

**Files:**
- Test: `tests/test_planner.py` (append one test function)

**Interfaces:**
- Consumes: `plan_chain`, `Chain` (already imported at `tests/test_planner.py:1-2`); the `db` fixture (`tests/conftest.py:29`); models `Cli`, `Capability`, `CliEdge` (`core/models`).
- Produces: nothing downstream (leaf test).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_planner.py`. This builds a fixture with 100+ competing candidates plus one `external` terminal shaped like the live `send_mail` row (`intent_tags='notify,send'`, `input_types='text'`, `output_types='text'`, `side_effect='external'`, `confidence='declared'`), and asserts the terminal is still present at the DEFAULT cap (`max_candidate_chains=100`). This is the exact scenario the cap-starvation fix (`16798e3`) repaired — the test FAILS if that fix regresses (the terminal gets starved out before sorting).

```python
def test_external_terminal_reachable_at_default_cap(db):
    # AC-02 regression pin for the cap-starvation fix (a2a-cli-registry 16798e3).
    # Before 16798e3, plan_chain broke out of the outer start-loop once
    # len(candidates) >= max_candidate_chains (default 100) BEFORE sorting, so a
    # favorably-ranked start could be starved out if dict-iteration visited 100+
    # other valid starts first. This pins that a live-shaped `external` terminal
    # (send_mail: notify,send | text->text | external) survives to the ranked
    # output at the DEFAULT cap even amid 120 competing text->text producers.
    # 120 competing producers, all text:doc -> text:summary, no side effect.
    for i in range(120):
        slug = f"producer_{i}"
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags="summarize",
                          input_types="text:doc", output_types="text:summary",
                          side_effect="none", confidence="declared"))
    # The live-shaped external terminal: consumes+produces text, side_effect external.
    db.add(Cli(slug="send_mail", lang="python"))
    db.add(Capability(cli_slug="send_mail", intent_tags="notify,send",
                      input_types="text:summary", output_types="text:summary",
                      side_effect="external", confidence="declared"))
    db.commit()

    chains = plan_chain(db, goal_inputs=["text:doc"], goal_outputs=["text:summary"],
                        allow_side_effects={"external"})
    assert any("send_mail" in c.slugs for c in chains), \
        "send_mail starved out at default cap — cap-starvation fix 16798e3 regressed"
```

- [ ] **Step 2: Run test to verify it passes (fix already shipped)**

Run: `.venv/bin/pytest tests/test_planner.py::test_external_terminal_reachable_at_default_cap -v`
Expected: PASS. (This is a regression PIN — the fix `16798e3` is already in the tree, so the test confirms GREEN. If it FAILS, the cap-starvation fix regressed and that is the finding.)

- [ ] **Step 3: Verify it would fail if the fix regressed (optional sanity)**

Confirm the test is load-bearing: temporarily lower the assertion's implicit reliance by re-running with an artificially tiny cap to observe starvation is what the test guards:
Run: `.venv/bin/python3 -c "from core.planner.search import plan_chain; import inspect; print('max_candidate_chains default:', inspect.signature(plan_chain).parameters['max_candidate_chains'].default)"`
Expected: prints `max_candidate_chains default: 100` — confirming the test asserts against the real default, not a widened cap.

- [ ] **Step 4: Commit**

```bash
git commit -- tests/test_planner.py -m "test: pin send_mail reachability at default cap (AC-02, guards 16798e3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: AC-03 — backfill `seed_anthropic_index` capability in the live DB

**Files:**
- Modify (data): `~/.hermes/cli-registry.db` (one row in the `capability` table)
- Test: `tests/test_backfill_seed_anthropic_index.py` (new — the `_hop_excluded` verification)

**Interfaces:**
- Consumes: `_hop_excluded` (`core/planner/search.py:46`), `Capability` (`core/models`).
- Produces: nothing downstream (leaf).

- [ ] **Step 1: Back up the live DB**

```bash
cp ~/.hermes/cli-registry.db ~/.hermes/cli-registry.db.bak-vocab01-ac03
ls -la ~/.hermes/cli-registry.db.bak-vocab01-ac03
```
Expected: the backup file exists with a non-zero size. This is the rollback path.

- [ ] **Step 2: Inspect the current `seed_anthropic_index` row (pre-state)**

```bash
.venv/bin/python3 - <<'PY'
import sqlite3, os
db = os.path.expanduser("~/.hermes/cli-registry.db")
con = sqlite3.connect(db)
rows = con.execute(
    "SELECT cli_slug, intent_tags, input_types, output_types, side_effect, confidence "
    "FROM capability WHERE cli_slug='seed_anthropic_index'").fetchall()
print("pre-state rows:", rows)
PY
```
Expected: exactly one row for `seed_anthropic_index` with empty/`none`-shaped I/O and side_effect. If ZERO rows, STOP — the slug is absent from the live DB and the AC-03 premise is stale; surface that rather than INSERTing a fabricated row.

- [ ] **Step 3: Write the failing verification test FIRST (RED)**

Create `tests/test_backfill_seed_anthropic_index.py`. It constructs a `Capability` with the TARGET post-backfill values and asserts `_hop_excluded` behaves correctly for a `writes-fs` cap. This test is independent of the live DB (it builds the row in-memory) — it pins the *semantics* the backfill must produce.

```python
from core.models import Capability
from core.planner.search import _hop_excluded


def _seed_cap():
    # The target post-backfill shape for seed_anthropic_index (AC-03):
    # side_effect='writes-fs', input_types='path', output_types='', confidence='inferred'.
    return [Capability(cli_slug="seed_anthropic_index", intent_tags="",
                       input_types="path", output_types="",
                       side_effect="writes-fs", confidence="inferred")]


def test_writes_fs_excluded_by_default():
    # writes-fs carries real blast radius; with no allow-set it must be excluded.
    assert _hop_excluded(_seed_cap(), set()) is True


def test_writes_fs_allowed_when_opted_in():
    # An operator opting into writes-fs accepts that blast radius.
    assert _hop_excluded(_seed_cap(), {"writes-fs"}) is False
```

- [ ] **Step 4: Run the verification test (GREEN — it pins existing `_hop_excluded` semantics)**

Run: `.venv/bin/pytest tests/test_backfill_seed_anthropic_index.py -v`
Expected: both PASS. (`_hop_excluded` already implements writes-fs exclusion; this test pins that the backfill's target shape routes correctly. If either FAILS, the target shape is wrong — do NOT proceed to the UPDATE.)

- [ ] **Step 5: Apply the backfill UPDATE (atomic, row-count asserted)**

```bash
.venv/bin/python3 - <<'PY'
import sqlite3, os
db = os.path.expanduser("~/.hermes/cli-registry.db")
con = sqlite3.connect(db)
cur = con.execute(
    "UPDATE capability SET side_effect='writes-fs', input_types='path', "
    "output_types='', confidence='inferred' WHERE cli_slug='seed_anthropic_index'")
n = cur.rowcount
if n != 1:
    con.rollback()
    raise SystemExit(f"ABORT: expected exactly 1 affected row, got {n}. Rolled back.")
con.commit()
print(f"OK: updated {n} row.")
PY
```
Expected: `OK: updated 1 row.` If it prints an ABORT with a row count ≠ 1, the change is rolled back — restore from the backup and investigate before retrying.

- [ ] **Step 6: Re-read and assert the post-state matches the target**

```bash
.venv/bin/python3 - <<'PY'
import sqlite3, os
db = os.path.expanduser("~/.hermes/cli-registry.db")
con = sqlite3.connect(db)
row = con.execute(
    "SELECT input_types, output_types, side_effect, confidence "
    "FROM capability WHERE cli_slug='seed_anthropic_index'").fetchone()
assert row == ("path", "", "writes-fs", "inferred"), f"post-state mismatch: {row}"
print("post-state verified:", row)
PY
```
Expected: `post-state verified: ('path', '', 'writes-fs', 'inferred')`.

- [ ] **Step 7: Commit the test (the DB is untracked/gitignored)**

The live DB lives outside the repo and is not version-controlled, so only the test is committed. The backup file + the re-read assertion (Step 6) are the durable record of the data change.

```bash
git commit -- tests/test_backfill_seed_anthropic_index.py -m "test: verify seed_anthropic_index writes-fs backfill hop-exclusion (AC-03)

Live DB ~/.hermes/cli-registry.db backfilled: side_effect writes-fs,
input_types path, output_types '', confidence inferred. Backup at
~/.hermes/cli-registry.db.bak-vocab01-ac03. Row-count-asserted UPDATE.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:** The slice spec (`2026-07-12-vocab01-sideeffect-reachability-slice.md`) has exactly two open ACs — AC-02 (Task 1) and AC-03 (Task 2). AC-01 is already DONE (`3a78aa8`), no task needed. Full coverage.

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"write tests for the above". Every code step shows the actual code; every command step shows the exact command + expected output. The one conditional ("if ZERO rows, STOP") is an explicit guard with a defined action, not a placeholder.

**3. Type consistency:** `_hop_excluded(caps_for_slug: list[Capability], allow_side_effects: set)` used consistently in Task 2 (list-of-Capability argument matches `core/planner/search.py:33` `{c.side_effect for c in caps_for_slug}`). `plan_chain(...).slugs` used consistently in Task 1 (matches `Chain.slugs` per existing tests). `Capability` field names (`cli_slug`, `intent_tags`, `input_types`, `output_types`, `side_effect`, `confidence`) match the fixture at `tests/test_planner.py:12-13`.

**Dependencies:** Task 1 and Task 2 are fully independent — either can land first.
