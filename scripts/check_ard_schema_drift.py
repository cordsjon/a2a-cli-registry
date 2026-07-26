"""US-8: detect upstream ARD schema drift vs the vendored byte-identical copy.

Exit 0 = identical; 1 = drift (changed top-level paths printed); 2 = fetch error.
Prints the vendored copy's retrieval date (from the provenance sidecar) so the
pin's age is visible (AC-8.2).

Operator note: intended as a periodic (e.g. weekly) job alongside
qmd_health_check. Registering that job is an operator step outside this repo.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

UPSTREAM_URL = ("https://raw.githubusercontent.com/ards-project/ard-spec/"
                "main/spec/schemas/ai-catalog.schema.json")
VENDORED = Path(__file__).resolve().parent.parent / "tests/fixtures/ai-catalog.schema.json"


def compare_schemas(vendored: dict, upstream: dict, prefix: str = "") -> list[str]:
    """Changed dotted paths, one level of detail past the divergence point."""
    changed = []
    keys = set(vendored) | set(upstream)
    for k in sorted(keys):
        path = f"{prefix}.{k}" if prefix else k
        if k not in vendored or k not in upstream:
            changed.append(path)
        elif isinstance(vendored[k], dict) and isinstance(upstream[k], dict):
            changed.extend(compare_schemas(vendored[k], upstream[k], path))
        elif vendored[k] != upstream[k]:
            changed.append(path)
    return changed


def _load(path_or_url: str) -> dict:
    if path_or_url.startswith(("http://", "https://")):
        with urllib.request.urlopen(path_or_url, timeout=15) as resp:
            return json.loads(resp.read(2_000_000))
    return json.loads(Path(path_or_url).read_text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendored", default=str(VENDORED))
    ap.add_argument("--upstream-json", default=UPSTREAM_URL)
    args = ap.parse_args(argv)
    prov = Path(args.vendored).with_name("ai-catalog.schema.provenance.md")
    if prov.exists():
        m = re.search(r"Retrieved:\s*(\S+)", prov.read_text())
        if m:
            print(f"vendored copy retrieved: {m.group(1)}")
    try:
        vendored = _load(args.vendored)
        upstream = _load(args.upstream_json)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"drift-check: fetch/parse failed: {e}", file=sys.stderr)
        return 2
    changed = compare_schemas(vendored, upstream)
    if not changed:
        print("no drift: vendored schema matches upstream")
        return 0
    print("DRIFT — changed paths:")
    for p in changed:
        print(f"  {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
