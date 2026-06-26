"""Tests for capture_help's crash-rejection, module-mode, and probe ladder
(the abstention-recovery fixes). Hermetic: builds tiny throwaway CLIs on disk
and runs them with the real interpreter — no router, no network.
"""
from __future__ import annotations

import os
import textwrap

import bridge.llm_infer as li


def _write(p, src):
    p.write_text(textwrap.dedent(src), encoding="utf-8")
    return str(p)


def test_rejects_traceback_as_no_help(tmp_path):
    """A CLI that crashes on --help (ImportError) must yield '' , not its traceback."""
    cli = _write(tmp_path / "boom.py", """
        import this_module_does_not_exist_xyz  # ImportError before argparse
        print("never reached")
    """)
    assert li.capture_help(cli, timeout=10) == ""


def test_file_mode_help_captured(tmp_path):
    """A standalone script with argparse --help is captured cleanly."""
    cli = _write(tmp_path / "tool.py", """
        import argparse
        p = argparse.ArgumentParser(description="convert pdf to text")
        p.add_argument("--out")
        p.parse_args()
    """)
    out = li.capture_help(cli, timeout=10)
    assert "usage:" in out.lower()
    assert "convert pdf to text" in out


def test_module_mode_resolves_package_imports(tmp_path):
    """The dominant fix: a package CLI that uses a package-relative import fails
    in file mode but succeeds via `python -m pkg.cli` from the project root."""
    # project root marker so _project_root finds it
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "helper.py").write_text("MESSAGE = 'lint source files'\n")
    cli = _write(pkg / "cli.py", """
        import argparse
        from mypkg.helper import MESSAGE   # package-relative: breaks in file mode
        p = argparse.ArgumentParser(description=MESSAGE)
        p.parse_args()
    """)
    # file mode alone would ImportError; capture_help must fall to module mode
    out = li.capture_help(cli, timeout=10)
    assert "lint source files" in out, out


def test_probe_ladder_falls_back_to_dash_h(tmp_path):
    """A tool that rejects --help but accepts -h is still captured (Fix 3)."""
    cli = _write(tmp_path / "dashh.py", """
        import sys
        if "-h" in sys.argv:
            print("usage: dashh [options]\\noptions:\\n  -h  show help")
        else:
            sys.stderr.write("error: unrecognized arguments: --help\\n")
            sys.exit(2)
    """)
    out = li.capture_help(cli, timeout=10)
    assert "usage: dashh" in out


def test_dotted_module_derivation(tmp_path):
    root = str(tmp_path)
    path = str(tmp_path / "pkg" / "sub" / "cli.py")
    assert li._dotted_module(path, root) == "pkg.sub.cli"


def test_project_root_walks_to_sentinel(tmp_path):
    (tmp_path / ".git").mkdir()
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    f = deep / "tool.py"
    f.write_text("x=1\n")
    assert li._project_root(str(f)) == str(tmp_path)


def test_is_crash_and_bad_flag_classifiers():
    assert li._is_crash("Traceback (most recent call last):\n  ...")
    assert li._is_crash("ModuleNotFoundError: No module named 'foo'")
    assert not li._is_crash("usage: tool [options]")
    assert li._is_bad_flag("error: unrecognized arguments: --help")
    assert not li._is_bad_flag("usage: tool\noptions:")


def test_bare_run_only_accepted_when_help_shaped(tmp_path):
    """A bare invocation that prints program output (not usage) is NOT accepted
    as help — guards against treating side-effecting output as a help screen."""
    cli = _write(tmp_path / "doer.py", """
        # no argparse; rejects flags, prints work output on bare run
        import sys
        if len(sys.argv) > 1:
            sys.stderr.write("no such option\\n"); sys.exit(2)
        print("Processed 42 records. Done.")
    """)
    assert li.capture_help(cli, timeout=10) == ""
