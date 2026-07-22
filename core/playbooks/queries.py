# core/playbooks/queries.py
from core.playbooks.loader import load_playbooks
from core.playbooks.index import rebuild_index, retrieve, stale_against_index
from core.playbooks.signature import playbook_drift

PLAYBOOKS_ROOT = "playbooks"


def _drift(session, pb) -> dict:
    d = playbook_drift(session, pb)            # broken/missing
    if d["status"] == "ok":
        stale = stale_against_index(session, pb)
        if stale:
            return {"status": "stale", "stale_clis": stale, "missing_clis": []}
    return d


def _ensure_index(session, playbooks):
    rebuild_index(session, playbooks)          # cheap; idempotent for a small set


def _step_dicts(pb):
    return [
        {"id": st.id, "cli": st.cli, "inputs": st.inputs, "out_type": st.out_type}
        for st in pb.steps
    ]


def list_playbooks(session, query: str = "") -> dict:
    pbs = load_playbooks(PLAYBOOKS_ROOT)
    _ensure_index(session, pbs)
    if query.strip():
        keep = set(retrieve(session, query, limit=len(pbs)))
        pbs = [p for p in pbs if p.slug in keep]
    return {
        "playbooks": [
            {
                "slug": p.slug,
                "description": p.description,
                "tags": list(p.tags),
                "status": p.status,
                "drift": _drift(session, p),
            }
            for p in pbs
        ]
    }


def _candidate_dict(session, p) -> dict:
    return {
        "slug": p.slug,
        "description": p.description,
        "tags": list(p.tags),
        "status": p.status,
        "steps": _step_dicts(p),
        "drift": _drift(session, p),
    }


def suggest_playbook(session, goal: str, limit: int = 3) -> dict:
    pbs = load_playbooks(PLAYBOOKS_ROOT)
    _ensure_index(session, pbs)
    by_slug = {p.slug: p for p in pbs}
    ranked = retrieve(session, goal, limit=limit)
    candidates = [_candidate_dict(session, by_slug[s]) for s in ranked if s in by_slug]
    return {"goal": goal, "candidates": candidates}


def get_playbook(session, slug: str) -> "dict | None":
    pbs = load_playbooks(PLAYBOOKS_ROOT)
    _ensure_index(session, pbs)
    for p in pbs:
        if p.slug == slug:
            return _candidate_dict(session, p)
    return None
