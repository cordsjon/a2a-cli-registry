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


def _declared_arg_attr_name(node: ast.Call) -> str | None:
    """Normalize an add_argument(...) call's flag string the way argparse
    would derive the destination attribute: strip leading dashes, replace
    '-' with '_'. E.g. '--output-file' -> 'output_file'."""
    arg_name = _first_str_arg(node)
    if not arg_name:
        return None
    return arg_name.lstrip("-").replace("-", "_")


def _parser_var_group_key(node: ast.Call) -> str | None:
    """Given an add_argument(...) Call node, return an identifier for which
    parser-like variable it was called on (the ast.Name id of node.func.value),
    e.g. 'p' for `p.add_argument(...)` or 'format_p' for `format_p.add_argument(...)`.

    Returns None if the call target isn't a plain Name (can't be grouped --
    treated as its own singleton group by the caller so it doesn't silently
    vanish from the count)."""
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        return node.func.value.id
    return None


def _group_add_argument_calls_by_parser(tree: ast.AST) -> list[list[ast.Call]]:
    """Group all add_argument(...) calls by which parser variable they were
    called on, so that subparser-scoped declarations don't contaminate their
    siblings' or the top-level parser's counts.

    For a CLI without add_subparsers(), every add_argument call is chained off
    the single top-level parser variable, so this naturally collapses to one
    group -- identical behavior to the old ungrouped/global count.

    For a CLI with add_subparsers(), each `<subparsers>.add_parser("name")`
    call returns a distinct parser object typically assigned to its own
    variable (e.g. `format_p = sub.add_parser("format")`); add_argument calls
    chained off that variable belong only to that subcommand's group.
    """
    groups: dict[str, list[ast.Call]] = {}
    ungrouped: list[list[ast.Call]] = []
    for node in _walk_add_argument_calls(tree):
        key = _parser_var_group_key(node)
        if key is None:
            ungrouped.append([node])
            continue
        groups.setdefault(key, []).append(node)
    return list(groups.values()) + ungrouped


def _writes_same_path_as_input(tree: ast.AST) -> bool:
    """Structural (declaration-count) rule, not name vocabulary, scoped PER
    PARSER GROUP (top-level parser, or each subcommand's subparser) so that
    sibling subcommands' argument counts don't contaminate one another:

    For each parser group, if it declares EXACTLY ONE argparse argument, and
    that argument's args.<attr> is opened in write/append mode, that group is
    an in-place tool (it's that (sub)command's only path -- reading and
    rewriting it is definitionally in-place) -> the whole CLI is "writes-fs"
    (capability extraction treats side_effect as a whole-CLI property: if any
    subcommand can do in-place modification, the CLI as a whole is capable of
    it).

    If a group declares TWO OR MORE arguments, any args.<attr> write within
    that group is treated as writing to a distinct output arg, not an
    in-place rewrite of the input -- that group contributes nothing, but it
    no longer suppresses a sibling group's genuine in-place classification.

    This cannot be bypassed by flag-name vocabulary (e.g. --result-path as an
    output, or --target-file as the sole in-place arg) because it never
    inspects the name content -- only the per-group declaration count.
    """
    for group in _group_add_argument_calls_by_parser(tree):
        declared_attrs: list[str] = []
        for node in group:
            attr = _declared_arg_attr_name(node)
            if attr and attr not in declared_attrs:
                declared_attrs.append(attr)

        if len(declared_attrs) != 1:
            continue

        sole_attr = declared_attrs[0]

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
                    if target.attr == sole_attr:
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
