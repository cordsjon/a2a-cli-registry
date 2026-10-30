#!/usr/bin/env python3
"""Render a Markdown file to PDF with pandoc + WeasyPrint (file:md -> file:pdf).

Usage: md2pdf.py <in.md> [-o <out.pdf>]

Default output is <in>.pdf next to the input. The PDF is written atomically
(temp file in the target directory, then replaced) and its path is printed on
stdout. pandoc's exit code propagates. No LaTeX: operator ruling 2026-10-30
(US-CLIREG-MD2PDF-CATALOG-01 AC-02) pins `-t html5 -s --pdf-engine=weasyprint`
because pandoc's default engine (pdflatex) is not installed on the fleet.
Local only, no network.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

EXIT_USAGE = 2
EXIT_MISSING_TOOL = 3


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="md2pdf.py",
        description="Render a Markdown (md) file to PDF via pandoc + WeasyPrint.",
    )
    ap.add_argument("input", help="Markdown file (file:md)")
    ap.add_argument("-o", "--output", help="PDF path (file:pdf); default <input>.pdf")
    args = ap.parse_args(argv)

    src = os.path.abspath(args.input)
    if not os.path.isfile(src):
        print(f"md2pdf: input not found: {args.input}", file=sys.stderr)
        return EXIT_USAGE
    out = os.path.abspath(args.output) if args.output else os.path.splitext(src)[0] + ".pdf"

    pandoc = shutil.which("pandoc")
    if pandoc is None or shutil.which("weasyprint") is None:
        print("md2pdf: needs pandoc and weasyprint on PATH (brew install pandoc weasyprint)",
              file=sys.stderr)
        return EXIT_MISSING_TOOL

    out_dir = os.path.dirname(out) or "."
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".md2pdf-", suffix=".pdf", dir=out_dir)
    os.close(fd)
    try:
        proc = subprocess.run(
            [pandoc, src, "-t", "html5", "-s", "--pdf-engine=weasyprint", "-o", tmp],
            stdout=sys.stderr, stderr=sys.stderr,
        )
        if proc.returncode != 0 or os.path.getsize(tmp) == 0:
            return proc.returncode or 1
        os.chmod(tmp, 0o644)  # mkstemp creates 0600; a shared artefact must be readable
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
