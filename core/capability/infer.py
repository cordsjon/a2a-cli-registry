"""Python-only, experimental capability inference. Kept SEPARATE from discovery
parsing so the LanguageAdapter contract is not Python-shaped. Non-Python adapters
return None (declared-required)."""
from typing import Optional
from core.discovery.base import CliRecord
from core.capability.model import CapabilityRecord


def infer_python_capability(rec: CliRecord) -> Optional[CapabilityRecord]:
    """Guess from --help/argparse metadata. v1 stub: returns None unless a
    deterministic heuristic matches. Always confidence='inferred' when it returns
    a record. Held to the §9 precision/recall floor against golden ground-truth."""
    # v1: no heuristic fires by default; real heuristics added behind the floor eval.
    return None
