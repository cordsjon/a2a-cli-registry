"""Grounding probe: is <slug> reachable by the planner, and if not, why?

    python -m core.planner.probe --slug send_mail \
        --goal-inputs text --goal-outputs text [--allow-side-effects network]

Spec grounding kept getting hand-rolled as throwaway `python3 -c` snippets
against the registry DB, which meant every reviewer re-derived the same three
facts by hand. This makes them one reproducible command:

  presence       — is the slug in the Cli table at all, and does it carry
                   Capability rows (a slug with none can never join a chain)
  hop-exclusion  — the _hop_excluded decision for THIS slug under the given
                   --allow-side-effects, i.e. would the fail-UNSAFE prune drop
                   it even if an edge reached it
  position       — for each chain plan_cli_chain returns, the 0-based index of
                   the slug (or absent), so "not in the plan" is distinguished
                   from "in the plan but last"

Exit 0 = the slug appears in at least one planned chain; 1 = it does not
(the grounding claim is false); 2 = the DB could not be read.
"""
import argparse
import json
import sys

from sqlmodel import select

from core.models import Capability, Cli
from core.catalog import queries
from core.planner.search import (
    _hop_excluded, _slug_side_effect, _slug_confidence_rank,
    _slug_produces, _slug_consumes, _slug_intent_tags,
)
from core.store.db import init_db, get_session


def _csv(value) -> list[str]:
    """--goal-inputs text,file:pdf and repeated flags both work."""
    out = []
    for item in value or []:
        out.extend(t.strip() for t in item.split(",") if t.strip())
    return out


def probe(session, slug, goal_inputs, goal_outputs, allow_side_effects=None,
          goal_actions=None, producer_terms=None) -> dict:
    """The three grounding facts for `slug`, as plain data.

    Takes an open session (not a path) so tests drive it against the same
    in-memory fixture DB the rest of the planner tests use.
    """
    allow = set(allow_side_effects or [])
    cli = session.get(Cli, slug)
    caps = session.exec(
        select(Capability).where(Capability.cli_slug == slug)).all()

    presence = {
        "registered": cli is not None,
        "capability_rows": len(caps),
        "health_status": cli.health_status if cli else None,
        "not_standalone": bool(cli.not_standalone) if cli else None,
        "consumes": sorted(_slug_consumes(caps)) if caps else [],
        "produces": sorted(_slug_produces(caps)) if caps else [],
        "intent_tags": sorted(_slug_intent_tags(caps)) if caps else [],
        "side_effect": _slug_side_effect(caps) if caps else None,
        "confidence": ("inferred" if caps and _slug_confidence_rank(caps)
                       else "declared" if caps else None),
    }

    # _hop_excluded needs at least one Capability row; a slug with none is not
    # "allowed", it is simply invisible to the planner — report that, don't
    # call into the prune with an empty list and get a misleading False.
    if caps:
        excluded = _hop_excluded(caps, allow)
        reason = ("side_effect %r not in allow_side_effects" % presence["side_effect"]
                  if excluded else "passes the fail-UNSAFE prune")
    else:
        excluded = True
        reason = "no Capability rows — never a candidate hop"

    chains = queries.plan_cli_chain(
        session, goal_inputs, goal_outputs, sorted(allow),
        goal_actions=goal_actions or [], producer_terms=producer_terms or [])
    positions = []
    for i, ch in enumerate(chains):
        if slug in ch["slugs"]:
            positions.append({"chain_index": i, "position": ch["slugs"].index(slug),
                              "length": ch["length"], "slugs": ch["slugs"]})

    return {
        "slug": slug,
        "goal_inputs": list(goal_inputs),
        "goal_outputs": list(goal_outputs),
        "allow_side_effects": sorted(allow),
        "presence": presence,
        "hop_excluded": {"excluded": excluded, "reason": reason},
        "chains_planned": len(chains),
        "positions": positions,
        "reachable": bool(positions),
    }


def _render(result) -> str:
    p = result["presence"]
    lines = [
        f"slug            : {result['slug']}",
        f"goal            : {result['goal_inputs']} -> {result['goal_outputs']}"
        f"  allow={result['allow_side_effects'] or '[]'}",
        f"presence        : registered={p['registered']} "
        f"capability_rows={p['capability_rows']} health={p['health_status']}",
        f"                  consumes={p['consumes']} produces={p['produces']}",
        f"                  side_effect={p['side_effect']} ({p['confidence']}) "
        f"intent_tags={p['intent_tags']}",
        f"hop-exclusion   : excluded={result['hop_excluded']['excluded']} "
        f"({result['hop_excluded']['reason']})",
        f"chains planned  : {result['chains_planned']}",
    ]
    if result["positions"]:
        for pos in result["positions"]:
            lines.append(f"position        : chain[{pos['chain_index']}] "
                         f"hop {pos['position']}/{pos['length'] - 1} "
                         f"{' -> '.join(pos['slugs'])}")
    else:
        lines.append("position        : ABSENT from every planned chain")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m core.planner.probe",
        description=__doc__.splitlines()[0])
    ap.add_argument("--slug", required=True)
    ap.add_argument("--goal-inputs", action="append", default=[],
                    help="typed port(s); comma-separated or repeated")
    ap.add_argument("--goal-outputs", action="append", default=[],
                    help="typed port(s); comma-separated or repeated")
    ap.add_argument("--allow-side-effects", action="append", default=[],
                    help="side-effect class(es) to opt into (fail-UNSAFE default)")
    ap.add_argument("--goal-actions", action="append", default=[],
                    help="final action verb (at most one, per spec §7)")
    ap.add_argument("--producer-terms", action="append", default=[])
    ap.add_argument("--db", default="registry.db")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    try:
        engine = init_db(args.db)
        with get_session(engine) as session:
            result = probe(session, args.slug,
                           _csv(args.goal_inputs), _csv(args.goal_outputs),
                           allow_side_effects=_csv(args.allow_side_effects),
                           goal_actions=_csv(args.goal_actions),
                           producer_terms=_csv(args.producer_terms))
    except (OSError, ValueError) as exc:
        # ValueError covers plan_chain's >1 action-verb guard; OSError a bad --db.
        print(f"probe: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2) if args.json else _render(result))
    return 0 if result["reachable"] else 1


if __name__ == "__main__":
    sys.exit(main())
