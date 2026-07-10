# Module-Mode Awareness for the Remediation Classifier — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach `core/remediation/classify.py` to recognize a locally-importable
package reachable via `python -m pkg.module` (not just a sibling file), so the
~46 CLIs currently mislabeled `PIP_UNKNOWN` route to `WRONG_CWD` with a
concrete fix instead of being treated as unfixable third-party gaps.

**Architecture:** Extract the existing, already-correct `_project_root`/
`_dotted_module` path derivation out of `bridge/llm_infer.py` into a new pure
module in `core/`, so both `bridge` (unchanged behavior) and
`core/remediation/classify.py` (new behavior) import the same logic — no
duplication, no reversed dependency direction. `classify.py` gains one new
proof check (`_proven_module_mode`) that only fires on an exact, full
dotted-path match on disk; it never guesses. Once merged and reviewed, the
live registry's 46 affected rows are re-classified and re-probed under
module-mode, flipping to healthy only the ones that demonstrably pass.

**Tech Stack:** Python 3.11+, pytest, SQLite (registry.db / cli-registry.db),
no new dependencies.

## Global Constraints

- `IMPORT_TO_PACKAGE` is PyPI-only — never map a local import to a PyPI
  distribution, and do not add/remove any entries in this task.
- `classify.py` stays pure: no subprocess calls, no network I/O. Only
  filesystem existence checks (`os.path.exists`, matching the existing
  `_proven_local` pattern).
- The new shared module lives in `core/` (not `bridge/`) — `bridge` already
  imports from `core`, never the reverse; this must not change.
- No change to `bridge/llm_infer.py`'s *behavior* — only its *source* of
  `_project_root`/`_dotted_module` changes (import instead of local def).
  Its own test suite (`bridge/test_capture_help.py`) is the regression gate.
- The existing test `test_dotted_module_uses_top_segment` (google.cloud ->
  top="google" -> PIP_UNKNOWN, in `tests/test_remediation_classify.py`) MUST
  continue to pass unmodified — it pins the fallback behavior for dotted
  names that are NOT proven to exist locally.
- A dotted failure where only the top segment exists locally but the full
  path does not (e.g. `localpkg.missing` where `localpkg/__init__.py` exists
  but `localpkg/missing.py` does not) must classify `PIP_UNKNOWN`, never
  `WRONG_CWD` — partial proof is not proof.
- Re-probing the live 46 rows (Task 4) only flips CLIs to `healthy` that
  demonstrably pass re-probe; nothing is force-flipped.

---

### Task 1: Extract `_project_root`/`_dotted_module` into a shared pure module

**Files:**
- Create: `core/paths/__init__.py`
- Create: `core/paths/module_root.py`
- Modify: `bridge/llm_infer.py:98-140` (remove local defs, add import)
- Test: `core/paths/test_module_root.py`

**Interfaces:**
- Produces: `core.paths.module_root._project_root(path: str) -> str | None`
  and `core.paths.module_root._dotted_module(path: str, root: str) -> str |
  None` — exact same signatures and behavior as the current
  `bridge/llm_infer.py` versions. Task 2 and Task 3 both import from here.

- [ ] **Step 1: Create the package directory and `__init__.py`**

```bash
mkdir -p core/paths
touch core/paths/__init__.py
```

- [ ] **Step 2: Write the failing test for the extracted module**

Create `core/paths/test_module_root.py`:

```python
import os
from core.paths.module_root import _project_root, _dotted_module


def test_project_root_finds_nearest_sentinel(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    sub = tmp_path / "pkg" / "sub"
    sub.mkdir(parents=True)
    cli = sub / "cli.py"
    cli.write_text("")
    assert _project_root(str(cli)) == str(tmp_path)


def test_project_root_returns_none_when_no_sentinel(tmp_path):
    # tmp_path itself has no sentinel and (in test envs) no parent will
    # either, so this must return None rather than walking to filesystem root
    # and matching an ancestor .git by accident. Use a deeply isolated dir.
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    cli = isolated / "c.py"
    cli.write_text("")
    result = _project_root(str(cli))
    # We can't assert None unconditionally (a real .git could exist above
    # tmp_path on some CI runners), so assert it's either None or a path
    # that does NOT equal our isolated dir (i.e., no false-positive on the
    # dir we just created without a sentinel in it).
    assert result != str(isolated)


def test_dotted_module_relative_path(tmp_path):
    root = tmp_path
    cli = root / "pkg" / "sub" / "cli.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("")
    assert _dotted_module(str(cli), str(root)) == "pkg.sub.cli"


def test_dotted_module_outside_root_returns_none(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside" / "c.py"
    outside.parent.mkdir()
    outside.write_text("")
    assert _dotted_module(str(outside), str(root)) is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ~/projects/a2a-cli-registry && python3 -m pytest core/paths/test_module_root.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.paths.module_root'`

- [ ] **Step 4: Create `core/paths/module_root.py`**

```python
"""Pure filesystem path derivation for module-mode invocation.

Shared by bridge/llm_infer.py (probe ladder) and
core/remediation/classify.py (module-mode proof). Pure path math only —
no subprocess, no network. Moved here from bridge/llm_infer.py so both
consumers use one definition (abstract-on-third)."""
import os

# Project-root sentinels: the nearest ancestor containing one of these is the
# directory from which `python -m pkg.module` resolves package-relative imports.
_ROOT_SENTINELS = ("pyproject.toml", "setup.py", "setup.cfg", ".git", "requirements.txt")


def _project_root(path: str) -> str | None:
    """Walk up from the file to the nearest dir holding a root sentinel."""
    d = os.path.dirname(os.path.abspath(path))
    prev = None
    while d and d != prev:
        for s in _ROOT_SENTINELS:
            if os.path.exists(os.path.join(d, s)):
                return d
        prev, d = d, os.path.dirname(d)
    return None


def _dotted_module(path: str, root: str) -> str | None:
    """Dotted module path of `path` relative to `root`.

    /root/pkg/sub/cli.py  under root  ->  pkg.sub.cli
    """
    try:
        rel = os.path.relpath(os.path.abspath(path), root)
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    rel = os.path.splitext(rel)[0]
    parts = [p for p in rel.split(os.sep) if p]
    if not parts:
        return None
    return ".".join(parts)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ~/projects/a2a-cli-registry && python3 -m pytest core/paths/test_module_root.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Update `bridge/llm_infer.py` to import instead of define**

Read `bridge/llm_infer.py:98-140` first to confirm exact current content
(the plan was written against a real read, but re-verify before editing —
another commit may have touched it). Remove the `_ROOT_SENTINELS` constant
and the `_project_root`/`_dotted_module` function definitions (originally
lines 98-140), and add an import near the top of the file alongside the
existing `from core.capability.model import CapabilityRecord` line:

```python
from core.paths.module_root import _project_root, _dotted_module
```

- [ ] **Step 7: Run bridge's existing test suite to confirm no behavior change**

Run: `cd ~/projects/a2a-cli-registry && python3 -m pytest bridge/test_capture_help.py -v`
Expected: PASS, same pass count as before the edit (this is the regression
gate for the extraction — if anything fails here, the extraction changed
behavior and must be fixed before proceeding).

- [ ] **Step 8: Commit**

```bash
git add core/paths/__init__.py core/paths/module_root.py core/paths/test_module_root.py bridge/llm_infer.py
git commit -m "refactor: extract project-root/dotted-module derivation to core/paths

Move _project_root/_dotted_module out of bridge/llm_infer.py into a new
pure core/paths/module_root.py so core/remediation/classify.py can reuse
them without reversing the bridge -> core dependency direction.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>" -- core/paths/__init__.py core/paths/module_root.py core/paths/test_module_root.py bridge/llm_infer.py
```

---

### Task 2: Add `_proven_module_mode` to the classifier

**Files:**
- Modify: `core/remediation/classify.py:1-99` (add function, wire into
  `classify_failure`)
- Test: `tests/test_remediation_classify.py` (append new tests)

**Interfaces:**
- Consumes: `core.paths.module_root._project_root`,
  `core.paths.module_root._dotted_module` (from Task 1).
- Produces: `core.remediation.classify._proven_module_mode(path: str, dotted:
  str) -> str | None` — returns the exact dotted module name on proof, `None`
  otherwise. `classify_failure` (existing function, same signature) is the
  only caller.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_remediation_classify.py` (after the existing
`test_dotted_module_uses_top_segment` test, keep that test unmodified):

```python
from core.remediation.classify import _proven_module_mode


def test_proven_module_mode_two_dirs_up(tmp_path):
    # syllabus_v2 lives at the project root, two directories above the
    # failing CLI's own file — _proven_local (adjacent-only) would miss
    # this; _proven_module_mode must find it via _project_root.
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "syllabus_v2").mkdir()
    (tmp_path / "syllabus_v2" / "__init__.py").write_text("")
    cli = tmp_path / "scripts" / "tools" / "categorize.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("import syllabus_v2\n")
    p = classify_failure("categorize", MNFE.format("syllabus_v2"), str(cli))
    assert p.failure_class == FailureClass.WRONG_CWD
    assert p.fix_kind == FixKind.PROPOSE_ONLY
    assert "python -m syllabus_v2" in p.evidence


def test_proven_module_mode_file_form(tmp_path):
    # A module as a single file (engine.py) at the project root, not a
    # package dir - both forms must be proven.
    (tmp_path / "setup.py").write_text("")
    (tmp_path / "engine.py").write_text("")
    cli = tmp_path / "sub" / "run.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("import engine\n")
    p = classify_failure("run", MNFE.format("engine"), str(cli))
    assert p.failure_class == FailureClass.WRONG_CWD
    assert "python -m engine" in p.evidence


def test_dotted_submodule_partial_proof_is_not_proof(tmp_path):
    # localpkg exists at the root, but the specific submodule 'missing' does
    # not. This must NOT be misclassified wrong-cwd - the missing submodule
    # is a real gap, not a wrong-cwd problem. (This is the case a partial
    # top-segment-only check would get wrong.)
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "localpkg").mkdir()
    (tmp_path / "localpkg" / "__init__.py").write_text("")
    cli = tmp_path / "sub" / "run.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("from localpkg import missing\n")
    p = classify_failure("run", MNFE.format("localpkg.missing"), str(cli))
    assert p.failure_class == FailureClass.PIP_UNKNOWN
    assert p.failure_class != FailureClass.WRONG_CWD


def test_proven_module_mode_empty_path_returns_none():
    assert _proven_module_mode("", "anything") is None


def test_proven_module_mode_no_root_found_returns_none(tmp_path):
    # No sentinel anywhere under tmp_path -> _project_root returns None ->
    # _proven_module_mode must return None, not raise.
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    cli = isolated / "c.py"
    cli.write_text("")
    assert _proven_module_mode(str(cli), "somepkg") is None


def test_adjacent_file_case_still_wins_over_module_mode(tmp_path):
    # Regression: the existing _proven_local (adjacent-file) path must still
    # be checked BEFORE _proven_module_mode, and still produce WRONG_CWD with
    # its own (non-python-m) evidence wording, per the current test
    # test_proven_local_module_is_wrong_cwd.
    (tmp_path / "syllabus_v2.py").write_text("# local module\n")
    cli = tmp_path / "seed_artefacts.py"
    cli.write_text("import syllabus_v2\n")
    p = classify_failure("seed_artefacts", MNFE.format("syllabus_v2"), str(cli))
    assert p.failure_class == FailureClass.WRONG_CWD
    assert "proven-local" in p.evidence
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/a2a-cli-registry && python3 -m pytest tests/test_remediation_classify.py -v -k "module_mode or partial_proof or adjacent_file_case"`
Expected: FAIL — `ImportError: cannot import name '_proven_module_mode'`

- [ ] **Step 3: Implement `_proven_module_mode` in `classify.py`**

Read `core/remediation/classify.py` in full first (it's ~100 lines) to
confirm current exact content before editing — this plan was written
against a real read but re-verify. Add the import at the top (after the
existing `from pathlib import Path` line):

```python
from core.paths.module_root import _project_root, _dotted_module
```

Add the new function immediately after `_proven_local` (currently ends
around line 76):

```python
def _proven_module_mode(path: str, dotted: str) -> str | None:
    """Full dotted module name iff `dotted` demonstrably exists as a file or
    package under the CLI's derived project root (python -m <dotted> would
    resolve it). This is a PROOF like _proven_local: only checks the EXACT
    full dotted path (not just its top segment), so a real missing submodule
    (e.g. localpkg.missing where localpkg exists but missing doesn't) is
    never mistaken for a proven module-mode fix. Returns the dotted name
    (for building the evidence string) or None."""
    if not path:
        return None
    root = _project_root(path)
    if not root:
        return None
    import os
    parts = dotted.split(".")
    candidate = os.path.join(root, *parts)
    if os.path.exists(candidate + ".py") or os.path.isdir(candidate):
        if os.path.isdir(candidate) and not os.path.exists(
            os.path.join(candidate, "__init__.py")
        ):
            return None
        return dotted
    return None
```

Update `classify_failure`'s missing-module branch (currently lines 87-99).
The regex match `m` already captures the FULL dotted string in
`m.group(1)` before the existing code truncates it to `top` — thread that
full string through as `dotted`:

```python
    # 2. Missing module — split third-party vs proven-local vs
    # proven-module-mode vs unknown.
    m = _MNFE_RE.search(note)
    if m:
        dotted = m.group(1)
        top = dotted.split(".")[0]
        if top in IMPORT_TO_PACKAGE:
            return _proposal(slug, FailureClass.PIP_3RD_PARTY, FixKind.AUTO_SAFE,
                             IMPORT_TO_PACKAGE[top], regex,
                             f"{note} | mapped {top}->{IMPORT_TO_PACKAGE[top]}")
        if _proven_local(path, top):
            return _proposal(slug, FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY,
                             top, regex, f"{note} | proven-local {top} adjacent to {path}")
        proven_dotted = _proven_module_mode(path, dotted)
        if proven_dotted:
            return _proposal(slug, FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY,
                             proven_dotted, regex,
                             f"{note} | proven module-mode: python -m {proven_dotted} "
                             f"(from {_project_root(path)})")
        return _proposal(slug, FailureClass.PIP_UNKNOWN, FixKind.PROPOSE_ONLY,
                         top, regex, f"{note} | unmapped, not proven local")
```

Note: `top` is still used for the `IMPORT_TO_PACKAGE` lookup and
`_proven_local` call (unchanged, matches existing `test_dotted_module_uses_top_segment`
behavior for the non-proof fallback case), while `dotted` (the untruncated
string) is only used for the new `_proven_module_mode` check and its
evidence string, per the spec's requirement that only a full exact match
proves module-mode.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/a2a-cli-registry && python3 -m pytest tests/test_remediation_classify.py -v`
Expected: PASS — all tests including the pre-existing ones (full file, not
just the new `-k` filter, to confirm no regressions).

- [ ] **Step 5: Commit**

```bash
git add core/remediation/classify.py tests/test_remediation_classify.py
git commit -m "feat(remediation): classify local packages reachable via python -m as wrong-cwd

Adds _proven_module_mode, checked after the existing adjacent-file
_proven_local check and before falling to pip-unknown. Only fires on an
exact full-dotted-path match under the derived project root — a partial
match on just the top segment is never treated as proof, so a genuinely
missing submodule still falls to pip-unknown.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>" -- core/remediation/classify.py tests/test_remediation_classify.py
```

---

### Task 3: Full regression run across both affected test suites

**Files:**
- None modified — verification only.

**Interfaces:**
- Consumes: everything from Task 1 and Task 2. No new interfaces produced.

- [ ] **Step 1: Run the full project test suite**

Run: `cd ~/projects/a2a-cli-registry && python3 -m pytest -q`
Expected: PASS, 0 failed. Note the total pass count in the task's review
notes (the ticket's own history logged "104 unit tests pass" / "339 tests
pass" at prior milestones — record whatever the actual current total is,
don't assume a stale number).

- [ ] **Step 2: If any test fails, stop and diagnose before continuing**

Do not proceed to Task 4 with a red suite. If a failure is unrelated to
this change (a pre-existing flake), confirm by running
`git stash && python3 -m pytest -q <failing test path> && git stash pop`
to prove it fails on unmodified code too, then note it as pre-existing in
the task's review notes — do not silently ignore it without that proof.

- [ ] **Step 3: No commit for this task** (verification-only; nothing to
  stage)

---

### Task 4: Re-probe the live 46 affected CLIs (ticket AC-02)

**Files:**
- Modify: none (data migration against the live DB, no source changes)
- Create: `tools/reclassify_modulemode.py` (one-off operational script,
  mirrors the pattern of other `tools/*.py` one-off scripts already in this
  repo, e.g. `tools/backfill_capabilities.py`)

**Interfaces:**
- Consumes: `core.remediation.classify.classify_fleet` (existing, unchanged
  signature: takes rows exposing `.slug`/`.description`/`.path`, returns a
  list of `RemediationProposal`), the live registry DB's `cli` table
  (columns confirmed earlier this session: `slug`, `path`, `description`,
  `health_status`, `updated_at`, ...).
- Produces: nothing consumed by later tasks — this is the terminal step.

- [ ] **Step 1: Confirm which DB is live before touching anything**

Run: `launchctl print gui/$(id -u)/ai.hermes.cli-registry | grep -E "pid|state"`
Expected: an active pid — confirms `~/.hermes/cli-registry.db` is the live
DB the running service reads (per this session's earlier root-cause finding
— do not operate on `~/projects/a2a-cli-registry/registry.db`, which is
stale test-fixture output, not production data).

- [ ] **Step 2: Back up the live DB before mutating it**

```bash
cp ~/.hermes/cli-registry.db ~/.hermes/cli-registry.db.bak-$(date +%Y%m%d-%H%M%S)-pre-modulemode
```

Expected: backup file created, non-zero size matching the source.

- [ ] **Step 3: Write the one-off re-probe script**

Create `tools/reclassify_modulemode.py`:

```python
"""One-off: re-classify pip-unknown rows against the new module-mode check,
re-probe the ones that newly resolve to wrong-cwd, and flip to healthy only
the CLIs that demonstrably pass. Ticket: US-REMED-MODULEMODE-01 AC-02.

Usage: python3 tools/reclassify_modulemode.py [--db PATH] [--dry-run]
"""
import argparse
import sqlite3
import subprocess
import sys

from core.remediation.classify import classify_failure
from core.remediation.proposal import FailureClass


class _Row:
    def __init__(self, slug, description, path):
        self.slug = slug
        self.description = description
        self.path = path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="Path to registry DB (default: ~/.hermes/cli-registry.db)")
    ap.add_argument("--dry-run", action="store_true", help="Report only, do not write")
    args = ap.parse_args()

    import os
    db_path = args.db or os.path.expanduser("~/.hermes/cli-registry.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT slug, description, path FROM cli WHERE health_status != 'healthy'"
    ).fetchall()

    flips = []
    for r in rows:
        proposal = classify_failure(r["slug"], r["description"] or "", r["path"] or "")
        if proposal.failure_class != FailureClass.WRONG_CWD:
            continue
        if "python -m" not in (proposal.evidence or ""):
            continue  # only the new module-mode path, not the adjacent-file case
        # Extract the python -m invocation and re-probe.
        # evidence format: "... | proven module-mode: python -m <dotted> (from <root>)"
        ev = proposal.evidence
        marker = "python -m "
        idx = ev.find(marker)
        rest = ev[idx + len(marker):]
        dotted = rest.split(" (from ")[0].strip()
        root = rest.split(" (from ")[1].rstrip(")").strip() if " (from " in rest else None
        if not root:
            continue
        try:
            proc = subprocess.run(
                ["python3", "-m", dotted, "--help"],
                capture_output=True, text=True, timeout=5, cwd=root,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if not out or "Traceback" in out or "ModuleNotFoundError" in out:
            continue
        flips.append(r["slug"])

    print(f"{len(flips)} CLIs proven to pass module-mode re-probe: {flips}")

    if args.dry_run or not flips:
        return

    conn.executemany(
        "UPDATE cli SET health_status = 'healthy' WHERE slug = ?",
        [(s,) for s in flips],
    )
    conn.commit()
    print(f"Flipped {len(flips)} rows to healthy.")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Dry-run against the live DB first**

Run: `cd ~/projects/a2a-cli-registry && python3 tools/reclassify_modulemode.py --dry-run`
Expected: prints a count and list of slugs that would flip — inspect the
list manually before proceeding. If the count is wildly different from the
ticket's expected ~46 (e.g. 0, or in the hundreds), stop and investigate
before running for real — do not force the number to match by adjusting the
script.

- [ ] **Step 5: Run for real**

Run: `cd ~/projects/a2a-cli-registry && python3 tools/reclassify_modulemode.py`
Expected: prints the same count as the dry run, then "Flipped N rows to
healthy."

- [ ] **Step 6: Verify live via the overview endpoint**

Run: `curl -s http://localhost:9113/overview | grep -oE '(healthy|unhealthy|unknown) [0-9]+'`
Expected: `healthy` count increased by the flipped total, `unhealthy`/`unknown`
decreased correspondingly. The service reads the DB per-request (confirmed
earlier this session in the not-standalone-flip precedent), so no restart is
needed.

- [ ] **Step 7: Commit the one-off script (not the DB — the DB is runtime
  state, not source)**

```bash
git add tools/reclassify_modulemode.py
git commit -m "chore(tools): add one-off module-mode re-probe script (US-REMED-MODULEMODE-01 AC-02)

Re-classifies unhealthy rows against the new _proven_module_mode check and
flips only the CLIs that pass a live re-probe to healthy. Run once against
the live ~/.hermes/cli-registry.db; backup taken before the mutating run.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>" -- tools/reclassify_modulemode.py
```

---

## Self-Review Notes (completed during plan authoring)

- **Spec coverage:** Task 1 = spec's "extract shared module" + "update
  llm_infer.py". Task 2 = spec's "extend classify.py". Task 3 = spec's
  "testing" section (full-suite regression, both empty-path and
  dotted-submodule edge cases from the spec are in Task 2's tests). Task 4 =
  spec's "re-probing the 46 live-fleet rows" section (backup, re-classify,
  re-probe, flip-only-provens).
- **Placeholder scan:** no TBD/TODO; every step has real code or an exact
  command with expected output.
- **Type consistency:** `_proven_module_mode(path: str, dotted: str) -> str |
  None` is used identically in Task 2's implementation and its call site;
  `_project_root`/`_dotted_module` signatures match between Task 1's
  extraction and Task 2's import usage. `classify_fleet`'s existing signature
  (row objects exposing `.slug`/`.description`/`.path`) is unchanged and
  reused as-is in Task 4's script via the local `_Row`-shaped sqlite3.Row
  access.
- **Locked regression:** `test_dotted_module_uses_top_segment` (existing,
  unmodified) continues to assert `google.cloud` -> `PIP_UNKNOWN` because
  no local `google/cloud.py` exists in that test's `tmp_path` — proving the
  new check doesn't change behavior for genuinely-unproven dotted names.
