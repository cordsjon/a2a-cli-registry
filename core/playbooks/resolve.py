# core/playbooks/resolve.py
import json
from sqlmodel import select
from core.models import Cli, Capability
from core.playbooks.loader import load_playbooks
from core.playbooks.index import rebuild_index
from core.playbooks.queries import _drift  # reuse the broken/stale/ok logic

PLAYBOOKS_ROOT = "playbooks"

_HIDDEN_SIDE_EFFECTS = {"none", "unknown", ""}


def _launch_spec(session, slug: str) -> dict:
    cli = session.get(Cli, slug)
    if cli is None or not cli.launch_spec:
        return {}
    try:
        return json.loads(cli.launch_spec)
    except (json.JSONDecodeError, TypeError):
        return {}


def _side_effect(session, slug: str) -> str:
    cap = session.exec(
        select(Capability).where(Capability.cli_slug == slug)
    ).first()
    return cap.side_effect if cap else "unknown"


def resolve_playbook(session, slug: str) -> "dict | None":
    pbs = load_playbooks(PLAYBOOKS_ROOT)
    rebuild_index(session, pbs)
    pb = next((p for p in pbs if p.slug == slug), None)
    if pb is None:
        return None

    drift = _drift(session, pb)
    plan = [
        {
            "step_id": st.id,
            "cli": st.cli,
            "launch_spec": _launch_spec(session, st.cli),
            "inputs": st.inputs,
            "out_type": st.out_type,
        }
        for st in pb.steps
    ]
    effects = []
    for slug_ in pb.allowed_tools:
        eff = _side_effect(session, slug_)
        if eff not in _HIDDEN_SIDE_EFFECTS and eff not in effects:
            effects.append(eff)

    return {
        "slug": pb.slug,
        "runnable": drift["status"] != "broken",
        "drift": drift,
        "plan": plan,
        "side_effects": effects,
    }
