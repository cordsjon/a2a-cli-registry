# core/playbooks/signature.py
import hashlib
from sqlmodel import select
from core.models import Cli, Capability
from core.playbooks.skillmd import Playbook


def cli_signature(session, slug: str) -> "str | None":
    cli = session.get(Cli, slug)
    if cli is None:
        return None
    cap = session.exec(
        select(Capability).where(Capability.cli_slug == slug)
    ).first()
    in_types = cap.input_types if cap else ""
    out_types = cap.output_types if cap else ""
    norm_in = ",".join(sorted(t for t in in_types.split(",") if t))
    norm_out = ",".join(sorted(t for t in out_types.split(",") if t))
    payload = f"{norm_in}|{norm_out}".encode()
    return hashlib.sha256(payload).hexdigest()


def playbook_drift(session, pb: Playbook) -> dict:
    missing = []
    for slug in pb.allowed_tools:
        if cli_signature(session, slug) is None:
            missing.append(slug)
    status = "broken" if missing else "ok"
    return {"status": status, "stale_clis": [], "missing_clis": missing}
