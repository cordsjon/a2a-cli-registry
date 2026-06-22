# core/cli/main.py
import argparse
import json
import sys

try:
    import tomllib as _toml          # py3.11+
except ModuleNotFoundError:          # pragma: no cover
    import tomli as _toml

from core.store.db import init_db, get_session
from core.catalog import queries


def load_config(path: str) -> dict:
    with open(path, "rb") as fh:
        return _toml.load(fh)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="a2a-cli-registry")
    parser.add_argument("command", choices=["audit", "discover", "populate", "lifecycle", "graph"])
    parser.add_argument("--db", default="registry.db")
    args, _rest = parser.parse_known_args(argv)

    engine = init_db(args.db)
    with get_session(engine) as session:
        if args.command == "graph":
            print(json.dumps(queries.cli_graph(session)))
            return 0
        # other commands wired in their own tasks; default success
        print(f"{args.command}: ok")
        return 0
