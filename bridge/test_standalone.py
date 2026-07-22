"""Tests for the not-standalone AST classifier. Hermetic: writes tiny source
files and classifies them WITHOUT executing (ast only). Mirrors the two
US-CLIAUDIT-83 ground-truth shapes verified from real source:
  - subapp:    consigliere/cli/memory_commands.py (typer.Typer, no __main__)
  - no_parser: a __main__-guarded batch script with no parser AND no sys.argv.

NOTE on the spec's named AC-02 example: keto-data/scripts/categorize_ai.py was
cited as a no_parser case, but it actually parses sys.argv for --dry-run /
--batch-size, so it is correctly 'standalone' (a CLI surface). The genuine
no_parser ground truth used here is simonw-tools/build_index.py (a build script
with a __main__ guard and zero arg access). See _REAL_NO_PARSER below.
"""
from __future__ import annotations

import os
import textwrap

import pytest

from bridge.standalone import classify_standalone

# Real on-disk ground-truth files (skipped if the sibling project isn't present).
_REAL_SUBAPP = "/Users/jc-folder/projects/20_CONSIGLIERE/consigliere/cli/memory_commands.py"
_REAL_NO_PARSER = "/Users/jc-folder/projects/75_Coaching/10_Consulting/20_Tooling/simonw-tools/build_index.py"


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


def test_sys_argv_under_main_is_standalone(tmp_path):
    """A __main__-guarded script that reads sys.argv parses args MANUALLY -> it
    is a real CLI surface, not a no_parser batch script."""
    f = _w(tmp_path / "manual.py", """
        import sys

        def main():
            if len(sys.argv) > 1:
                print(sys.argv[1])

        if __name__ == "__main__":
            main()
    """)
    assert classify_standalone(f) == "standalone"


def test_sys_argv_indexed_access_is_standalone(tmp_path):
    """Direct sys.argv[1] indexing under __main__ also counts as manual parsing."""
    f = _w(tmp_path / "idx.py", """
        import sys
        if __name__ == "__main__":
            target = sys.argv[1]
            print(target)
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


@pytest.mark.skipif(not os.path.exists(_REAL_SUBAPP), reason="consigliere not present")
def test_real_subapp_ground_truth():
    """AC-01 against the real file: consigliere memory_commands -> subapp."""
    assert classify_standalone(_REAL_SUBAPP) == "subapp"


@pytest.mark.skipif(not os.path.exists(_REAL_NO_PARSER), reason="simonw-tools not present")
def test_real_no_parser_ground_truth():
    """AC-02 against a real genuine batch script: build_index.py -> no_parser."""
    assert classify_standalone(_REAL_NO_PARSER) == "no_parser"
