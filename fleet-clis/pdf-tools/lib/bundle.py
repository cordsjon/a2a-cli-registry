#!/usr/bin/env python3
"""bundle/unbundle — reversible multi-doc PDF packaging.

Steals the format trick from github.com/AlexandrosGounis/pdfx (SPEC.md):
concatenate pages, embed a `pdfx-manifest.json` file attachment (ISO
32000-1:2008 SS7.11.4) recording each source document's name and page
count. Any standard reader shows all pages in sequence; unbundle() reads
the attachment back and re-splits pages exactly. A PDF with no manifest
attachment degrades to "one document" (unbundle is then a passthrough).

pdfx format version implemented: "1.0".
"""
import json
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter

MANIFEST_NAME = "pdfx-manifest.json"
PDFX_VERSION = "1.0"


def bundle(input_paths: list[str], out_path: str, title: str | None = None) -> str:
    """Concatenate input_paths into out_path with an embedded page-boundary manifest."""
    writer = PdfWriter()
    documents = []
    for p in input_paths:
        src = Path(p)
        reader = PdfReader(str(src))
        page_count = len(reader.pages)
        for page in reader.pages:
            writer.add_page(page)
        documents.append({"name": src.stem, "pages": page_count})

    manifest = {"pdfx": PDFX_VERSION, "documents": documents}
    if title:
        manifest["title"] = title

    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    writer.add_attachment(MANIFEST_NAME, manifest_bytes)

    tmp = Path(out_path).with_suffix(Path(out_path).suffix + ".tmp")
    with open(tmp, "wb") as f:
        writer.write(f)
    tmp.replace(out_path)
    return out_path


def _read_manifest(reader: PdfReader) -> dict | None:
    attachments = reader.attachments
    if MANIFEST_NAME not in attachments:
        return None
    # pypdf returns a list of byte-blobs per filename (duplicates allowed by spec).
    blobs = attachments[MANIFEST_NAME]
    raw = blobs[0] if isinstance(blobs, list) else blobs
    return json.loads(raw.decode("utf-8"))


def unbundle(input_path: str, out_dir: str) -> list[str]:
    """Split input_path back into its original documents per the embedded manifest.

    If no manifest attachment is present, treat the input as a single
    document (pdfx graceful-degradation rule) and copy it through unchanged.
    """
    reader = PdfReader(input_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    manifest = _read_manifest(reader)
    if manifest is None:
        stem = Path(input_path).stem
        dest = out / f"{stem}.pdf"
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        tmp = dest.with_suffix(".pdf.tmp")
        with open(tmp, "wb") as f:
            writer.write(f)
        tmp.replace(dest)
        return [str(dest)]

    written = []
    cursor = 0
    for doc in manifest["documents"]:
        n = doc["pages"]
        writer = PdfWriter()
        for page in reader.pages[cursor : cursor + n]:
            writer.add_page(page)
        cursor += n
        dest = out / f"{doc['name']}.pdf"
        tmp = dest.with_suffix(".pdf.tmp")
        with open(tmp, "wb") as f:
            writer.write(f)
        tmp.replace(dest)
        written.append(str(dest))
    return written


def _main(argv: list[str]) -> int:
    if len(argv) < 1:
        print("usage: bundle.py bundle <in.pdf...> --out <out.pdf> [--title T]", file=sys.stderr)
        print("       bundle.py unbundle <in.pdf> --out <outdir>", file=sys.stderr)
        return 2

    cmd = argv[0]
    rest = argv[1:]
    out = None
    title = None
    positional = []
    i = 0
    while i < len(rest):
        if rest[i] == "--out":
            out = rest[i + 1]
            i += 2
        elif rest[i] == "--title":
            title = rest[i + 1]
            i += 2
        else:
            positional.append(rest[i])
            i += 1

    if out is None:
        print("bundle.py: --out is required", file=sys.stderr)
        return 2

    if cmd == "bundle":
        if not positional:
            print("bundle.py: at least one input PDF required", file=sys.stderr)
            return 2
        for p in positional:
            if not Path(p).is_file():
                print(f"bundle.py: input not found: {p}", file=sys.stderr)
                return 2
        result = bundle(positional, out, title=title)
        print(result)
        return 0

    if cmd == "unbundle":
        if len(positional) != 1:
            print("bundle.py: unbundle takes exactly one input PDF", file=sys.stderr)
            return 2
        if not Path(positional[0]).is_file():
            print(f"bundle.py: input not found: {positional[0]}", file=sys.stderr)
            return 2
        for path in unbundle(positional[0], out):
            print(path)
        return 0

    print(f"bundle.py: unknown command '{cmd}'", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
