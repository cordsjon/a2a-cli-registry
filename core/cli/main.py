# core/cli/main.py
import argparse
import json
import os
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


def _mass_removal_threshold(cfg: dict) -> float:
    """Read the populate mass-removal guard from config, falling back to
    populate()'s own default when [thresholds].mass_removal is absent.

    Keeps config optional: a config without a [thresholds] section still works.
    """
    return cfg.get("thresholds", {}).get("mass_removal", _DEFAULT_MASS_REMOVAL)


# populate()'s own default; mirrored here so an absent config key behaves
# identically to calling populate() with no threshold override.
_DEFAULT_MASS_REMOVAL = 0.30


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
                populate(session, src, [PythonAdapter()], vocab, _RealClock(),
                         mass_removal_threshold=_mass_removal_threshold(_cfg))
        return 0

    if args.command in ("audit", "lifecycle"):
        # Still pending — fail loudly BEFORE init_db so we never leave an empty
        # registry.db behind for a command that did nothing.
        print(f"{args.command}: not implemented in v1.0 (tracked for a follow-up)",
              file=sys.stderr)
        return 2

    engine = init_db(args.db)

    if args.command == "serve":
        import uvicorn
        from core.server.app import create_app
        from core.store.db import session_factory
        # Make the running server internally consistent with --host/--port.
        # Precedence: an explicit A2A_BASE_URL (e.g. a public URL behind a proxy)
        # always wins; otherwise derive it from --host/--port so BOTH the agent
        # card (core/server/app.py) AND the MCP allowed-hosts (core/mcp/http.py,
        # read at create_app time) point at the address we actually bind.
        # "0.0.0.0" is a bind-all address, not a reachable client address, so the
        # derived base_url substitutes localhost for it.
        if "A2A_BASE_URL" not in os.environ:
            reachable_host = "localhost" if args.host == "0.0.0.0" else args.host
            os.environ["A2A_BASE_URL"] = f"http://{reachable_host}:{args.port}"
        # Per-request REST sessions + a build-time MCP session, both managed by
        # the app from this factory. The engine outlives the call via init_db.
        app = create_app(session_factory(engine))
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    if args.command == "populate":
        _cfg, src, vocab = _build_source_and_vocab(args.config)
        with get_session(engine) as session:
            result = populate(session, src, [PythonAdapter()], vocab, _RealClock(),
                              mass_removal_threshold=_mass_removal_threshold(_cfg))
            edges = len(queries.cli_graph(session))
        print(json.dumps({
            "added": result["added"],
            "removed": result["removed"],
            "edges": edges,
        }))
        return 0

    with get_session(engine) as session:
        # Only `graph` reaches here (audit/lifecycle short-circuited above).
        print(json.dumps(queries.cli_graph(session)))
        return 0
