"""Remediate orchestration (spec §5). Default invocation is read-only w.r.t. the
DB and external systems: it classifies already-persisted failure notes and writes
exactly one local artifact (proposals.json), atomically. Hermes and Paperclip are
opt-in. SafeFixer is stubbed."""
import json
import os
import tempfile

from sqlmodel import select

from core.models import Cli
from core.remediation.classify import classify_fleet, MAP_VERSION
from core.remediation.proposal import build_envelope, FailureClass
from core.remediation.paperclip_adapter import PaperclipAdapter


def write_proposals(envelope: dict, out_path: str) -> None:
    """Atomic write (tempfile + os.replace), mirroring core/okf/serialize."""
    directory = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(envelope, fh, indent=2, sort_keys=True)
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_unhealthy(session) -> list:
    return list(session.exec(select(Cli).where(Cli.health_status == "unhealthy")).all())


def run_remediate(session, *, out_path, do_file, apply_safe, max_llm_calls,
                  session_id, generated_at, hermes=None, paperclip=None,
                  safe_fixer=None) -> dict:
    rows = read_unhealthy(session)
    proposals = classify_fleet(rows)              # step 2: deterministic
    failure_records = []

    # step 3: Hermes only on the abstained subset, only if explicitly enabled.
    if max_llm_calls > 0 and hermes is not None:
        by_slug = {r.slug: r for r in rows}
        unknown_props = [p for p in proposals if p.failure_class == FailureClass.UNKNOWN]
        unknown_rows = [by_slug[p.slug] for p in unknown_props]
        refined, failure_records = hermes.diagnose(unknown_rows, max_calls=max_llm_calls)
        refined_by_slug = {p.slug: p for p in refined}
        proposals = [refined_by_slug.get(p.slug, p) for p in proposals]

    # step 4: SafeFixer — when armed, run the live install+re-probe pipeline.
    # Route through the full eligibility gate (class AND confidence AND mapped
    # target), not class alone — an LLM-inferred pip-3rd-party must not reach
    # apply() when SafeFixer is armed (spec §3.4).
    fix_results = []
    apply_safe_requested = False
    if apply_safe and safe_fixer is not None:
        apply_safe_requested = True
        eligible = [p for p in proposals if safe_fixer.is_eligible(p)]
        by_slug = {r.slug: r for r in rows}

        def _health_cmd_for(slug):
            r = by_slug.get(slug)
            return r.health_cmd if (r and r.health_cmd) else "false"

        fix_results = safe_fixer.apply(eligible, session=session,
                                       health_cmd_for=_health_cmd_for)

    # step 5: write the envelope atomically BEFORE filing (proposals.json is the
    # reconciliation source of truth if filing later crashes).
    envelope = build_envelope(proposals, failure_records, map_version=MAP_VERSION,
                              generated_at=generated_at, session_id=session_id)
    write_proposals(envelope, out_path)

    # step 6: Paperclip (dry-run unless --file).
    pc = paperclip if paperclip is not None else PaperclipAdapter(session_id=session_id)
    issues = pc.file(proposals, dry_run=not do_file)

    # step 7: summary.
    counts = {}
    for p in proposals:
        counts[p.failure_class.value] = counts.get(p.failure_class.value, 0) + 1
    return {
        "counts": counts,
        "out_path": out_path,
        "issues_filed": len(issues),
        "apply_safe_requested": apply_safe_requested,
        "fixes_applied": sum(1 for r in fix_results if r.outcome == "fixed"),
        "fix_results": [r.to_dict() for r in fix_results],
    }
