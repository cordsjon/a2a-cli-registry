"""Bridge: cli-audit per-file results -> a2a-cli-registry feed JSON.

SPIKE (component #3 of the registry-bridge epic). Proves the *mechanical*
field mapping between the two schemas. Capability inference (component #2,
LLM-per-CLI) is intentionally stubbed here — see `infer_capability`.

Source schema  (cli-audit per-file result, design doc §6):
    {bucket, project, file, invocation, exit_code, stdout, stderr,
     class, fix_applied, fix_diff, fix_result, final_class, backlog_title}

Target schema  (registry feed, tests/golden_clis/fleet.json):
    {schema_version, run_id, clis: [{slug, lang, path, description,
     capability: {intent_tags, input_types, output_types, side_effect}}]}

The target is validated by core.discovery.cli_audit_source.CliAuditSource,
which requires {slug, lang, path} per entry and fails closed otherwise.
"""
from __future__ import annotations

import json
from pathlib import Path

from bridge.standalone import classify_standalone

# Audit health classes that represent a runnable CLI worth listing.
# BUG / TRIVIAL-UNFIXED crash on --help -> not chainable -> excluded.
_USABLE_FINAL_CLASSES = {"PASS", "ENV", "DEP", "TRIVIAL-FIXED", "TRIVIAL"}

_LANG_BY_SUFFIX = {".py": "python", ".go": "go", ".sh": "shell", ".js": "node", ".ts": "node"}


def _slug_from_file(file_path: str) -> str:
    """Derive a stable slug from the file path. The audit has no slug field;
    the registry uses slug as the chaining identity, so we need a deterministic
    one. Stem is the pragmatic choice (main.py -> 'main' is weak, so fall back
    to parent dir when the stem is a generic entrypoint name)."""
    p = Path(file_path)
    stem = p.stem
    if stem in {"main", "__main__", "cli", "app", "server"}:
        # generic entrypoint — qualify with parent dir for a meaningful slug
        return f"{p.parent.name}-{stem}" if p.parent.name else stem
    return stem


def _lang_from_file(file_path: str) -> str:
    return _LANG_BY_SUFFIX.get(Path(file_path).suffix, "unknown")


def infer_capability(record: dict) -> dict | None:
    """STUB for component #2 (LLM-inferred capability per CLI).

    The audit collects *health*, not *capability*. Real implementation will
    feed each CLI's --help output to an LLM to infer intent_tags / input_types /
    output_types / side_effect. Until then we emit None (no capability) so the
    registry lists the tool for discovery+health but does not chain it.

    NOTE: when this is implemented, inferred caps fed through the cli-audit JSON
    path will be mislabeled confidence='declared' by CliAuditSource (line ~36).
    That hardcode must be addressed so inference is honestly tagged.
    """
    return None


def audit_record_to_cli(record: dict) -> dict | None:
    """Map one audit result -> one registry `clis[]` entry, or None to skip."""
    if record.get("final_class") not in _USABLE_FINAL_CLASSES:
        return None
    file_path = record.get("file")
    if not file_path:
        return None
    entry = {
        "slug": _slug_from_file(file_path),
        "lang": _lang_from_file(file_path),
        "path": file_path,
        "description": record.get("backlog_title", "") or record.get("invocation", ""),
    }
    if record.get("project"):
        entry["project"] = record["project"]
    if record.get("bucket"):
        entry["bucket"] = record["bucket"]
    # US-CLIAUDIT-83: statically detect Typer/click sub-apps and no-parser batch
    # scripts. Only stamp the truthy case so standalone CLIs keep byte-identical
    # feed entries (existing golden round-trip assertions stay green).
    if classify_standalone(file_path) != "standalone":
        entry["not_standalone"] = True
    cap = infer_capability(record)
    if cap is not None:
        entry["capability"] = cap
    return entry


def build_feed(audit_records: list[dict], run_id: str) -> dict:
    """Convert a list of audit result records into a registry feed dict."""
    clis = []
    seen_slugs: dict[str, int] = {}
    for rec in audit_records:
        entry = audit_record_to_cli(rec)
        if entry is None:
            continue
        # de-dupe slugs deterministically (audit can have many main.py)
        slug = entry["slug"]
        if slug in seen_slugs:
            seen_slugs[slug] += 1
            entry["slug"] = f"{slug}-{seen_slugs[slug]}"
        else:
            seen_slugs[slug] = 0
        clis.append(entry)
    return {"schema_version": 1, "run_id": run_id, "clis": clis}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Convert cli-audit results JSON to registry feed JSON")
    ap.add_argument("audit_json", help="Path to cli-audit results (a JSON array of per-file records)")
    ap.add_argument("--run-id", default="bridge", help="run_id stamped into the feed")
    ap.add_argument("-o", "--out", help="Output path (default: stdout)")
    args = ap.parse_args(argv)

    records = json.loads(Path(args.audit_json).read_text(encoding="utf-8"))
    if isinstance(records, dict) and "results" in records:
        records = records["results"]
    feed = build_feed(records, run_id=args.run_id)
    out = json.dumps(feed, indent=2)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"wrote {len(feed['clis'])} clis -> {args.out}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
