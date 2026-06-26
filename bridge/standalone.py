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
