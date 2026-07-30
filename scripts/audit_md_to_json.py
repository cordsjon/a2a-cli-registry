"""Wiki `all-clis.md` markdown table -> cli-audit JSON records (and, optionally,
a registry feed).

The governance wiki export (`00_Governance/wiki/export_md/cli-tools/all-clis.md`)
is the fleet's audit of record, but it is a 474-row markdown table — not JSON.
Every session that wanted to seed the registry from it re-wrote the same
throwaway parser. This is that parser, once.

Output is the *cli-audit per-file result* schema that
`bridge.audit_to_registry.build_feed` already consumes, so this script does not
duplicate the audit -> feed mapping; `--feed` just chains into it.

Table shape (one table per `## <project>` section):

    | File | Invocation | Status | Notes |
    |------|-----------|--------|-------|
    | `70_X/tool.py` | `timeout 5 python3 ... --help` | PASS | - |

Rows in any other table (e.g. the leading Summary table) are ignored, so the
status counts at the top of the wiki page never leak into the records.

Exit 0 = parsed; 2 = unreadable source or an unrecognized status class.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Audit health classes the wiki table is allowed to carry. An unknown class is a
# fail-closed error, not a silent drop: a renamed status upstream must be seen.
_STATUS_CLASSES = {"PASS", "ENV", "DEP", "TRIVIAL-FIXED", "TRIVIAL-UNFIXED", "BUG"}

_HEADER_CELLS = ["file", "invocation", "status", "notes"]

# Placeholder characters the wiki uses for "nothing to report".
_EMPTY_NOTES = {"", "-", "—", "--"}

_SEPARATOR_RE = re.compile(r"^[\s|:-]+$")


def _cells(line: str) -> list[str]:
    """Split a markdown table row into its cells (outer pipes dropped)."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _unquote(cell: str) -> str:
    return cell.strip().strip("`").strip()


def normalize_status(cell: str) -> str:
    """`🔧 TRIVIAL fixed` -> `TRIVIAL-FIXED`. Emoji and spacing are cosmetic."""
    ascii_only = "".join(ch for ch in cell if ch.isascii())
    return "-".join(ascii_only.split()).upper()


def parse_markdown(text: str, root: str | None = None) -> list[dict]:
    """Parse the wiki export into cli-audit per-file records.

    `root` prefixes the (repo-relative) File column so downstream probing gets
    absolute paths — the registry resolves nothing on its own.
    """
    records: list[dict] = []
    project = ""
    in_table = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line.startswith("## "):
            project = line[3:].strip()
            in_table = False
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = _cells(line)
        if [c.lower() for c in cells] == _HEADER_CELLS:
            in_table = True
            continue
        if not in_table or _SEPARATOR_RE.match(line):
            continue
        if len(cells) < 4:
            continue
        file_path = _unquote(cells[0])
        if not file_path:
            continue
        status = normalize_status(cells[2])
        if status not in _STATUS_CLASSES:
            raise ValueError(
                f"line {lineno}: unrecognized status {status!r} "
                f"(known: {sorted(_STATUS_CLASSES)})"
            )
        notes = _unquote(cells[3])
        records.append({
            "project": project,
            "file": str(Path(root) / file_path) if root else file_path,
            "invocation": _unquote(cells[1]),
            "class": status,
            "final_class": status,
            # The wiki's Notes column is the failure reason for ENV/DEP/BUG rows
            # and a placeholder otherwise. Carry it as stderr; do NOT promote it
            # to backlog_title, or it becomes the CLI's description downstream.
            "stderr": "" if notes in _EMPTY_NOTES else notes,
        })
    return records


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("markdown", help="path to all-clis.md (wiki export)")
    ap.add_argument("--root", default=None,
                    help="prefix for relative File paths (e.g. ~/projects)")
    ap.add_argument("--feed", action="store_true",
                    help="emit a registry feed instead of raw audit records")
    ap.add_argument("--run-id", default="wiki-audit",
                    help="[--feed] run_id stamped into the feed")
    ap.add_argument("-o", "--out", help="output path (default: stdout)")
    args = ap.parse_args(argv)

    try:
        text = Path(args.markdown).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: cannot read {args.markdown}: {exc}", file=sys.stderr)
        return 2

    root = str(Path(args.root).expanduser()) if args.root else None
    try:
        records = parse_markdown(text, root=root)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.feed:
        from bridge.audit_to_registry import build_feed
        payload = build_feed(records, run_id=args.run_id)
        count = len(payload["clis"])
        label = "cli(s) in feed"
    else:
        payload = records
        count = len(records)
        label = "audit record(s)"

    out = json.dumps(payload, indent=2)
    if args.out:
        tmp = Path(args.out).with_suffix(Path(args.out).suffix + ".tmp")
        tmp.write_text(out, encoding="utf-8")
        tmp.replace(args.out)
        print(f"wrote {count} {label} -> {args.out}", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
