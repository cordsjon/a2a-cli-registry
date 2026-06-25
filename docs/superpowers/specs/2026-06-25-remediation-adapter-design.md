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
        │                 │                    ∩ allowlist ∩ --apply-safe
        │           HermesAdapter.diagnose()         │
        │           (deepseek-v4-flash via :9109)     SafeFixer.apply()
        │                 │                    (sandbox venv; STUBBED in MVP)
        └────────┬────────┘                          │
        PaperclipAdapter.file(propose-only proposals) │
        (cluster by (class,target); dry_run default)  └─▶ re-probe, flip health
```

### 2.1 The single new contract: `RemediationProposal`

A typed value object (mirrors how `CapabilityRecord` is a value object), defined
in `core/remediation/proposal.py`:

```python
@dataclass(frozen=True)
class RemediationProposal:
    slug: str
    failure_class: str   # pip-3rd-party | wrong-cwd | wrong-venv |
                         # code-bug | env-missing | unknown
    fix_kind: str        # auto-safe | propose-only | needs-human
    target: str          # e.g. "weasyprint" | venv path | env var name | ""
    confidence: str      # declared-by-regex | llm-inferred
    evidence: str        # failure note + what matched (audit trail)
```

`failure_class` and `fix_kind` are independent axes: `pip-3rd-party` is the only
class that can carry `fix_kind=auto-safe`, and only when its `target` is on the
allowlist. Everything else is `propose-only` or `needs-human`.

---

## 3. Components

### 3.1 `classify.py` — deterministic classifier

```python
def classify_failure(slug: str, note: str, path: str) -> RemediationProposal
```

Pure and total — never raises; an unmatched note yields `failure_class=unknown,
fix_kind=needs-human`. Rules, in order:

1. Extract a missing-module name from `ModuleNotFoundError: No module named 'X'`.
   - If `X` ∈ `THIRD_PARTY_ALLOWLIST` → `pip-3rd-party`, `auto-safe`, target=X.
   - Else (local-looking name) → `wrong-cwd`, `propose-only`, target=X.
2. `SyntaxError` / `IndentationError` → `code-bug`, `needs-human`.
3. `env`/`API key`/`KeyError: '...ENV...'` signals → `env-missing`,
   `propose-only`, target=env var if extractable.
4. `FileNotFoundError` → `wrong-cwd`, `propose-only`.
5. Anything else → `unknown`, `needs-human` (routed to Hermes).

`THIRD_PARTY_ALLOWLIST` is a curated, in-repo set of known-PyPI package names
seen across the fleet. It is conservative by design: a name not on the list is
NEVER auto-installed, only proposed. Growing the list is a reviewed change, not
an automatic one.

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

- Eligible **only** for `failure_class=pip-3rd-party` AND
  `confidence=declared-by-regex` AND `target ∈ THIRD_PARTY_ALLOWLIST`.
- Gated behind `remediate --apply-safe`. Absent flag = pure proposal mode.
- Installs into a **dedicated sandbox venv** (`demo/.remediation-venv`), never
  the system or any project venv. A bad install cannot corrupt anything outside
  the sandbox.
- Re-probes the CLI **inside the sandbox venv**; flips `health_status` to
  healthy only if the re-probe passes. Records `fixed_by=remediation` provenance.
- Atomic per CLI: an install/probe failure leaves that CLI unhealthy with the
  proposal recorded; no partial-state writes.
- **Never** touches `wrong-cwd` / `wrong-venv` / `code-bug` / `env-missing`.

In the MVP, `apply()` raises `NotImplementedError`; the contract, eligibility
gate, and tests for the *refusal* behavior are written, but no live install runs
this session.

---

## 4. CLI surface

New subcommand in `core/cli/main.py`:

```
a2a-cli-registry remediate [--db PATH]
                           [--file]            # actually file Paperclip issues (default: dry-run)
                           [--apply-safe]      # arm SafeFixer (MVP: errors, NotImplementedError)
                           [--max-llm-calls N] # Hermes diagnosis cap (default: 0 = skip Hermes)
```

Default invocation (`remediate --db demo/registry.db`) is fully read-only: it
classifies, prints a summary table, and writes `proposals.json`. No network, no
mutation, no issue filing unless `--file`. Hermes is opt-in via `--max-llm-calls`.

---

## 5. Data flow

```
remediate [--file] [--apply-safe] [--max-llm-calls N]:
  1. read unhealthy rows (probe already populated them)
  2. classify_failure() each            → proposals        [deterministic]
  3. if N>0: HermesAdapter.diagnose(unknowns, max_calls=N)  [LLM, capped, degradable]
  4. if --apply-safe: SafeFixer.apply(pip-3rd-party ∩ allowlist) → re-probe   [MVP: errors]
  5. PaperclipAdapter.file(propose-only proposals, dry_run=not --file)
  6. print summary table + write proposals.json
```

---

## 6. Error handling

- **Classifier:** pure/total — unmatched input → `unknown`, never raises.
- **Hermes:** per-call try/except; any failure downgrades that batch to
  `unknown / needs-human`. Hermes being down does not fail the pass.
- **Paperclip:** `paperclip.sh` non-zero exit is caught; the proposal set is
  still written to `proposals.json` so no work is lost.
- **SafeFixer (when armed):** install failure → CLI stays unhealthy, proposal
  recorded; atomic per CLI, no partial writes.

All three external dependencies (Hermes, Paperclip, pip) are bulkheaded: a
failure in one degrades its own output and never corrupts the DB or aborts the
others.

---

## 7. Testing strategy

| Unit | Cases |
|------|-------|
| `classify_failure` | Table-driven over the real taxonomy: `ModuleNotFoundError: numpy` → pip-3rd-party; `ModuleNotFoundError: syllabus_v2` → wrong-cwd (NOT pip); `SyntaxError` → code-bug; env signal → env-missing; FileNotFound → wrong-cwd; gibberish → unknown. Asserts the third-party-vs-local split explicitly. |
| `HermesAdapter` | Mock the HTTP call: (a) unknowns-only filter, (b) degradation-on-non-200 returns `unknown/needs-human`, (c) `max_calls` cap logs skipped count. |
| `PaperclipAdapter` | (a) clustering by `(class,target)`, (b) `dry_run=True` default writes YAML without shelling, (c) idempotency: existing open issue → skipped. Mock `paperclip.sh`. |
| `SafeFixer` | (a) `apply()` raises NotImplementedError in MVP, (b) eligibility gate refuses non-allowlist names and all non-pip classes (assert via the eligibility predicate, which is implemented even though `apply` is stubbed). |

The classifier is the highest-value test target — it is the deterministic core
that decides what is safe to auto-fix vs. what must stay proposal-only.

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
- `--apply-safe` (when implemented) only ever writes to a sandbox venv and flips
  `health_status`; reverting is deleting the sandbox venv + re-probing.
