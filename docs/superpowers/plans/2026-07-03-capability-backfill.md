# Registry Capability Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `capability.input_types`/`output_types`/`intent_tags`/`side_effect` for the 471 Python-resolvable CLIs in `registry.db`, regenerate `cli.description` for all 474 rows (all are currently corrupted — path strings or traceback text), and run an LLM sanity-check pass so the final catalog is genuinely human-readable and typed, not just non-empty.

**Architecture:** Five new pure/read-only modules under a new `tools/` directory (offline batch tooling, kept out of the `core/` serving path), composed by one guarded writer CLI. Pipeline order: description regeneration → capability extraction (static AST, argparse/click/Typer) → LLM fallback for partial/failed extractions → sanity check over the full proposed dataset → guarded write (backup, dry-run default, `--commit` gate).

**Tech Stack:** Python 3.11+, stdlib `ast` for source parsing, stdlib `sqlite3` for all DB access (never SQLModel/ORM — see Global Constraints), stdlib `urllib.request` for LLM calls (mirrors `bridge/llm_infer.py`, no new dependency), `pytest` for tests.

## Global Constraints

- **All 5 new modules MUST use raw `sqlite3`, never SQLModel/ORM reads of `Cli`.** The live `registry.db`'s `cli` table has no `not_standalone` column (present in `core/models.py:17`, never migrated); any `select(Cli)` raises `OperationalError: no such column: cli.not_standalone`. Read via explicit column lists (`SELECT slug, path, description FROM cli`), never `SELECT *` through the ORM.
- **CSV, not JSON, for `input_types`/`output_types`/`intent_tags`.** `core/models.py:29-31` defaults these to `""`; `core/playbooks/signature.py:17-18` splits on `,` and filters empties (`t for t in s.split(",") if t`, no spaces). The writer must emit this exact format.
- **`confidence` vocabulary:** `declared`/`inferred` (`core/models.py:32`, `core/capability/model.py`). All backfilled rows are `inferred`, never `declared`.
- **`side_effect` vocabulary:** `none`/`writes-fs`/`network`/`destructive`/`unknown` (`core/models.py:30`).
- **`side_effect` semantics for `writes-fs` must match `bridge/llm_infer.py`'s existing prompt (lines 56-67 of that file's `_SYSTEM` string):** `writes-fs` ONLY for tools that modify an input file **in place** (formatters, in-place sorters) — NOT tools that merely produce a new output file (a CSV→JSON converter is `none`). This matters because `core/planner/search.py:46-70` (`_hop_excluded`) prunes chains on inferred non-`none` side effects by default — over-tagging `writes-fs` would wrongly hide converters from chain search.
- **LLM calls target the existing local router, not literal Ollama** (confirmed with user 2026-07-03): `POST http://localhost:9111/v1/chat/completions`, model `deepseek-v4-flash`, `urllib.request` — mirror `bridge/llm_infer.py:31-33` (`ROUTER_URL`, `ROUTER_MODEL`, `ROUTER_KEY`) and its `_call_router`/`_extract_json` pattern (`bridge/llm_infer.py:215-242`) exactly. No new package.
- **Guarded `ALTER TABLE` pattern:** mirror `core/store/migrations.py`'s `_table_exists`/`_column_exists`/`ensure_fixed_by_column` (lines 10-39) exactly — check-then-ALTER, catch `sqlite3.OperationalError`, swallow only `"duplicate column"` (case-insensitive substring match), re-raise anything else. This closes the TOCTOU race where a concurrent caller adds the column between your check and your ALTER.
- **Atomic writes:** DB backup via tempfile + `Path.replace` (per user's global atomic-write rule), never a plain `shutil.copy` that could leave a half-written backup.
- **No bare `except Exception`.** Catch specific exceptions (`sqlite3.OperationalError`, `json.JSONDecodeError`, `urllib.error.URLError`, `OSError`, `TimeoutError`) per `bridge/llm_infer.py`'s existing style.
- **Commit-guard:** this repo blocks bare `git commit` — use `git commit -m "..." -- <paths>` (explicit pathspec) per every commit step below.
- **Test venv:** `.venv/bin/python -m pytest`.
- **Fallback cap:** if more than ~30 CLIs (out of 471) need LLM fallback, the pipeline stops and reports — signals the static extractor needs tuning, not brute force.
- **Sanity threshold:** if more than ~10% of all 474 rows fail the sanity check, `--commit` refuses to proceed.

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/__init__.py` | Empty, makes `tools` an importable package. |
| `tools/description_regenerator.py` | Pure. `regenerate_description(slug, source) -> str`. AST-extracts docstring/parser-help/entrypoint-signature, calls local router for a 1-2 sentence description. Runs first — feeds `extract_intent_tags`. |
| `tools/capability_extractor.py` | Pure, read-only. `extract_inputs`, `extract_outputs`, `extract_intent_tags`, `infer_side_effect`, `extract_capability`. No DB, no LLM. argparse (incl. aliased import, subparsers) + click + Typer AST parsing. |
| `tools/capability_llm_fallback.py` | `infer_capability_llm(slug, description, extract) -> dict`. For CLIs static extraction can't fully resolve. Same shape as `extract_capability`, `provenance="llm"`. |
| `tools/sanity_check.py` | `check_row(slug, description, capability) -> dict`. Mechanical pre-filter (path/traceback pattern reject, no LLM call) then LLM coherence check. Runs last, over all 474 proposed rows. |
| `tools/backfill_capabilities.py` | CLI entrypoint. Backup, guarded `ALTER TABLE` for `provenance`/`description_provenance`, orchestrates the pipeline, `--dry-run` (default) / `--commit`, idempotent per-slug per-field writes. |
| `tests/test_description_regenerator.py` | Unit tests, router call monkeypatched. |
| `tests/test_capability_extractor.py` | Unit tests, no DB/LLM — the bulk of coverage. |
| `tests/test_capability_llm_fallback.py` | Unit tests, router call monkeypatched. |
| `tests/test_sanity_check.py` | Unit tests, router call monkeypatched. |
| `tests/test_backfill_capabilities.py` | Integration tests against a temp `sqlite3` DB built with `executescript` (mirrors live schema-drift, i.e. no `not_standalone` column). |

---

## Task 1: Capability extractor — argparse + name heuristics + side_effect + intent_tags

**Files:**
- Create: `tools/__init__.py` (empty)
- Create: `tools/capability_extractor.py`
- Test: `tests/test_capability_extractor.py`

**Interfaces:**
- Produces: `extract_inputs(source: str) -> list[str]`, `extract_outputs(source: str) -> list[str]`, `extract_intent_tags(slug: str, description: str, source: str) -> list[str]`, `infer_side_effect(source: str) -> str`, `extract_capability(slug: str, description: str, source: str) -> dict` with shape `{"input_types": list[str], "output_types": list[str], "intent_tags": list[str], "side_effect": str, "confidence": "inferred", "provenance": "static"}`.
- Consumes: nothing from other tasks (pure, first task).

- [ ] **Step 1: Write failing tests for argparse type mapping, name heuristics, output inference, intent tags, and side_effect (network / in-place writes-fs / new-file none)**

```python
# tests/test_capability_extractor.py
import pytest
from tools.capability_extractor import (
    extract_inputs, extract_outputs, extract_intent_tags,
    infer_side_effect, extract_capability,
)


def test_argparse_type_path():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--in", type=Path)
'''
    assert "path" in extract_inputs(source)


def test_argparse_type_int():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--n", type=int)
'''
    assert "int" in extract_inputs(source)


def test_argparse_type_float():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--ratio", type=float)
'''
    assert "float" in extract_inputs(source)


def test_argparse_name_heuristic_untyped():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--input-file")
'''
    inputs = extract_inputs(source)
    assert "path" in inputs


def test_argparse_json_name_heuristic():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--json")
'''
    assert "json" in extract_inputs(source)


def test_argparse_untyped_no_heuristic_falls_back_to_str():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--verbose")
'''
    assert extract_inputs(source) == ["str"]


def test_argparse_import_alias():
    source = '''
import argparse as ap
p = ap.ArgumentParser()
p.add_argument("--in", type=Path)
'''
    assert "path" in extract_inputs(source)


def test_argparse_subparsers():
    source = '''
import argparse
p = argparse.ArgumentParser()
sub = p.add_subparsers()
build_p = sub.add_parser("build")
build_p.add_argument("--in", type=Path)
'''
    assert "path" in extract_inputs(source)


def test_output_file_write_text():
    source = '''
from pathlib import Path
Path("out.txt").write_text("hi")
'''
    assert "path" in extract_outputs(source)


def test_output_open_write_mode():
    source = '''
with open("out.csv", "w") as f:
    f.write("a,b")
'''
    assert "path" in extract_outputs(source)


def test_output_json_dump():
    source = '''
import json
with open("out.json", "w") as f:
    json.dump({"a": 1}, f)
'''
    outputs = extract_outputs(source)
    assert "path" in outputs
    assert "json" in outputs


def test_output_json_stdout():
    source = '''
import json
print(json.dumps({"a": 1}))
'''
    assert extract_outputs(source) == ["json"]


def test_output_bare_print_text():
    source = '''
print("hello world")
'''
    assert extract_outputs(source) == ["text"]


def test_output_empty_source():
    assert extract_outputs("") == []


def test_intent_tags_vocab_constrained():
    tags = extract_intent_tags("svg-export", "publish SVGs to Etsy", "")
    assert "export" in tags
    assert "publish" in tags
    # a word not in the controlled vocab must never appear
    assert "etsy" not in tags


def test_intent_tags_no_signal_returns_empty():
    assert extract_intent_tags("xz", "", "") == []


def test_side_effect_network_wins():
    source = '''
import httpx
def main():
    httpx.get("https://example.com")
    with open("cache.json", "w") as f:
        f.write("{}")
'''
    assert infer_side_effect(source) == "network"


def test_side_effect_writes_fs_in_place():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--file", type=Path)
args = p.parse_args()
with open(args.file, "w") as f:
    f.write("formatted")
'''
    assert infer_side_effect(source) == "writes-fs"


def test_side_effect_new_output_file_is_none():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--in", type=Path)
p.add_argument("--out", type=Path)
args = p.parse_args()
with open(args.out, "w") as f:
    f.write("converted")
'''
    assert infer_side_effect(source) == "none"


def test_side_effect_none_when_neither():
    source = '''
def add(a, b):
    return a + b
'''
    assert infer_side_effect(source) == "none"


def test_extract_capability_partial_input_only_flags_incomplete():
    # input detected, output empty -> extract_capability itself still reports
    # empty output_types; routing to fallback is backfill_capabilities' job,
    # not the extractor's -- the extractor just reports honestly.
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--in", type=Path)
'''
    cap = extract_capability("myclitool", "reads a file", source)
    assert cap["input_types"] == ["path"]
    assert cap["output_types"] == []
    assert cap["confidence"] == "inferred"
    assert cap["provenance"] == "static"


def test_extract_capability_empty_source_all_empty():
    cap = extract_capability("myclitool", "", "")
    assert cap["input_types"] == []
    assert cap["output_types"] == []
    assert cap["intent_tags"] == []
    assert cap["side_effect"] == "none"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_capability_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.capability_extractor'` (or `tools`).

- [ ] **Step 3: Create `tools/__init__.py`**

Empty file.

- [ ] **Step 4: Implement `tools/capability_extractor.py` (argparse + name heuristics + outputs + intent_tags + side_effect + compose, NO Typer/click/subparsers yet — those land in Task 2)**

```python
"""Static AST-based capability extraction for one CLI's source.

Pure functions: no DB access, no network calls, no imports of core.models.Cli.
Feeds capability.input_types/output_types/intent_tags/side_effect for the
registry capability backfill.
"""
from __future__ import annotations

import ast

_TYPE_MAP = {
    "Path": "path",
    "int": "int",
    "float": "float",
    "str": "str",
}

_NAME_HEURISTICS = {
    "input": "path",
    "file": "path",
    "in-dir": "path",
    "in_dir": "path",
    "path": "path",
    "json": "json",
}

_INTENT_VOCAB = [
    "build", "extract", "package", "publish", "download", "convert",
    "analyze", "export", "sync", "validate", "generate", "transform",
]

_NETWORK_MODULES = {"httpx", "requests", "urllib", "socket", "aiohttp"}

_FS_WRITE_CALLS = {"write_text", "write", "dump"}


def _arg_name_to_key(arg_name: str) -> str | None:
    """'--input-file' -> 'input-file' -> matches '--input-file' or 'file' etc."""
    key = arg_name.lstrip("-")
    for needle, mapped in _NAME_HEURISTICS.items():
        if needle in key.replace("_", "-"):
            return mapped
    return None


def _resolve_type_arg(node: ast.Call) -> str | None:
    for kw in node.keywords:
        if kw.arg == "type":
            if isinstance(kw.value, ast.Name) and kw.value.id in _TYPE_MAP:
                return _TYPE_MAP[kw.value.id]
    return None


def _first_str_arg(node: ast.Call) -> str | None:
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def _walk_add_argument_calls(tree: ast.AST):
    """Yield every add_argument(...) Call node, including calls on subparser
    objects returned by add_subparsers().add_parser(...)."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            yield node


def extract_inputs(source: str) -> list[str]:
    if not source.strip():
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    found: list[str] = []
    has_any_arg = False
    for node in _walk_add_argument_calls(tree):
        has_any_arg = True
        arg_name = _first_str_arg(node)
        typed = _resolve_type_arg(node)
        if typed:
            found.append(typed)
            continue
        if arg_name:
            heuristic = _arg_name_to_key(arg_name)
            if heuristic:
                found.append(heuristic)
                continue
        found.append("str")

    if not has_any_arg:
        return []
    # de-dup, preserve first-seen order
    seen = []
    for t in found:
        if t not in seen:
            seen.append(t)
    return seen


def extract_outputs(source: str) -> list[str]:
    if not source.strip():
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    outputs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "write_text":
                outputs.append("path")
            elif node.func.attr in ("copy", "move") and isinstance(node.func.value, ast.Name) and node.func.value.id == "shutil":
                outputs.append("path")
            elif node.func.attr == "replace" and isinstance(node.func.value, ast.Attribute):
                outputs.append("path")
            elif node.func.attr == "dump" and isinstance(node.func.value, ast.Name) and node.func.value.id == "json":
                outputs.append("json")
                outputs.append("path")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            for kw in list(node.keywords) + ([ast.keyword(arg=None, value=node.args[1])] if len(node.args) > 1 else []):
                mode = kw.value
                if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(m in mode.value for m in ("w", "a")):
                    outputs.append("path")

    is_json_stdout = False
    is_bare_print = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            if node.args and isinstance(node.args[0], ast.Call):
                inner = node.args[0]
                if isinstance(inner.func, ast.Attribute) and inner.func.attr == "dumps":
                    is_json_stdout = True
                    continue
            is_bare_print = True

    if is_json_stdout:
        outputs.append("json")
    elif is_bare_print and not outputs:
        outputs.append("text")

    seen = []
    for t in outputs:
        if t not in seen:
            seen.append(t)
    return seen


def extract_intent_tags(slug: str, description: str, source: str) -> list[str]:
    haystack = f"{slug} {description}".lower().replace("-", " ").replace("_", " ")
    return [tag for tag in _INTENT_VOCAB if tag in haystack]


def _writes_same_path_as_input(tree: ast.AST) -> bool:
    """True only if a variable that was assigned from an input-arg attribute
    (e.g. args.file) is later opened/written in a 'w'/'a' mode -- i.e. the
    same path read as input is reopened for writing (in-place modification).
    Conservative: only matches the args.<attr> -> open(args.<attr>, 'w') shape.
    """
    read_paths = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "args":
            read_paths.add(node.attr)

    if not read_paths:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            if not node.args:
                continue
            target = node.args[0]
            mode_ok = False
            for kw in list(node.keywords) + ([ast.keyword(arg=None, value=node.args[1])] if len(node.args) > 1 else []):
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str) and any(m in kw.value.value for m in ("w", "a")):
                    mode_ok = True
            if not mode_ok:
                continue
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "args":
                if target.attr in read_paths:
                    return True
    return False


def infer_side_effect(source: str) -> str:
    if not source.strip():
        return "none"
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "unknown"

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])

    if imported_modules & _NETWORK_MODULES:
        return "network"

    if _writes_same_path_as_input(tree):
        return "writes-fs"

    return "none"


def extract_capability(slug: str, description: str, source: str) -> dict:
    return {
        "input_types": extract_inputs(source),
        "output_types": extract_outputs(source),
        "intent_tags": extract_intent_tags(slug, description, source),
        "side_effect": infer_side_effect(source),
        "confidence": "inferred",
        "provenance": "static",
    }
```

- [ ] **Step 5: Run tests, iterate until all pass**

Run: `.venv/bin/python -m pytest tests/test_capability_extractor.py -v`
Expected: all tests PASS. Debug any AST-matching mismatches against the exact fixture source strings above — do not loosen assertions to fit the code; fix the code.

- [ ] **Step 6: Commit**

```bash
git add tools/__init__.py tools/capability_extractor.py tests/test_capability_extractor.py
git commit -m "feat: add static capability extractor (argparse + name heuristics + side_effect)" -- tools/__init__.py tools/capability_extractor.py tests/test_capability_extractor.py
```

---

## Task 2: Extend extractor — click, Typer, subparsers-in-outputs, partial-extraction routing signal

**Files:**
- Modify: `tools/capability_extractor.py`
- Test: `tests/test_capability_extractor.py`

**Interfaces:**
- Consumes: `_TYPE_MAP`, `extract_inputs` from Task 1 (extends the same function, does not replace its signature).
- Produces: `extract_inputs` now also handles click and Typer; `extract_capability` return dict gains no new keys but callers (Task 4/6) will route to fallback when `input_types == [] or output_types == []`.

- [ ] **Step 1: Write failing tests for click, Typer, Typer-only-no-fallback-routing-signal**

```python
# append to tests/test_capability_extractor.py

def test_click_option_path():
    source = '''
import click

@click.command()
@click.option("--out", type=click.Path())
def main(out):
    pass
'''
    assert "path" in extract_inputs(source)


def test_typer_command_path_param():
    source = '''
import typer
from pathlib import Path

app = typer.Typer()

@app.command()
def main(path: Path):
    pass
'''
    assert "path" in extract_inputs(source)


def test_typer_command_int_param():
    source = '''
import typer

app = typer.Typer()

@app.command()
def main(count: int):
    pass
'''
    assert "int" in extract_inputs(source)


def test_typer_option_default():
    source = '''
import typer

app = typer.Typer()

@app.command()
def main(name: str = typer.Option(...)):
    pass
'''
    assert "str" in extract_inputs(source)


def test_typer_only_no_argparse_click_signal_extractor_still_finds_parser():
    # Full Typer CLI with zero argparse/click markers -- this is the 72-CLI
    # Typer-only gap the spec calls out. Extractor must find inputs (not
    # empty), so backfill_capabilities does NOT route this to LLM fallback.
    source = '''
import typer
from pathlib import Path

app = typer.Typer()

@app.command()
def convert(input_file: Path, output_file: Path):
    """Convert input to output."""
    pass

if __name__ == "__main__":
    app()
'''
    inputs = extract_inputs(source)
    assert inputs, "Typer-only CLI must not extract to empty input_types"
    assert "path" in inputs
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv/bin/python -m pytest tests/test_capability_extractor.py -v -k "click or typer"`
Expected: FAIL — click/Typer params not yet detected (assertion errors, not import errors).

- [ ] **Step 3: Extend `extract_inputs` in `tools/capability_extractor.py` to handle click and Typer**

Replace the body of `extract_inputs` with a version that also walks click decorators and Typer function parameters:

```python
def _click_option_type(node: ast.Call) -> str | None:
    for kw in node.keywords:
        if kw.arg == "type" and isinstance(kw.value, ast.Call):
            if isinstance(kw.value.func, ast.Attribute) and kw.value.func.attr == "Path":
                return "path"
        if kw.arg == "type" and isinstance(kw.value, ast.Name) and kw.value.id in _TYPE_MAP:
            return _TYPE_MAP[kw.value.id]
    return None


def _annotation_to_type(annotation: ast.expr | None) -> str | None:
    if annotation is None:
        return None
    if isinstance(annotation, ast.Name) and annotation.id in _TYPE_MAP:
        return _TYPE_MAP[annotation.id]
    if isinstance(annotation, ast.Attribute) and annotation.attr in _TYPE_MAP:
        return _TYPE_MAP[annotation.attr]
    return None


def _is_typer_command_function(node: ast.FunctionDef) -> bool:
    for deco in node.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        if isinstance(target, ast.Attribute) and target.attr == "command":
            return True
    return False


def extract_inputs(source: str) -> list[str]:
    if not source.strip():
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    found: list[str] = []
    has_any_arg = False

    # argparse (incl. aliased import + subparsers, walked via ast.walk already
    # covers subparser add_argument calls since they're still Call/Attribute
    # nodes with .attr == "add_argument" anywhere in the tree)
    for node in _walk_add_argument_calls(tree):
        has_any_arg = True
        arg_name = _first_str_arg(node)
        typed = _resolve_type_arg(node)
        if typed:
            found.append(typed)
            continue
        if arg_name:
            heuristic = _arg_name_to_key(arg_name)
            if heuristic:
                found.append(heuristic)
                continue
        found.append("str")

    # click: @click.option(...) / @click.argument(...) decorators
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for deco in node.decorator_list:
                if not isinstance(deco, ast.Call):
                    continue
                target = deco.func
                if isinstance(target, ast.Attribute) and target.attr in ("option", "argument"):
                    has_any_arg = True
                    typed = _click_option_type(deco)
                    if typed:
                        found.append(typed)
                        continue
                    arg_name = _first_str_arg(deco)
                    heuristic = _arg_name_to_key(arg_name) if arg_name else None
                    found.append(heuristic or "str")

    # Typer: @app.command() function parameters, by annotation or typer.Option/Argument default
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and _is_typer_command_function(node):
            for arg in node.args.args:
                has_any_arg = True
                typed = _annotation_to_type(arg.annotation)
                found.append(typed or "str")

    if not has_any_arg:
        return []
    seen = []
    for t in found:
        if t not in seen:
            seen.append(t)
    return seen
```

Delete the old `extract_inputs` body (from Task 1) and the now-superseded `_arg_name_to_key`/`_resolve_type_arg`/`_first_str_arg`/`_walk_add_argument_calls` stay as-is (still used) — only `extract_inputs` itself is replaced, plus three new helpers (`_click_option_type`, `_annotation_to_type`, `_is_typer_command_function`) are added above it.

- [ ] **Step 4: Run tests, iterate until all pass (Task 1 + Task 2 tests together)**

Run: `.venv/bin/python -m pytest tests/test_capability_extractor.py -v`
Expected: all PASS, including the original Task 1 argparse tests (no regression) and the new click/Typer tests.

- [ ] **Step 5: Commit**

```bash
git add tools/capability_extractor.py tests/test_capability_extractor.py
git commit -m "feat: add click and Typer support to capability extractor" -- tools/capability_extractor.py tests/test_capability_extractor.py
```

---

## Task 3: Description regenerator

**Files:**
- Create: `tools/description_regenerator.py`
- Test: `tests/test_description_regenerator.py`

**Interfaces:**
- Consumes: nothing from other tasks (independent of the extractor; both read raw source).
- Produces: `regenerate_description(slug: str, source: str) -> str`, `provenance: str` is always `"llm"` for this module's output (never `"static"` — regeneration always goes through the router). Downstream: Task 4 (`extract_intent_tags`) consumes this function's return value as its `description` argument.

- [ ] **Step 1: Write failing tests, router call monkeypatched**

```python
# tests/test_description_regenerator.py
import pytest
import tools.description_regenerator as regen


def test_normal_source_produces_description(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {"description": "Converts CSV files to JSON."}
    monkeypatch.setattr(regen, "_call_router", fake_router)
    result = regen.regenerate_description("csv2json", "def main(): pass")
    assert result == "Converts CSV files to JSON."


def test_old_corrupted_description_never_passed_to_model(monkeypatch):
    captured = {}

    def fake_router(prompt, slug, timeout=30):
        captured["prompt"] = prompt
        return {"description": "does something"}

    monkeypatch.setattr(regen, "_call_router", fake_router)
    regen.regenerate_description("mytool", "def main(): pass")
    assert "ModuleNotFoundError" not in captured["prompt"]
    assert "30_SVG-PAINT" not in captured["prompt"]


def test_empty_source_returns_placeholder_never_crashes(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        raise AssertionError("router must not be called for empty source")
    monkeypatch.setattr(regen, "_call_router", fake_router)
    result = regen.regenerate_description("emptytool", "")
    assert result == "unknown purpose (emptytool)"


def test_unreadable_source_returns_placeholder(monkeypatch):
    result = regen.regenerate_description("badtool", None)
    assert result == "unknown purpose (badtool)"


def test_malformed_model_output_returns_placeholder_not_exception(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return None  # simulates network/JSON failure, same contract as bridge/llm_infer.py
    monkeypatch.setattr(regen, "_call_router", fake_router)
    result = regen.regenerate_description("flakytool", "def main(): pass")
    assert result == "unknown purpose (flakytool)"


def test_extract_context_pulls_docstring_and_signature():
    source = '''
"""Converts CSV files to JSON format."""
import argparse

def main(input_path, output_path):
    """Runs the conversion."""
    pass
'''
    context = regen._extract_context(source)
    assert "Converts CSV files to JSON format." in context
    assert "Runs the conversion." in context
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_description_regenerator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.description_regenerator'`.

- [ ] **Step 3: Implement `tools/description_regenerator.py`**

```python
"""Regenerate a 1-2 sentence purpose description for one CLI, via the local
router. Runs first in the backfill pipeline -- its output feeds
capability_extractor.extract_intent_tags, never the corrupted original
cli.description.
"""
from __future__ import annotations

import ast
import json
import urllib.error
import urllib.request

ROUTER_URL = "http://localhost:9111/v1/chat/completions"
ROUTER_MODEL = "deepseek-v4-flash"
ROUTER_KEY = "router-local"

_SYSTEM = (
    "You write a single 1-2 sentence description of what a command-line tool "
    "does, in plain language, based on its docstring, parser help text, and "
    "entrypoint signature. Return ONLY a compact JSON object with one key: "
    "description (string). Do not invent functionality not evidenced by the "
    "given context."
)


def _extract_context(source: str) -> str:
    """AST-extract module docstring + parser/command help strings + entrypoint
    function signature+docstring, plus the first ~20 lines as light context.
    NOT a fixed first-N-lines slice -- parser definitions land beyond line 60
    in ~50% of sampled files."""
    parts = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "\n".join(source.splitlines()[:20])

    module_doc = ast.get_docstring(tree)
    if module_doc:
        parts.append(module_doc)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("add_argument", "command", "ArgumentParser"):
                for kw in node.keywords:
                    if kw.arg in ("description", "help") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        parts.append(kw.value.value)
        if isinstance(node, ast.FunctionDef):
            fn_doc = ast.get_docstring(node)
            if fn_doc:
                parts.append(fn_doc)

    parts.append("\n".join(source.splitlines()[:20]))
    return "\n".join(parts)


def _call_router(prompt: str, slug: str, timeout: int = 30) -> dict | None:
    payload = {
        "model": ROUTER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Tool slug: {slug}\n\nContext:\n{prompt}"},
        ],
        "max_tokens": 150,
        "temperature": 0,
    }
    req = urllib.request.Request(
        ROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {ROUTER_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    try:
        content = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return None
    return _extract_json(content)


def _extract_json(content: str) -> dict | None:
    s = content.find("{")
    e = content.rfind("}")
    if s == -1 or e == -1 or e < s:
        return None
    try:
        return json.loads(content[s : e + 1])
    except json.JSONDecodeError:
        return None


def regenerate_description(slug: str, source: str | None) -> str:
    if not source or not source.strip():
        return f"unknown purpose ({slug})"

    context = _extract_context(source)
    result = _call_router(context, slug)
    if not result or "description" not in result or not isinstance(result["description"], str):
        return f"unknown purpose ({slug})"
    return result["description"].strip()
```

Note: `_call_router` here takes `(prompt, slug, ...)` — test 1 above calls `fake_router(prompt, slug, timeout=30)` matching this signature exactly, and `test_extract_context_pulls_docstring_and_signature` calls the module-private `_extract_context` directly.

- [ ] **Step 4: Run tests, iterate until all pass**

Run: `.venv/bin/python -m pytest tests/test_description_regenerator.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/description_regenerator.py tests/test_description_regenerator.py
git commit -m "feat: add LLM-backed description regenerator" -- tools/description_regenerator.py tests/test_description_regenerator.py
```

---

## Task 4: LLM fallback for capability extraction

**Files:**
- Create: `tools/capability_llm_fallback.py`
- Test: `tests/test_capability_llm_fallback.py`

**Interfaces:**
- Consumes: `tools.description_regenerator._extract_context` (Task 3, reused for the same targeted extract — not a fixed-prefix slice).
- Produces: `infer_capability_llm(slug: str, description: str, source: str) -> dict` — same shape as `capability_extractor.extract_capability`, but `provenance="llm"`.

- [ ] **Step 1: Write failing tests, router call monkeypatched**

```python
# tests/test_capability_llm_fallback.py
import pytest
import tools.capability_llm_fallback as fallback


def test_normal_response_parsed_into_shape(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {
            "input_types": ["path"],
            "output_types": ["json"],
            "intent_tags": ["convert"],
            "side_effect": "none",
        }
    monkeypatch.setattr(fallback, "_call_router", fake_router)
    result = fallback.infer_capability_llm("mytool", "converts files", "def main(): pass")
    assert result["input_types"] == ["path"]
    assert result["output_types"] == ["json"]
    assert result["intent_tags"] == ["convert"]
    assert result["side_effect"] == "none"
    assert result["provenance"] == "llm"
    assert result["confidence"] == "inferred"


def test_malformed_output_degrades_to_empties_no_crash(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return None
    monkeypatch.setattr(fallback, "_call_router", fake_router)
    result = fallback.infer_capability_llm("mytool", "", "")
    assert result["input_types"] == []
    assert result["output_types"] == []
    assert result["intent_tags"] == []
    assert result["side_effect"] == "unknown"
    assert result["provenance"] == "llm"


def test_partial_model_response_missing_keys_defaults_safely(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {"input_types": ["path"]}  # missing everything else
    monkeypatch.setattr(fallback, "_call_router", fake_router)
    result = fallback.infer_capability_llm("mytool", "desc", "src")
    assert result["input_types"] == ["path"]
    assert result["output_types"] == []
    assert result["intent_tags"] == []
    assert result["side_effect"] == "unknown"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_capability_llm_fallback.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `tools/capability_llm_fallback.py`**

```python
"""LLM fallback for CLIs the static extractor could not fully resolve (empty
input_types OR output_types). Local router only -- token-frugal, local-first.
Capped by backfill_capabilities.py at ~30 CLIs; a larger fallback set signals
the static extractor needs tuning, not brute LLM force.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from tools.description_regenerator import _extract_context

ROUTER_URL = "http://localhost:9111/v1/chat/completions"
ROUTER_MODEL = "deepseek-v4-flash"
ROUTER_KEY = "router-local"

_SIDE_EFFECTS = ["none", "writes-fs", "network", "destructive", "unknown"]

_SYSTEM = (
    "You infer a command-line tool's capability shape from its description "
    "and source context. Return ONLY a compact JSON object with keys: "
    "input_types (list of strings: path/int/float/str/json), "
    "output_types (list of strings: path/json/text), "
    "intent_tags (list of verb strings), "
    f"side_effect (one of: {', '.join(_SIDE_EFFECTS)}). "
    "side_effect='writes-fs' ONLY if the tool modifies an input file in "
    "place (formatters); a tool producing a NEW output file is 'none'. "
    "If genuinely unsure about any field, return an empty list (or "
    "'unknown' for side_effect) rather than guessing."
)


def _call_router(prompt: str, slug: str, timeout: int = 30) -> dict | None:
    payload = {
        "model": ROUTER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Tool slug: {slug}\n\nContext:\n{prompt}"},
        ],
        "max_tokens": 200,
        "temperature": 0,
    }
    req = urllib.request.Request(
        ROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {ROUTER_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    try:
        content = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return None
    return _extract_json(content)


def _extract_json(content: str) -> dict | None:
    s = content.find("{")
    e = content.rfind("}")
    if s == -1 or e == -1 or e < s:
        return None
    try:
        return json.loads(content[s : e + 1])
    except json.JSONDecodeError:
        return None


def infer_capability_llm(slug: str, description: str, source: str) -> dict:
    context = _extract_context(source) if source else description
    result = _call_router(context, slug) or {}
    return {
        "input_types": result.get("input_types") or [],
        "output_types": result.get("output_types") or [],
        "intent_tags": result.get("intent_tags") or [],
        "side_effect": result.get("side_effect") or "unknown",
        "confidence": "inferred",
        "provenance": "llm",
    }
```

- [ ] **Step 4: Run tests, iterate until all pass**

Run: `.venv/bin/python -m pytest tests/test_capability_llm_fallback.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/capability_llm_fallback.py tests/test_capability_llm_fallback.py
git commit -m "feat: add LLM fallback for partial capability extraction" -- tools/capability_llm_fallback.py tests/test_capability_llm_fallback.py
```

---

## Task 5: Sanity check

**Files:**
- Create: `tools/sanity_check.py`
- Test: `tests/test_sanity_check.py`

**Interfaces:**
- Consumes: nothing structurally from other tasks (operates on plain `description: str` + `capability: dict` shape matching `capability_extractor.extract_capability`'s return type).
- Produces: `check_row(slug: str, description: str, capability: dict) -> dict` with shape `{"ok": bool, "reason": str}`. `CALIBRATION_SET: list[dict]` — the ~10 hand-authored known-good/known-bad pairs, each `{"slug": str, "description": str, "capability": dict, "expected_ok": bool}`, consumed by Task 6's writer for the calibration gate.

- [ ] **Step 1: Write failing tests, router call monkeypatched**

```python
# tests/test_sanity_check.py
import pytest
import tools.sanity_check as sanity


def test_coherent_row_passes(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {"ok": True, "reason": "clear purpose"}
    monkeypatch.setattr(sanity, "_call_router", fake_router)
    result = sanity.check_row(
        "csv2json",
        "Converts CSV files to JSON format.",
        {"input_types": ["path"], "output_types": ["json"], "intent_tags": ["convert"], "side_effect": "none"},
    )
    assert result["ok"] is True


def test_path_like_description_rejected_by_mechanical_prefilter_no_router_call(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        raise AssertionError("router must not be called for path-like description")
    monkeypatch.setattr(sanity, "_call_router", fake_router)
    result = sanity.check_row(
        "brokentool",
        "30_SVG-PAINT/scripts/ppv-dashboard.py",
        {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "unknown"},
    )
    assert result["ok"] is False
    assert "path-like" in result["reason"] or "traceback" in result["reason"]


def test_traceback_like_description_rejected_by_mechanical_prefilter(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        raise AssertionError("router must not be called for traceback-like description")
    monkeypatch.setattr(sanity, "_call_router", fake_router)
    result = sanity.check_row(
        "brokentool2",
        "ModuleNotFoundError: No module named 'portalocker'",
        {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "unknown"},
    )
    assert result["ok"] is False


def test_mismatched_garbage_not_path_shaped_goes_through_llm(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return {"ok": False, "reason": "description does not match capability fields"}
    monkeypatch.setattr(sanity, "_call_router", fake_router)
    result = sanity.check_row(
        "weirdtool",
        "does stuff sometimes maybe",
        {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "unknown"},
    )
    assert result["ok"] is False
    assert result["reason"]


def test_ambiguous_model_output_fails_closed(monkeypatch):
    def fake_router(prompt, slug, timeout=30):
        return None  # simulates malformed/unparseable model output
    monkeypatch.setattr(sanity, "_call_router", fake_router)
    result = sanity.check_row(
        "ambiguoustool",
        "a reasonably normal-sounding description",
        {"input_types": ["path"], "output_types": ["json"], "intent_tags": [], "side_effect": "none"},
    )
    assert result["ok"] is False


def test_calibration_set_has_known_good_and_bad_cases():
    assert len(sanity.CALIBRATION_SET) >= 8
    goods = [c for c in sanity.CALIBRATION_SET if c["expected_ok"]]
    bads = [c for c in sanity.CALIBRATION_SET if not c["expected_ok"]]
    assert goods
    assert bads
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sanity_check.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `tools/sanity_check.py`**

```python
"""Read-only sanity check over a proposed (description, capability) pair.
Runs last in the backfill pipeline, before any DB write. Purely additive --
never edits rows, only flags them ok=True/False with a reason.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

ROUTER_URL = "http://localhost:9111/v1/chat/completions"
ROUTER_MODEL = "deepseek-v4-flash"
ROUTER_KEY = "router-local"

_PATH_LIKE = re.compile(r"^[\w./-]+\.py$")
_TRACEBACK_MARKERS = ("Error", "Traceback", "Errno", "Exception")

_SYSTEM = (
    "You are a strict reviewer. Given a CLI's description and its capability "
    "fields (input_types, output_types, intent_tags, side_effect), decide: can "
    "a reader tell what this CLI is for and how it fits into a pipeline? "
    "Return ONLY a compact JSON object with keys: ok (boolean), reason "
    "(short string). If ambiguous, return ok=false with a reason -- never "
    "guess true."
)


def _mechanical_prefilter(description: str) -> str | None:
    """Returns a rejection reason string if description is still corrupted
    (path-like or traceback-like), else None (passes, proceed to LLM)."""
    if _PATH_LIKE.match(description.strip()):
        return "description is path-like, not a purpose statement"
    if any(marker in description for marker in _TRACEBACK_MARKERS):
        return "description contains traceback/exception markers"
    return None


def _call_router(prompt: str, slug: str, timeout: int = 30) -> dict | None:
    payload = {
        "model": ROUTER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 150,
        "temperature": 0,
    }
    req = urllib.request.Request(
        ROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {ROUTER_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    try:
        content = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return None
    return _extract_json(content)


def _extract_json(content: str) -> dict | None:
    s = content.find("{")
    e = content.rfind("}")
    if s == -1 or e == -1 or e < s:
        return None
    try:
        return json.loads(content[s : e + 1])
    except json.JSONDecodeError:
        return None


def check_row(slug: str, description: str, capability: dict) -> dict:
    rejection = _mechanical_prefilter(description)
    if rejection:
        return {"ok": False, "reason": rejection}

    prompt = (
        f"Tool slug: {slug}\n"
        f"Description: {description}\n"
        f"Capability fields: {json.dumps(capability)}"
    )
    result = _call_router(prompt, slug)
    if not result or "ok" not in result or not isinstance(result["ok"], bool):
        return {"ok": False, "reason": "ambiguous or malformed model output"}
    return {"ok": bool(result["ok"]), "reason": str(result.get("reason", ""))}


CALIBRATION_SET = [
    {
        "slug": "csv2json",
        "description": "Converts CSV files to JSON format.",
        "capability": {"input_types": ["path"], "output_types": ["json"], "intent_tags": ["convert"], "side_effect": "none"},
        "expected_ok": True,
    },
    {
        "slug": "svg-export",
        "description": "Exports SVG assets and publishes them to Etsy.",
        "capability": {"input_types": ["path"], "output_types": ["path"], "intent_tags": ["export", "publish"], "side_effect": "network"},
        "expected_ok": True,
    },
    {
        "slug": "auto-format",
        "description": "Formats Python source files in place.",
        "capability": {"input_types": ["path"], "output_types": ["path"], "intent_tags": ["build"], "side_effect": "writes-fs"},
        "expected_ok": True,
    },
    {
        "slug": "fetch-data",
        "description": "Downloads a dataset from a remote URL and saves it locally.",
        "capability": {"input_types": ["str"], "output_types": ["path"], "intent_tags": ["download"], "side_effect": "network"},
        "expected_ok": True,
    },
    {
        "slug": "broken1",
        "description": "30_SVG-PAINT/scripts/ppv-dashboard.py",
        "capability": {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "unknown"},
        "expected_ok": False,
    },
    {
        "slug": "broken2",
        "description": "ModuleNotFoundError: No module named 'portalocker'",
        "capability": {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "unknown"},
        "expected_ok": False,
    },
    {
        "slug": "mismatch1",
        "description": "Converts CSV files to JSON format.",
        "capability": {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "destructive"},
        "expected_ok": False,
    },
    {
        "slug": "vague1",
        "description": "does stuff",
        "capability": {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "unknown"},
        "expected_ok": False,
    },
]
```

- [ ] **Step 4: Run tests, iterate until all pass**

Run: `.venv/bin/python -m pytest tests/test_sanity_check.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/sanity_check.py tests/test_sanity_check.py
git commit -m "feat: add sanity-check pass with mechanical pre-filter and calibration set" -- tools/sanity_check.py tests/test_sanity_check.py
```

---

## Task 6: Guarded writer (`backfill_capabilities.py`)

**Files:**
- Create: `tools/backfill_capabilities.py`
- Test: `tests/test_backfill_capabilities.py`

**Interfaces:**
- Consumes: `tools.description_regenerator.regenerate_description`, `tools.capability_extractor.extract_capability`, `tools.capability_llm_fallback.infer_capability_llm`, `tools.sanity_check.check_row`, `tools.sanity_check.CALIBRATION_SET` (all prior tasks).
- Produces: CLI entrypoint `main()` (argparse: `--db PATH`, `--dry-run` default `True`-equivalent via absence of `--commit`, `--commit` flag). Also exposes `_column_exists`, `_table_exists`, `ensure_provenance_columns(db_path)`, `backup_db(db_path) -> Path`, `run_pipeline(db_path) -> dict` (the dry-run body, returns the summary dict, also called internally by `--commit`), `write_commit(db_path, proposals, sanity_results) -> None` for direct testing.

- [ ] **Step 1: Write failing integration tests against a temp DB matching the live schema-drift shape**

```python
# tests/test_backfill_capabilities.py
import json
import sqlite3

import pytest

import tools.backfill_capabilities as backfill


def _make_drifted_db(path):
    """Mirrors the LIVE registry.db schema exactly, including the missing
    not_standalone column and missing provenance/description_provenance
    columns on capability -- built with raw sqlite3.executescript, NOT
    SQLModel.metadata.create_all, so this fixture reproduces the real
    production drift condition."""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE cli (
            slug VARCHAR NOT NULL,
            lang VARCHAR NOT NULL,
            bucket VARCHAR,
            project VARCHAR,
            path VARCHAR,
            launch_spec VARCHAR NOT NULL,
            description VARCHAR NOT NULL,
            source_class VARCHAR,
            health_cmd VARCHAR,
            health_status VARCHAR NOT NULL,
            health_checked_at FLOAT,
            fixed_by VARCHAR,
            enabled BOOLEAN NOT NULL,
            a2a_invokable BOOLEAN NOT NULL,
            source_run_id VARCHAR,
            last_seen_at FLOAT,
            updated_at FLOAT,
            PRIMARY KEY (slug)
        );
        CREATE TABLE capability (
            id INTEGER NOT NULL,
            cli_slug VARCHAR NOT NULL,
            intent_tags VARCHAR NOT NULL,
            input_types VARCHAR NOT NULL,
            output_types VARCHAR NOT NULL,
            side_effect VARCHAR NOT NULL,
            confidence VARCHAR NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(cli_slug) REFERENCES cli (slug)
        );
        """
    )
    con.execute(
        "INSERT INTO cli VALUES ('csv2json','python',NULL,NULL,'/tmp/csv2json.py','{}','30_x/csv2json.py',NULL,NULL,'unknown',NULL,NULL,1,0,NULL,NULL,NULL)"
    )
    con.execute(
        "INSERT INTO capability (cli_slug, intent_tags, input_types, output_types, side_effect, confidence) VALUES ('csv2json','','','','unknown','declared')"
    )
    con.execute(
        "INSERT INTO cli VALUES ('shellwrap','shell',NULL,NULL,'/usr/local/bin/shellwrap','{}','Traceback: crashed',NULL,NULL,'unknown',NULL,NULL,1,0,NULL,NULL,NULL)"
    )
    con.execute(
        "INSERT INTO capability (cli_slug, intent_tags, input_types, output_types, side_effect, confidence) VALUES ('shellwrap','','','','unknown','declared')"
    )
    con.commit()
    con.close()


@pytest.fixture
def drifted_db(tmp_path):
    db_path = str(tmp_path / "registry.db")
    _make_drifted_db(db_path)
    return db_path


def _patch_pipeline(monkeypatch, cap_result=None, desc_result="A test CLI that converts things.", sanity_ok=True):
    import tools.capability_extractor as extractor
    import tools.description_regenerator as regen
    import tools.sanity_check as sanity

    monkeypatch.setattr(regen, "regenerate_description", lambda slug, source: desc_result)
    monkeypatch.setattr(
        extractor, "extract_capability",
        lambda slug, description, source: cap_result or {
            "input_types": ["path"], "output_types": ["json"], "intent_tags": ["convert"],
            "side_effect": "none", "confidence": "inferred", "provenance": "static",
        },
    )
    monkeypatch.setattr(sanity, "check_row", lambda slug, description, capability: {"ok": sanity_ok, "reason": ""})


def test_dry_run_writes_proposals_and_zero_db_changes(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    summary = backfill.run_pipeline(drifted_db)
    assert (tmp_path / "backfill_proposals.jsonl").exists()
    assert (tmp_path / "sanity_report.jsonl").exists()
    con = sqlite3.connect(drifted_db)
    row = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    con.close()
    assert row[0] == "30_x/csv2json.py"  # unchanged -- dry-run never writes


def test_commit_updates_capability_and_description_and_creates_backup(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    backfill.main(["--db", drifted_db, "--commit"])
    con = sqlite3.connect(drifted_db)
    row = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    cap = con.execute("SELECT input_types, output_types, provenance FROM capability WHERE cli_slug='csv2json'").fetchone()
    con.close()
    assert row[0] == "A test CLI that converts things."
    assert cap[0] == "path"
    assert cap[1] == "json"
    assert cap[2] == "static"
    backups = list(tmp_path.glob("registry.db.bak-*")) + [p for p in __import__("pathlib").Path(drifted_db).parent.glob("*.bak-*")]
    assert backups


def test_manual_capability_provenance_protected_independently_of_description(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    backfill.ensure_provenance_columns(drifted_db)
    con = sqlite3.connect(drifted_db)
    con.execute("UPDATE capability SET provenance='manual', input_types='manual-path' WHERE cli_slug='csv2json'")
    con.commit()
    con.close()

    backfill.main(["--db", drifted_db, "--commit"])

    con = sqlite3.connect(drifted_db)
    cap = con.execute("SELECT input_types, provenance FROM capability WHERE cli_slug='csv2json'").fetchone()
    desc = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    con.close()
    assert cap[0] == "manual-path"  # capability protected
    assert cap[1] == "manual"
    assert desc[0] == "A test CLI that converts things."  # description still refreshed


def test_manual_description_provenance_protected_independently_of_capability(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    backfill.ensure_provenance_columns(drifted_db)
    con = sqlite3.connect(drifted_db)
    con.execute("UPDATE capability SET description_provenance='manual' WHERE cli_slug='csv2json'")
    con.execute("UPDATE cli SET description='Hand-written accurate description.' WHERE slug='csv2json'")
    con.commit()
    con.close()

    backfill.main(["--db", drifted_db, "--commit"])

    con = sqlite3.connect(drifted_db)
    desc = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    cap = con.execute("SELECT input_types FROM capability WHERE cli_slug='csv2json'").fetchone()
    con.close()
    assert desc[0] == "Hand-written accurate description."  # description protected
    assert cap[0] == "path"  # capability still refreshed


def test_backup_failure_aborts_write(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)

    def fail_backup(db_path):
        raise OSError("disk full")
    monkeypatch.setattr(backfill, "backup_db", fail_backup)

    with pytest.raises(OSError):
        backfill.main(["--db", drifted_db, "--commit"])

    con = sqlite3.connect(drifted_db)
    row = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    con.close()
    assert row[0] == "30_x/csv2json.py"  # unchanged -- abort must precede any write


def test_both_provenance_columns_auto_added_when_missing(drifted_db):
    con = sqlite3.connect(drifted_db)
    cols_before = {r[1] for r in con.execute("PRAGMA table_info(capability)")}
    con.close()
    assert "provenance" not in cols_before
    assert "description_provenance" not in cols_before

    backfill.ensure_provenance_columns(drifted_db)

    con = sqlite3.connect(drifted_db)
    cols_after = {r[1] for r in con.execute("PRAGMA table_info(capability)")}
    con.close()
    assert "provenance" in cols_after
    assert "description_provenance" in cols_after


def test_commit_refuses_when_sanity_failure_rate_exceeds_threshold(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, sanity_ok=False)  # 100% failure rate
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        backfill.main(["--db", drifted_db, "--commit"])
    con = sqlite3.connect(drifted_db)
    row = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    con.close()
    assert row[0] == "30_x/csv2json.py"  # refused -- no write happened


def test_commit_proceeds_when_failure_rate_under_threshold(drifted_db, monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, sanity_ok=True)  # 0% failure rate
    monkeypatch.chdir(tmp_path)
    backfill.main(["--db", drifted_db, "--commit"])  # must not raise
    con = sqlite3.connect(drifted_db)
    row = con.execute("SELECT description FROM cli WHERE slug='csv2json'").fetchone()
    con.close()
    assert row[0] == "A test CLI that converts things."


def test_all_474_rows_get_description_only_python_rows_get_capability(drifted_db, monkeypatch, tmp_path):
    # csv2json is python (lang='python'), shellwrap is lang='shell'
    _patch_pipeline(monkeypatch)
    monkeypatch.chdir(tmp_path)
    backfill.main(["--db", drifted_db, "--commit"])
    con = sqlite3.connect(drifted_db)
    shell_desc = con.execute("SELECT description FROM cli WHERE slug='shellwrap'").fetchone()
    shell_cap = con.execute("SELECT input_types, provenance FROM capability WHERE cli_slug='shellwrap'").fetchone()
    con.close()
    assert shell_desc[0] == "A test CLI that converts things."  # description regenerated for shell row too
    assert shell_cap[0] == ""  # capability fields NOT populated for shell row
    assert shell_cap[1] is None  # never touched by the static/llm extractor path


def test_no_module_imports_core_models_cli_for_reads():
    import ast
    import pathlib

    for path in pathlib.Path("tools").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "core.models":
                names = {alias.name for alias in node.names}
                assert "Cli" not in names, f"{path} imports core.models.Cli -- must use raw sqlite3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backfill_capabilities.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `tools/backfill_capabilities.py`**

```python
"""Guarded writer for the registry capability backfill. The ONLY module that
mutates registry.db. Backup-first, dry-run-default, sanity-gated --commit.

Pipeline order per CLI: description_regenerator -> capability_extractor
-> (capability_llm_fallback if input_types or output_types empty)
-> sanity_check over the full proposed dataset -> write.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tools.capability_extractor import extract_capability
from tools.capability_llm_fallback import infer_capability_llm
from tools.description_regenerator import regenerate_description
from tools.sanity_check import CALIBRATION_SET, check_row

FALLBACK_CAP = 30
SANITY_FAILURE_THRESHOLD = 0.10


def _table_exists(con, table: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _column_exists(con, table: str, column: str) -> bool:
    return any(r[1] == column for r in con.execute(f"PRAGMA table_info({table})"))


def _add_column_guarded(con, table: str, column: str, coltype: str) -> None:
    if _table_exists(con, table) and not _column_exists(con, table, column):
        try:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
            con.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise


def ensure_provenance_columns(db_path: str) -> None:
    con = sqlite3.connect(db_path)
    try:
        _add_column_guarded(con, "capability", "provenance", "TEXT")
        _add_column_guarded(con, "capability", "description_provenance", "TEXT")
    finally:
        con.close()


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or "nogit"
    except (OSError, subprocess.SubprocessError):
        return "nogit"


def backup_db(db_path: str) -> Path:
    src = Path(db_path)
    sha = _git_sha()
    dest = src.parent / f"{src.name}.bak-{sha}"
    fd, tmp_name = tempfile.mkstemp(dir=str(src.parent))
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "wb") as tmp_f, open(src, "rb") as src_f:
            shutil.copyfileobj(src_f, tmp_f)
        tmp_path.replace(dest)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise
    return dest


def _fetch_all_cli_rows(con) -> list[dict]:
    rows = con.execute(
        "SELECT slug, lang, path, description FROM cli"
    ).fetchall()
    return [{"slug": r[0], "lang": r[1], "path": r[2], "description": r[3]} for r in rows]


def _read_source(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text()
    except (OSError, UnicodeDecodeError):
        return ""


def run_pipeline(db_path: str) -> dict:
    """Dry-run body: regenerate descriptions, extract/fallback capabilities,
    sanity-check everything, write both jsonl report files. Never writes to
    the DB. Returns a summary dict; also the first phase of --commit."""
    start = time.time()
    con = sqlite3.connect(db_path)
    try:
        cli_rows = _fetch_all_cli_rows(con)
    finally:
        con.close()

    proposals = []
    fallback_count = 0
    for row in cli_rows:
        slug, lang, path, _old_description = row["slug"], row["lang"], row["path"], row["description"]
        source = _read_source(path) if lang == "python" else ""
        description = regenerate_description(slug, source)

        capability = None
        if lang == "python":
            capability = extract_capability(slug, description, source)
            if not capability["input_types"] or not capability["output_types"]:
                capability = infer_capability_llm(slug, description, source)
                fallback_count += 1

        proposals.append({"slug": slug, "description": description, "capability": capability})

    if fallback_count > FALLBACK_CAP:
        print(
            f"STOP: {fallback_count} CLIs required LLM fallback (cap: {FALLBACK_CAP}). "
            "Static extractor needs tuning before proceeding.",
            file=sys.stderr,
        )
        sys.exit(1)

    calibration_ok, calibration_detail = _run_calibration()

    sanity_results = []
    for p in proposals:
        result = check_row(p["slug"], p["description"], p["capability"] or {})
        sanity_results.append({"slug": p["slug"], **result})

    fail_count = sum(1 for r in sanity_results if not r["ok"])
    fail_rate = fail_count / len(sanity_results) if sanity_results else 0.0

    Path("backfill_proposals.jsonl").write_text(
        "\n".join(json.dumps(p) for p in proposals) + "\n"
    )
    Path("sanity_report.jsonl").write_text(
        "\n".join(json.dumps(r) for r in sanity_results) + "\n"
    )

    elapsed = time.time() - start
    summary = {
        "total_rows": len(cli_rows),
        "python_rows": sum(1 for r in cli_rows if r["lang"] == "python"),
        "fallback_count": fallback_count,
        "sanity_fail_count": fail_count,
        "sanity_fail_rate": fail_rate,
        "calibration_ok": calibration_ok,
        "calibration_detail": calibration_detail,
        "elapsed_seconds": elapsed,
    }
    print(json.dumps(summary, indent=2))
    return {"proposals": proposals, "sanity_results": sanity_results, "summary": summary}


def _run_calibration() -> tuple[bool, str]:
    mismatches = []
    for case in CALIBRATION_SET:
        result = check_row(case["slug"], case["description"], case["capability"])
        if result["ok"] != case["expected_ok"]:
            mismatches.append(case["slug"])
    ok = not mismatches
    detail = "all calibration cases matched" if ok else f"mismatched: {mismatches}"
    return ok, detail


def write_commit(db_path: str, proposals: list[dict]) -> None:
    con = sqlite3.connect(db_path)
    try:
        for p in proposals:
            slug, description, capability = p["slug"], p["description"], p["capability"]

            row = con.execute(
                "SELECT provenance, description_provenance FROM capability WHERE cli_slug=?",
                (slug,),
            ).fetchone()
            cap_provenance, desc_provenance = (row if row else (None, None))

            if desc_provenance in (None, "static", "llm"):
                con.execute(
                    "UPDATE cli SET description=? WHERE slug=?", (description, slug)
                )
                con.execute(
                    "UPDATE capability SET description_provenance='llm' WHERE cli_slug=?",
                    (slug,),
                )

            if capability is not None and cap_provenance in (None, "static", "llm"):
                con.execute(
                    """UPDATE capability SET input_types=?, output_types=?, intent_tags=?,
                       side_effect=?, confidence=?, provenance=? WHERE cli_slug=?""",
                    (
                        ",".join(capability["input_types"]),
                        ",".join(capability["output_types"]),
                        ",".join(capability["intent_tags"]),
                        capability["side_effect"],
                        capability["confidence"],
                        capability["provenance"],
                        slug,
                    ),
                )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Registry capability backfill")
    parser.add_argument("--db", required=True, help="Path to registry.db")
    parser.add_argument("--commit", action="store_true", help="Write to the DB (default: dry-run)")
    args = parser.parse_args(argv)

    ensure_provenance_columns(args.db)
    result = run_pipeline(args.db)

    if not args.commit:
        return

    if not result["summary"]["calibration_ok"]:
        print(
            f"REFUSED: sanity-check calibration failed ({result['summary']['calibration_detail']}). "
            "The checker may be miscalibrated -- fix before committing.",
            file=sys.stderr,
        )
        sys.exit(1)

    if result["summary"]["sanity_fail_rate"] > SANITY_FAILURE_THRESHOLD:
        print(
            f"REFUSED: sanity failure rate {result['summary']['sanity_fail_rate']:.1%} "
            f"exceeds threshold {SANITY_FAILURE_THRESHOLD:.0%}. "
            "Fix the regenerator/extractor and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    backup_db(args.db)
    write_commit(args.db, result["proposals"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, iterate until all pass**

Run: `.venv/bin/python -m pytest tests/test_backfill_capabilities.py -v`
Expected: all PASS. Pay particular attention to `test_backup_failure_aborts_write` (backup must run before any DB mutation in `main()`) and the two independent-provenance tests (each field's guard must be checked separately, never coupled).

- [ ] **Step 5: Run the full test suite for regressions**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all PASS, including all pre-existing tests (`test_planner.py`, `test_fixed_by_migration.py`, etc.) — this task touches no existing file, but confirm no import-time side effects leaked.

- [ ] **Step 6: Commit**

```bash
git add tools/backfill_capabilities.py tests/test_backfill_capabilities.py
git commit -m "feat: add guarded backfill writer with dry-run default and sanity gate" -- tools/backfill_capabilities.py tests/test_backfill_capabilities.py
```

---

## Task 7: Dry-run against the live DB, tune, then commit (acceptance gate)

**Files:**
- None created — this task runs the pipeline against the real `registry.db` and inspects output. May produce follow-up commits if tuning is needed (see Step 3).

- [ ] **Step 1: Run a dry-run against the live DB**

Run: `.venv/bin/python -m tools.backfill_capabilities --db registry.db`
Expected: prints a summary JSON with `total_rows: 474`, `python_rows: 471`, `fallback_count` (watch for `> 30` — triggers `sys.exit(1)`), `sanity_fail_count`/`sanity_fail_rate`, `calibration_ok: true`. Writes `backfill_proposals.jsonl` and `sanity_report.jsonl` in the cwd.

- [ ] **Step 2: Eyeball the proposals and sanity report**

Run: `head -20 backfill_proposals.jsonl` and `grep '"ok": false' sanity_report.jsonl | head -20`
Expected: descriptions read as real purpose statements (not path/traceback junk); sanity failures are a reviewable minority, not systemic garbage.

- [ ] **Step 3: If `fallback_count > 30` or `sanity_fail_rate > 10%` or `calibration_ok: false`**

Do not force past the gate. Return to Task 1/2 (extractor) or Task 3 (regenerator) or Task 5 (sanity check) fixtures/prompts, fix the root cause, re-run unit tests, then repeat Step 1. This loop is the "stop and tune" philosophy named in the spec — never skip the gate with a flag.

- [ ] **Step 4: Run one-line acceptance queries**

```bash
sqlite3 registry.db "SELECT COUNT(*) FROM capability WHERE input_types != '' OR output_types != ''"
```
Expected (after Step 5's commit, not before): jumps from 0 toward 440+ out of 471 Python rows.

```bash
python3 -c "
import json
rows = [json.loads(l) for l in open('sanity_report.jsonl')]
ok = sum(1 for r in rows if r['ok'])
print(f'{ok}/{len(rows)} = {ok/len(rows):.1%}')
"
```
Expected: ≥90% pass rate, scoped to all 474 rows.

- [ ] **Step 5: Commit to the live DB**

```bash
.venv/bin/python -m tools.backfill_capabilities --db registry.db --commit
```
Expected: prints the same summary, then a backup file `registry.db.bak-<gitsha>` appears alongside `registry.db`, and the acceptance queries in Step 4 now show the improved counts.

- [ ] **Step 6: Commit the proposals/report files for the audit trail (optional but recommended — human-review artifacts)**

```bash
git add backfill_proposals.jsonl sanity_report.jsonl
git commit -m "chore: record capability-backfill proposals and sanity report from live run" -- backfill_proposals.jsonl sanity_report.jsonl
```

---

## Self-Review Notes

**Spec coverage:** Every module in the spec's Architecture table (description_regenerator, capability_extractor, capability_llm_fallback, sanity_check, backfill_capabilities) has a task. Typer/click/argparse/subparsers/aliased-import are all covered (Tasks 1-2). The 471-vs-474 scope split is enforced in Task 6's `run_pipeline` (`lang == "python"` gates capability extraction, not description regeneration). Two independent provenance columns, guarded ALTER, dry-run default, sanity gate, calibration set, fallback cap, and the raw-sqlite3-only constraint (with its own regression test) are all present. Output-type/side_effect trade-offs are implemented per the named semantics (`bridge/llm_infer.py`-matching `writes-fs` rule).

**Placeholder scan:** No TBD/TODO; every test has concrete fixture code; every implementation step has complete code, not descriptions of code.

**Type consistency:** `extract_capability` / `infer_capability_llm` both return the same dict shape (`input_types`, `output_types`, `intent_tags`, `side_effect`, `confidence`, `provenance`) — verified consistent across Tasks 1, 2, 4, and consumed identically in Task 6's `run_pipeline`. `check_row`'s `{"ok": bool, "reason": str}` shape is consistent across Tasks 5 and 6.
