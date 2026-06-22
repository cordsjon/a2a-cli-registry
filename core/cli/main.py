# core/cli/main.py
import argparse
import json
import sys
import time

try:
    import tomllib as _toml          # py3.11+
except ModuleNotFoundError:          # pragma: no cover
    import tomli as _toml

from core.store.db import init_db, get_session
from core.catalog import queries
from core.discovery.cli_audit_source import CliAuditSource
from core.adapters.python_adapter import PythonAdapter
from core.vocabulary import VocabularyRegistry
from core.populate import populate


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


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="a2a-cli-registry")
    parser.add_argument(
        "command",
        choices=["audit", "discover", "populate", "lifecycle", "serve", "graph"],
    )
    parser.add_argument("--db", default="registry.db")
    parser.add_argument("--config", default="examples/reference-fleet/config.toml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args, _rest = parser.parse_known_args(argv)

    if args.command == "discover":
        # A pure --dry-run discover only LISTS; it must not create registry.db.
        # Defer init_db until we actually write.
        _cfg, src, vocab = _build_source_and_vocab(args.config)
        records = src.discover()
        for r in records:
            print(r.slug)
        if not args.dry_run:
            engine = init_db(args.db)
            with get_session(engine) as session:
                populate(session, src, [PythonAdapter()], vocab, _RealClock())
        return 0

    engine = init_db(args.db)

    if args.command == "serve":
        import uvicorn
        from core.server.app import create_app
        from core.store.db import session_factory
        # Per-request REST sessions + a build-time MCP session, both managed by
        # the app from this factory. The engine outlives the call via init_db.
        app = create_app(session_factory(engine))
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    if args.command == "populate":
        _cfg, src, vocab = _build_source_and_vocab(args.config)
        with get_session(engine) as session:
            result = populate(session, src, [PythonAdapter()], vocab, _RealClock())
            edges = len(queries.cli_graph(session))
        print(json.dumps({
            "added": result["added"],
            "removed": result["removed"],
            "edges": edges,
        }))
        return 0

    with get_session(engine) as session:
        if args.command == "graph":
            print(json.dumps(queries.cli_graph(session)))
            return 0
        # audit / lifecycle still pending — fail loudly, do not pretend success
        print(f"{args.command}: not implemented in v1.0 (tracked for a follow-up)",
              file=sys.stderr)
        return 2
