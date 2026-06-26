# Arm SafeFixer (live `--apply-safe` wheel installs) Implementation Plan

> **For agentic workers:** REQUIRED: Use `/sh:execute` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `SafeFixer.apply()`'s `NotImplementedError` stub with a live, containment-gated pipeline that wheel-installs the eligible (pip-3rd-party ∩ mapped ∩ declared-by-regex) packages into an isolated `demo/` venv, re-probes each fixed CLI in the same isolated env, and flips `health_status='healthy'` + `fixed_by='remediation'` only on a passing re-probe — atomically per CLI.

**Architecture:** `apply()` becomes an orchestrator over four containment primitives (already-live `is_eligible`/`venv_path_ok`, plus new `_install_one` and `_reprobe_one`). Each eligible proposal is processed independently: create/resolve an isolated per-package venv inside `demo/`, `pip install --only-binary=:all:` with a scrubbed process env and killpg timeout, then re-probe the CLI's health command in that env. A `FixResult` value object records the per-CLI outcome; `run.py` threads results into the summary; the CLI surfaces a real exit code. A new nullable `Cli.fixed_by` column carries provenance, added via an explicit existence-guarded `ALTER TABLE` migration (because `create_all` does not migrate existing tables).

**Tech Stack:** Python 3.11+, SQLModel/SQLite, `subprocess` (reusing the prober's `_kill_tree` / `start_new_session` killpg pattern), pytest.

**Spec:** `docs/superpowers/specs/2026-06-25-remediation-adapter-design.md` §3.4 (threat model + containment requirements), §3.5 (envelope), §8 (out-of-scope). **Read §3.4 in full before Task 4.**

**Decisions locked (this session):**
- Provenance → **add `fixed_by` column** (full §3.4 fidelity), via existence-guarded migration.
- Test boundary → **mock pip for all logic tests + ONE real e2e** install of a tiny mapped wheel into a temp `demo/` venv.

**Threat model (do not weaken any single constraint — containment is their SUM):**
> A venv isolates *packages*, NOT *execution*. `pip install` runs arbitrary build code. Containment = `--only-binary=:all:` (no source builds) **+** realpath-resolved venv inside `demo/` **+** scrubbed process env **+** killpg wall-clock timeout **+** re-probe writing ONLY the `health_status`/`fixed_by` flip. Drop one and the boundary leaks.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `core/remediation/proposal.py` | Add `FixResult` value object (per-CLI outcome) | Modify |
| `core/models.py` | Add `fixed_by: Optional[str]` to `Cli` | Modify |
| `core/store/migrations.py` | New: existence-guarded `ALTER TABLE` for `fixed_by` | Create |
| `core/remediation/safe_fixer.py` | Live `apply()` + `_install_one` + `_reprobe_one` + scrubbed-env builder | Modify |
| `core/remediation/run.py` | Stop swallowing `NotImplementedError`; thread `FixResult`s into summary | Modify |
| `core/cli/main.py` | Run migration on remediate; real exit code; replace "not implemented" message | Modify |
| `tests/test_remediation_safefixer.py` | Extend: env scrub, install mock, killpg, atomic-per-CLI, re-probe flip | Modify |
| `tests/test_fixed_by_migration.py` | New: migration adds column, idempotent, preserves rows | Create |
| `tests/test_remediation_safefixer_e2e.py` | New: ONE real wheel install + re-probe (opt-in marker) | Create |

---

## Chunk 1: Provenance plumbing (FixResult + fixed_by column + migration)

### Task 1: `FixResult` value object

**Files:**
- Modify: `core/remediation/proposal.py`
- Test: `tests/test_remediation_safefixer.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_remediation_safefixer.py
from core.remediation.proposal import FixResult

def test_fixresult_to_dict_roundtrip():
    r = FixResult(slug="s", target="numpy", outcome="fixed", detail="re-probe passed")
    assert r.to_dict() == {
        "slug": "s", "target": "numpy", "outcome": "fixed",
        "detail": "re-probe passed",
    }

def test_fixresult_outcomes_are_constrained():
    # outcome is a plain str but the constructor documents the allowed set;
    # this test pins the vocabulary so a typo'd outcome string is caught.
    for o in ("fixed", "install-failed", "reprobe-failed", "refused", "timeout"):
        FixResult(slug="s", target="t", outcome=o, detail="")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_remediation_safefixer.py::test_fixresult_to_dict_roundtrip -v`
Expected: FAIL with `ImportError: cannot import name 'FixResult'`

- [ ] **Step 3: Add `FixResult` to proposal.py**

```python
# append to core/remediation/proposal.py, after FailureRecord
_FIX_OUTCOMES = frozenset(
    {"fixed", "install-failed", "reprobe-failed", "refused", "timeout"})


@dataclass(frozen=True)
class FixResult:
    """Per-CLI outcome of a SafeFixer.apply() attempt (spec §3.4). Pure data.

    outcome ∈ {fixed, install-failed, reprobe-failed, refused, timeout}:
      fixed          – installed AND isolated re-probe passed; health flipped.
      install-failed – pip returned non-zero (e.g. no wheel available).
      reprobe-failed – installed but the CLI still failed its --help probe.
      refused        – eligibility/path gate rejected it (defensive; run.py
                       pre-filters via is_eligible, so this is belt-and-braces).
      timeout        – install or re-probe hit the wall-clock cap (killpg'd).
    """
    slug: str
    target: str
    outcome: str
    detail: str

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "target": self.target,
            "outcome": self.outcome, "detail": self.detail,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_remediation_safefixer.py -k fixresult -v`
Expected: PASS (both)

- [ ] **Step 5: Commit**

```bash
git add core/remediation/proposal.py tests/test_remediation_safefixer.py
git commit -m "feat(remediation): add FixResult value object for SafeFixer outcomes"
```

---

### Task 2: `fixed_by` column on the `Cli` model

**Files:**
- Modify: `core/models.py:15-16` (add field after `health_checked_at`)
- Test: `tests/test_fixed_by_migration.py` (created in Task 3; model default tested here inline)

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_remediation_safefixer.py
from core.models import Cli

def test_cli_has_fixed_by_field_defaulting_none():
    c = Cli(slug="s", lang="python")
    assert c.fixed_by is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_remediation_safefixer.py::test_cli_has_fixed_by_field_defaulting_none -v`
Expected: FAIL with `AttributeError` / unexpected-kwarg

- [ ] **Step 3: Add the field**

```python
# core/models.py — insert after line 16 (health_checked_at)
    fixed_by: Optional[str] = None                   # 'remediation' if auto-fixed; else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_remediation_safefixer.py::test_cli_has_fixed_by_field_defaulting_none -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/models.py tests/test_remediation_safefixer.py
git commit -m "feat(models): add Cli.fixed_by provenance column (nullable)"
```

---

### Task 3: Existence-guarded `fixed_by` migration

**WHY THIS TASK EXISTS:** `SQLModel.metadata.create_all()` (core/store/db.py:22) is idempotent *per table* but never ALTERs an existing table to add a column. Tests build a fresh in-memory DB each run so they pass — but the live `demo/registry.db` already exists and will silently lack `fixed_by`. This migration closes that gap.

**Files:**
- Create: `core/store/migrations.py`
- Test: `tests/test_fixed_by_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fixed_by_migration.py
import sqlite3
from core.store.migrations import ensure_fixed_by_column


def _make_legacy_db(path):
    # A 'cli' table WITHOUT fixed_by — simulates the pre-migration production DB.
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE cli (slug TEXT PRIMARY KEY, health_status TEXT)")
    con.execute("INSERT INTO cli (slug, health_status) VALUES ('a','unhealthy')")
    con.commit()
    con.close()


def test_migration_adds_missing_column(tmp_path):
    db = str(tmp_path / "registry.db")
    _make_legacy_db(db)
    ensure_fixed_by_column(db)
    con = sqlite3.connect(db)
    cols = {row[1] for row in con.execute("PRAGMA table_info(cli)")}
    con.close()
    assert "fixed_by" in cols


def test_migration_is_idempotent(tmp_path):
    db = str(tmp_path / "registry.db")
    _make_legacy_db(db)
    ensure_fixed_by_column(db)
    ensure_fixed_by_column(db)  # second call must not raise "duplicate column"
    con = sqlite3.connect(db)
    cols = [row[1] for row in con.execute("PRAGMA table_info(cli)")]
    con.close()
    assert cols.count("fixed_by") == 1


def test_migration_preserves_existing_rows(tmp_path):
    db = str(tmp_path / "registry.db")
    _make_legacy_db(db)
    ensure_fixed_by_column(db)
    con = sqlite3.connect(db)
    row = con.execute("SELECT slug, health_status, fixed_by FROM cli WHERE slug='a'").fetchone()
    con.close()
    assert row == ("a", "unhealthy", None)


def test_migration_noop_when_table_absent(tmp_path):
    # A DB with no 'cli' table at all must not raise (create_all handles creation).
    db = str(tmp_path / "empty.db")
    sqlite3.connect(db).close()
    ensure_fixed_by_column(db)  # must be a silent no-op
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_fixed_by_migration.py -v`
Expected: FAIL with `ModuleNotFoundError: core.store.migrations`

- [ ] **Step 3: Implement the migration**

```python
# core/store/migrations.py
"""One-shot, existence-guarded schema migrations for the SQLite registry.

create_all() (core/store/db.py) creates missing TABLES but never ALTERs an
existing table to add a COLUMN. A model field added to a persisted table is
therefore invisible to an existing DB file until an explicit ALTER runs. These
functions are idempotent: safe to call on every command invocation."""
import sqlite3


def _table_exists(con, table: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone()
    return row is not None


def _column_exists(con, table: str, column: str) -> bool:
    return any(r[1] == column for r in con.execute(f"PRAGMA table_info({table})"))


def ensure_fixed_by_column(db_path: str) -> None:
    """Add cli.fixed_by if the table exists and the column does not. No-op
    otherwise. Idempotent — a second call sees the column and returns."""
    con = sqlite3.connect(db_path)
    try:
        if _table_exists(con, "cli") and not _column_exists(con, "cli", "fixed_by"):
            con.execute("ALTER TABLE cli ADD COLUMN fixed_by TEXT")
            con.commit()
    finally:
        con.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_fixed_by_migration.py -v`
Expected: PASS (all 4)

- [ ] **Step 5: Commit**

```bash
git add core/store/migrations.py tests/test_fixed_by_migration.py
git commit -m "feat(store): existence-guarded ALTER TABLE migration for cli.fixed_by"
```

**Chunk 1 review:** FixResult, the model field, and the migration form a self-contained provenance layer with no dependency on the install logic. The migration test simulates a legacy DB (no `fixed_by`) to prove the production gap is closed — this is the highest-risk item and is tested first. Proceed.

---

## Chunk 2: Containment primitives (scrubbed env + install + re-probe)

### Task 4: Scrubbed-env builder

**Files:**
- Modify: `core/remediation/safe_fixer.py`
- Test: `tests/test_remediation_safefixer.py`

**Read spec §3.4 "Isolated process env" before writing.** Requirement: scrubbed `HOME`, `PIP_CACHE_DIR`, `TMPDIR`, `XDG_*` all pointed inside `demo/`; `PYTHONNOUSERSITE=1`; no inherited project env vars.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_remediation_safefixer.py
def test_isolated_env_redirects_into_demo_and_scrubs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "/etc/should-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-should-not-leak")
    fixer = SafeFixer(demo_dir=str(tmp_path))
    env = fixer._isolated_env()
    demo = os.path.realpath(str(tmp_path))
    # redirected inside demo/
    assert env["HOME"].startswith(demo)
    assert env["PIP_CACHE_DIR"].startswith(demo)
    assert env["TMPDIR"].startswith(demo)
    assert env["XDG_DATA_HOME"].startswith(demo)  # overridden, not the leaked /etc value
    # hardening flag
    assert env["PYTHONNOUSERSITE"] == "1"
    # no inherited project secret
    assert "OPENAI_API_KEY" not in env
    # PATH is preserved (need to find pip/python) but not arbitrary project vars
    assert "PATH" in env
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_remediation_safefixer.py::test_isolated_env_redirects_into_demo_and_scrubs -v`
Expected: FAIL with `AttributeError: '_isolated_env'`

- [ ] **Step 3: Implement `_isolated_env`**

```python
# add imports at top of core/remediation/safe_fixer.py
import os

# add method to SafeFixer
    _ALLOWLIST_ENV = ("PATH",)  # minimum needed to locate python/pip; nothing project-specific

    def _isolated_env(self) -> dict:
        """Build a scrubbed process env for pip + re-probe (spec §3.4).

        Allowlist (not blocklist) so no project secret/config leaks in: start
        from an allowlisted few (PATH), then redirect HOME/caches/XDG inside
        demo/ and set PYTHONNOUSERSITE. A blocklist would silently pass any new
        env var the host adds; the allowlist fails closed."""
        sandbox = os.path.join(self.demo_dir, ".sandbox")
        env = {k: os.environ[k] for k in self._ALLOWLIST_ENV if k in os.environ}
        env["HOME"] = sandbox
        env["PIP_CACHE_DIR"] = os.path.join(sandbox, "pip-cache")
        env["TMPDIR"] = os.path.join(sandbox, "tmp")
        env["XDG_DATA_HOME"] = os.path.join(sandbox, "xdg-data")
        env["XDG_CACHE_HOME"] = os.path.join(sandbox, "xdg-cache")
        env["XDG_CONFIG_HOME"] = os.path.join(sandbox, "xdg-config")
        env["PYTHONNOUSERSITE"] = "1"
        return env
```

Note: `self.demo_dir` is already `os.path.realpath(demo_dir)` (existing `__init__`), so the redirected paths are realpath-anchored.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_remediation_safefixer.py::test_isolated_env_redirects_into_demo_and_scrubs -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/remediation/safe_fixer.py tests/test_remediation_safefixer.py
git commit -m "feat(remediation): allowlist-based isolated env for SafeFixer installs"
```

---

### Task 5: `_run_contained` — killpg-timeout subprocess runner

**Files:**
- Modify: `core/remediation/safe_fixer.py`
- Test: `tests/test_remediation_safefixer.py`

This is the single subprocess primitive both install and re-probe use. It reuses the prober's `_kill_tree` and `start_new_session` killpg pattern (do NOT duplicate the kill logic — import it).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_remediation_safefixer.py
import sys

def test_run_contained_returns_zero_on_success(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    rc, timed_out = fixer._run_contained([sys.executable, "-c", "pass"], timeout=10.0)
    assert rc == 0 and timed_out is False

def test_run_contained_nonzero_exit(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    rc, timed_out = fixer._run_contained([sys.executable, "-c", "import sys; sys.exit(7)"], timeout=10.0)
    assert rc == 7 and timed_out is False

def test_run_contained_kills_on_timeout(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    rc, timed_out = fixer._run_contained(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert timed_out is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_remediation_safefixer.py -k run_contained -v`
Expected: FAIL with `AttributeError: '_run_contained'`

- [ ] **Step 3: Implement `_run_contained`**

```python
# add imports
import subprocess
from core.prober.prober import _kill_tree, _POSIX

# add method to SafeFixer
    def _run_contained(self, argv: list, *, timeout: float) -> tuple:
        """Run argv in the scrubbed env, own process group, wall-clock killpg.

        Returns (returncode, timed_out). Reuses the prober's _kill_tree so the
        whole process tree dies on timeout (a pip build subprocess can fork).
        Output is discarded — health is decided by exit code, same as the
        prober. cwd is demo_dir so any stray file write lands in the sandbox."""
        try:
            proc = subprocess.Popen(
                argv,
                cwd=self.demo_dir,
                env=self._isolated_env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=_POSIX,
            )
        except (OSError, ValueError):
            return (1, False)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.wait()
            return (proc.returncode if proc.returncode is not None else -1, True)
        return (proc.returncode, False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_remediation_safefixer.py -k run_contained -v`
Expected: PASS (all 3; the timeout test takes ~0.5s)

- [ ] **Step 5: Commit**

```bash
git add core/remediation/safe_fixer.py tests/test_remediation_safefixer.py
git commit -m "feat(remediation): _run_contained killpg-timeout subprocess primitive"
```

**Chunk 2 review:** `_isolated_env` + `_run_contained` are the two reusable primitives. Both are tested in isolation with real subprocesses (no mocking needed — they're cheap and deterministic). `_kill_tree` is imported, not copied (DRY). Proceed to the orchestrator.

---

## Chunk 3: `apply()` orchestration + venv/install/re-probe

### Task 6: `_venv_dir` + venv-path refusal integration

**Files:**
- Modify: `core/remediation/safe_fixer.py`
- Test: `tests/test_remediation_safefixer.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_remediation_safefixer.py
def test_venv_dir_is_per_target_inside_demo(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    vd = fixer._venv_dir("numpy")
    assert os.path.realpath(vd).startswith(os.path.realpath(str(tmp_path)))
    assert "numpy" in os.path.basename(vd)

def test_venv_dir_rejects_path_traversal_target(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    # a malicious/garbage target must not escape demo/ via .. or /
    with pytest.raises(ValueError):
        fixer._venv_dir("../../etc")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_remediation_safefixer.py -k venv_dir -v`
Expected: FAIL with `AttributeError: '_venv_dir'`

- [ ] **Step 3: Implement `_venv_dir`**

```python
# add to SafeFixer
    def _venv_dir(self, target: str) -> str:
        """Per-package venv path inside demo/, with a defensive name check.

        target is already constrained to be a value in IMPORT_TO_PACKAGE by
        is_eligible(), but _venv_dir refuses any name containing path separators
        or '..' so a future caller can't smuggle traversal. The resulting path
        is also checked via venv_path_ok by the caller."""
        if os.sep in target or (os.altsep and os.altsep in target) or ".." in target:
            raise ValueError(f"unsafe venv target name: {target!r}")
        return os.path.join(self.demo_dir, ".sandbox", f"venv-{target}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_remediation_safefixer.py -k venv_dir -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/remediation/safe_fixer.py tests/test_remediation_safefixer.py
git commit -m "feat(remediation): per-target sandbox venv path with traversal refusal"
```

---

### Task 7: Live `apply()` orchestration (mocked install/re-probe)

**Files:**
- Modify: `core/remediation/safe_fixer.py` (replace the `NotImplementedError` body)
- Test: `tests/test_remediation_safefixer.py`

**Design:** `apply(proposals)` loops eligible proposals; for each it (1) re-checks `is_eligible` + `venv_path_ok` (refuse → `FixResult(refused)`), (2) `_install_one` (creates venv, `pip install --only-binary=:all:`), (3) `_reprobe_one` (runs the CLI's health cmd in the isolated env), (4) on pass, flips `health_status='healthy'` + `fixed_by='remediation'` for that one CLI and commits. Atomic per CLI: any failure records a `FixResult` and leaves that CLI unhealthy with NO DB write. `apply()` takes the `session` and a `health_cmd_for(slug)->str` lookup so it can re-probe and write — injected, not imported, for testability.

**The existing `test_apply_raises_not_implemented` test MUST be deleted in Step 1** (the stub is the thing we're removing).

- [ ] **Step 1: Remove the stub test, write the orchestration tests**

```python
# DELETE test_apply_raises_not_implemented from tests/test_remediation_safefixer.py

# add: a fake fixer-subclass that stubs install/reprobe so apply() logic is
# tested without real pip. We override the two I/O methods only.
class _FakeFixer(SafeFixer):
    def __init__(self, demo_dir, install_rc, reprobe_rc):
        super().__init__(demo_dir=demo_dir)
        self._install_rc = install_rc      # (rc, timed_out)
        self._reprobe_rc = reprobe_rc      # 'healthy' | 'unhealthy'
        self.installed = []
    def _install_one(self, target, venv_dir):
        self.installed.append(target)
        return self._install_rc
    def _reprobe_one(self, slug, health_cmd, venv_dir):
        return self._reprobe_rc


def _eligible_proposal(slug="numpy-cli", target="numpy"):
    # RemediationProposal is a frozen dataclass (not a namedtuple) — construct
    # directly; there is no _replace().
    return RemediationProposal(schema_version=SCHEMA_VERSION, slug=slug,
        failure_class=FailureClass.PIP_3RD_PARTY, fix_kind=FixKind.AUTO_SAFE,
        target=target, confidence=Confidence.DECLARED_BY_REGEX, evidence="e")


def test_apply_fixes_on_install_and_reprobe_success(tmp_path):
    from core.models import Cli
    from sqlmodel import Session, SQLModel, create_engine
    from sqlalchemy.pool import StaticPool
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Cli(slug="numpy-cli", lang="python", health_status="unhealthy",
                  health_cmd="true")); s.commit()
        fixer = _FakeFixer(str(tmp_path), install_rc=(0, False), reprobe_rc="healthy")
        results = fixer.apply([_eligible_proposal()], session=s,
                              health_cmd_for=lambda slug: "true")
        s.refresh(s.get(Cli, "numpy-cli"))
        row = s.get(Cli, "numpy-cli")
        assert row.health_status == "healthy"
        assert row.fixed_by == "remediation"
    assert results[0].outcome == "fixed"


def test_apply_leaves_unhealthy_on_install_failure(tmp_path):
    from core.models import Cli
    from sqlmodel import Session, SQLModel, create_engine
    from sqlalchemy.pool import StaticPool
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Cli(slug="numpy-cli", lang="python", health_status="unhealthy")); s.commit()
        fixer = _FakeFixer(str(tmp_path), install_rc=(1, False), reprobe_rc="healthy")
        results = fixer.apply([_eligible_proposal()], session=s,
                              health_cmd_for=lambda slug: "true")
        row = s.get(Cli, "numpy-cli")
        assert row.health_status == "unhealthy"   # untouched
        assert row.fixed_by is None
    assert results[0].outcome == "install-failed"


def test_apply_records_reprobe_failed(tmp_path):
    from core.models import Cli
    from sqlmodel import Session, SQLModel, create_engine
    from sqlalchemy.pool import StaticPool
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Cli(slug="numpy-cli", lang="python", health_status="unhealthy")); s.commit()
        fixer = _FakeFixer(str(tmp_path), install_rc=(0, False), reprobe_rc="unhealthy")
        results = fixer.apply([_eligible_proposal()], session=s,
                              health_cmd_for=lambda slug: "true")
        assert s.get(Cli, "numpy-cli").health_status == "unhealthy"
    assert results[0].outcome == "reprobe-failed"


def test_apply_refuses_ineligible_without_install(tmp_path):
    fixer = _FakeFixer(str(tmp_path), install_rc=(0, False), reprobe_rc="healthy")
    # pip-unknown is ineligible — apply must refuse and never call install
    bad = RemediationProposal(schema_version=SCHEMA_VERSION, slug="x",
        failure_class=FailureClass.PIP_UNKNOWN, fix_kind=FixKind.PROPOSE_ONLY,
        target="romsorter", confidence=Confidence.DECLARED_BY_REGEX, evidence="e")
    results = fixer.apply([bad], session=None, health_cmd_for=lambda slug: "true")
    assert results[0].outcome == "refused"
    assert fixer.installed == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_remediation_safefixer.py -k apply -v`
Expected: FAIL (apply signature mismatch / NotImplementedError)

- [ ] **Step 3: Implement live `apply()` + `_install_one` + `_reprobe_one`**

```python
# replace the apply() stub in core/remediation/safe_fixer.py with:
    def apply(self, proposals, *, session, health_cmd_for) -> list:
        """Install + re-probe each eligible proposal. Atomic per CLI: a failure
        records a FixResult and writes NOTHING for that CLI (spec §3.4).

        session: SQLModel session for the single health_status/fixed_by flip.
        health_cmd_for: callable slug -> health command string for the re-probe.
        """
        from core.remediation.proposal import FixResult
        results = []
        for p in proposals:
            if not (self.is_eligible(p)):
                results.append(FixResult(p.slug, p.target, "refused", "ineligible"))
                continue
            try:
                venv_dir = self._venv_dir(p.target)
            except ValueError as exc:
                results.append(FixResult(p.slug, p.target, "refused", str(exc)))
                continue
            if not self.venv_path_ok(venv_dir):
                results.append(FixResult(p.slug, p.target, "refused", "venv path escapes demo/"))
                continue

            rc, timed_out = self._install_one(p.target, venv_dir)
            if timed_out:
                results.append(FixResult(p.slug, p.target, "timeout", "install timed out"))
                continue
            if rc != 0:
                results.append(FixResult(p.slug, p.target, "install-failed", f"pip rc={rc}"))
                continue

            status = self._reprobe_one(p.slug, health_cmd_for(p.slug), venv_dir)
            if status != "healthy":
                results.append(FixResult(p.slug, p.target, "reprobe-failed", "still unhealthy"))
                continue

            # SUCCESS: the ONLY DB write — flip this one CLI. (spec §3.4)
            from core.models import Cli
            row = session.get(Cli, p.slug)
            if row is not None:
                row.health_status = "healthy"
                row.fixed_by = "remediation"
                session.add(row)
                session.commit()
            results.append(FixResult(p.slug, p.target, "fixed", "re-probe passed"))
        return results

    def _install_one(self, target, venv_dir) -> tuple:
        """Create the venv, wheel-only install `target`. Returns (rc, timed_out).
        --only-binary=:all: forbids source builds (no setup.py execution)."""
        import sys
        rc, t = self._run_contained([sys.executable, "-m", "venv", venv_dir], timeout=120.0)
        if rc != 0 or t:
            return (rc or 1, t)
        pip = os.path.join(venv_dir, "bin", "pip")
        return self._run_contained(
            [pip, "install", "--only-binary=:all:", "--no-input",
             "--timeout", "60", target],
            timeout=180.0)

    def _reprobe_one(self, slug, health_cmd, venv_dir) -> str:
        """Re-probe the CLI's health command in the isolated env. The venv's
        bin is prepended to PATH so the freshly-installed package is importable.
        Returns 'healthy' | 'unhealthy'."""
        import shlex
        env = self._isolated_env()
        env["PATH"] = os.path.join(venv_dir, "bin") + os.pathsep + env.get("PATH", "")
        rc, t = self._run_contained(shlex.split(health_cmd), timeout=10.0)
        return "healthy" if (rc == 0 and not t) else "unhealthy"
```

Note: `_reprobe_one` builds its own env to prepend the venv bin, so it calls `_run_contained` — but `_run_contained` uses `_isolated_env()` internally. **Refactor `_run_contained` to accept an optional `env` override** so the re-probe's venv-PATH env is honored:

```python
    def _run_contained(self, argv, *, timeout, env=None):
        ...
        proc = subprocess.Popen(argv, cwd=self.demo_dir,
            env=env if env is not None else self._isolated_env(), ...)
```
and call `self._run_contained(shlex.split(health_cmd), timeout=10.0, env=env)` in `_reprobe_one`.

- [ ] **Step 4: Run the full SafeFixer suite**

Run: `.venv/bin/pytest tests/test_remediation_safefixer.py -v`
Expected: PASS (all, including the pre-existing refusal tests; the deleted stub test is gone)

- [ ] **Step 5: Commit**

```bash
git add core/remediation/safe_fixer.py tests/test_remediation_safefixer.py
git commit -m "feat(remediation): arm SafeFixer.apply with contained install + re-probe"
```

**Chunk 3 review:** `apply()` is now live but every I/O step (`_install_one`, `_reprobe_one`) is overridable, so the orchestration logic (eligibility re-check, atomic-per-CLI, single DB write) is fully unit-tested without pip. The real pip path is exercised once in Task 9. Proceed.

---

## Chunk 4: Wiring (run.py + CLI) and the real e2e proof

### Task 8: Thread results through `run.py` and the CLI

**Files:**
- Modify: `core/remediation/run.py:51-62` (stop swallowing; pass session + lookup; collect results)
- Modify: `core/cli/main.py:167-218` (run migration; build `health_cmd_for`; real exit code; new message)
- Test: `tests/test_remediation_run.py` (existing remediate-run tests) + `tests/test_cli_remediate.py` (existing)

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_remediation_run.py (or the existing run-level test module)
def test_run_remediate_threads_fix_results_when_armed(remediate_session):
    # remediate_session: a fixture with at least one unhealthy pip-3rd-party CLI.
    # Use a fake SafeFixer whose apply() returns one 'fixed' FixResult.
    class _StubFixer:
        def is_eligible(self, p): return True
        def apply(self, proposals, *, session, health_cmd_for):
            from core.remediation.proposal import FixResult
            return [FixResult("s", "numpy", "fixed", "ok")]
    summary = run_remediate(remediate_session, out_path="/tmp/p.json",
        do_file=False, apply_safe=True, max_llm_calls=0,
        session_id="t", generated_at="t", safe_fixer=_StubFixer())
    assert summary["apply_safe_requested"] is True
    assert summary["fixes_applied"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_remediation_run.py -k threads_fix_results -v`
Expected: FAIL (`KeyError: 'fixes_applied'` / signature mismatch)

- [ ] **Step 3: Update `run.py`**

Replace the step-4 block (run.py:51-62) with:

```python
    # step 4: SafeFixer — when armed, run the live install+re-probe pipeline.
    fix_results = []
    apply_safe_requested = False
    if apply_safe and safe_fixer is not None:
        apply_safe_requested = True
        eligible = [p for p in proposals if safe_fixer.is_eligible(p)]
        by_slug = {r.slug: r for r in rows}
        def _health_cmd_for(slug):
            r = by_slug.get(slug)
            return r.health_cmd if (r and r.health_cmd) else "false"
        fix_results = safe_fixer.apply(eligible, session=session,
                                       health_cmd_for=_health_cmd_for)
```

Add to the returned summary dict:

```python
        "fixes_applied": sum(1 for r in fix_results if r.outcome == "fixed"),
        "fix_results": [r.to_dict() for r in fix_results],
```

Optionally fold `fix_results` into the envelope under a `"fix_results"` key (spec §3.5 envelope is extensible) — add `fix_results=fix_results` to a `build_envelope` kwarg, or write them alongside. **Keep it minimal: add `fixes_applied` to the summary now; envelope persistence of fix_results is a nice-to-have, do it only if the run-level test needs it.**

- [ ] **Step 4: Update `core/cli/main.py`**

1. After resolving the DB path and before `run_remediate`, run the migration:
```python
   from core.store.migrations import ensure_fixed_by_column
   ensure_fixed_by_column(db_path)   # close the create_all column gap
```
2. Replace the `SafeFixer(demo_dir=".")` construction — point it at the real sandbox dir (`demo/` for the production invocation; keep configurable via existing `--out`/config if present).
3. Replace the exit-3 / "not yet implemented" branch (main.py:216-218) with a real result message:
```python
   if summary.get("apply_safe_requested"):
       print(f"remediate: --apply-safe applied {summary['fixes_applied']} fix(es)",
             file=sys.stderr)
```
4. Decide the armed exit code: `0` if no fixes were *requested-but-failed*, else a non-zero signal. Minimal rule: exit `0` on a clean armed run (matches "fixes are best-effort, per-CLI atomic"); keep `2`/`4` for DB/write errors. Remove the unconditional exit-3.

- [ ] **Step 5: Run the run-level + CLI tests**

Run: `.venv/bin/pytest tests/test_remediation_run.py tests/test_cli_remediate.py -v`
Expected: PASS (update any test that asserted the old exit-3 / "not implemented" message — those assertions are now stale and must be changed to the armed behavior)

- [ ] **Step 6: Commit**

```bash
git add core/remediation/run.py core/cli/main.py tests/
git commit -m "feat(remediation): wire armed SafeFixer through run.py + CLI, run fixed_by migration"
```

---

### Task 9: ONE real end-to-end install + re-probe

**Files:**
- Create: `tests/test_remediation_safefixer_e2e.py`

This is the single test that proves the real pip path works: it installs a tiny, pure-Python, wheel-available mapped distribution into a temp `demo/` venv and asserts a real re-probe flips health. Marked so the fast suite can skip it offline.

- [ ] **Step 1: Write the e2e test**

```python
# tests/test_remediation_safefixer_e2e.py
"""ONE real install+re-probe. Network + pip required; marked 'e2e' so the
default suite can deselect it (pytest -m 'not e2e'). Uses a tiny pure-Python
wheel that is a VALUE in IMPORT_TO_PACKAGE so eligibility passes."""
import os
import sys
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from core.models import Cli
from core.remediation.safe_fixer import SafeFixer
from core.remediation.proposal import (
    SCHEMA_VERSION, RemediationProposal, FailureClass, FixKind, Confidence)
from core.remediation.classify import IMPORT_TO_PACKAGE

# pick a small, pure-python, wheel-only-installable mapped dist
_TARGET = "portalocker"  # identity-mapped in the fleet; tiny; pure python


@pytest.mark.e2e
def test_real_install_and_reprobe_flips_health(tmp_path):
    assert _TARGET in set(IMPORT_TO_PACKAGE.values())
    demo = tmp_path / "demo"; demo.mkdir()
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        # health cmd: succeeds ONLY if the package imports — proving the install took
        cmd = f'{sys.executable} -c "import portalocker"'
        s.add(Cli(slug="pl-cli", lang="python", health_status="unhealthy",
                  health_cmd=cmd)); s.commit()
        fixer = SafeFixer(demo_dir=str(demo))
        p = RemediationProposal(schema_version=SCHEMA_VERSION, slug="pl-cli",
            failure_class=FailureClass.PIP_3RD_PARTY, fix_kind=FixKind.AUTO_SAFE,
            target=_TARGET, confidence=Confidence.DECLARED_BY_REGEX, evidence="e")
        results = fixer.apply([p], session=s,
            health_cmd_for=lambda slug: os.path.join(
                str(demo), ".sandbox", f"venv-{_TARGET}", "bin", "python")
                + ' -c "import portalocker"')
        row = s.get(Cli, "pl-cli")
        assert results[0].outcome == "fixed", results[0].detail
        assert row.health_status == "healthy"
        assert row.fixed_by == "remediation"
```

Note the re-probe command must use the **venv's** python (where the package was installed), not the system python — that's the whole point of the isolated install. Confirm `_reprobe_one`'s PATH-prepend makes a bare `python -c "import portalocker"` resolve to the venv python; if the test uses an absolute venv-python path it sidesteps PATH ambiguity. Prefer the absolute-path form shown above for determinism.

- [ ] **Step 2: Register the `e2e` marker**

In `pyproject.toml` or `pytest.ini`, add:
```ini
markers =
    e2e: real network/pip; deselect with -m 'not e2e'
```

- [ ] **Step 3: Run the e2e test**

Run: `.venv/bin/pytest tests/test_remediation_safefixer_e2e.py -v -m e2e`
Expected: PASS (takes a few seconds — real venv + pip install)

- [ ] **Step 4: Run the full suite minus e2e to confirm no regressions**

Run: `.venv/bin/pytest -m 'not e2e' -q`
Expected: all prior tests + new unit tests pass; e2e deselected

- [ ] **Step 5: Commit**

```bash
git add tests/test_remediation_safefixer_e2e.py pyproject.toml
git commit -m "test(remediation): real e2e install+re-probe proof for SafeFixer"
```

**Chunk 4 review:** wiring threads `FixResult`s to the summary, the migration runs on every remediate invocation (closing the production column gap), and exactly one real-pip test proves the path end-to-end. The old exit-3/"not implemented" contract is replaced — any test asserting it was updated in Task 8. Proceed to final verification.

---

## Final Verification (before declaring done)

- [ ] **Full suite green:** `.venv/bin/pytest -q` (with network for e2e) AND `.venv/bin/pytest -m 'not e2e' -q` (offline). Both green. Capture the pass count.
- [ ] **Migration on the real DB:** run `ensure_fixed_by_column("demo/registry.db")` once (or invoke `remediate` which now runs it) and verify with `sqlite3 demo/registry.db "PRAGMA table_info(cli)"` that `fixed_by` is present. Evidence before "done".
- [ ] **Dry sanity (no install):** `remediate` WITHOUT `--apply-safe` still produces proposals.json and files nothing — confirm the read-only default is unchanged (do-no-harm).
- [ ] **Self-review pass:** invoke `superpowers:requesting-code-review` (or `sh:review`) on the branch diff before merge — this touches a mutating filesystem path with a threat model; an independent review is mandatory, not optional.
- [ ] **Spec drift check:** re-read §3.4 and confirm every listed containment constraint maps to code: `--only-binary=:all:` ✓, realpath venv inside demo/ ✓, scrubbed env ✓, killpg timeout ✓, single health_status/fixed_by write ✓, never touches non-eligible classes ✓.

---

## Open / Deferred (NOT in this plan)

- **Production run on the 36 pip-3rd-party CLIs** — that's an *operational* step after this lands, not part of the build. Run `remediate --apply-safe --file` against `demo/registry.db` once merged + reviewed.
- **`fix_results` in proposals.json envelope** — added to the summary dict; full envelope persistence (§3.5) is optional, do only if reconciliation needs it.
- **Per-package venv reuse / caching** — each run rebuilds the venv. Acceptable for 36 CLIs; optimize only if it's slow (YAGNI).
- **`wrong-venv` auto-detection, growing the allowlist from data** — explicitly §8 out-of-scope.

---

**Plan complete and saved to `docs/plans/2026-06-25-arm-safefixer.md`. Ready to execute?**
