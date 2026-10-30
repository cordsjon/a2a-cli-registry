"""md2pdf wrapper (US-CLIREG-MD2PDF-CATALOG-01, operator ruling Q12).

Real seam: these tests run the actual script against the real pandoc +
WeasyPrint on this machine (no mocks of the converter). They skip, not pass,
when pandoc is absent. Run with:

    .venv/bin/pytest fleet-clis/md2pdf/tests -q
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "md2pdf.py"

needs_pandoc = pytest.mark.skipif(
    shutil.which("pandoc") is None or shutil.which("weasyprint") is None,
    reason="pandoc + weasyprint not installed",
)


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=cwd, timeout=120,
    )


def test_help_exits_zero_and_names_the_ports():
    # The registry's health probe is `python <path> --help`; it must exit 0.
    r = _run("--help")
    assert r.returncode == 0, r.stderr
    assert "md" in r.stdout.lower() and "pdf" in r.stdout.lower()


@needs_pandoc
def test_converts_markdown_to_pdf_at_explicit_output(tmp_path):
    src = tmp_path / "in.md"
    src.write_text("# Überschrift\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    out = tmp_path / "out.pdf"
    r = _run(str(src), "-o", str(out))
    assert r.returncode == 0, r.stderr
    assert out.read_bytes()[:5] == b"%PDF-"
    # the wrapper prints the output path so a dispatching agent can hand it on
    assert str(out) in r.stdout


@needs_pandoc
def test_default_output_is_sibling_pdf_with_same_stem(tmp_path):
    src = tmp_path / "notes.md"
    src.write_text("plain text\n", encoding="utf-8")
    r = _run(str(src))
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "notes.pdf").read_bytes()[:5] == b"%PDF-"


def test_missing_input_fails_nonzero_without_writing(tmp_path):
    out = tmp_path / "out.pdf"
    r = _run(str(tmp_path / "nope.md"), "-o", str(out))
    assert r.returncode != 0
    assert not out.exists()
    assert "nope.md" in r.stderr


@needs_pandoc
def test_failed_conversion_leaves_no_partial_output(tmp_path, monkeypatch):
    # Point the wrapper at a pandoc that fails: the output path must not be
    # created (atomic write), and pandoc's exit code must propagate.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "pandoc"
    fake.write_text("#!/bin/sh\necho 'boom' >&2\nexit 83\n")
    fake.chmod(0o755)
    src = tmp_path / "in.md"
    src.write_text("x\n")
    out = tmp_path / "out.pdf"
    env = dict(os.environ, PATH=f"{fake_bin}:{os.environ.get('PATH', '')}")
    r = subprocess.run([sys.executable, str(SCRIPT), str(src), "-o", str(out)],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 83
    assert not out.exists()
    assert "boom" in r.stderr
