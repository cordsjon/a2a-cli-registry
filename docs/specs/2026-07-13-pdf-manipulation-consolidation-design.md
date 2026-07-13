# PDF Manipulation Consolidation — Design Spec

- **Date:** 2026-07-13
- **Status:** Draft (pending user review)
- **Owner:** Jonas Cords
- **Project:** `a2a-cli-registry` (new fleet CLI + registry entry) with a self-hosted Stirling PDF backend
- **Related tenets:** `token-frugality`, `repurpose-before-build`, `do-no-harm`, `MVA`

---

## 1. Problem & Motivation

The fleet is **over-provisioned on PDF generation and nearly empty on PDF manipulation.** A fleet-wide inventory (2026-07-13) found:

- **Generation:** 4+ redundant WeasyPrint HTML/MD→PDF pipelines (SVG-PAINT `generate_pdf.py`, its KETO fork, Consigliere report renderer, briefing-publisher) plus a ReportLab poster lineage duplicated across 6+ `generate_poster.py` scripts. **Adequately covered — over-covered.**
- **Manipulation:** the canonical manipulation verb set is **seven** — `merge`, `ocr`, `split`, `redact`, `compress`, `form-fill`, `convert`. Of these, only `merge` has real tooling (SVG-PAINT `collection_overview_pdf_service.py`, pypdf) and `ocr` has two narrow tools (`mistral_ocr` = cloud API; `termux-ocr-server` = image-only). **The remaining five verbs have zero tooling anywhere in the fleet:** `split`, `redact`, `compress`, `form-fill`, and local `convert`. (`extract` / OCR-to-searchable-PDF is a related but separate capability — deferred to v1.1, see §7.) No `pikepdf`/`ocrmypdf`/`ghostscript`/`qpdf` exists in any project.

Agents (hermes-adapter fleet, Claude Code) therefore cannot split, redact, compress, form-fill, or locally convert a PDF. This spec closes those gaps with **one** consolidated, best-of-breed capability→tool mapping — not a new silo.

### Non-goals

- **No new PDF generation.** WeasyPrint and ReportLab remain the owners. This CLI never generates PDFs.
- **No native MCP server** for Stirling. A permanently-mounted MCP server loads ~50 tool schemas into every session's context regardless of use — a direct violation of `token-frugality`. The A2A CLI registry is the on-demand alternative: schema cost is paid only when a PDF task surfaces.
- **SVG-PAINT is out of scope.** Its pypdf `merge` and PDF-atom services are a mature product engine; `do-no-harm` applies. The capability map *records* SVG-PAINT as the owner of `merge` without modifying it.
- **Generation-side homogenization is a secondary goal, logged not executed.** See §7.

---

## 2. Capability → Tool Map (the core deliverable)

Best-of-breed, one owner per verb, zero duplication:

| Verb | Owner tool | Status | Notes |
|---|---|---|---|
| **generate** (HTML/MD→PDF) | WeasyPrint | keep, untouched | 4 existing pipelines; not this CLI's concern |
| **generate** (poster) | ReportLab (`poster_template.py`) | keep, untouched | homogenization candidate (§7) |
| **merge** | pypdf (SVG-PAINT) | keep, untouched | mature; SVG-PAINT owns it. `pdf-tools` does NOT implement merge |
| **ocr** | `mistral_ocr` (cloud API) | keep as primary | Stirling local OCR added as a **fallback/offline** path only (see AC-6) |
| **split** | **Stirling** | NEW (gap) | page-range / burst-to-pages |
| **redact** | **Stirling** | NEW (gap) | true redaction (removes underlying text), not overlay |
| **compress** | **Stirling** | NEW (gap) | shrink-to-fit |
| **form-fill** | **Stirling** | NEW (gap) | AcroForm field fill |
| **convert** (local) | **Stirling** | NEW (gap) | pdf↔image, pdf→docx, etc. — local, no cloud |

**`pdf-tools` implements exactly the 5 NEW verbs + optional offline-OCR fallback.** merge/generate stay where they are.

---

## 3. Architecture & Components

```
agent / hermes-adapter
   │  (discovers via producer-relevance, on demand)
   ▼
a2a-cli-registry  ──►  pdf-tools  (shell CLI, lang: shell)
                          │  ensure_backend()
                          ▼
                    Stirling PDF (Docker, headless)
                    http://localhost:8091   ← NOT 8080 (dagu holds 8080)
                          │  REST API
                          ▼
                    result written atomically to -o <path>
```

### 3.1 `pdf-tools` CLI

- **Language:** `shell` (`lang: shell`). Rationale: the registry's Go/Node/shell adapters are stubs, so a non-Python CLI works purely by **declaring** its capability in the feed — lowest friction. A shell script calling Stirling's REST API via `curl` needs no runtime beyond Docker + curl.
- **Location:** fleet CLI directory (same convention as existing fleet CLIs; exact path resolved in `/sh:plan`). The registry indexes it by absolute `path`; the executable lives in the fleet, not inside the registry repo.
- **Subcommands (v1):** `split`, `redact`, `compress`, `form-fill`, `convert` (+ `ocr` fallback, gated — see AC-6).
- **Every subcommand:** `pdf-tools <verb> <input.pdf> [args] -o <output.pdf>`. Prints the output path to stdout on success.

### 3.2 Self-managed Stirling backend

`ensure_backend()` on every invocation:
1. `GET http://localhost:8091/api/v1/info/status` — if healthy, proceed.
2. If down: `docker run -d --restart unless-stopped -p 8091:8091 stirlingtools/stirling-pdf` (restart policy → survives reboot).
3. Poll health up to `PDF_BACKEND_TIMEOUT` (default 60s). On timeout: fail with the last `docker logs` tail, **never hang** (ref: codex-stdin-hang lesson — bounded waits only).
4. Run the op via REST; write output atomically (tempfile + `Path.replace` equivalent in shell: write to `$out.tmp`, `mv` on success).
5. **Idle-reaper (optional, v1.1):** a background check tears the container down after `PDF_BACKEND_IDLE_MIN` idle minutes. v1 may leave it running; document the RAM cost.

### 3.3 Registry integration (feed-driven, not manifest)

The registry has **no hand-authored per-CLI manifest**. Registration path:
1. Add a feed entry to the cli-audit JSON consumed by `populate` (path set by `cli_audit_path` in the active config TOML).
2. Run `a2a-cli-registry populate --config <cfg>` then `probe`.
3. Once in `registry.db`, the CLI is automatically exposed over the registry's existing A2A + MCP surface and becomes searchable/chainable via `search_cli_catalog` / `plan_cli_chain`.

**Feed entry shape** (two capability rows to respect the planner's side-effect gate):

```json
{
  "slug": "pdf-tools",
  "lang": "shell",
  "path": "<fleet>/pdf-tools/pdf-tools",
  "description": "PDF manipulation: split, redact, compress, form-fill, convert (Stirling-backed, local)",
  "not_standalone": false,
  "capability": [
    {
      "intent_tags": ["split", "compress", "convert"],
      "input_types": ["file:pdf"],
      "output_types": ["file:pdf", "file:png", "file:docx"],
      "side_effect": "writes-fs",
      "confidence": "declared"
    },
    {
      "intent_tags": ["redact", "fill", "encrypt"],
      "input_types": ["file:pdf"],
      "output_types": ["file:pdf"],
      "side_effect": "destructive",
      "confidence": "declared"
    }
  ]
}
```

- `file:pdf`, `file:png`, `file:docx` are **already in the registry vocabulary** — no vocabulary changes needed. Ports chain for free (e.g. `ocr → split` type-connect).
- **Confidence must resolve to `declared` for both rows — which is the feed default, so simply DO NOT set `confidence: "inferred"`.** The planner's `_hop_excluded` (`core/planner/search.py:71-74`) excludes any `writes-fs`/`network` hop carried by an **inferred** capability, even when the caller has not restricted side-effects. Grounding note: `core/discovery/cli_audit_source.py:41` defaults an omitted `confidence` to `"declared"` (fixing the old bridge bug that hardcoded declared for everything). So a hand-authored feed entry that omits `confidence` is already treated as declared and its `writes-fs` verbs flow freely. **Setting `confidence: "declared"` explicitly (as below) is the safe, self-documenting choice — it is harmless because it matches the default, and it guards against a future feed-builder that flips the default.** The hazard to avoid is an LLM-enriched feed stamping these rows `inferred`, which would silently prune `split`/`compress`/`convert` from every unguarded plan.
- **Safe vs. destructive split is mandatory:** with `confidence: declared` set, the planner *excludes* only `destructive` verbs unless the caller passes `allow_side_effects` (`_UNSAFE_DEFAULT = {"destructive","unknown"}`, `search.py:9`). `redact`/`form-fill`/`encrypt` mutate/remove content → `destructive`. `split`/`compress`/`convert` → `writes-fs` (declared → not gated).
- Slug `pdf-tools` + PDF verbs guarantee it matches `producer_terms=["pdf", …]` (substring predicate over slug/description + capability blob).

---

## 4. Data Flow

1. Agent has a PDF task → registry `plan_cli_chain` with `producer_terms=["pdf","split",…]` ranks `pdf-tools`.
2. Registry describes the CLI + args; agent invokes `pdf-tools <verb> … -o out.pdf`.
3. CLI `ensure_backend()` → Stirling up on 8091.
4. CLI POSTs to the Stirling REST endpoint for that verb; streams result to `out.tmp`.
5. On HTTP 200 + non-empty body: `mv out.tmp out.pdf`, print path, exit 0.
6. Any failure: no partial output, exit non-zero, actionable message.

---

## 5. Error Handling

| Condition | Behaviour |
|---|---|
| Docker not installed | Exit non-zero, message: how to install Docker. No hang. |
| Backend not healthy within timeout | Exit non-zero with `docker logs` tail. No hang. |
| Port 8091 already taken by non-Stirling | Detect, exit with clear message (do not assume it's ours). |
| Input file missing/not a PDF | Exit non-zero, no output written. |
| Stirling returns non-200 or empty body | Exit non-zero, delete `.tmp`, surface Stirling error. |
| `destructive` verb called without `allow_side_effects` at plan layer | Planner excludes it (registry behaviour, not CLI). |

---

## 6. User Story & Acceptance Criteria

**US-PDF-MANIP-01** — *As an agent in the fleet, I can split, redact, compress, form-fill, and locally convert a PDF via one discoverable CLI, so that document workflows complete locally without a permanently-mounted MCP server or a new generation silo.*

- **AC-1 (self-start):** `pdf-tools split in.pdf --pages 1-3 -o out.pdf` with the backend **down** auto-starts Stirling on **8091** and produces `out.pdf`. Verified: command → `out.pdf` exists, is a valid 3-page PDF.
- **AC-2 (five gap verbs):** `split`, `redact`, `compress`, `form-fill`, `convert` each succeed against Stirling's REST API with **atomic** output writes (no partial file on failure). Verified per verb.
- **AC-3 (discoverable):** after `populate` + `probe`, `search_cli_catalog` returns `pdf-tools` for a "pdf" query and `plan_cli_chain` with `producer_terms=["pdf"]` ranks it. Verified: op output shows the slug.
- **AC-4 (side-effect gate, both directions):** `redact`/`form-fill` are **excluded** from an unguarded plan and **included** only with `allow_side_effects`; AND `split`/`compress`/`convert` are **included** in an unguarded plan (proving `confidence: declared` correctly prevents the `writes-fs` inferred-exclusion path in `search.py:71-74`). Verified via `plan_cli_chain` calls covering both the guarded and unguarded cases — a regression that re-inferred the safe verbs would fail this AC, not pass silently.
- **AC-5 (no-hang failure):** backend-down + Docker-absent exits **non-zero** with an actionable message within the timeout, no hang. Verified.
- **AC-6 (no generation, no merge overlap):** `pdf-tools` exposes **no** generate/merge subcommand. OCR is present only as an explicit **offline fallback** subcommand documented as secondary to `mistral_ocr`. Verified: `pdf-tools --help` lists exactly the 5 gap verbs (+ gated `ocr`), no `generate`/`merge`.
- **AC-7 (capability map committed):** the capability→tool map (§2) is committed as the single source of truth for which tool owns each PDF verb. Verified: file present in repo.

---

## 7. Secondary Goal — Homogenizing the PDF Landscape (logged, NOT executed here)

The inventory exposed real generation-side sprawl. This spec does **not** execute it (scope + `do-no-harm` + SVG-PAINT carve-out), but records it as follow-on backlog:

- **US-PDF-GEN-CONSOLIDATE (backlog):** collapse the 4 redundant WeasyPrint HTML/MD→PDF pipelines (KETO fork, Consigliere renderer, briefing-publisher — **excluding SVG-PAINT**) and the 6+ duplicated ReportLab `generate_poster.py` scripts into one shared generation library. Separate spec → plan → implementation cycle. Higher risk (multi-project); not gated behind this CLI.
- The `pdf-tools` capability map (§2) becomes the registry the homogenization effort de-duplicates against.
- **US-PDF-EXTRACT (deferred to v1.1):** `extract` / OCR-to-searchable-PDF (local text+table extraction, e.g. PyMuPDF4LLM or Stirling's OCR-to-searchable) is a real fleet gap (Consigliere's `pdf-ingest` is backlog-only, `mistral_ocr` is cloud). It is **explicitly out of v1** — no verb, capability row, or AC — to keep v1 to the 5 net-new manipulation verbs. When built, it declares `input_types:[file:pdf]`, `output_types:[file:pdf, text:doc]`, `side_effect: writes-fs`, `confidence: declared`, and chains `ocr → split`/`convert` for free.

---

## 8. Open Questions / Risks

- **Speculative demand:** no *recurring* PDF-manipulation need is yet proven. Risk: an idle JVM container for a hypothetical. **Mitigation:** self-start + idle-reap means zero idle cost when unused; but confirm a real first use (invoice batching? scan redaction?) before building.
- **Stirling REST endpoint stability:** exact API paths per verb resolved during `/sh:plan` against Stirling's current API version.
- **Idle-reaper** deferred to v1.1 if it complicates v1; document the RAM trade-off either way.

---

## 9. Verification Plan

Each AC has a concrete command. Full end-to-end: start with backend down → run one of each verb → assert outputs → run `populate`/`probe`/`search_cli_catalog` → assert discoverability → run two `plan_cli_chain` calls to prove the side-effect gate. No "done" without quoted command output.
