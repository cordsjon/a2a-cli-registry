"""Deterministic, pure, total classifier for probe failure notes.

Reads the failure note ALREADY persisted in cli.description (the prober/audit
writes it). NEVER runs a subprocess. An unmatched note abstains to
unknown/needs-human and is routed to Hermes by the caller."""
import re
from pathlib import Path

from core.remediation.proposal import (
    SCHEMA_VERSION, RemediationProposal,
    FailureClass, FixKind, Confidence,
)

MAP_VERSION = 1

# import name -> PyPI DISTRIBUTION name. The two frequently differ; treating
# them as equal would auto-install the wrong package. An import name NOT in this
# map is never auto-installed (falls to pip-unknown). Growing the map is a
# reviewed change. Verified against the live 474-CLI fleet (spec §1, §3.1).
IMPORT_TO_PACKAGE = {
    # import != distribution
    "bs4": "beautifulsoup4",
    "pptx": "python-pptx",
    "docx": "python-docx",
    "fitz": "PyMuPDF",
    "Quartz": "pyobjc",
    "cv2": "opencv-python",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "sklearn": "scikit-learn",
    "dotenv": "python-dotenv",
    # identity-mapped (import == distribution), seen in the fleet
    "numpy": "numpy",
    "boto3": "boto3",
    "lxml": "lxml",
    "markdown": "markdown",
    "weasyprint": "weasyprint",
    "portalocker": "portalocker",
    "reportlab": "reportlab",
    "networkx": "networkx",
    "textual": "textual",
    "requests": "requests",
    "httpx": "httpx",
    "flask": "flask",
    "bottle": "bottle",
    "streamlit": "streamlit",
    "cbor2": "cbor2",
    "tinycss2": "tinycss2",
    "static_ffmpeg": "static-ffmpeg",
    # ulid: two dists provide `import ulid` (python-ulid vs ulid-py) with
    # incompatible APIs. The consuming CLI uses `from ulid import ULID`, which is
    # the python-ulid surface — mapping to ulid-py would import-but-break at runtime.
    "ulid": "python-ulid",
    "requests_html": "requests-html",
}

_MNFE_RE = re.compile(r"No module named ['\"]([\w][\w.]*)['\"]")
_ENV_KEYERR_RE = re.compile(r"KeyError:\s*['\"]([A-Z][A-Z0-9_]+)['\"]")
_ENV_WORDS_RE = re.compile(r"\b(env var|environment variable|API key)\b", re.IGNORECASE)


def _proposal(slug, fc, fk, target, conf, note):
    return RemediationProposal(
        schema_version=SCHEMA_VERSION, slug=slug, failure_class=fc,
        fix_kind=fk, target=target, confidence=conf, evidence=note,
    )


def _proven_local(path: str, module: str) -> bool:
    """True iff a module named `module` exists adjacent to the CLI's path —
    a file `module.py` or a package dir `module/`. This is a PROOF, not a
    heuristic: only then do we call it wrong-cwd rather than abstaining."""
    if not path:
        return False
    parent = Path(path).parent
    return (parent / f"{module}.py").exists() or (parent / module).is_dir()


def classify_failure(slug: str, note: str, path: str) -> RemediationProposal:
    note = note or ""
    regex = Confidence.DECLARED_BY_REGEX

    # 1. Code bug — checked first so a syntax failure is never swallowed below.
    if "SyntaxError" in note or "IndentationError" in note:
        return _proposal(slug, FailureClass.CODE_BUG, FixKind.NEEDS_HUMAN, "", regex, note)

    # 2. Missing module — split third-party vs proven-local vs unknown.
    m = _MNFE_RE.search(note)
    if m:
        top = m.group(1).split(".")[0]
        if top in IMPORT_TO_PACKAGE:
            return _proposal(slug, FailureClass.PIP_3RD_PARTY, FixKind.AUTO_SAFE,
                             IMPORT_TO_PACKAGE[top], regex,
                             f"{note} | mapped {top}->{IMPORT_TO_PACKAGE[top]}")
        if _proven_local(path, top):
            return _proposal(slug, FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY,
                             top, regex, f"{note} | proven-local {top} adjacent to {path}")
        return _proposal(slug, FailureClass.PIP_UNKNOWN, FixKind.PROPOSE_ONLY,
                         top, regex, f"{note} | unmapped, not proven local")

    # 3. Missing env var / API key.
    mk = _ENV_KEYERR_RE.search(note)
    if mk:
        return _proposal(slug, FailureClass.ENV_MISSING, FixKind.PROPOSE_ONLY,
                         mk.group(1), regex, note)
    if _ENV_WORDS_RE.search(note):
        return _proposal(slug, FailureClass.ENV_MISSING, FixKind.PROPOSE_ONLY, "", regex, note)

    # 4. FileNotFound -> wrong cwd.
    if "FileNotFoundError" in note:
        return _proposal(slug, FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "", regex, note)

    # 5. Anything else (incl. path-only descriptions) -> abstain to Hermes.
    return _proposal(slug, FailureClass.UNKNOWN, FixKind.NEEDS_HUMAN, "", regex, note)


def classify_fleet(rows) -> list:
    """Classify a list of unhealthy CLI rows. Each row exposes .slug,
    .description (the failure note), .path. Pure: no I/O beyond _proven_local's
    filesystem existence check on already-recorded paths."""
    return [classify_failure(r.slug, r.description or "", r.path or "") for r in rows]
