# Remediation Adapter — Design

**Date:** 2026-06-25
**Status:** Design (approved sections 1–3; pending spec review)
**Scope:** Add a `remediate` pass to the registry that classifies why unhealthy
CLIs fail and emits typed remediation proposals. Two adapters consume proposals:
Hermes (LLM diagnosis of the unknowns, cheapest model) and Paperclip (issue
tracking). One mutating path (`--apply-safe`) is specced but stubbed in the MVP.

---

## 1. Motivation & grounding data

A live probe of the 474-CLI fleet (2026-06-25) returned **257 healthy / 217
unhealthy**. Categorizing the 217 unhealthy failure notes:

| Count | Class | Fixability |
|------:|-------|------------|
| 106 | other / unknown | needs diagnosis (Hermes) |
| 80 | ModuleNotFoundError | **split — see below** |
| 24 | other runtime error | propose-only |
| 5 | ImportError | propose-only |
| 2 | FileNotFound | propose-only |

**The load-bearing insight:** `ModuleNotFoundError` is NOT one problem. The
missing-module names split into two populations:

- **Third-party (PyPI-resolvable):** `numpy`, `weasyprint`, `boto3`, `lxml`,
  `bs4`, `markdown`, `pptx`, `portalocker` — a genuine `pip install`.
- **First-party (local) modules:** `syllabus_v2` (×11), `engine` (×8), `app`
  (×8), `scripts`, `autopilot` — these are NOT on PyPI. The CLI is being invoked
  with the wrong working directory or wrong venv, not missing a dependency.

A naive "pip install the missing module" auto-fixer would (a) fail on the
majority of cases and (b) risk installing a PyPI typosquat for a name that was
meant to be a local import. **Distinguishing these two is the classifier's
primary job**, and it is why auto-fix is gated to an explicit third-party
allowlist.

---

## 2. Architecture

The registry already runs a `probe` pass that writes `cli.health_status` and a
failure note into `cli.description`. This feature adds a **third pass, after
probe: `remediate`** — read-only over the DB by default.

```
probe  ──writes──▶  cli.health_status + cli.description (failure note)
                          │
                   remediate pass (new)
                          │
        classify_failure(note, path, missing_module)   [deterministic, no I/O]
                 → RemediationProposal
                          │
        ┌─────────────────┼──────────────────────────┐
   class known      class == unknown          class == pip-3rd-party
        │                 │                    ∩ mapped ∩ --apply-safe
        │           HermesAdapter.diagnose()         │
        │           (deepseek-v4-flash via :9109)     SafeFixer.apply()
        │                 │                    (isolated install; STUBBED in MVP)
        └────────┬────────┘                          │
        PaperclipAdapter.file(propose-only + needs-human) │
        (cluster by (class,target); dry_run default)  └─▶ re-probe, flip health
```

### 2.1 The single new contract: `RemediationProposal`

A typed value object (mirrors how `CapabilityRecord` is a value object), defined
in `core/remediation/proposal.py`:

```python
SCHEMA_VERSION = 1

class FailureClass(str, Enum):
    PIP_3RD_PARTY = "pip-3rd-party"   # mapped third-party import; target = PyPI dist name
    PIP_UNKNOWN   = "pip-unknown"     # un-mapped import, not proven local; target = import name
    WRONG_CWD     = "wrong-cwd"       # proven-local module missing / FileNotFound; target = module/file
    CODE_BUG      = "code-bug"        # SyntaxError/IndentationError; target = ""
    ENV_MISSING   = "env-missing"     # missing env var / API key; target = var name if known else ""
    UNKNOWN       = "unknown"         # classifier abstained; target = ""; routed to Hermes

class FixKind(str, Enum):
    AUTO_SAFE    = "auto-safe"     # eligible for SafeFixer (pip-3rd-party only)
    PROPOSE_ONLY = "propose-only"  # file a Paperclip issue, no auto action
    NEEDS_HUMAN  = "needs-human"   # diagnosis incomplete; Hermes or human required

class Confidence(str, Enum):
    DECLARED_BY_REGEX = "declared-by-regex"
    LLM_INFERRED      = "llm-inferred"

@dataclass(frozen=True)
class RemediationProposal:
    schema_version: int           # == SCHEMA_VERSION
    slug: str
    failure_class: FailureClass
    fix_kind: FixKind
    target: str                   # semantics fixed per-class (see enum comments)
    confidence: Confidence
    evidence: str                 # failure note + what matched (audit trail)

    def to_dict(self) -> dict: ...   # enums serialized as their .value; for proposals.json
```

**Axes are independent but constrained:** `pip-3rd-party` is the ONLY class that
may carry `fix_kind=auto-safe`, and only when its `target` is a mapped PyPI
distribution name. `unknown` → `needs-human`. Everything else → `propose-only`.

**Paperclip routing by fix_kind:** `propose-only` AND `needs-human` proposals are
BOTH filed (a `needs-human` cluster is still actionable triage). `auto-safe`
proposals are filed only if SafeFixer is not armed or its fix failed — a
successfully auto-fixed CLI produces no issue.

---

## 3. Components

### 3.1 `classify.py` — deterministic classifier

```python
def classify_failure(slug: str, note: str, path: str) -> RemediationProposal
```

Pure and total — never raises; an unmatched note yields `failure_class=unknown,
fix_kind=needs-human`. Rules, in order:

1. Extract the missing import name `X` from
   `ModuleNotFoundError: No module named 'X'` (take the top-level segment of a
   dotted name: `google.cloud` → `google`).
   - **If `X` ∈ `IMPORT_TO_PACKAGE` map** → `pip-3rd-party`, `auto-safe`,
     `target = IMPORT_TO_PACKAGE[X]` (the PyPI *distribution* name, which often
     differs from the import name — see below).
   - **Else if a file named `X.py` or a package dir `X/` exists adjacent to the
     CLI's `path`** (proven local module) → `wrong-cwd`, `propose-only`,
     target=X.
   - **Else** → `pip-unknown`, `propose-only`, target=X. NOT auto-installed, NOT
     assumed local. This is the honest "we don't know if X is a third-party
     package we haven't mapped or a local module we can't see" bucket. It is
     filed for human review, never auto-fixed.
2. `SyntaxError` / `IndentationError` → `code-bug`, `needs-human`.
3. `env`/`API key`/`KeyError: '...ENV...'` signals → `env-missing`,
   `propose-only`, target=env var if extractable.
4. `FileNotFoundError` → `wrong-cwd`, `propose-only`.
5. Anything else → `unknown`, `needs-human` (routed to Hermes).

**`IMPORT_TO_PACKAGE` is an import-name → PyPI-distribution-name map, NOT a flat
set.** Import name and distribution name frequently differ, and treating them as
equal would auto-install the wrong package (or fail). Verified against the live
fleet, the map must cover at least: `bs4→beautifulsoup4`, `pptx→python-pptx`,
`docx→python-docx`, `fitz→PyMuPDF`, `Quartz→pyobjc`, `cv2→opencv-python`,
`PIL→pillow`, `yaml→pyyaml`, `sklearn→scikit-learn`, `dotenv→python-dotenv`,
plus the identity-mapped ones seen in the fleet (`numpy`, `boto3`, `lxml`,
`markdown`, `weasyprint`, `portalocker`, `reportlab`, `networkx`, `textual`,
`requests`, `httpx`, `flask`, `bottle`, `streamlit`, `cbor2`, `tinycss2`,
`static_ffmpeg`). The map is curated and in-repo: an import name not in the map
is NEVER auto-installed — it falls to `pip-unknown` and is only proposed.
Growing the map is a reviewed change, not automatic.

**Why a proven-local check, not a heuristic:** the previous design folded "not
on the allowlist" into `wrong-cwd`, which mislabels every un-mapped third-party
package (numpy, boto3, …) as a cwd problem. The classifier now only emits
`wrong-cwd` when it can *prove* a local module of that name exists adjacent to
the CLI; otherwise it abstains into `pip-unknown`.

### 3.2 `hermes_adapter.py` — LLM diagnosis (cheapest model)

```python
class HermesAdapter:
    def diagnose(self, unknowns: list[Cli], *, max_calls: int) -> list[RemediationProposal]
```

- **Input:** only CLIs the classifier marked `unknown`. Never re-diagnoses what
  regex already answered (token-frugality).
- **Call:** `POST http://localhost:9109/v1/chat/completions`, body
  `{"model": "deepseek-v4-flash", "messages": [...]}`. Hermes routes to the
  cheapest configured provider (verified: deepseek-v4-flash, ~$0.0007/call).
  Batched ≤10 CLIs per call to amortize overhead.
- **Prompt:** failure note + first ~20 lines of `--help` output + first ~40
  lines of source. Requests a strict-JSON `RemediationProposal` per CLI.
- **Degradation (bulkhead):** any non-200 / parse failure → return the inputs
  unchanged as `unknown / needs-human`. The pass degrades; it never crashes the
  registry. Mirrors the prober's per-future exception isolation.
- **Cost guard:** `max_calls` caps the number of HTTP *calls* (batches), not
  CLIs — at ≤10 CLIs/batch, the 106 unknowns need ~11 calls. If the cap is hit,
  remaining unknowns stay `unknown` and the CLI logs how many were skipped (no
  silent truncation).

### 3.3 `paperclip_adapter.py` — issue tracking

```python
class PaperclipAdapter:
    def file(self, proposals: list[RemediationProposal], *, dry_run: bool = True) -> list[IssueRef]
```

- **Clusters** proposals by `(failure_class, target)` → one issue per cluster,
  not per CLI. E.g. "install weasyprint (2 CLIs)" and "wrong-cwd in syllabus
  project (11 CLIs)" each become a single issue listing member CLIs in the body.
- **Emits** a `bulk-create` YAML and shells `paperclip.sh bulk-create <yaml>`.
  `dry_run=True` (default) writes + prints the YAML without filing.
- **Idempotency:** each issue title carries a stable short hash of
  `(failure_class, target)`. Before filing, the adapter queries
  `paperclip.sh list` and skips clusters that already have an open issue. Safe to
  re-run; no duplicate spam.

### 3.4 `SafeFixer` — the one mutating path (STUBBED in MVP)

```python
class SafeFixer:
    def apply(self, proposals: list[RemediationProposal]) -> list[FixResult]  # raises NotImplementedError in MVP
```

**Honest threat model (corrects an earlier overclaim):** a venv isolates
*packages*, NOT *execution*. `pip install` can run arbitrary `setup.py` /
build-backend code with the invoking user's full permissions — it can write
outside the venv (caches, `~`, config), open network connections, and follow
symlinks. "Install into a venv" is therefore NOT a security boundary by itself.
SafeFixer's containment is the sum of the constraints below, and even then it is
defense-in-depth, not a guarantee — which is exactly why it is opt-in,
allowlist-gated, and stubbed for the MVP.

- **Eligibility (all required):** `failure_class=pip-3rd-party` AND
  `confidence=declared-by-regex` AND `target` is a value in `IMPORT_TO_PACKAGE`
  (a mapped PyPI distribution name). Anything else is refused.
- Gated behind `remediate --apply-safe`. Absent flag = pure proposal mode.
- **Install containment requirements:**
  - Dedicated venv at a **canonicalized, symlink-resolved** path
    (`realpath`); refuse if the resolved path escapes the repo's `demo/` dir.
  - `pip install --only-binary=:all:` (**wheel-only** — no source builds, so no
    `setup.py` execution) for the eligible package; `--no-input`, pinned index,
    hard `--timeout`.
  - Isolated process env: scrubbed `HOME`, `PIP_CACHE_DIR`, `TMPDIR`, `XDG_*`
    pointed inside `demo/`; `PYTHONNOUSERSITE=1`; no inherited project env vars.
  - Wall-clock timeout + killpg on the install subprocess (reuse the prober's
    `_kill_tree`).
- **Re-probe after install** runs the CLI's `--help` in the same isolated env,
  with the prober's existing cwd/timeout/output-cap/killpg controls. The ONLY DB
  write permitted during re-probe is the single `health_status` (+ provenance)
  flip for that one CLI — no capability or edge writes.
- Flips `health_status` to healthy only if the isolated re-probe passes; records
  `fixed_by=remediation`.
- Atomic per CLI: an install/probe failure leaves that CLI unhealthy with the
  proposal recorded; no partial-state writes.
- **Never** touches `pip-unknown` / `wrong-cwd` / `code-bug` / `env-missing` /
  `unknown`.

In the MVP, `apply()` raises `NotImplementedError`; the eligibility predicate
and the *refusal* tests (non-mapped name, non-pip class, symlink-escape path)
ARE implemented, but no live install runs this session.

---

## 4. CLI surface

New subcommand in `core/cli/main.py`:

```
a2a-cli-registry remediate [--db PATH]
                           [--out PATH]        # proposals JSON path (default: ./proposals.json)
                           [--file]            # actually file Paperclip issues (default: dry-run)
                           [--apply-safe]      # arm SafeFixer (MVP: errors, NotImplementedError)
                           [--max-llm-calls N] # Hermes diagnosis cap (default: 0 = skip Hermes)
```

**"Read-only" defined precisely:** the default invocation performs NO network
call, NO DB mutation, and files NO issues. It DOES write one local artifact —
the proposals JSON at `--out` (default `./proposals.json`), overwritten
atomically (tempfile + `Path.replace`) on each run. "Read-only" means read-only
*with respect to the registry DB and external systems*, not zero filesystem
output. Hermes is opt-in via `--max-llm-calls` (default 0 = skipped); issue
filing is opt-in via `--file`.

**`--apply-safe` in the MVP:** SafeFixer raises `NotImplementedError`. The
command catches it, prints a clear "auto-fix not yet implemented; run without
--apply-safe for proposals" message, **still writes proposals.json and (if
`--file`) files issues**, then exits non-zero (code 3) to signal the requested
action didn't run. It does NOT abort before producing the proposal artifact —
the read-only work is never lost to an unimplemented mutating flag.

---

## 5. Data flow

```
remediate [--file] [--apply-safe] [--max-llm-calls N]:
  1. read unhealthy rows (probe already populated them)
  2. classify_failure() each            → proposals        [deterministic]
  3. if N>0: HermesAdapter.diagnose(unknowns, max_calls=N)  [LLM, capped, degradable]
  4. if --apply-safe: SafeFixer.apply(pip-3rd-party ∩ mapped) → re-probe   [MVP: NotImplementedError, caught]
  5. write proposals.json atomically (tempfile + Path.replace)
  6. PaperclipAdapter.file(propose-only + needs-human, dry_run=not --file)
  7. print summary table; exit 3 if --apply-safe was requested (MVP), else 0
```

---

## 6. Error handling

- **DB read failure / corrupt DB:** the read in step 1 is wrapped; a read error
  prints a clear message and exits non-zero (code 2) before any other work. No
  empty proposals.json is written for a DB that couldn't be read.
- **Classifier:** pure/total — unmatched input → `unknown`, never raises.
- **Hermes:** per-batch try/except covering connection-refused, **timeout**
  (hard request timeout), non-200, and **malformed/parse-failure JSON** — all
  downgrade that batch to `unknown / needs-human`. Hermes being down or slow
  never fails the pass.
- **proposals.json write failure** (disk-full, permission): atomic write via
  tempfile + `Path.replace`; a write failure leaves any prior file intact,
  prints the error, exits non-zero (code 4). The in-memory summary is still
  printed so the run's findings are visible.
- **Paperclip:** `paperclip.sh` **missing** (not on PATH) → skip filing with a
  warning, proposals.json already written. Non-zero exit from a present
  `paperclip.sh` → caught per cluster; remaining clusters still attempted.
- **SafeFixer (when armed):** install **timeout/hang** → killpg; install or
  re-probe failure → CLI stays unhealthy, proposal recorded; atomic per CLI, no
  partial writes.

All external dependencies (Hermes, Paperclip, pip, the DB) are bulkheaded: a
failure in one degrades its own output and never corrupts the DB or aborts the
others. The ordering (write proposals.json BEFORE filing issues) guarantees the
deterministic findings survive any external-system failure.

---

## 7. Testing strategy

| Unit | Cases |
|------|-------|
| `classify_failure` | Table-driven over the real taxonomy. **Mapped third-party** (`numpy`, `boto3`) → pip-3rd-party, target=dist name. **Import≠dist alias** (`bs4`→beautifulsoup4, `pptx`→python-pptx, `fitz`→PyMuPDF) → pip-3rd-party with the mapped distribution name, NOT the import name. **Un-mapped, not proven local** (`romsorter`, `skillmine`) → `pip-unknown` (NOT wrong-cwd, NOT auto-fix). **Proven local** (a `X.py` exists next to path) → wrong-cwd. **Dotted** (`google.cloud`) → top-segment lookup. `SyntaxError` → code-bug; env signal → env-missing; FileNotFound → wrong-cwd; gibberish → unknown. Explicitly asserts a non-mapped third-party name does NOT become wrong-cwd. |
| `HermesAdapter` | Mock the HTTP call: (a) unknowns-only filter, (b) non-200 → `unknown/needs-human`, (c) **connection-refused → degrade**, (d) **timeout → degrade**, (e) **malformed JSON response → degrade**, (f) `max_calls` (batch) cap logs skipped count, (g) batch size ≤10. |
| `PaperclipAdapter` | (a) clustering by `(class,target)`, (b) `dry_run=True` default writes YAML without shelling, (c) idempotency: existing open issue → skipped, (d) **`paperclip.sh` missing → warn + skip, proposals.json intact**, (e) needs-human proposals ARE filed. Mock `paperclip.sh`. |
| `SafeFixer` (predicate only) | (a) `apply()` raises NotImplementedError, (b) eligibility refuses **non-mapped** names, (c) refuses **all non-pip classes**, (d) **refuses a symlink-escape venv path** (resolved path outside `demo/`). |
| `remediate` CLI | (a) default makes **no network call and no DB mutation** (assert via spy), (b) writes proposals.json atomically to `--out`, (c) `--apply-safe` → exit 3 but proposals.json still written, (d) DB-read failure → exit 2, no proposals.json, (e) proposals.json write failure → exit 4, summary still printed. |

The classifier is the highest-value test target — it is the deterministic core
that decides what is safe to auto-fix vs. what must stay proposal-only. The
import≠distribution alias cases and the "non-mapped ≠ local" case are the
specific defects a pre-implementation review surfaced; they are mandatory.

---

## 8. MVP scope (this session)

**Build:** `core/remediation/{proposal.py, classify.py, hermes_adapter.py,
paperclip_adapter.py}` + `remediate` subcommand + tests. All proposal-only /
dry-run by default.

**Stub:** `SafeFixer.apply()` raises NotImplementedError. Its eligibility
predicate and refusal tests ARE implemented — the mutating path is
designed-and-guarded but not armed.

**Out of scope (follow-ups):** live `--apply-safe` installs; growing the
allowlist from observed data; `wrong-venv` auto-detection of the correct venv;
re-running discovery to refresh capabilities post-fix.

---

## 9. Reversibility

- Default `remediate` is read-only: revert = delete `core/remediation/` + the
  subcommand. No DB schema change (proposals live in `proposals.json`, not the
  DB, in the MVP).
- `--file` issues are visible in Paperclip and idempotency-keyed, so a bad run
  files at most one issue per cluster and can be closed in bulk.
- `--apply-safe` (when implemented) only ever wheel-installs into the isolated
  `demo/` venv and flips `health_status`; reverting is deleting that venv +
  re-probing. See §3.4 for the full containment requirements and the honest
  threat model (a venv isolates packages, not execution).
