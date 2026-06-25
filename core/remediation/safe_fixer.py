"""The one mutating path — STUBBED in the MVP. apply() raises NotImplementedError.

Honest threat model (spec §3.4): a venv isolates PACKAGES, not EXECUTION. pip can
run arbitrary build code. Containment is the SUM of the §3.4 constraints, opt-in
and allowlist-gated. Only the eligibility predicate and refusal paths are live
this session — no install runs."""
import os

from core.remediation.proposal import FailureClass, Confidence
from core.remediation.classify import IMPORT_TO_PACKAGE

_MAPPED_DISTS = set(IMPORT_TO_PACKAGE.values())


class SafeFixer:
    def __init__(self, *, demo_dir: str):
        self.demo_dir = os.path.realpath(demo_dir)

    def is_eligible(self, proposal) -> bool:
        """All required (spec §3.4): pip-3rd-party class AND declared-by-regex
        confidence AND target is a MAPPED distribution name. Anything else refused."""
        return (
            proposal.failure_class == FailureClass.PIP_3RD_PARTY
            and proposal.confidence == Confidence.DECLARED_BY_REGEX
            and proposal.target in _MAPPED_DISTS
        )

    def venv_path_ok(self, candidate_path: str) -> bool:
        """The resolved (symlink-followed) venv path must stay inside demo_dir.
        Refuses a symlink that escapes the sandbox."""
        resolved = os.path.realpath(candidate_path)
        return resolved == self.demo_dir or resolved.startswith(self.demo_dir + os.sep)

    def apply(self, proposals) -> list:
        raise NotImplementedError(
            "SafeFixer.apply is stubbed in the MVP; run remediate without "
            "--apply-safe for proposals")
