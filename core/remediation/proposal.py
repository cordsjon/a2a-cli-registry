"""Typed value objects for the remediation pass (mirrors CapabilityRecord-style
value objects). Pure data — no I/O, no DB."""
from dataclasses import dataclass
from enum import Enum

SCHEMA_VERSION = 1


class FailureClass(str, Enum):
    PIP_3RD_PARTY = "pip-3rd-party"   # mapped third-party import; target = PyPI dist name
    PIP_UNKNOWN = "pip-unknown"       # un-mapped import, not proven local; target = import name
    WRONG_CWD = "wrong-cwd"           # proven-local module missing / FileNotFound; target = module/file
    CODE_BUG = "code-bug"             # SyntaxError/IndentationError; target = ""
    ENV_MISSING = "env-missing"       # missing env var / API key; target = var name if known else ""
    UNKNOWN = "unknown"               # classifier abstained; target = ""; routed to Hermes


class FixKind(str, Enum):
    AUTO_SAFE = "auto-safe"           # eligible for SafeFixer (pip-3rd-party only)
    PROPOSE_ONLY = "propose-only"     # file a Paperclip issue, no auto action
    NEEDS_HUMAN = "needs-human"       # diagnosis incomplete; Hermes or human required


class Confidence(str, Enum):
    DECLARED_BY_REGEX = "declared-by-regex"
    LLM_INFERRED = "llm-inferred"


@dataclass(frozen=True)
class RemediationProposal:
    schema_version: int
    slug: str
    failure_class: FailureClass
    fix_kind: FixKind
    target: str
    confidence: Confidence
    evidence: str

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "slug": self.slug,
            "failure_class": self.failure_class.value,
            "fix_kind": self.fix_kind.value,
            "target": self.target,
            "confidence": self.confidence.value,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class FailureRecord:
    """A lightweight record of a Hermes attempt that failed (timeout|refused|
    non200|parse). Observability, not a retry engine — see spec §3.2."""
    slug: str
    reason: str
    attempt_at: str

    def to_dict(self) -> dict:
        return {"slug": self.slug, "reason": self.reason, "attempt_at": self.attempt_at}


_FIX_OUTCOMES = frozenset(
    {"fixed", "install-failed", "reprobe-failed", "refused", "timeout"})


@dataclass(frozen=True)
class FixResult:
    """Per-CLI outcome of a SafeFixer.apply() attempt (spec §3.4). Pure data.

    outcome ∈ {fixed, install-failed, reprobe-failed, refused, timeout}:
      fixed          – installed AND isolated re-probe passed; health flipped.
      install-failed – pip returned non-zero (e.g. no wheel available).
      reprobe-failed – installed but the CLI still failed its --help probe.
      refused        – eligibility/path gate rejected it (defensive; run.py
                       pre-filters via is_eligible, so this is belt-and-braces).
      timeout        – install or re-probe hit the wall-clock cap (killpg'd).
    """
    slug: str
    target: str
    outcome: str
    detail: str

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "target": self.target,
            "outcome": self.outcome, "detail": self.detail,
        }


def build_envelope(proposals, failure_records, *, map_version, generated_at, session_id) -> dict:
    """Wrap proposals in the staleness/reconciliation envelope (spec §3.5).

    generated_at and session_id are passed IN (never generated here) so the
    envelope is deterministic for tests and resume-safe."""
    return {
        "schema_version": SCHEMA_VERSION,
        "map_version": map_version,
        "generated_at": generated_at,
        "session_id": session_id,
        "proposals": [p.to_dict() for p in proposals],
        "failure_records": [f.to_dict() for f in failure_records],
    }
