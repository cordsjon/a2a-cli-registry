"""Feed enrichment: --help capture -> LLM capability inference -> write into feed.

Component #2 of the registry-bridge epic, production form. The spike (llm_infer.py)
proved one CLI at a time; this enriches a whole feed and is re-runnable offline.

The enrich-at-feed-build decision (handover 2026-06-25): inference happens here,
at feed-build time, and is written into each `clis[]` entry as a `capability`
block tagged confidence="inferred". The registry's CliAuditSource then loads it
honestly (after the line-36 confidence fix), merge_capabilities lets any genuine
declared capability override, and compute_edges forms chain edges from the typed
ports. Without this pass every CLI has null capability -> plan_cli_chain has no
edges.

Design constraints (load-bearing):
  - --help capture is the slow/risky step (arbitrary file imports). We run it ONLY
    on entries marked healthy by the audit, with a short per-CLI timeout, and we
    CACHE results keyed by (path, mtime) so reruns skip unchanged CLIs. This makes
    the pass resumable and token-frugal (local-first tenet).
  - Abstention is honest: if --help yields nothing OR the LLM returns empty
    intent_tags, we write NO capability block (null), so no false edge forms.
  - Atomic write: tempfile + os.replace, never a partial feed on disk.
  - Local router only (deepseek-v4-flash) — zero paid-API cost.
"""
from __future__ import annotations

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from bridge.llm_infer import capture_help, infer_llm_capability

# Audit health marker for entries safe to invoke --help on. Unhealthy/BUG CLIs
# crash on --help; skip them rather than burn a timeout per crash.
_HEALTHY = "healthy"

# Per-CLI --help timeout (seconds). Conservative: a CLI whose --help hangs past
# this is treated as "no help" and abstained on, not retried.
_HELP_TIMEOUT = 5

# Default cache location. Keyed by (path, mtime) -> {help, capability}. JSON so
# it is inspectable and survives across runs.
_DEFAULT_CACHE = Path.home() / ".hermes" / "cli-registry-enrich-cache.json"


def _cache_key(path: str) -> str:
    """(path, mtime) so an edited CLI re-enriches but an unchanged one is reused."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    return f"{path}::{mtime}"


def _load_cache(cache_path: Path) -> dict:
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_write_json(target: Path, obj: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _enrich_one(entry: dict, cache: dict) -> tuple[str, dict | None, bool]:
    """Return (cache_key, capability_dict_or_None, used_cache).

    capability_dict is None when we abstain (no help, or LLM found no signal).
    Pure w.r.t. the entry — caller writes the result back. Safe to thread.
    """
    path = entry.get("path", "")
    key = _cache_key(path)
    if key in cache:
        return key, cache[key].get("capability"), True

    help_text = capture_help(path, timeout=_HELP_TIMEOUT)
    if not help_text.strip():
        return key, None, False

    rec = infer_llm_capability(entry.get("slug", ""), help_text)
    # Abstain on empty/None: no signal -> no capability block -> no false edge.
    if rec is None or not rec.intent_tags:
        return key, None, False
    return key, asdict(rec), False


def enrich_feed(
    feed: dict,
    *,
    cache_path: Path = _DEFAULT_CACHE,
    healthy_only: bool = True,
    max_workers: int = 6,
    limit: int | None = None,
    progress=None,
) -> dict:
    """Enrich a feed dict in place and return stats.

    healthy_only: only invoke --help on audit-healthy entries (recommended).
    limit: cap the number of CLIs processed this run (for incremental passes).
    progress: optional callable(done, total, slug) for a progress line.
    """
    clis = feed.get("clis", [])
    targets = [
        c for c in clis
        if (not healthy_only or c.get("_audit_health") == _HEALTHY)
        and c.get("path")
    ]
    if limit is not None:
        targets = targets[:limit]

    cache = _load_cache(cache_path)
    stats = {"targets": len(targets), "enriched": 0, "abstained": 0, "from_cache": 0}

    by_slug = {c.get("slug"): c for c in clis}
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_enrich_one, c, cache): c for c in targets}
        for fut in as_completed(futures):
            entry = futures[fut]
            try:
                key, cap, used_cache = fut.result()
            except Exception as exc:  # one CLI failing must not abort the batch
                cap, used_cache, key = None, False, _cache_key(entry.get("path", ""))
                if progress:
                    progress(done, len(targets), f"ERR {entry.get('slug')}: {exc}")
            if used_cache:
                stats["from_cache"] += 1
            cache[key] = {"capability": cap}
            target = by_slug.get(entry.get("slug"))
            if cap is not None:
                target["capability"] = cap
                stats["enriched"] += 1
            else:
                stats["abstained"] += 1
            done += 1
            if progress:
                progress(done, len(targets), entry.get("slug", ""))

    _atomic_write_json(cache_path, cache)
    return stats


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Enrich a registry feed with LLM-inferred capability")
    ap.add_argument("feed_json", help="Path to the feed JSON to enrich (modified in place)")
    ap.add_argument("-o", "--out", help="Output path (default: overwrite input)")
    ap.add_argument("--all", action="store_true", help="Process all entries, not just audit-healthy")
    ap.add_argument("--limit", type=int, default=None, help="Cap CLIs processed this run")
    ap.add_argument("--workers", type=int, default=6, help="Concurrent --help+LLM workers")
    ap.add_argument("--cache", default=str(_DEFAULT_CACHE), help="Cache JSON path")
    args = ap.parse_args(argv)

    feed_path = Path(args.feed_json)
    feed = json.loads(feed_path.read_text(encoding="utf-8"))

    def _progress(done, total, slug):
        print(f"  [{done}/{total}] {slug}", flush=True)

    stats = enrich_feed(
        feed,
        cache_path=Path(args.cache),
        healthy_only=not args.all,
        max_workers=args.workers,
        limit=args.limit,
        progress=_progress,
    )
    out = Path(args.out) if args.out else feed_path
    _atomic_write_json(out, feed)
    print(
        f"enriched {stats['enriched']}/{stats['targets']} "
        f"(abstained {stats['abstained']}, from-cache {stats['from_cache']}) -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
