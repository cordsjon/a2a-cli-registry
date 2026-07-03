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

    Only considers attributes that match input name heuristics (file, input, path, etc.)
    to avoid false positives with output-only arguments (--out, --output, etc.).
    """
    # Collect args attributes that match input heuristics
    read_paths = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "args":
            attr_name = node.attr
            # Only consider this a "read path" if the attribute name suggests it's an input
            if _arg_name_to_key(f"--{attr_name}"):
                read_paths.add(attr_name)

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
