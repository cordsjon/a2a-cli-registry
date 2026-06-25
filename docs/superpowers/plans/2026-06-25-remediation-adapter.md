# Remediation Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `remediate` pass that classifies *why* unhealthy CLIs fail and emits typed, proposal-only remediation proposals (default no network, no DB mutation, no issue filing).

**Architecture:** A new `core/remediation/` package with a pure deterministic classifier at its core, two degradable adapters (Hermes LLM diagnosis, Paperclip issue tracking), a stubbed mutating `SafeFixer`, and a `remediate` subcommand wired into `core/cli/main.py`. The classifier reads the failure note already persisted in `cli.description` by the probe/audit pass — it never re-runs subprocesses. Output is a single atomically-written `proposals.json` envelope.

**Tech Stack:** Python 3.11+, `dataclasses` + `enum`, `sqlmodel`/`select` (read-only), `urllib`/`http.client` for Hermes (no new deps), `subprocess` shelling `paperclip.sh`, `pytest`.

## Global Constraints

- Python 3.11+; no new third-party packages (stdlib only — `urllib.request`, `subprocess`, `tempfile`, `pathlib`, `hashlib`, `json`).
- `SCHEMA_VERSION = 1`, `MAP_VERSION = 1` — stamped into every `proposals.json`.
- Default `remediate` invocation: NO network call, NO DB mutation, files NO issues. It writes exactly one local artifact (`proposals.json` at `--out`, default `./proposals.json`), atomically (tempfile + `os.replace`).
- `classify_failure` is **pure and total** — never raises; unmatched input → `failure_class=unknown, fix_kind=needs-human`.
- `IMPORT_TO_PACKAGE` is an import-name → PyPI-**distribution**-name map (the two often differ). An import name not in the map is NEVER auto-installed → falls to `pip-unknown`, propose-only.
- Only `pip-3rd-party` may carry `fix_kind=auto-safe`, and only when `target` is a mapped distribution name. `unknown` → `needs-human`. Everything else → `propose-only`.
- `SafeFixer.apply()` raises `NotImplementedError` in the MVP; its eligibility predicate and refusal paths ARE implemented.
- Atomic writes only (tempfile + `os.replace`); no bare `except Exception`; check subprocess/HTTP status before parsing.
- Timestamps (`generated_at`) and `session_id` are passed INTO the writer, never generated inside library code (determinism; mirrors okf serialize).
- Exit codes: 0 ok · 2 DB-read failure (no proposals.json written) · 3 `--apply-safe` requested in MVP (proposals.json still written) · 4 proposals.json write failure (summary still printed).

---

## File Structure

- `core/remediation/__init__.py` — package marker + public exports.
- `core/remediation/proposal.py` — `SCHEMA_VERSION`, `FailureClass`, `FixKind`, `Confidence` enums, `RemediationProposal` + `FailureRecord` dataclasses, `build_envelope()`.
- `core/remediation/classify.py` — `MAP_VERSION`, `IMPORT_TO_PACKAGE`, `classify_failure()`, `classify_fleet()`.
- `core/remediation/hermes_adapter.py` — `HermesAdapter.diagnose()` (LLM, capped, degradable).
- `core/remediation/paperclip_adapter.py` — `PaperclipClient`, `PaperclipAdapter.file()`, `cluster_hash()`.
- `core/remediation/safe_fixer.py` — `SafeFixer` (eligibility predicate real; `apply()` stubbed).
- `core/remediation/run.py` — `run_remediate()` orchestration (steps 1–7 of spec §5) + atomic `write_proposals()`.
- `core/cli/main.py` — add `remediate` to the command list + handler block.
- `tests/test_remediation_classify.py`, `tests/test_remediation_hermes.py`, `tests/test_remediation_paperclip.py`, `tests/test_remediation_envelope.py`, `tests/test_remediation_safefixer.py`, `tests/test_remediation_cli.py`.

---

### Task 1: Proposal value objects + envelope

**Files:**
- Create: `core/remediation/__init__.py`
- Create: `core/remediation/proposal.py`
- Test: `tests/test_remediation_envelope.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces:
  - `SCHEMA_VERSION: int = 1`
  - `class FailureClass(str, Enum)`: `PIP_3RD_PARTY="pip-3rd-party"`, `PIP_UNKNOWN="pip-unknown"`, `WRONG_CWD="wrong-cwd"`, `CODE_BUG="code-bug"`, `ENV_MISSING="env-missing"`, `UNKNOWN="unknown"`
  - `class FixKind(str, Enum)`: `AUTO_SAFE="auto-safe"`, `PROPOSE_ONLY="propose-only"`, `NEEDS_HUMAN="needs-human"`
  - `class Confidence(str, Enum)`: `DECLARED_BY_REGEX="declared-by-regex"`, `LLM_INFERRED="llm-inferred"`
  - `@dataclass(frozen=True) class RemediationProposal` with fields `schema_version:int, slug:str, failure_class:FailureClass, fix_kind:FixKind, target:str, confidence:Confidence, evidence:str` and method `to_dict() -> dict` (enums serialized as `.value`).
  - `@dataclass(frozen=True) class FailureRecord` with fields `slug:str, reason:str, attempt_at:str` and `to_dict() -> dict`.
  - `build_envelope(proposals, failure_records, *, map_version, generated_at, session_id) -> dict` returning the §3.5 envelope.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_remediation_envelope.py
from core.remediation.proposal import (
    SCHEMA_VERSION, FailureClass, FixKind, Confidence,
    RemediationProposal, FailureRecord, build_envelope,
)


def _proposal(**kw):
    base = dict(
        schema_version=SCHEMA_VERSION,
        slug="generate-pdf",
        failure_class=FailureClass.PIP_3RD_PARTY,
        fix_kind=FixKind.AUTO_SAFE,
        target="beautifulsoup4",
        confidence=Confidence.DECLARED_BY_REGEX,
        evidence="ModuleNotFoundError: No module named 'bs4' | mapped bs4->beautifulsoup4",
    )
    base.update(kw)
    return RemediationProposal(**base)


def test_proposal_to_dict_serializes_enums_as_values():
    d = _proposal().to_dict()
    assert d["failure_class"] == "pip-3rd-party"
    assert d["fix_kind"] == "auto-safe"
    assert d["confidence"] == "declared-by-regex"
    assert d["schema_version"] == 1
    assert d["slug"] == "generate-pdf"
    assert d["target"] == "beautifulsoup4"


def test_failure_record_to_dict():
    fr = FailureRecord(slug="app", reason="timeout", attempt_at="2026-06-25T20:00:00Z")
    assert fr.to_dict() == {
        "slug": "app", "reason": "timeout", "attempt_at": "2026-06-25T20:00:00Z",
    }


def test_build_envelope_shape():
    env = build_envelope(
        [_proposal()],
        [FailureRecord(slug="app", reason="refused", attempt_at="2026-06-25T20:00:00Z")],
        map_version=1,
        generated_at="2026-06-25T20:00:00Z",
        session_id="11111111-1111-1111-1111-111111111111",
    )
    assert env["schema_version"] == 1
    assert env["map_version"] == 1
    assert env["generated_at"] == "2026-06-25T20:00:00Z"
    assert env["session_id"] == "11111111-1111-1111-1111-111111111111"
    assert isinstance(env["proposals"], list) and env["proposals"][0]["failure_class"] == "pip-3rd-party"
    assert env["failure_records"][0]["reason"] == "refused"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_envelope.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.remediation'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/remediation/__init__.py
"""Remediation pass: classify why unhealthy CLIs fail and emit typed proposals."""
```

```python
# core/remediation/proposal.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_envelope.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add core/remediation/__init__.py core/remediation/proposal.py tests/test_remediation_envelope.py
git commit -m "feat(remediation): proposal value objects + envelope"
```

---

### Task 2: Deterministic classifier (the highest-value unit)

**Files:**
- Create: `core/remediation/classify.py`
- Test: `tests/test_remediation_classify.py`

**Interfaces:**
- Consumes: `RemediationProposal`, `FailureClass`, `FixKind`, `Confidence`, `SCHEMA_VERSION` from `core/remediation/proposal.py`.
- Produces:
  - `MAP_VERSION: int = 1`
  - `IMPORT_TO_PACKAGE: dict[str, str]` (import name → PyPI distribution name).
  - `classify_failure(slug: str, note: str, path: str) -> RemediationProposal` — pure, total.
  - `classify_fleet(rows) -> list[RemediationProposal]` where each row is an object/dict with `.slug`, `.description`, `.path` (used by Task 6).

**Classification rules (spec §3.1), in order — first match wins:**
1. `SyntaxError` / `IndentationError` in note → `code-bug`, `needs-human`, target=`""`.
2. `ModuleNotFoundError: No module named 'X'` → take top-level segment of dotted `X`:
   - `X` in `IMPORT_TO_PACKAGE` → `pip-3rd-party`, `auto-safe`, target=`IMPORT_TO_PACKAGE[X]`, confidence=`declared-by-regex`.
   - else if `Path(path).parent / "X.py"` or `Path(path).parent / "X"` (dir) exists → `wrong-cwd`, `propose-only`, target=`X`.
   - else → `pip-unknown`, `propose-only`, target=`X`.
3. env / API key signal (`KeyError` naming an UPPER_SNAKE env var, or note containing `env var`/`API key`/`environment variable`) → `env-missing`, `propose-only`, target=var name if extractable else `""`.
4. `FileNotFoundError` → `wrong-cwd`, `propose-only`, target=`""`.
5. `ImportError` (not ModuleNotFound) or `other runtime error` → still try the above; anything unmatched → `unknown`, `needs-human`, target=`""`.

> **Ordering note:** SyntaxError is checked FIRST because a `ModuleNotFoundError` substring never co-occurs with it, but checking code-bug first keeps the `pip-unknown` branch from ever swallowing a genuine syntax failure. A note that is just a file path (114/217 fleet rows) matches nothing → `unknown`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_remediation_classify.py
import os
import pytest
from core.remediation.classify import (
    classify_failure, IMPORT_TO_PACKAGE, MAP_VERSION,
)
from core.remediation.proposal import FailureClass, FixKind, Confidence

MNFE = "ModuleNotFoundError: No module named '{}'"


def test_mapped_identity_third_party():
    p = classify_failure("detect_freshness", MNFE.format("numpy"), "/x/detect_freshness.py")
    assert p.failure_class == FailureClass.PIP_3RD_PARTY
    assert p.fix_kind == FixKind.AUTO_SAFE
    assert p.target == "numpy"
    assert p.confidence == Confidence.DECLARED_BY_REGEX


@pytest.mark.parametrize("imp,dist", [
    ("bs4", "beautifulsoup4"),
    ("pptx", "python-pptx"),
    ("docx", "python-docx"),
    ("fitz", "PyMuPDF"),
    ("yaml", "pyyaml"),
    ("sklearn", "scikit-learn"),
    ("dotenv", "python-dotenv"),
    ("PIL", "pillow"),
    ("cv2", "opencv-python"),
])
def test_import_not_equal_distribution_alias(imp, dist):
    p = classify_failure("c", MNFE.format(imp), "/x/c.py")
    assert p.failure_class == FailureClass.PIP_3RD_PARTY
    assert p.target == dist, f"{imp} must map to distribution {dist}, not import name"


def test_unmapped_not_proven_local_is_pip_unknown_not_wrong_cwd():
    # The specific defect a review surfaced: a non-mapped third-party name must
    # NOT be mislabelled wrong-cwd. No local romsorter.py adjacent -> pip-unknown.
    p = classify_failure("rs", MNFE.format("romsorter"), "/nonexistent/dir/rs.py")
    assert p.failure_class == FailureClass.PIP_UNKNOWN
    assert p.fix_kind == FixKind.PROPOSE_ONLY
    assert p.target == "romsorter"
    assert p.failure_class != FailureClass.WRONG_CWD


def test_proven_local_module_is_wrong_cwd(tmp_path):
    (tmp_path / "syllabus_v2.py").write_text("# local module\n")
    cli = tmp_path / "seed_artefacts.py"
    cli.write_text("import syllabus_v2\n")
    p = classify_failure("seed_artefacts", MNFE.format("syllabus_v2"), str(cli))
    assert p.failure_class == FailureClass.WRONG_CWD
    assert p.fix_kind == FixKind.PROPOSE_ONLY
    assert p.target == "syllabus_v2"


def test_proven_local_package_dir_is_wrong_cwd(tmp_path):
    (tmp_path / "engine").mkdir()
    (tmp_path / "engine" / "__init__.py").write_text("")
    cli = tmp_path / "run.py"
    cli.write_text("import engine\n")
    p = classify_failure("run", MNFE.format("engine"), str(cli))
    assert p.failure_class == FailureClass.WRONG_CWD


def test_dotted_module_uses_top_segment(tmp_path):
    # google.cloud -> top segment 'google'; not mapped, not local -> pip-unknown
    p = classify_failure("c", MNFE.format("google.cloud"), str(tmp_path / "c.py"))
    assert p.target == "google"
    assert p.failure_class == FailureClass.PIP_UNKNOWN


def test_syntax_error_is_code_bug():
    p = classify_failure("c", "SyntaxError: invalid syntax (foo.py, line 3)", "/x/c.py")
    assert p.failure_class == FailureClass.CODE_BUG
    assert p.fix_kind == FixKind.NEEDS_HUMAN
    assert p.target == ""


def test_indentation_error_is_code_bug():
    p = classify_failure("c", "IndentationError: unexpected indent", "/x/c.py")
    assert p.failure_class == FailureClass.CODE_BUG


def test_env_missing_extracts_var():
    p = classify_failure("c", "KeyError: 'OPENAI_API_KEY'", "/x/c.py")
    assert p.failure_class == FailureClass.ENV_MISSING
    assert p.fix_kind == FixKind.PROPOSE_ONLY
    assert p.target == "OPENAI_API_KEY"


def test_file_not_found_is_wrong_cwd():
    p = classify_failure("c", "FileNotFoundError: [Errno 2] No such file or directory: 'data.csv'", "/x/c.py")
    assert p.failure_class == FailureClass.WRONG_CWD
    assert p.fix_kind == FixKind.PROPOSE_ONLY


def test_path_only_description_is_unknown():
    # 114/217 fleet rows: description is just the file path, no error signal.
    p = classify_failure("inlay", "70_ASSET-ENGINE/backend/revisions/inlay.py", "/x/inlay.py")
    assert p.failure_class == FailureClass.UNKNOWN
    assert p.fix_kind == FixKind.NEEDS_HUMAN


def test_gibberish_is_unknown():
    p = classify_failure("c", "the cat sat on the mat", "/x/c.py")
    assert p.failure_class == FailureClass.UNKNOWN


def test_classifier_never_raises_on_empty():
    p = classify_failure("c", "", "")
    assert p.failure_class == FailureClass.UNKNOWN


def test_map_covers_required_aliases():
    for imp in ("bs4", "pptx", "docx", "fitz", "cv2", "PIL", "yaml", "sklearn", "dotenv"):
        assert imp in IMPORT_TO_PACKAGE
    assert MAP_VERSION == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.remediation.classify'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/remediation/classify.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_classify.py -v`
Expected: all passed (24 cases incl. parametrize).

- [ ] **Step 5: Commit**

```bash
git add core/remediation/classify.py tests/test_remediation_classify.py
git commit -m "feat(remediation): deterministic classifier + IMPORT_TO_PACKAGE map"
```

---

### Task 3: Hermes adapter (LLM diagnosis, capped, degradable)

**Files:**
- Create: `core/remediation/hermes_adapter.py`
- Test: `tests/test_remediation_hermes.py`

**Interfaces:**
- Consumes: `RemediationProposal`, `FailureClass`, `FixKind`, `Confidence`, `FailureRecord`, `SCHEMA_VERSION` from `proposal.py`.
- Produces:
  - `class HermesAdapter` with `__init__(self, *, base_url="http://localhost:9109", model="deepseek-v4-flash", timeout=30.0, now=None)` where `now` is a zero-arg callable returning an ISO8601 string (injected for determinism).
  - `diagnose(self, unknowns: list, *, max_calls: int) -> tuple[list[RemediationProposal], list[FailureRecord]]` — `unknowns` are CLI rows (`.slug`, `.description`, `.path`); returns refined proposals + failure records. Batches ≤10 per HTTP call; `max_calls` caps the number of HTTP calls (batches); CLIs beyond the cap stay `unknown`.
  - `_post(self, payload: dict) -> dict` — the single HTTP seam tests monkeypatch.

**Degradation contract:** any connection-refused / timeout / non-200 / parse-failure for a batch → every CLI in that batch returned unchanged as `unknown / needs-human`, plus one `FailureRecord{slug, reason∈(timeout|refused|non200|parse), attempt_at=now()}` per CLI in the failed batch.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_remediation_hermes.py
import json
import pytest
from core.remediation.hermes_adapter import HermesAdapter
from core.remediation.proposal import FailureClass, FixKind, Confidence


class Row:
    def __init__(self, slug, description="", path=""):
        self.slug = slug
        self.description = description
        self.path = path


def _fixed_now():
    return "2026-06-25T20:00:00Z"


def test_empty_input_makes_no_call():
    calls = []
    a = HermesAdapter(now=_fixed_now)
    a._post = lambda payload: calls.append(payload) or {}
    props, recs = a.diagnose([], max_calls=5)
    assert props == [] and recs == []
    assert calls == []


def test_success_refines_to_llm_inferred():
    a = HermesAdapter(now=_fixed_now)

    def fake_post(payload):
        return {"choices": [{"message": {"content": json.dumps([
            {"slug": "app", "failure_class": "wrong-cwd", "target": "app",
             "evidence": "local module app/ exists one level up"},
        ])}}]}
    a._post = fake_post
    props, recs = a.diagnose([Row("app")], max_calls=5)
    assert recs == []
    assert props[0].slug == "app"
    assert props[0].failure_class == FailureClass.WRONG_CWD
    assert props[0].confidence == Confidence.LLM_INFERRED
    assert props[0].fix_kind == FixKind.PROPOSE_ONLY


@pytest.mark.parametrize("exc_or_status,reason", [
    ("refused", "refused"),
    ("timeout", "timeout"),
    ("non200", "non200"),
    ("parse", "parse"),
])
def test_degrades_to_unknown_with_failure_record(exc_or_status, reason):
    a = HermesAdapter(now=_fixed_now)

    def fake_post(payload):
        if exc_or_status == "refused":
            raise ConnectionRefusedError("refused")
        if exc_or_status == "timeout":
            raise TimeoutError("slow")
        if exc_or_status == "non200":
            from core.remediation.hermes_adapter import HermesHTTPError
            raise HermesHTTPError(503, "non200")
        return {"choices": [{"message": {"content": "NOT JSON"}}]}  # parse failure
    a._post = fake_post
    props, recs = a.diagnose([Row("app"), Row("cli")], max_calls=5)
    assert all(p.failure_class == FailureClass.UNKNOWN for p in props)
    assert all(p.fix_kind == FixKind.NEEDS_HUMAN for p in props)
    assert {r.reason for r in recs} == {reason}
    assert {r.slug for r in recs} == {"app", "cli"}
    assert all(r.attempt_at == "2026-06-25T20:00:00Z" for r in recs)


def test_max_calls_caps_batches_and_leaves_rest_unknown():
    a = HermesAdapter(now=_fixed_now)
    seen = []

    def fake_post(payload):
        seen.append(payload)
        return {"choices": [{"message": {"content": json.dumps([])}}]}
    a._post = fake_post
    rows = [Row(f"c{i}") for i in range(25)]  # 25 CLIs -> 3 batches of <=10
    props, recs = a.diagnose(rows, max_calls=1)  # only 1 batch allowed
    assert len(seen) == 1  # exactly one HTTP call made
    # 15 CLIs beyond the cap stay unknown
    unknown = [p for p in props if p.failure_class == FailureClass.UNKNOWN]
    assert len(unknown) == 15


def test_batch_size_at_most_ten():
    a = HermesAdapter(now=_fixed_now)
    sizes = []

    def fake_post(payload):
        sizes.append(len(payload["_batch_slugs"]))
        return {"choices": [{"message": {"content": json.dumps([])}}]}
    a._post = fake_post
    a.diagnose([Row(f"c{i}") for i in range(23)], max_calls=10)
    assert max(sizes) <= 10
    assert sum(sizes) == 23
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_hermes.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# core/remediation/hermes_adapter.py
"""Hermes LLM diagnosis for CLIs the deterministic classifier abstained on.

Bulkheaded: any Hermes failure (refused/timeout/non200/parse) degrades the
affected batch to unknown/needs-human and records a FailureRecord. Hermes being
down or slow NEVER fails the remediate pass (mirrors the prober's per-future
isolation). Token-frugality: only ever sees the classifier's `unknown` rows."""
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

from core.remediation.proposal import (
    SCHEMA_VERSION, RemediationProposal, FailureRecord,
    FailureClass, FixKind, Confidence,
)

_BATCH = 10

# Map an LLM-returned class string back to the enum; unknown strings abstain.
_CLASS_BY_VALUE = {fc.value: fc for fc in FailureClass}
# fix_kind is derived from class so the LLM cannot mint an auto-safe fix.
_FIXKIND_BY_CLASS = {
    FailureClass.PIP_3RD_PARTY: FixKind.PROPOSE_ONLY,  # LLM-inferred is never auto-safe
    FailureClass.PIP_UNKNOWN: FixKind.PROPOSE_ONLY,
    FailureClass.WRONG_CWD: FixKind.PROPOSE_ONLY,
    FailureClass.CODE_BUG: FixKind.NEEDS_HUMAN,
    FailureClass.ENV_MISSING: FixKind.PROPOSE_ONLY,
    FailureClass.UNKNOWN: FixKind.NEEDS_HUMAN,
}


class HermesHTTPError(Exception):
    def __init__(self, status, body=""):
        super().__init__(f"hermes returned {status}")
        self.status = status
        self.body = body


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unknown(slug, note):
    return RemediationProposal(
        schema_version=SCHEMA_VERSION, slug=slug,
        failure_class=FailureClass.UNKNOWN, fix_kind=FixKind.NEEDS_HUMAN,
        target="", confidence=Confidence.DECLARED_BY_REGEX, evidence=note or "",
    )


class HermesAdapter:
    def __init__(self, *, base_url="http://localhost:9109",
                 model="deepseek-v4-flash", timeout=30.0, now=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._now = now or _utc_now

    def _post(self, payload: dict) -> dict:
        """The single HTTP seam (monkeypatched in tests). Raises
        HermesHTTPError on non-200, urllib errors on connection problems."""
        data = json.dumps({k: v for k, v in payload.items()
                           if not k.startswith("_")}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions", data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise HermesHTTPError(resp.status)
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise HermesHTTPError(exc.code) from exc

    def _build_payload(self, batch):
        msg = "\n\n".join(
            f"slug: {r.slug}\nnote: {r.description or ''}\npath: {r.path or ''}"
            for r in batch)
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content":
                 "You diagnose why a Python CLI failed to run. For each slug "
                 "return strict JSON array of {slug, failure_class, target, "
                 "evidence}. failure_class in: pip-3rd-party, pip-unknown, "
                 "wrong-cwd, code-bug, env-missing, unknown."},
                {"role": "user", "content": msg},
            ],
            "_batch_slugs": [r.slug for r in batch],  # test hook; stripped before POST
        }

    def _parse(self, resp, batch):
        content = resp["choices"][0]["message"]["content"]
        items = json.loads(content)  # raises on non-JSON -> caught as parse failure
        by_slug = {it["slug"]: it for it in items if "slug" in it}
        out = []
        for r in batch:
            it = by_slug.get(r.slug)
            if not it:
                out.append(_unknown(r.slug, r.description))
                continue
            fc = _CLASS_BY_VALUE.get(it.get("failure_class", ""), FailureClass.UNKNOWN)
            out.append(RemediationProposal(
                schema_version=SCHEMA_VERSION, slug=r.slug, failure_class=fc,
                fix_kind=_FIXKIND_BY_CLASS[fc], target=it.get("target", ""),
                confidence=Confidence.LLM_INFERRED,
                evidence=it.get("evidence", "") or (r.description or ""),
            ))
        return out

    def diagnose(self, unknowns, *, max_calls):
        proposals, records = [], []
        batches = [unknowns[i:i + _BATCH] for i in range(0, len(unknowns), _BATCH)]
        for idx, batch in enumerate(batches):
            if idx >= max_calls:
                # Beyond the cap: leave remaining CLIs unknown (no silent truncation).
                proposals.extend(_unknown(r.slug, r.description) for r in batch)
                continue
            try:
                resp = self._post(self._build_payload(batch))
                proposals.extend(self._parse(resp, batch))
            except (ConnectionRefusedError, urllib.error.URLError) as exc:
                self._degrade(batch, "refused", proposals, records)
            except TimeoutError:
                self._degrade(batch, "timeout", proposals, records)
            except HermesHTTPError:
                self._degrade(batch, "non200", proposals, records)
            except (json.JSONDecodeError, KeyError, TypeError, IndexError):
                self._degrade(batch, "parse", proposals, records)
        return proposals, records

    def _degrade(self, batch, reason, proposals, records):
        at = self._now()
        for r in batch:
            proposals.append(_unknown(r.slug, r.description))
            records.append(FailureRecord(slug=r.slug, reason=reason, attempt_at=at))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_hermes.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add core/remediation/hermes_adapter.py tests/test_remediation_hermes.py
git commit -m "feat(remediation): Hermes adapter with bulkheaded degradation + cost cap"
```

---

### Task 4: Paperclip adapter (clustering + order-independent idempotency)

**Files:**
- Create: `core/remediation/paperclip_adapter.py`
- Test: `tests/test_remediation_paperclip.py`

**Interfaces:**
- Consumes: `RemediationProposal`, `FailureClass`, `FixKind` from `proposal.py`.
- Produces:
  - `cluster_hash(failure_class_value: str, target: str, member_slugs: list[str]) -> str` — `sha256(fc + "\0" + target + "\0" + "\0".join(sorted(slugs)))[:12]`, order-independent.
  - `class PaperclipClient` with `__init__(self, script="paperclip.sh")`, `available() -> bool` (is `script` on PATH), `list_open_hashes() -> set[str]` (shells `<script> list --json`, parses titles for embedded hashes), `bulk_create(yaml_text: str) -> None` (shells `<script> bulk-create <file>`).
  - `class PaperclipAdapter` with `__init__(self, client=None, *, session_id="")`, `file(self, proposals, *, dry_run=True) -> list` returning `IssueRef` dicts `{title, hash, members, dry_run}`. Filters to `propose-only` + `needs-human` (auto-safe excluded). Clusters by `(failure_class, target)`. Skips clusters whose hash is already open. Missing `paperclip.sh` → warn + skip (return `[]`), never raise.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_remediation_paperclip.py
from core.remediation.paperclip_adapter import (
    PaperclipAdapter, cluster_hash,
)
from core.remediation.proposal import (
    SCHEMA_VERSION, RemediationProposal, FailureClass, FixKind, Confidence,
)


def _p(slug, fc, fk, target):
    return RemediationProposal(
        schema_version=SCHEMA_VERSION, slug=slug, failure_class=fc, fix_kind=fk,
        target=target, confidence=Confidence.DECLARED_BY_REGEX, evidence="e")


class FakeClient:
    def __init__(self, available=True, open_hashes=None):
        self._available = available
        self._open = open_hashes or set()
        self.created = []
    def available(self):
        return self._available
    def list_open_hashes(self):
        return set(self._open)
    def bulk_create(self, yaml_text):
        self.created.append(yaml_text)


def test_cluster_hash_is_order_independent():
    h1 = cluster_hash("wrong-cwd", "syllabus_v2", ["b", "a", "c"])
    h2 = cluster_hash("wrong-cwd", "syllabus_v2", ["c", "b", "a"])
    assert h1 == h2
    assert len(h1) == 12


def test_clusters_by_class_and_target():
    props = [
        _p("a", FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "syllabus_v2"),
        _p("b", FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "syllabus_v2"),
        _p("c", FailureClass.PIP_UNKNOWN, FixKind.PROPOSE_ONLY, "romsorter"),
    ]
    client = FakeClient()
    refs = PaperclipAdapter(client, session_id="s1").file(props, dry_run=True)
    # 2 clusters: (wrong-cwd, syllabus_v2) with 2 members, (pip-unknown, romsorter) with 1
    by_members = sorted(len(r["members"]) for r in refs)
    assert by_members == [1, 2]


def test_dry_run_default_writes_no_issue():
    client = FakeClient()
    PaperclipAdapter(client, session_id="s1").file(
        [_p("a", FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "x")])  # dry_run defaults True
    assert client.created == []


def test_actual_file_shells_bulk_create():
    client = FakeClient()
    PaperclipAdapter(client, session_id="s1").file(
        [_p("a", FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "x")], dry_run=False)
    assert len(client.created) == 1


def test_existing_open_hash_is_skipped():
    props = [_p("a", FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "x")]
    h = cluster_hash("wrong-cwd", "x", ["a"])
    client = FakeClient(open_hashes={h})
    refs = PaperclipAdapter(client, session_id="s1").file(props, dry_run=False)
    assert refs == []  # already open -> skipped
    assert client.created == []


def test_needs_human_proposals_are_filed():
    props = [_p("a", FailureClass.UNKNOWN, FixKind.NEEDS_HUMAN, "")]
    client = FakeClient()
    refs = PaperclipAdapter(client, session_id="s1").file(props, dry_run=True)
    assert len(refs) == 1


def test_auto_safe_proposals_excluded():
    props = [_p("a", FailureClass.PIP_3RD_PARTY, FixKind.AUTO_SAFE, "numpy")]
    client = FakeClient()
    refs = PaperclipAdapter(client, session_id="s1").file(props, dry_run=True)
    assert refs == []


def test_missing_paperclip_warns_and_skips(capsys):
    props = [_p("a", FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "x")]
    client = FakeClient(available=False)
    refs = PaperclipAdapter(client, session_id="s1").file(props, dry_run=False)
    assert refs == []
    assert client.created == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_paperclip.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# core/remediation/paperclip_adapter.py
"""Paperclip issue tracking for remediation proposals.

Clusters proposals by (failure_class, target) -> one issue per cluster (not per
CLI). Idempotency via an order-independent cluster hash embedded in each issue
title; duplicate detection reads `paperclip.sh list --json` (machine-readable),
never scraped free text. Missing paperclip.sh -> warn + skip, never raise
(proposals.json is already written by the caller before this runs)."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

from core.remediation.proposal import FixKind

# Only these fix_kinds get filed. auto-safe is excluded (a successful SafeFixer
# leaves no issue; an armed-but-failed one is re-filed by the caller).
_FILED_KINDS = {FixKind.PROPOSE_ONLY, FixKind.NEEDS_HUMAN}


def cluster_hash(failure_class_value: str, target: str, member_slugs) -> str:
    """Stable, ORDER-INDEPENDENT cluster id (spec §3.3)."""
    payload = (failure_class_value + "\0" + target + "\0"
               + "\0".join(sorted(member_slugs)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


class PaperclipClient:
    def __init__(self, script="paperclip.sh"):
        self.script = script

    def available(self) -> bool:
        return shutil.which(self.script) is not None

    def list_open_hashes(self) -> set:
        """Read open issues via `list --json`; extract embedded cluster hashes
        from titles formatted '[remediate:<hash>] ...'. A format/connection
        failure raises CalledProcessError/JSONDecodeError to the caller, which
        surfaces it distinctly (never a silent idempotency break)."""
        out = subprocess.run([self.script, "list", "--json"],
                             capture_output=True, text=True, check=True)
        issues = json.loads(out.stdout)
        hashes = set()
        for it in issues:
            title = it.get("title", "")
            if title.startswith("[remediate:") and "]" in title:
                hashes.add(title[len("[remediate:"):title.index("]")])
        return hashes

    def bulk_create(self, yaml_text: str) -> None:
        fd, tmp = tempfile.mkstemp(suffix=".yaml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(yaml_text)
            subprocess.run([self.script, "bulk-create", tmp], check=True)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


class PaperclipAdapter:
    def __init__(self, client=None, *, session_id=""):
        self.client = client or PaperclipClient()
        self.session_id = session_id

    def _cluster(self, proposals):
        clusters = {}
        for p in proposals:
            if p.fix_kind not in _FILED_KINDS:
                continue
            key = (p.failure_class.value, p.target)
            clusters.setdefault(key, []).append(p)
        return clusters

    def _yaml(self, title, members):
        body = "\\n".join(f"- {p.slug}: {p.evidence}" for p in members)
        lines = [
            "- title: " + json.dumps(title),
            "  body: " + json.dumps(f"session={self.session_id}\\n{body}"),
        ]
        return "\n".join(lines) + "\n"

    def file(self, proposals, *, dry_run=True):
        if not self.client.available():
            print("remediate: paperclip.sh not found; skipping issue filing "
                  "(proposals.json already written)", file=sys.stderr)
            return []
        clusters = self._cluster(proposals)
        open_hashes = set() if dry_run else self.client.list_open_hashes()
        refs = []
        for (fc_value, target), members in clusters.items():
            slugs = [p.slug for p in members]
            h = cluster_hash(fc_value, target, slugs)
            if h in open_hashes:
                continue  # idempotent: cluster already filed
            title = f"[remediate:{h}] {fc_value} / {target} ({len(members)} CLIs)"
            if not dry_run:
                self.client.bulk_create(self._yaml(title, members))
            refs.append({"title": title, "hash": h, "members": slugs, "dry_run": dry_run})
        return refs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_paperclip.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add core/remediation/paperclip_adapter.py tests/test_remediation_paperclip.py
git commit -m "feat(remediation): Paperclip adapter with order-independent cluster idempotency"
```

---

### Task 5: SafeFixer (eligibility real, apply() stubbed)

**Files:**
- Create: `core/remediation/safe_fixer.py`
- Test: `tests/test_remediation_safefixer.py`

**Interfaces:**
- Consumes: `RemediationProposal`, `FailureClass`, `FixKind`, `Confidence` from `proposal.py`; `IMPORT_TO_PACKAGE` from `classify.py`.
- Produces:
  - `class SafeFixer` with `__init__(self, *, demo_dir: str)` (the only directory a venv path may resolve inside).
  - `is_eligible(self, proposal: RemediationProposal) -> bool` — True ONLY if `failure_class==PIP_3RD_PARTY` AND `confidence==DECLARED_BY_REGEX` AND `target` is a value in `IMPORT_TO_PACKAGE`.
  - `venv_path_ok(self, candidate_path: str) -> bool` — `os.path.realpath(candidate)` must be inside `realpath(demo_dir)` (symlink-escape refused).
  - `apply(self, proposals) -> list` — raises `NotImplementedError` in the MVP.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_remediation_safefixer.py
import os
import pytest
from core.remediation.safe_fixer import SafeFixer
from core.remediation.proposal import (
    SCHEMA_VERSION, RemediationProposal, FailureClass, FixKind, Confidence,
)


def _p(fc, target, conf=Confidence.DECLARED_BY_REGEX, fk=FixKind.AUTO_SAFE):
    return RemediationProposal(
        schema_version=SCHEMA_VERSION, slug="s", failure_class=fc, fix_kind=fk,
        target=target, confidence=conf, evidence="e")


def test_apply_raises_not_implemented(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    with pytest.raises(NotImplementedError):
        fixer.apply([_p(FailureClass.PIP_3RD_PARTY, "numpy")])


def test_eligible_for_mapped_pip_third_party(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    assert fixer.is_eligible(_p(FailureClass.PIP_3RD_PARTY, "numpy")) is True
    assert fixer.is_eligible(_p(FailureClass.PIP_3RD_PARTY, "beautifulsoup4")) is True


def test_refuses_unmapped_name(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    # 'romsorter' is not a value in IMPORT_TO_PACKAGE
    assert fixer.is_eligible(_p(FailureClass.PIP_3RD_PARTY, "romsorter")) is False


def test_refuses_all_non_pip_classes(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    for fc in (FailureClass.PIP_UNKNOWN, FailureClass.WRONG_CWD,
               FailureClass.CODE_BUG, FailureClass.ENV_MISSING, FailureClass.UNKNOWN):
        assert fixer.is_eligible(_p(fc, "numpy")) is False


def test_refuses_llm_inferred_confidence(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    assert fixer.is_eligible(
        _p(FailureClass.PIP_3RD_PARTY, "numpy", conf=Confidence.LLM_INFERRED)) is False


def test_venv_inside_demo_ok(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    assert fixer.venv_path_ok(str(tmp_path / "venv-numpy")) is True


def test_venv_symlink_escape_refused(tmp_path):
    demo = tmp_path / "demo"
    demo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    escape = demo / "escape"
    os.symlink(str(outside), str(escape))  # demo/escape -> outside (resolves out)
    fixer = SafeFixer(demo_dir=str(demo))
    assert fixer.venv_path_ok(str(escape / "venv")) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_safefixer.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# core/remediation/safe_fixer.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_safefixer.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add core/remediation/safe_fixer.py tests/test_remediation_safefixer.py
git commit -m "feat(remediation): SafeFixer eligibility+refusal guards (apply stubbed)"
```

---

### Task 6: Orchestration (`run_remediate`) + atomic writer

**Files:**
- Create: `core/remediation/run.py`
- Test: `tests/test_remediation_cli.py` (orchestration-level tests live here; CLI wiring added in Task 7 reuses them)

**Interfaces:**
- Consumes: `classify_fleet` from `classify.py`; `HermesAdapter`; `PaperclipAdapter`; `SafeFixer`; `build_envelope`, `FailureClass` from `proposal.py`; `Cli` from `core/models.py`; `select` from `sqlmodel`.
- Produces:
  - `write_proposals(envelope: dict, out_path: str) -> None` — atomic (tempfile + `os.replace`), mirrors `core/okf/serialize._atomic_write`.
  - `read_unhealthy(session) -> list[Cli]` — `select(Cli).where(Cli.health_status == "unhealthy")`.
  - `run_remediate(session, *, out_path, do_file, apply_safe, max_llm_calls, session_id, generated_at, hermes=None, paperclip=None, safe_fixer=None) -> dict` returning a summary `{counts: {...}, out_path, issues_filed, apply_safe_requested}`. Implements spec §5 steps 1–7. Returns the summary; the caller (Task 7) maps it to an exit code.

**Orchestration order (spec §5):** classify → (if `max_llm_calls>0`) Hermes-diagnose the `unknown` subset, replacing those proposals → (if `apply_safe`) SafeFixer.apply (catches `NotImplementedError`, sets `apply_safe_requested=True`) → `write_proposals` atomically → `PaperclipAdapter.file(dry_run=not do_file)` → return summary.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_remediation_cli.py  (orchestration half)
import json
import pytest
from sqlmodel import select
from core.models import Cli
from core.remediation.run import run_remediate, read_unhealthy, write_proposals


def _seed(db, slug, desc, status="unhealthy", path="/x/c.py"):
    db.add(Cli(slug=slug, lang="python", description=desc,
               health_status=status, path=path))
    db.commit()


class NoopPaperclip:
    def __init__(self):
        self.filed = None
    def file(self, proposals, *, dry_run=True):
        self.filed = (list(proposals), dry_run)
        return []


def test_read_unhealthy_only(db):
    _seed(db, "bad", "ModuleNotFoundError: No module named 'numpy'", "unhealthy")
    _seed(db, "good", "", "healthy")
    rows = read_unhealthy(db)
    assert [r.slug for r in rows] == ["bad"]


def test_run_classifies_and_writes_envelope(db, tmp_path):
    _seed(db, "bad", "ModuleNotFoundError: No module named 'numpy'")
    out = tmp_path / "proposals.json"
    pc = NoopPaperclip()
    summary = run_remediate(
        db, out_path=str(out), do_file=False, apply_safe=False,
        max_llm_calls=0, session_id="sid", generated_at="2026-06-25T20:00:00Z",
        paperclip=pc)
    env = json.loads(out.read_text())
    assert env["session_id"] == "sid"
    assert env["map_version"] == 1
    assert env["proposals"][0]["failure_class"] == "pip-3rd-party"
    assert env["proposals"][0]["target"] == "numpy"
    assert pc.filed[1] is True  # dry_run (do_file=False)


def test_run_skips_hermes_when_max_calls_zero(db, tmp_path):
    _seed(db, "u", "totally opaque failure")  # classifies to unknown
    out = tmp_path / "p.json"
    called = {"n": 0}

    class SpyHermes:
        def diagnose(self, unknowns, *, max_calls):
            called["n"] += 1
            return [], []
    run_remediate(db, out_path=str(out), do_file=False, apply_safe=False,
                  max_llm_calls=0, session_id="s", generated_at="t",
                  hermes=SpyHermes(), paperclip=NoopPaperclip())
    assert called["n"] == 0  # max_llm_calls=0 -> Hermes never invoked


def test_run_invokes_hermes_on_unknowns(db, tmp_path):
    _seed(db, "u", "totally opaque failure")
    out = tmp_path / "p.json"
    seen = {}

    class SpyHermes:
        def diagnose(self, unknowns, *, max_calls):
            seen["slugs"] = [r.slug for r in unknowns]
            seen["cap"] = max_calls
            return [], []
    run_remediate(db, out_path=str(out), do_file=False, apply_safe=False,
                  max_llm_calls=3, session_id="s", generated_at="t",
                  hermes=SpyHermes(), paperclip=NoopPaperclip())
    assert seen["slugs"] == ["u"]
    assert seen["cap"] == 3


def test_apply_safe_requested_caught_and_still_writes(db, tmp_path):
    _seed(db, "n", "ModuleNotFoundError: No module named 'numpy'")
    out = tmp_path / "p.json"

    class StubFixer:
        def apply(self, proposals):
            raise NotImplementedError("stubbed")
    summary = run_remediate(
        db, out_path=str(out), do_file=False, apply_safe=True, max_llm_calls=0,
        session_id="s", generated_at="t", safe_fixer=StubFixer(),
        paperclip=NoopPaperclip())
    assert summary["apply_safe_requested"] is True
    assert out.exists()  # proposals.json written despite stubbed apply


def test_write_proposals_is_atomic_overwrite(tmp_path):
    out = tmp_path / "p.json"
    write_proposals({"a": 1}, str(out))
    write_proposals({"a": 2}, str(out))  # overwrite
    assert json.loads(out.read_text()) == {"a": 2}
    # no leftover temp files in the dir
    assert [p.name for p in tmp_path.iterdir()] == ["p.json"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.remediation.run'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/remediation/run.py
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

    # step 4: SafeFixer (MVP: NotImplementedError caught; read-only work preserved).
    apply_safe_requested = False
    if apply_safe and safe_fixer is not None:
        apply_safe_requested = True
        try:
            safe_fixer.apply([p for p in proposals
                              if p.failure_class == FailureClass.PIP_3RD_PARTY])
        except NotImplementedError:
            pass  # MVP: proposals.json + filing still happen below

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
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_cli.py -v`
Expected: all (orchestration) tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/remediation/run.py tests/test_remediation_cli.py
git commit -m "feat(remediation): run_remediate orchestration + atomic proposals.json writer"
```

---

### Task 7: CLI wiring (`remediate` subcommand)

**Files:**
- Modify: `core/cli/main.py` (command list ~line 95; add a handler block before the final `with get_session` fallthrough ~line 242)
- Test: `tests/test_remediation_cli.py` (append CLI-level tests)

**Interfaces:**
- Consumes: `run_remediate`, `read_unhealthy` from `core/remediation/run.py`; existing `init_db`, `get_session`, `with_file_lock`, `_db_lock_path` in `main.py`.
- Produces: the `remediate` command, parsed flags `--out` (reuse existing `--out`; default `./proposals.json` when command is remediate), `--file`, `--apply-safe`, `--max-llm-calls`. Exit codes per Global Constraints.

**Note on `--out` default:** the existing `--out` defaults to `./bundle` (for okf-produce). Add a remediate-specific default: if `args.command == "remediate"` and the user did not pass `--out`, use `./proposals.json`. Detect "not passed" by setting the argparse default to `None` is risky (okf needs `./bundle`); instead, add a dedicated `--proposals-out` is over-engineering — reuse `--out` but override when it still equals the okf default `./bundle`.

- [ ] **Step 1: Write the failing test (append to tests/test_remediation_cli.py)**

```python
# --- CLI-level tests (append) ---
import os
import uuid
import pytest
from core.cli import main as cli_main


def _make_db(tmp_path, seed_rows):
    from core.store.db import init_db, get_session
    db_path = str(tmp_path / "registry.db")
    engine = init_db(db_path)
    with get_session(engine) as s:
        for slug, desc, status in seed_rows:
            s.add(Cli(slug=slug, lang="python", description=desc,
                      health_status=status, path="/x/" + slug + ".py"))
        s.commit()
    return db_path


def test_cli_default_writes_proposals_no_network(tmp_path, monkeypatch):
    db_path = _make_db(tmp_path, [
        ("bad", "ModuleNotFoundError: No module named 'numpy'", "unhealthy")])
    out = tmp_path / "proposals.json"
    # Spy: any HermesAdapter.diagnose call is a failure of "no network by default".
    import core.remediation.run as run_mod
    monkeypatch.setattr(
        "core.remediation.hermes_adapter.HermesAdapter._post",
        lambda self, payload: (_ for _ in ()).throw(AssertionError("network used")))
    rc = cli_main.main(["remediate", "--db", db_path, "--out", str(out)])
    assert rc == 0
    assert out.exists()
    env = json.loads(out.read_text())
    assert env["proposals"][0]["target"] == "numpy"


def test_cli_apply_safe_exits_3_but_writes(tmp_path):
    db_path = _make_db(tmp_path, [
        ("n", "ModuleNotFoundError: No module named 'numpy'", "unhealthy")])
    out = tmp_path / "p.json"
    rc = cli_main.main(["remediate", "--db", db_path, "--out", str(out), "--apply-safe"])
    assert rc == 3
    assert out.exists()  # read-only artifact still produced


def test_cli_db_read_failure_exits_2_no_proposals(tmp_path):
    # Point at a path that is a directory -> init_db/read fails.
    bad_db = tmp_path / "adir"
    bad_db.mkdir()
    out = tmp_path / "p.json"
    rc = cli_main.main(["remediate", "--db", str(bad_db), "--out", str(out)])
    assert rc == 2
    assert not out.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_cli.py -k cli_ -v`
Expected: FAIL — argparse rejects `remediate` (invalid choice) / handler missing.

- [ ] **Step 3: Write minimal implementation**

In `core/cli/main.py`, add `"remediate"` to the `choices` list (after `"okf-ingest"`):

```python
    parser.add_argument(
        "command",
        choices=["audit", "discover", "populate", "lifecycle", "serve",
                 "graph", "probe", "overview", "okf-produce", "okf-ingest",
                 "remediate"],
    )
```

Add the remediate-specific flags near the other `add_argument` calls (after `--bundle`):

```python
    parser.add_argument("--file", action="store_true",
                        help="[remediate] actually file Paperclip issues (default: dry-run)")
    parser.add_argument("--apply-safe", action="store_true",
                        help="[remediate] arm SafeFixer (MVP: errors, NotImplementedError)")
    parser.add_argument("--max-llm-calls", type=int, default=0,
                        help="[remediate] Hermes diagnosis batch cap (default 0 = skip Hermes)")
```

Add the handler block BEFORE `engine = init_db(args.db)` at line 159 (it manages its own engine + exit codes; mirrors okf-produce). Place it right after the `okf-ingest` block:

```python
    if args.command == "remediate":
        import uuid
        from core.remediation.run import run_remediate
        from core.remediation.hermes_adapter import HermesAdapter
        # remediate-specific --out default: --out still defaults to ./bundle
        # (okf-produce's default), so substitute ./proposals.json when unset.
        out_path = "./proposals.json" if args.out == "./bundle" else args.out
        # DB-read failure -> exit 2 BEFORE writing any proposals.json (spec §6).
        try:
            engine = init_db(args.db)
            with get_session(engine) as session:
                from core.remediation.run import read_unhealthy
                read_unhealthy(session)  # force a read; surfaces a corrupt/unreadable DB
        except Exception as exc:   # narrow: DB open/read is the only thing here
            print(f"remediate: cannot read DB: {exc}", file=sys.stderr)
            return 2
        sid = str(uuid.uuid4())
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        hermes = HermesAdapter() if args.max_llm_calls > 0 else None
        try:
            with get_session(engine) as session:
                summary = run_remediate(
                    session, out_path=out_path, do_file=args.file,
                    apply_safe=args.apply_safe, max_llm_calls=args.max_llm_calls,
                    session_id=sid, generated_at=generated_at, hermes=hermes)
        except OSError as exc:
            # proposals.json write failure (disk/permission): summary lost, but
            # surface clearly and exit 4 (spec §6).
            print(f"remediate: failed to write proposals: {exc}", file=sys.stderr)
            return 4
        print(json.dumps(summary["counts"]))
        print(f"remediate: wrote {out_path}; issues_filed={summary['issues_filed']}",
              file=sys.stderr)
        if summary["apply_safe_requested"]:
            print("remediate: --apply-safe not yet implemented; ran proposal-only. "
                  "Re-run without --apply-safe for proposals.", file=sys.stderr)
            return 3
        return 0
```

> **`except Exception` note:** the DB-read guard catches broadly *only* around `init_db` + a single read because SQLAlchemy raises a family of `OperationalError`/`DatabaseError` types that don't share one narrow base worth enumerating here; the body does nothing but print + return 2, so it does not swallow logic errors. This is the one justified broad catch (an explicit, documented boundary), consistent with the prober's per-future `except Exception` isolation.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest tests/test_remediation_cli.py -v`
Expected: all pass.

- [ ] **Step 5: Run the full remediation suite + a smoke against the real demo DB**

```bash
cd /Users/jcords-macmini/projects/a2a-cli-registry
python -m pytest tests/test_remediation_*.py -q
python -m core.cli.main remediate --db demo/registry.db --out /tmp/proposals.json --config demo/config.toml
python -c "import json; e=json.load(open('/tmp/proposals.json')); \
from collections import Counter; \
print(Counter(p['failure_class'] for p in e['proposals']))"
```
Expected: suite green; the Counter shows the spec §1 distribution (pip-3rd-party for numpy/weasyprint/markdown/…, wrong-cwd for proven-local syllabus_v2/engine, pip-unknown for unmapped, unknown for the ~114 path-only rows).

- [ ] **Step 6: Run the FULL project test suite (no regressions)**

Run: `cd /Users/jcords-macmini/projects/a2a-cli-registry && python -m pytest -q`
Expected: all pre-existing tests still pass (remediate adds no DB schema change).

- [ ] **Step 7: Commit**

```bash
git add core/cli/main.py tests/test_remediation_cli.py
git commit -m "feat(remediation): wire remediate subcommand with spec'd exit codes"
```

---

## Self-Review

**Spec coverage:**
- §2.1 `RemediationProposal` + axes constraints → Task 1 (+ FixKind derivation in Tasks 2/3).
- §3.1 classifier, `IMPORT_TO_PACKAGE`, `MAP_VERSION`, proven-local check → Task 2.
- §3.2 Hermes (unknowns-only, batch ≤10, `max_calls` cap, 4 degradation modes, FailureRecord) → Task 3.
- §3.3 Paperclip (cluster by (class,target), order-independent hash, `list --json` read, missing-script skip, needs-human filed) → Task 4.
- §3.4 SafeFixer (eligibility all-required, symlink-escape refusal, apply stubbed) → Task 5.
- §3.5 envelope (schema/map_version, generated_at, session_id, failure_records) → Task 1 (`build_envelope`) + Task 6 (wiring).
- §4 CLI surface + §5 data-flow order + §6 exit codes (2/3/4) → Tasks 6–7.
- §7 testing strategy: every named case mapped to a test (alias cases, non-mapped≠local, degradation modes, hash order-independence, refusals, exit codes).
- §8 MVP scope (proposal-only default; SafeFixer stubbed) → honored throughout. §9 reversibility: no DB schema change (verified — `core/models.py` untouched).

**Placeholder scan:** none — every code step carries full implementations and exact commands.

**Type consistency:** `RemediationProposal`/`FailureRecord` field names and `to_dict()` keys are identical across Tasks 1/3/4/6. `cluster_hash` signature consistent (Task 4 def == Task 4 use). `diagnose() -> (proposals, records)` tuple consumed correctly in Task 6. `run_remediate` kwargs in Task 6 def == Task 7 call. `is_eligible`/`venv_path_ok` names consistent.

**One known seam to watch during execution:** Task 7's exit-2 guard does a throwaway `read_unhealthy()` to force a DB read. If `init_db` auto-creates a fresh empty DB for a non-existent path (it does — SQLModel `create_all`), exit-2 only fires for a genuinely *unreadable* DB (e.g. the directory-as-db-path test), not a missing one. That matches the spec ("corrupt DB"), and the test uses a directory path to trigger it.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-25-remediation-adapter.md`.
