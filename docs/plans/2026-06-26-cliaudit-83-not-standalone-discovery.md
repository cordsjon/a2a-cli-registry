# US-CLIAUDIT-83: Not-Standalone Discovery Filter Implementation Plan

> **For agentic workers:** REQUIRED: Use `/sh:execute` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Statically detect the two "not a standalone CLI" classes — (a) Typer/click sub-apps with no `if __name__` guard, and (b) `__main__`-guarded batch scripts with no argument parser — and represent them as a durable 5th health badge (`not_standalone`) that survives the prober's re-probe pass, so 54 working-but-not-standalone modules stop being filed as broken CLIs.

**Architecture:** A new pure-`ast` classifier (`bridge/standalone.py`) inspects source **without executing it** (these are untrusted files) and returns one of `standalone` / `subapp` / `no_parser`. The bridge (`audit_to_registry.py`) calls it at feed-build time and stamps a `not_standalone: true` flag onto non-standalone feed entries. That flag flows through `CliRecord` → `Cli` model → DB. The prober's Phase-1 partition learns to route `not_standalone` rows to a preserved state (never probed, never overwritten). The four render/count sites (`models.py`, `prober.py`, `tui/overview.py`, `web/overview_view.py`) gain the 5th badge. Reuses `_project_root`/`_dotted_module` from `llm_infer.py` (abstract-on-third) for the module-mode evidence string.

**Trade-off (decided):** 5th badge + prober skip, NOT feed-build exclusion. Excluding would satisfy AC-01 literally but violate AC-03 (the 54 rows must be *re-evaluated and leave the unhealthy set* — they must still exist as rows tagged "known not-a-CLI", not vanish). Cost of the badge: the `assert summary["total"] == sum(...)` tripwire in `overview_view.py` and 4 render sites must all learn the new value. `health_status` is free-text `VARCHAR` (verified `.schema cli`), so **no DB migration** is needed — only code.

**Tech Stack:** Python 3.11+ stdlib `ast`, SQLModel/SQLite, pytest (hermetic on-disk CLIs, real interpreter — matches `bridge/test_capture_help.py`). Test command: `pytest bridge tests -v` (testpaths from `pyproject.toml`).

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `bridge/standalone.py` | Pure-`ast` classifier: `classify_standalone(path) -> "standalone"\|"subapp"\|"no_parser"`. No execution. | Create |
| `bridge/test_standalone.py` | Hermetic tests incl. the two AC ground-truth shapes. | Create |
| `bridge/audit_to_registry.py` | Call classifier in `audit_record_to_cli`; stamp `not_standalone`. | Modify |
| `bridge/test_audit_to_registry.py` | Round-trip a not-standalone record through the real loader. | Modify |
| `core/discovery/base.py` (`CliRecord`) | Carry `not_standalone: bool` field. | Modify |
| `core/discovery/cli_audit_source.py` | Read `not_standalone` from feed entry. | Modify |
| `core/models.py` (`Cli`) | `not_standalone` column; doc the 5th status. | Modify |
| `core/prober/prober.py` | Phase-1 routes `not_standalone` rows to preserved state. | Modify |
| `core/web/overview_view.py` | 5th badge in `_CANON_HEALTH`, glyph, summary, assert. | Modify |
| `core/tui/overview.py` | 5th badge style. | Modify |
| `scripts/reeval_not_standalone.py` | One-shot AC-03 re-eval of live DB rows. | Create |
| `~/projects/00_Governance/KNOWN_PATTERNS.md` | AC-04 entry. | Modify |

**Important discovery flow note:** `audit_to_registry.py` consumes a cli-audit JSON feed whose records carry `file` (absolute path) and `final_class`. The classifier reads that `file` path from disk. If a path no longer exists at feed-build time, the classifier must fail **open** (return `standalone`) so a missing file never silently suppresses a real CLI.

---

## Chunk 1: The AST classifier (AC-01, AC-02 core logic)

### Task 1: `classify_standalone` — the pure-ast detector

**Files:**
- Create: `bridge/standalone.py`
- Test: `bridge/test_standalone.py`

- [ ] **Step 1: Write the failing tests (the two AC ground-truth shapes + standalone control)**

```python
# bridge/test_standalone.py
"""Tests for the not-standalone AST classifier. Hermetic: writes tiny source
files and classifies them WITHOUT executing (ast only). Mirrors the two
US-CLIAUDIT-83 ground-truth shapes verified from real source:
  - subapp:    consigliere/cli/memory_commands.py (typer.Typer, no __main__)
  - no_parser: keto-data/scripts/categorize_ai.py (__main__, no parser)
"""
from __future__ import annotations

import textwrap

from bridge.standalone import classify_standalone


def _w(p, src):
    p.write_text(textwrap.dedent(src), encoding="utf-8")
    return str(p)


def test_subapp_typer_no_main(tmp_path):
    """AC-01: module-level typer.Typer(...) with NO if __name__ -> subapp."""
    f = _w(tmp_path / "memory_commands.py", """
        import typer
        app = typer.Typer(name="memory", help="Entity memory")

        @app.command()
        def show(entity_id: int):
            ...
    """)
    assert classify_standalone(f) == "subapp"


def test_subapp_click_group_no_main(tmp_path):
    """click.Group() / @click.group() sub-app with no __main__ -> subapp."""
    f = _w(tmp_path / "grp.py", """
        import click

        @click.group()
        def cli():
            ...
    """)
    assert classify_standalone(f) == "subapp"


def test_no_parser_main_batch_script(tmp_path):
    """AC-02: if __name__ guard present but NO parser anywhere -> no_parser."""
    f = _w(tmp_path / "categorize_ai.py", """
        def run():
            print("categorizing...")

        if __name__ == "__main__":
            run()
    """)
    assert classify_standalone(f) == "no_parser"


def test_standalone_argparse_with_main(tmp_path):
    """Control: __main__ guard + argparse -> standalone (NOT flagged)."""
    f = _w(tmp_path / "tool.py", """
        import argparse

        def main():
            p = argparse.ArgumentParser()
            p.parse_args()

        if __name__ == "__main__":
            main()
    """)
    assert classify_standalone(f) == "standalone"


def test_standalone_typer_with_main(tmp_path):
    """A Typer app that DOES guard __main__ is a real entrypoint -> standalone.
    This is the line that separates a mounted sub-app from a runnable app."""
    f = _w(tmp_path / "app.py", """
        import typer
        app = typer.Typer()

        @app.command()
        def go(): ...

        if __name__ == "__main__":
            app()
    """)
    assert classify_standalone(f) == "standalone"


def test_fire_counts_as_parser(tmp_path):
    """fire.Fire under __main__ is a real CLI -> standalone (not no_parser)."""
    f = _w(tmp_path / "f.py", """
        import fire

        def cmd(): ...

        if __name__ == "__main__":
            fire.Fire(cmd)
    """)
    assert classify_standalone(f) == "standalone"


def test_argparse_no_main_still_standalone(tmp_path):
    """argparse called at module top-level with no __main__ guard still parses
    args when run as a file -> standalone (the US-77 if-__name__-AND-argparse
    filter already handled the inverse; we must not regress it)."""
    f = _w(tmp_path / "topparse.py", """
        import argparse
        p = argparse.ArgumentParser()
        p.parse_args()
    """)
    assert classify_standalone(f) == "standalone"


def test_missing_file_fails_open(tmp_path):
    """A path that does not exist must NOT be suppressed -> standalone."""
    assert classify_standalone(str(tmp_path / "gone.py")) == "standalone"


def test_syntax_error_fails_open(tmp_path):
    """Unparseable source fails open (don't suppress a possibly-real CLI)."""
    f = _w(tmp_path / "broken.py", "def (:\n")
    assert classify_standalone(f) == "standalone"


def test_non_python_fails_open(tmp_path):
    """A .sh/.go path isn't ast-parseable Python -> standalone (out of scope)."""
    f = _w(tmp_path / "x.sh", "echo hi\n")
    assert classify_standalone(f) == "standalone"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/a2a-cli-registry && pytest bridge/test_standalone.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bridge.standalone'`

- [ ] **Step 3: Write the classifier**

```python
# bridge/standalone.py
"""Static (ast-only) detector for the two "not a standalone CLI" classes that
US-CLIAUDIT-83 (continuation of US-CLIAUDIT-77) targets:

  - "subapp":    a module-level Typer/click app object (typer.Typer(...),
                 click.Group()/@click.group()/@click.command at module level)
                 with NO `if __name__ == "__main__"` guard. These are mounted
                 into a parent CLI via add_typer / add_command and are never run
                 directly — probing them as files yields a non-zero --help exit
                 that the audit mislabels "code-bug".
  - "no_parser": a script WITH an `if __name__ == "__main__"` guard but NO
                 argument parser anywhere (argparse / click / typer / fire).
                 A batch script, not a CLI surface.

Everything else -> "standalone".

Why ast, not execution: these are arbitrary third-party files across the whole
fleet. We must classify WITHOUT importing or running them. ast.parse executes
no module code.

Fail-open contract: any path we cannot read/parse (missing file, syntax error,
non-Python) returns "standalone" — we never suppress a possibly-real CLI on a
classification failure.
"""
from __future__ import annotations

import ast

# Names whose *call* constitutes "this file parses CLI args".
# Matched on the attribute/func name, so both `argparse.ArgumentParser(...)`
# and a bare `ArgumentParser(...)` import-aliased call are caught.
_PARSER_CALL_NAMES = {
    "ArgumentParser",   # argparse
    "Typer",            # typer.Typer
    "Group",            # click.Group
    "group",            # click.group decorator
    "command",          # click.command / typer.command decorator
    "Fire",             # fire.Fire
    "OptionParser",     # optparse (legacy)
}

# Subset that, when bound at MODULE LEVEL, marks a mountable sub-app object.
_SUBAPP_CTOR_NAMES = {"Typer", "Group"}
_SUBAPP_DECORATOR_NAMES = {"group", "command"}


def _call_name(node: ast.AST) -> str | None:
    """Return the simple callee name of a Call node (last attribute segment),
    or None. `typer.Typer()` -> 'Typer'; `Fire()` -> 'Fire'."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _decorator_name(dec: ast.AST) -> str | None:
    """'@click.group()' -> 'group'; '@app.command' -> 'command'."""
    target = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return None


def _has_main_guard(tree: ast.Module) -> bool:
    """True if the module has a top-level `if __name__ == "__main__":`."""
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare):
            continue
        left = test.left
        if isinstance(left, ast.Name) and left.id == "__name__":
            for comp in test.comparators:
                if isinstance(comp, ast.Constant) and comp.value == "__main__":
                    return True
    return False


def _has_parser_call(tree: ast.Module) -> bool:
    """True if ANY parser-constructing call or click/typer decorator appears
    anywhere in the module (argparse/click/typer/fire/optparse)."""
    for node in ast.walk(tree):
        name = _call_name(node)
        if name in _PARSER_CALL_NAMES:
            return True
        # decorators: @click.group(), @app.command(), @cli.command
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if _decorator_name(dec) in (_SUBAPP_DECORATOR_NAMES | {"command"}):
                    return True
    return False


def _module_level_subapp(tree: ast.Module) -> bool:
    """True if a Typer()/click.Group() object is constructed at MODULE LEVEL,
    or a module-level function carries an @click.group()/@click.command() (or
    typer @app.command) decorator. These are the mountable sub-app shapes."""
    for node in tree.body:
        # `app = typer.Typer(...)` / `cli = click.Group(...)`
        if isinstance(node, ast.Assign) and _call_name(node.value) in _SUBAPP_CTOR_NAMES:
            return True
        # top-level `@click.group()` / `@click.command()` decorated def
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if _decorator_name(dec) in _SUBAPP_DECORATOR_NAMES:
                    return True
    return False


def classify_standalone(path: str) -> str:
    """Classify a Python file as 'standalone' | 'subapp' | 'no_parser'.

    Fail-open: returns 'standalone' on any read/parse failure or non-.py path.
    """
    if not path.endswith(".py"):
        return "standalone"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
    except (OSError, SyntaxError, ValueError):
        return "standalone"

    has_main = _has_main_guard(tree)

    # A real entrypoint guards __main__. If it does, it's standalone regardless
    # of whether it also defines a Typer app (a runnable app, not a mounted one).
    if has_main:
        # __main__ present: it's a standalone IF it has a parser; else batch.
        return "standalone" if _has_parser_call(tree) else "no_parser"

    # No __main__ guard. A module-level Typer/click app object is a mounted
    # sub-app (the dominant false-positive class).
    if _module_level_subapp(tree):
        return "subapp"

    # No __main__, no sub-app object: e.g. argparse at module top-level (runs on
    # file execution) — treat as standalone, don't suppress.
    return "standalone"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/a2a-cli-registry && pytest bridge/test_standalone.py -v`
Expected: PASS (all 10 tests)

- [ ] **Step 5: Verify against the REAL ground-truth files (not just synthetic)**

Run:
```bash
cd ~/projects/a2a-cli-registry && python3 -c "
from bridge.standalone import classify_standalone
import glob, os
gt = {
  '/Users/jc-folder/projects/20_CONSIGLIERE/consigliere/cli/memory_commands.py': 'subapp',
  '/Users/jc-folder/projects/50_KETO/keto-data/scripts/categorize_ai.py': 'no_parser',
}
for p, exp in gt.items():
    got = classify_standalone(p) if os.path.exists(p) else 'MISSING'
    print(f'{\"OK \" if got==exp else \"XX \"}{got:12} (want {exp})  {p}')
"
```
Expected: both lines start `OK ` — `subapp` for memory_commands.py, `no_parser` for categorize_ai.py.
If a file is `MISSING`, note it but do not fail — the live re-eval (Task 7) handles absent paths.

- [ ] **Step 6: Commit**

```bash
git add bridge/standalone.py bridge/test_standalone.py
git commit -m "feat(US-CLIAUDIT-83): ast classifier for not-standalone CLIs (subapp / no_parser)

Pure-ast detection of the two false-positive classes from US-CLIAUDIT-77's
follow-up: module-level Typer/click sub-apps with no __main__ guard, and
__main__-guarded batch scripts with no parser. Fails open on unreadable paths.

Co-Authored-By: Claude Opus 4.7 (1M context)"
```

### Chunk 1 review
- AC-01 covered by `test_subapp_typer_no_main` + real `memory_commands.py` check.
- AC-02 covered by `test_no_parser_main_batch_script` + real `categorize_ai.py` check.
- Fail-open paths (missing/syntax/non-py) all tested — a classifier bug can't silently delete a real CLI.
- **Known limitation to log, not fix:** import-aliased parsers (`from argparse import ArgumentParser as AP; AP()`) match because we key on the call name `ArgumentParser`, but a fully-renamed `as AP` would be missed. Accepted: rare, and fail-direction is "treat as standalone" (safe — never suppresses). No action.

---

## Chunk 2: Plumb `not_standalone` through the feed → model → DB

### Task 2: `CliRecord` and feed source carry the flag

**Files:**
- Modify: `core/discovery/base.py` (CliRecord dataclass)
- Modify: `core/discovery/cli_audit_source.py:43-48`
- Test: extend `bridge/test_audit_to_registry.py`

- [ ] **Step 1: Read the two files to confirm exact field list / constructor**

Run: `sed -n '1,60p' core/discovery/base.py` and re-read `cli_audit_source.py` lines 43-48.
(`CliRecord` is constructed in `cli_audit_source.py`; the new field must be optional with default `False` so every existing construction site stays valid.)

- [ ] **Step 2: Write the failing test (feed entry with not_standalone round-trips)**

```python
# append to bridge/test_audit_to_registry.py
def test_not_standalone_flag_round_trips(tmp_path):
    """A feed entry tagged not_standalone survives the real CliAuditSource load."""
    import json
    from core.discovery.cli_audit_source import CliAuditSource

    feed = {
        "schema_version": 1,
        "run_id": "t",
        "clis": [
            {"slug": "memory_commands", "lang": "python",
             "path": "/x/consigliere/cli/memory_commands.py",
             "not_standalone": True},
        ],
    }
    p = tmp_path / "feed.json"
    p.write_text(json.dumps(feed), encoding="utf-8")
    records = CliAuditSource(str(p)).discover()
    assert records[0].not_standalone is True
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest bridge/test_audit_to_registry.py::test_not_standalone_flag_round_trips -v`
Expected: FAIL — `AttributeError: 'CliRecord' object has no attribute 'not_standalone'`

- [ ] **Step 4: Add the field to `CliRecord` and read it in the source**

In `core/discovery/base.py`, add to the `CliRecord` dataclass (with default so all
existing call sites stay valid):
```python
    not_standalone: bool = False
```

In `core/discovery/cli_audit_source.py`, inside the `records.append(CliRecord(...))`
call (after `source_class=...`), add:
```python
                not_standalone=bool(entry.get("not_standalone", False)),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest bridge/test_audit_to_registry.py::test_not_standalone_flag_round_trips -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/discovery/base.py core/discovery/cli_audit_source.py bridge/test_audit_to_registry.py
git commit -m "feat(US-CLIAUDIT-83): CliRecord carries not_standalone flag from feed

Co-Authored-By: Claude Opus 4.7 (1M context)"
```

### Task 3: Bridge stamps the flag at feed-build

**Files:**
- Modify: `bridge/audit_to_registry.py:62-82` (`audit_record_to_cli`)
- Test: extend `bridge/test_audit_to_registry.py`

- [ ] **Step 1: Write the failing test (a subapp record gets not_standalone:true in the feed)**

```python
# append to bridge/test_audit_to_registry.py
def test_subapp_record_flagged_not_standalone(tmp_path):
    """audit_record_to_cli stamps not_standalone:true for a real sub-app file."""
    import textwrap
    from bridge.audit_to_registry import audit_record_to_cli

    f = tmp_path / "sub_commands.py"
    f.write_text(textwrap.dedent("""
        import typer
        app = typer.Typer(name="sub")
        @app.command()
        def go(): ...
    """), encoding="utf-8")

    rec = {"final_class": "PASS", "file": str(f), "project": "p"}
    entry = audit_record_to_cli(rec)
    assert entry is not None
    assert entry.get("not_standalone") is True


def test_real_cli_not_flagged(tmp_path):
    """A standalone argparse CLI is NOT flagged."""
    import textwrap
    from bridge.audit_to_registry import audit_record_to_cli

    f = tmp_path / "real.py"
    f.write_text(textwrap.dedent("""
        import argparse
        def main():
            argparse.ArgumentParser().parse_args()
        if __name__ == "__main__":
            main()
    """), encoding="utf-8")

    rec = {"final_class": "PASS", "file": str(f), "project": "p"}
    entry = audit_record_to_cli(rec)
    assert "not_standalone" not in entry or entry["not_standalone"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest bridge/test_audit_to_registry.py -k "subapp_record or real_cli_not" -v`
Expected: FAIL — `not_standalone` not present.

- [ ] **Step 3: Wire the classifier into `audit_record_to_cli`**

In `bridge/audit_to_registry.py`, add the import at top:
```python
from bridge.standalone import classify_standalone
```
Then in `audit_record_to_cli`, after `entry = {...}` and before the `cap` block, add:
```python
    cls = classify_standalone(file_path)
    if cls != "standalone":
        entry["not_standalone"] = True
```
(Only stamp the truthy case so existing golden feeds stay byte-identical for standalone CLIs — keeps `test_audit_to_registry.py`'s existing round-trip assertions green.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest bridge/test_audit_to_registry.py -v`
Expected: PASS (new + all pre-existing)

- [ ] **Step 5: Commit**

```bash
git add bridge/audit_to_registry.py bridge/test_audit_to_registry.py
git commit -m "feat(US-CLIAUDIT-83): stamp not_standalone at feed-build via ast classifier

Co-Authored-By: Claude Opus 4.7 (1M context)"
```

### Task 4: `Cli` model column

**Files:**
- Modify: `core/models.py` (Cli model — add column next to `health_status`)

- [ ] **Step 1: Read `core/models.py` Cli definition**

Run: `sed -n '1,60p' core/models.py`
Confirm whether `Cli` is the SQLModel table class and how `health_status` is declared (default `"unknown"`). The new column must default `False` so existing rows/inserts are valid without a migration (SQLite adds NULL-defaulted columns transparently for new code paths, but we default in-model to keep ORM inserts explicit).

- [ ] **Step 2: Add the column**

In `core/models.py`, in the `Cli` class, next to `health_status`, add:
```python
    not_standalone: bool = False        # US-CLIAUDIT-83: known not-a-standalone-CLI (sub-app or no-parser batch); never probed
```
And update the inline comment on `health_status` to list the 5th value:
```python
    health_status: str = "unknown"      # healthy/unhealthy/unknown/stale/not_standalone
```

- [ ] **Step 3: Verify the model imports and a fresh DB gets the column**

Run:
```bash
cd ~/projects/a2a-cli-registry && python3 -c "
from core.models import Cli
import inspect
assert 'not_standalone' in Cli.model_fields, Cli.model_fields.keys()
print('Cli.not_standalone field present:', Cli.model_fields['not_standalone'].default)
"
```
Expected: `Cli.not_standalone field present: False`

- [ ] **Step 4: Add the column to the LIVE DB (no destructive migration — additive ALTER)**

> The live DB `~/.hermes/cli-registry.db` predates this column. SQLModel won't
> add columns to an existing table. Add it once, idempotently. BACK UP FIRST.

Run:
```bash
cp ~/.hermes/cli-registry.db ~/.hermes/cli-registry.db.bak-$(/bin/date +%Y%m%d-%H%M%S)-pre-notstandalone-col
sqlite3 ~/.hermes/cli-registry.db "ALTER TABLE cli ADD COLUMN not_standalone BOOLEAN NOT NULL DEFAULT 0;" 2>&1 || echo "(column may already exist — ok)"
sqlite3 ~/.hermes/cli-registry.db "PRAGMA table_info(cli);" | grep not_standalone
```
Expected: a row naming `not_standalone` in the schema.

- [ ] **Step 5: Commit**

```bash
git add core/models.py
git commit -m "feat(US-CLIAUDIT-83): Cli.not_standalone column (additive, no migration)

Co-Authored-By: Claude Opus 4.7 (1M context)"
```

### Chunk 2 review
- Flag now flows feed → CliRecord → Cli model → DB column. AC-01/AC-02 detection is wired to persistence.
- `not_standalone` is independent of `health_status` so the prober logic in Chunk 3 can key on the boolean, not parse the status string.
- No migration framework exists here (verified: no alembic) — the additive ALTER + in-model default is the matching idiom. Backup taken before touching the live DB.

---

## Chunk 3: Durability — prober preserves the badge, UI shows it (AC-03)

### Task 5: Prober Phase-1 routes not_standalone rows to a preserved state

**Files:**
- Modify: `core/prober/prober.py:159-216`
- Test: extend the prober's test file (locate: `ls core/prober/test_*.py tests/**/test_prober*.py`)

- [ ] **Step 1: Locate and read the prober test**

Run: `ls core/prober/test_*.py tests/ -R 2>/dev/null | grep -i prob`
Read the existing prober test to match its session/clock fixtures (it uses an in-memory or temp SQLite session + a fake clock — reuse those, do not invent new fixtures).

- [ ] **Step 2: Write the failing test (a not_standalone CLI keeps its status across a probe run)**

```python
# in the prober test file, matching its existing fixture style:
def test_not_standalone_rows_are_preserved_not_probed(session, clock, adapters):
    """A row with not_standalone=True must end the probe run with
    health_status='not_standalone' and must NOT be probed (no adapter call)."""
    from core.models import Cli
    from core.prober.prober import probe_fleet   # use the real entrypoint name

    cli = Cli(slug="memory_commands", lang="python", launch_spec="x",
              description="", health_status="unhealthy", enabled=True,
              a2a_invokable=False, not_standalone=True)
    session.add(cli); session.commit()

    counts = probe_fleet(session, adapters, clock=clock)   # match real signature

    refreshed = session.get(Cli, "memory_commands")
    assert refreshed.health_status == "not_standalone"
    assert counts.get("not_standalone", 0) == 1
```
> Adjust `probe_fleet`/arg names to the real function (read in Step 1). The
> assertion semantics are the contract; the call shape follows the codebase.

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest <prober_test_path> -k not_standalone -v`
Expected: FAIL — status overwritten to unhealthy/unknown, no `not_standalone` count.

- [ ] **Step 4: Add the partition branch in Phase 1 and a write branch**

In `core/prober/prober.py`, in the Phase-1 loop (around line 163, the
`for cli in clis:` that fills `to_probe`/`no_cmd`), add a FIRST check before the
adapter lookup:
```python
    not_standalone_rows: list[Cli] = []
    for cli in clis:
        if getattr(cli, "not_standalone", False):
            not_standalone_rows.append(cli)
            continue
        try:
            adapter, rec = _find_adapter(cli, adapters)
            ...
```
Add `"not_standalone": 0` to the `counts` dict initialiser (line ~194).
After the `no_cmd` write loop (after line 213), add:
```python
    for cli in not_standalone_rows:
        cli.health_status = "not_standalone"
        cli.health_checked_at = now
        session.add(cli)
        counts["not_standalone"] += 1
```

- [ ] **Step 5: Run test to verify it passes; run the whole prober suite**

Run: `pytest <prober_test_path> -v`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add core/prober/prober.py <prober_test_path>
git commit -m "feat(US-CLIAUDIT-83): prober preserves not_standalone rows (skip + tag), survives re-probe

Co-Authored-By: Claude Opus 4.7 (1M context)"
```

### Task 6: 5th badge in the web + tui render/count sites

**Files:**
- Modify: `core/web/overview_view.py:6-18,48-89`
- Modify: `core/tui/overview.py:5-19`
- Test: extend `core/web` test (locate: `grep -rl build_overview_model --include=test_*.py`)

- [ ] **Step 1: Write the failing test (summary counts a not_standalone row and assert holds)**

```python
# in the overview_view test file:
def test_not_standalone_counted_and_badged():
    from core.web.overview_view import build_overview_model
    rows = {"clis": [
        {"slug": "a", "health_status": "healthy"},
        {"slug": "b", "health_status": "not_standalone"},
    ], "caps_by_slug": {}, "edges": []}
    model = build_overview_model(rows)
    assert model["summary"]["not_standalone"] == 1
    assert model["summary"]["total"] == 2   # the internal assert must not trip
    card_b = next(c for bucket in model["buckets"] for c in bucket["clis"] if c["slug"] == "b")
    assert card_b["health_status"] == "not_standalone"
    assert card_b["health_glyph"]   # a glyph exists for it
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest <overview_test_path> -k not_standalone -v`
Expected: FAIL — `not_standalone` collapses to `unknown` via `_norm_health`; the
`assert summary["total"] == healthy+unhealthy+stale+unknown` trips or the count lands in `unknown`.

- [ ] **Step 3: Add the 5th badge to `overview_view.py`**

```python
_CANON_HEALTH = {"healthy", "unhealthy", "stale", "unknown", "not_standalone"}
_HEALTH_GLYPHS = {
    "healthy": "●",
    "unhealthy": "▲",
    "stale": "◆",
    "unknown": "○",
    "not_standalone": "◌",   # dotted circle: present-but-not-a-CLI
}
```
In `build_overview_model`, add `"not_standalone": 0,` to the `summary` dict (next to `"unknown": 0`).
Update the tripwire assert to include the new term:
```python
    assert summary["total"] == (
        summary["healthy"] + summary["unhealthy"] + summary["stale"]
        + summary["unknown"] + summary["not_standalone"]
    )
```

- [ ] **Step 4: Add the tui style**

In `core/tui/overview.py`, extend `_HEALTH_STYLE`:
```python
_HEALTH_STYLE = {"healthy": "green", "unhealthy": "red",
                 "stale": "yellow", "unknown": "dim", "not_standalone": "dim cyan"}
```

- [ ] **Step 5: Run tests to verify pass; run full web+tui tests**

Run: `pytest core -k overview -v` (or the located paths)
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/web/overview_view.py core/tui/overview.py <overview_test_path>
git commit -m "feat(US-CLIAUDIT-83): 5th health badge not_standalone in web + tui render/count

Co-Authored-By: Claude Opus 4.7 (1M context)"
```

### Chunk 3 review
- The badge now survives re-probing (prober preserves) AND renders/counts correctly (UI + assert).
- The `assert summary["total"] == sum(...)` is the self-verifying tripwire: if any of the 5 categories is mishandled, the page 500s in dev — caught immediately.
- AC-03's "leave the unhealthy set" is satisfied: detected rows become `not_standalone`, not `unhealthy`, with no pip install and no code change to the target CLI.

---

## Chunk 4: Live re-evaluation (AC-03) + KNOWN_PATTERNS (AC-04)

### Task 7: One-shot re-eval of the live DB rows

**Files:**
- Create: `scripts/reeval_not_standalone.py`

> AC-03: "The 54 currently-affected registry rows are re-evaluated; not-standalone
> ones leave the unhealthy set without a pip install or code change." The 46
> interim-flipped rows are `unknown`; the remaining affected rows are still
> `unhealthy`. This script classifies every row's `path` and sets the durable flag.

- [ ] **Step 1: Write the script (dry-run by default, --apply to write)**

```python
# scripts/reeval_not_standalone.py
"""US-CLIAUDIT-83 AC-03: re-evaluate every registry row's source file with the
ast classifier and set not_standalone + health_status='not_standalone' for the
two false-positive classes. Dry-run unless --apply. Backs up the DB on --apply.

NO pip install, NO edit to any target CLI — pure reclassification.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3

from bridge.standalone import classify_standalone

DB = os.path.expanduser("~/.hermes/cli-registry.db")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT slug, path, health_status FROM cli WHERE enabled = 1").fetchall()

    to_flag = []
    for r in rows:
        path = r["path"]
        if not path:
            continue
        cls = classify_standalone(path)
        if cls != "standalone":
            to_flag.append((r["slug"], cls, r["health_status"]))

    print(f"{len(to_flag)} rows classify as not-standalone "
          f"(of {len(rows)} enabled):")
    by_class = {}
    for slug, cls, old in to_flag:
        by_class.setdefault(cls, 0)
        by_class[cls] += 1
    for cls, n in sorted(by_class.items()):
        print(f"  {cls}: {n}")

    if not args.apply:
        print("\nDRY RUN — re-run with --apply to write. Sample:")
        for slug, cls, old in to_flag[:15]:
            print(f"  {slug:40} {old:12} -> not_standalone ({cls})")
        return 0

    bak = f"{args.db}.bak-pre-reeval-notstandalone"
    shutil.copy2(args.db, bak)
    print(f"backed up -> {bak}")
    cur = con.cursor()
    for slug, cls, _old in to_flag:
        cur.execute(
            "UPDATE cli SET not_standalone = 1, health_status = 'not_standalone' WHERE slug = ?",
            (slug,),
        )
    con.commit()
    print(f"updated {len(to_flag)} rows.")
    # report the new distribution
    for hs, n in con.execute(
        "SELECT health_status, COUNT(*) FROM cli GROUP BY 1 ORDER BY 1"
    ):
        print(f"  {hs}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Dry-run against the live DB and eyeball the classes**

Run: `cd ~/projects/a2a-cli-registry && python3 scripts/reeval_not_standalone.py`
Expected: a count of subapp + no_parser rows (should land near the 46–54 range
the US cites) and a 15-row sample. **STOP and read the sample** — if a known-real
CLI appears in the list, the classifier has a false positive; fix the classifier
(Chunk 1), do NOT --apply.

- [ ] **Step 3: Apply (writes the live DB, after backup)**

Run: `cd ~/projects/a2a-cli-registry && python3 scripts/reeval_not_standalone.py --apply`
Expected: backup path printed; updated row count; new distribution showing a
`not_standalone` bucket and a reduced `unhealthy`/`unknown` count.

- [ ] **Step 4: Verify the UI reflects it**

Run:
```bash
sqlite3 ~/.hermes/cli-registry.db "SELECT health_status, COUNT(*) FROM cli GROUP BY 1 ORDER BY 1;"
curl -s localhost:9113/overview >/dev/null && echo "overview served OK"
```
Expected: a `not_standalone|N` row; overview endpoint still 200s (the assert held).

- [ ] **Step 5: Commit the script (DB is not git-tracked)**

```bash
git add scripts/reeval_not_standalone.py
git commit -m "feat(US-CLIAUDIT-83): live re-eval script — flag not_standalone rows (AC-03)

Co-Authored-By: Claude Opus 4.7 (1M context)"
```

### Task 8: KNOWN_PATTERNS entry (AC-04)

**Files:**
- Modify: `~/projects/00_Governance/KNOWN_PATTERNS.md`

- [ ] **Step 1: Append the pattern entry**

Add an entry tying this to US-CLIAUDIT-77 and the Hermes over-assignment:
```markdown
### KP-XXXX: A non-zero `--help` exit is not a code bug — classify not-standalone statically

**Context:** US-CLIAUDIT-83 (continuation of closed US-CLIAUDIT-77). The a2a-cli-registry
audit probed every discovered file with `--help` and filed a non-zero exit as a
broken CLI. Hermes LLM triage then over-assigned "code-bug" to 54 of these.

**Pattern:** Two large classes are *not broken CLIs*, determinable statically by AST
(no execution): (a) Typer/click sub-apps — module-level `typer.Typer()`/`click.Group()`
with **no** `if __name__` guard, mounted into a parent via `add_typer`; (b) `__main__`-guarded
batch scripts with **no** argument parser. Detect with `bridge/standalone.py::classify_standalone`
BEFORE probing; tag as the 5th health badge `not_standalone` rather than `unhealthy`.

**Rule:** Never infer "broken" from a `--help` exit code alone. A `--help` non-zero is
"wrong probe for this surface", not "code bug". Continuation of the US-77
`if-__name__-AND-argparse` filter.
```
(Use the next KP-id in sequence; check the file's current max KP number first.)

- [ ] **Step 2: Commit (governance repo)**

```bash
cd ~/projects/00_Governance
git add KNOWN_PATTERNS.md
git commit -m "docs(US-CLIAUDIT-83): KP — non-zero --help exit is not a code bug (AC-04)

Co-Authored-By: Claude Opus 4.7 (1M context)"
```

### Chunk 4 review
- AC-03 satisfied by the re-eval script (reclassify-only, no pip/code change, backed up, dry-run-first).
- AC-04 satisfied by the KP entry tying to US-77 + the Hermes over-assignment.
- The dry-run-first gate on Task 7 Step 2 is the safety valve against a classifier false positive nuking a real CLI's status — same "high-precision over high-recall for status mutations" discipline the prior session locked in.

---

## Final verification (all ACs)

- [ ] Run the full suite: `cd ~/projects/a2a-cli-registry && pytest bridge tests core -v` — expect green (the prior baseline was 83 tests passing; new tests add to that).
- [ ] AC-01: `classify_standalone('.../consigliere/cli/memory_commands.py') == 'subapp'` and that slug is NOT inventoried as standalone (carries not_standalone).
- [ ] AC-02: `classify_standalone('.../keto-data/scripts/categorize_ai.py') == 'no_parser'` and the row is tagged.
- [ ] AC-03: live DB shows a `not_standalone` bucket; affected rows left `unhealthy`/`unknown` with zero pip installs and zero edits to target CLIs (the re-eval script only UPDATEs status).
- [ ] AC-04: KNOWN_PATTERNS.md has the KP entry referencing US-CLIAUDIT-77 + the Hermes code-bug over-assignment.
- [ ] Move US-CLIAUDIT-83 to Done in `~/projects/00_Governance/BACKLOG.md` with the ACs checked.
- [ ] Merge feature branch → master, push both (per session-close git ops).

## Rollback
- Live DB: restore from `~/.hermes/cli-registry.db.bak-*-pre-notstandalone-col` (col add) or `.bak-pre-reeval-notstandalone` (the flip). The column is additive — leaving it on a restored older DB is harmless.
- Code: the badge is purely additive; reverting the commits removes the 5th category without affecting the existing 4.

## Open risks (named, not hidden)
1. **Classifier recall vs precision.** The plan optimizes precision (fail-open). It will MISS some not-standalone files (e.g. parser imported under an exotic alias). That's the correct direction — a miss leaves a CLI as `unhealthy` (status quo), a false positive would hide a real CLI. The dry-run gate (Task 7) catches egregious false positives before they hit the live DB.
2. **`final_class` gating interaction.** `audit_record_to_cli` only emits entries whose `final_class` ∈ `_USABLE_FINAL_CLASSES`. A not-standalone file that the audit already dropped as BUG never reaches the classifier. Acceptable for v1 — the 54 cited rows are ones that DID get inventoried. If coverage gaps appear, widening the gate is a separate change.
3. **No alembic.** The additive ALTER is manual and must be run once against the live DB (Task 4 Step 4). A fresh DB created by SQLModel gets the column automatically from the model. The script and prober use `getattr(cli, "not_standalone", False)` defensively so a pre-ALTER DB won't crash them.
