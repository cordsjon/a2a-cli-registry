# core/cli/main.py
import argparse
import json
import os
import subprocess
import sys
import time

try:
    import tomllib as _toml          # py3.11+
except ModuleNotFoundError:          # pragma: no cover
    import tomli as _toml

from core.store.db import init_db, get_session, with_file_lock
from core.prober.prober import probe_fleet
from core.catalog import queries
from core.discovery.cli_audit_source import CliAuditSource
from core.adapters.python_adapter import PythonAdapter
from core.adapters.stub_adapter import StubAdapter
from core.vocabulary import VocabularyRegistry
from core.populate import populate


def _adapters():
    """The language adapters every mutating command dispatches through.

    PythonAdapter infers from --help; StubAdapter supplies declared-only
    health_cmd for go/node/shell. Both populate AND probe must use the same
    set so a CLI that populate accepts is also one probe can health-check —
    otherwise non-Python CLIs silently stay 'unknown' after a probe sweep.
    """
    return [PythonAdapter(), StubAdapter()]


def _db_lock_path(db_path: str) -> str:
    """Sidecar lock file serializing mutating commands on one registry DB.

    A separate <db>.lock file (not the DB file itself) keeps the advisory lock
    independent of SQLite's own file handling, and lets the lock be held BEFORE
    init_db so two first-run commands cannot race schema creation, and a probe
    sweep cannot interleave with a populate's delete/insert.
    """
    return db_path + ".lock"


def load_config(path: str) -> dict:
    with open(path, "rb") as fh:
        return _toml.load(fh)


class _RealClock:
    def now(self) -> float:
        return time.time()


def _build_source_and_vocab(config_path: str):
    cfg = load_config(config_path)
    src = CliAuditSource(cfg["cli_audit_path"])
    vocab_cfg = cfg.get("vocabulary", {})
    vocab = VocabularyRegistry(
        registered=set(vocab_cfg.get("registered", [])),
        aliases=vocab_cfg.get("aliases", {}),
    )
    return cfg, src, vocab


# populate()'s own default; mirrored here so an absent config key behaves
# identically to calling populate() with no threshold override.
_DEFAULT_MASS_REMOVAL = 0.30


def _mass_removal_threshold(cfg: dict) -> float:
    """Read the populate mass-removal guard from config, falling back to
    populate()'s own default when [thresholds].mass_removal is absent.

    Keeps config optional: a config without a [thresholds] section still works.
    """
    return cfg.get("thresholds", {}).get("mass_removal", _DEFAULT_MASS_REMOVAL)


_PROBE_DEFAULTS = {"probe_timeout": 10.0, "max_probe_output_bytes": 65536,
                   "probe_concurrency": 8, "staleness_ttl": 3600}


def _probe_config(cfg: dict) -> dict:
    """Read the [probe] table, falling back to code defaults per key."""
    p = cfg.get("probe", {})
    return {k: p.get(k, d) for k, d in _PROBE_DEFAULTS.items()}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="a2a-cli-registry")
    parser.add_argument(
        "command",
        choices=["audit", "discover", "populate", "lifecycle", "serve",
                 "graph", "probe", "overview", "okf-produce", "okf-ingest",
                 "remediate"],
    )
    parser.add_argument("--db", default="registry.db")
    parser.add_argument("--config", default="examples/reference-fleet/config.toml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--strict-port", action="store_true",
        help="[serve] fail if --port is in use instead of auto-selecting the "
             "next free port",
    )
    parser.add_argument("--query", default="")
    parser.add_argument("--out", default="./bundle",
                        help="[okf-produce] output directory for the bundle")
    parser.add_argument("--bundle", default="./bundle",
                        help="[okf-ingest] input bundle directory to read from")
    parser.add_argument("--file", action="store_true",
                        help="[remediate] actually file Paperclip issues (default: dry-run)")
    parser.add_argument("--apply-safe", action="store_true",
                        help="[remediate] arm SafeFixer (MVP: errors, NotImplementedError)")
    parser.add_argument("--max-llm-calls", type=int, default=0,
                        help="[remediate] Hermes diagnosis batch cap (default 0 = skip Hermes)")
    args, _rest = parser.parse_known_args(argv)

    if args.command == "discover":
        # A pure --dry-run discover only LISTS; it must not create registry.db.
        # Defer init_db until we actually write.
        _cfg, src, vocab = _build_source_and_vocab(args.config)
        records = src.discover()
        for r in records:
            print(r.slug)
        if not args.dry_run:
            with with_file_lock(_db_lock_path(args.db)):
                engine = init_db(args.db)
                with get_session(engine) as session:
                    populate(session, src, _adapters(), vocab, _RealClock(),
                             mass_removal_threshold=_mass_removal_threshold(_cfg))
        return 0

    if args.command in ("audit", "lifecycle"):
        # Still pending — fail loudly BEFORE init_db so we never leave an empty
        # registry.db behind for a command that did nothing.
        print(f"{args.command}: not implemented in v1.0 (tracked for a follow-up)",
              file=sys.stderr)
        return 2

    if args.command == "okf-produce":
        # Read-only export: no lock needed, creates its own engine.
        from core.okf import produce_bundle
        engine = init_db(args.db)
        with get_session(engine) as session:
            result = produce_bundle(session, args.out)
        print(f"okf-produce: wrote {result['concepts']} concept(s) to {args.out}",
              file=sys.stderr)
        return 0

    if args.command == "okf-ingest":
        # Mutating: acquire the sidecar lock BEFORE init_db so schema creation
        # cannot race a concurrent first-run command (mirrors discover/populate).
        from core.okf import ingest_bundle
        with with_file_lock(_db_lock_path(args.db)):
            engine = init_db(args.db)
            with get_session(engine) as session:
                result = ingest_bundle(session, args.bundle)
        print(f"okf-ingest: updated {result['updated']}, skipped {result['skipped']}, "
              f"failed {result['failed']}", file=sys.stderr)
        return 1 if result["failed"] else 0

    if args.command == "remediate":
        import uuid
        from core.remediation.run import run_remediate
        from core.remediation.hermes_adapter import HermesAdapter
        # remediate-specific --out default: --out still defaults to ./bundle
        # (okf-produce's default), so substitute ./proposals.json when unset.
        out_path = "./proposals.json" if args.out == "./bundle" else args.out
        # DB-read failure -> exit 2 BEFORE writing any proposals.json (spec §6).
        try:
            engine = init_db(args.db)
            with get_session(engine) as session:
                from core.remediation.run import read_unhealthy
                read_unhealthy(session)  # force a read; surfaces a corrupt/unreadable DB
        except Exception as exc:   # narrow: DB open/read is the only thing here
            print(f"remediate: cannot read DB: {exc}", file=sys.stderr)
            return 2
        # Close the create_all column gap: an existing DB predates Cli.fixed_by,
        # which create_all never adds to a table that already exists (the armed
        # SafeFixer writes fixed_by on a successful fix).
        from core.store.migrations import ensure_fixed_by_column
        ensure_fixed_by_column(args.db)
        sid = str(uuid.uuid4())
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        hermes = HermesAdapter() if args.max_llm_calls > 0 else None
        # SafeFixer is ARMED: when --apply-safe is set it runs real wheel-only
        # installs into an isolated demo/ venv and re-probes (spec §3.4).
        safe_fixer = None
        if args.apply_safe:
            from core.remediation.safe_fixer import SafeFixer
            safe_fixer = SafeFixer(demo_dir="demo")
        summary = None
        try:
            with get_session(engine) as session:
                summary = run_remediate(
                    session, out_path=out_path, do_file=args.file,
                    apply_safe=args.apply_safe, max_llm_calls=args.max_llm_calls,
                    session_id=sid, generated_at=generated_at, hermes=hermes,
                    safe_fixer=safe_fixer)
        except OSError as exc:
            # proposals.json write failure (disk/permission): summary lost, but
            # surface clearly and exit 4 (spec §6).
            print(f"remediate: failed to write proposals: {exc}", file=sys.stderr)
            return 4
        except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            # paperclip.sh failed during --file filing. proposals.json was already
            # written (write happens before filing), so the deterministic findings
            # survive; report and exit 0.
            print(f"remediate: warning: Paperclip filing error: {exc}", file=sys.stderr)
            print(f"remediate: wrote {out_path}; issues_filed=0 (filing failed)",
                  file=sys.stderr)
            return 0
        print(json.dumps(summary["counts"]))
        print(f"remediate: wrote {out_path}; issues_filed={summary['issues_filed']}",
              file=sys.stderr)
        if summary["apply_safe_requested"]:
            print(f"remediate: --apply-safe applied {summary['fixes_applied']} fix(es)",
                  file=sys.stderr)
        return 0

    engine = init_db(args.db)

    if args.command == "serve":
        import uvicorn
        from core.server.app import create_app
        from core.server.portmanager import resolve_port, NoFreePortError
        from core.store.db import session_factory
        # Resolve the bind port BEFORE deriving A2A_BASE_URL: on a busy box the
        # requested port is often taken (e.g. dagu on 8080), so unless
        # --strict-port is set we auto-select the next free port. Everything
        # downstream (base_url, agent card, MCP allowed-hosts) must reference the
        # port we ACTUALLY bind, not the one originally requested.
        try:
            bind_port = resolve_port(args.host, args.port, strict=args.strict_port)
        except NoFreePortError as exc:
            print(f"serve: {exc}", file=sys.stderr)
            return 2
        if bind_port != args.port:
            print(f"serve: port {args.port} in use; bound {bind_port} instead",
                  file=sys.stderr)
        # Make the running server internally consistent with --host/bind_port.
        # Precedence: an explicit A2A_BASE_URL (e.g. a public URL behind a proxy)
        # always wins; otherwise derive it from --host/bind_port so BOTH the agent
        # card (core/server/app.py) AND the MCP allowed-hosts (core/mcp/http.py,
        # read at create_app time) point at the address we actually bind.
        # "0.0.0.0" is a bind-all address, not a reachable client address, so the
        # derived base_url substitutes localhost for it.
        if "A2A_BASE_URL" not in os.environ:
            reachable_host = "localhost" if args.host == "0.0.0.0" else args.host
            os.environ["A2A_BASE_URL"] = f"http://{reachable_host}:{bind_port}"
        # Per-request REST sessions + a build-time MCP session, both managed by
        # the app from this factory. The engine outlives the call via init_db.
        app = create_app(session_factory(engine))
        uvicorn.run(app, host=args.host, port=bind_port)
        return 0

    if args.command == "populate":
        _cfg, src, vocab = _build_source_and_vocab(args.config)
        with with_file_lock(_db_lock_path(args.db)):
            with get_session(engine) as session:
                result = populate(session, src, _adapters(), vocab, _RealClock(),
                                  mass_removal_threshold=_mass_removal_threshold(_cfg))
                edges = len(queries.cli_graph(session))
        print(json.dumps({
            "added": result["added"],
            "removed": result["removed"],
            "edges": edges,
        }))
        return 0

    if args.command == "probe":
        cfg = load_config(args.config)
        pc = _probe_config(cfg)
        # Same sidecar lock as populate: serialize the sweep against a
        # concurrent populate's delete/insert so probe never commits stale rows.
        with with_file_lock(_db_lock_path(args.db)):
            with get_session(engine) as session:
                summary = probe_fleet(
                    session, _adapters(), _RealClock(),
                    concurrency=pc["probe_concurrency"],
                    probe_timeout=pc["probe_timeout"],
                    max_output_bytes=pc["max_probe_output_bytes"],
                    staleness_ttl=pc["staleness_ttl"],
                )
        print(json.dumps(summary))
        return 0

    if args.command == "overview":
        from core.tui.overview import render_overview
        with get_session(engine) as session:
            rows = queries.search_clis(session, args.query)
            for r in rows:
                desc = queries.describe_cli(session, r["slug"])
                r["capabilities"] = desc["capabilities"] if desc else []
            graph = queries.cli_graph(session)
        # When --query filters the CLI set, restrict edges to those between
        # shown CLIs — otherwise the edge table references slugs absent from
        # the CLI table above. No query -> all rows shown -> all edges shown.
        shown = {r["slug"] for r in rows}
        graph = [e for e in graph if e["from"] in shown and e["to"] in shown]
        render_overview(rows, graph)
        return 0

    with get_session(engine) as session:
        # Only `graph` reaches here (audit/lifecycle short-circuited above).
        print(json.dumps(queries.cli_graph(session)))
        return 0


if __name__ == "__main__":          # `python -m core.cli.main ...`
    # Propagate the command's exit code (remediate returns 2/3/4) so a shell
    # caller sees it, matching the console-script entry (core.cli.main:main).
    sys.exit(main())
