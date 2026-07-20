# pdf-tools bundle/unbundle — Reversible Multi-Doc PDF Packaging

- **Date:** 2026-07-20
- **Status:** Shipped
- **Owner:** Jonas Cords
- **Project:** `a2a-cli-registry` — `fleet-clis/pdf-tools` (existing CLI, new verbs)
- **Origin:** stolen from the format idea in
  [github.com/AlexandrosGounis/pdfx](https://github.com/AlexandrosGounis/pdfx)'s
  `SPEC.md` — not the Electron app, just the manifest trick. Reimplemented in
  Python (`pypdf`) instead of depending on the TS/Electron project.
- **Related tenets:** `repurpose-before-build`, `MVA`, `do-no-harm`

---

## 1. Problem & Motivation

`pdf-tools` (see `docs/specs/2026-07-13-pdf-manipulation-consolidation-design.md`)
deliberately has no bundling verb — `merge` was scoped to SVG-PAINT's mature
pypdf lineage and left untouched. But plain concatenation (what `merge`
does) is one-way: once pages are combined, the original document boundaries
are lost. There was no fleet capability to combine documents *reversibly*.

PDFx's format spec solves exactly this with one trick: embed a small JSON
manifest as a PDF file attachment recording each source document's name and
page count, in order. The combined file stays a fully valid, spec-compliant
PDF — any reader shows all pages in sequence — but a manifest-aware tool can
recover the original documents losslessly. No new container format, no
forked PDF spec.

This is a genuinely new capability (not overlap with `merge`, `split`, or
SVG-PAINT), implementable in ~140 lines of pure Python against a dependency
(`pypdf`) already vetted and in use elsewhere in the fleet (SVG-PAINT
`requirements.txt`).

### Non-goals

- **No dependency on the PDFx repo/app.** Only the manifest *format idea* is
  reused. No Electron, no TypeScript, no viewer UI.
- **No change to `merge`.** SVG-PAINT's pypdf merge stays untouched
  (`do-no-harm`); `bundle` is additive, not a replacement.
- **No Stirling involvement.** `bundle`/`unbundle` never touch the Docker
  backend — pure Python against the input file(s).

---

## 2. Format (pdfx manifest v1.0, as specified upstream)

Embedded as a PDF file attachment (ISO 32000-1:2008 §7.11.4) named
`pdfx-manifest.json`, UTF-8 JSON:

```json
{
  "pdfx": "1.0",
  "title": "optional collection title",
  "documents": [
    { "name": "docA", "pages": 3 },
    { "name": "docB", "pages": 2 }
  ]
}
```

Page ranges partition the combined page sequence in order: document *i*
owns the pages starting immediately after document *i-1*'s pages end.
A PDF with no such attachment is treated as a single document (graceful
degradation — plain PDFs are valid inputs to `unbundle`).

---

## 3. Implementation

- **`fleet-clis/pdf-tools/lib/bundle.py`** — pure-Python `pypdf` helper.
  `bundle(input_paths, out_path, title=None)` concatenates pages, embeds the
  manifest, atomic write (`.tmp` + `Path.replace`). `unbundle(input_path,
  out_dir)` reads the manifest (if present) and re-splits; falls through to
  a single-document passthrough if absent.
- **`fleet-clis/pdf-tools/pdf-tools`** — two new case branches (`bundle`,
  `unbundle`) shelling out to `lib/bundle.py` via a dedicated `.venv`
  (isolated from the root `a2a-cli-registry` venv — the registry service
  itself has no PDF dependency and shouldn't inherit one for a fleet CLI's
  sake). Same atomic-write / non-zero-on-failure conventions as the
  Stirling verbs, reusing `_die` from `lib/backend.sh`.
- **`fleet-clis/pdf-tools/requirements.txt`** — `pypdf>=4.0.0` (same
  version floor SVG-PAINT already pins).
- **`fleet-clis/pdf-tools/seed/feed-entries.json`** — `bundle`, `unbundle`,
  `merge` added to the `pdf-tools-safe` slug's `intent_tags` (writes-fs, not
  destructive — same row as `split`/`compress`/`convert`, no new slug
  needed).

---

## 4. User Story & Acceptance Criteria

**US-PDF-BUNDLE-01** — *As an agent or user merging multiple PDFs into one
deliverable, I want the merge to embed a recoverable manifest of the
original document boundaries, so that the combined file still opens as one
normal PDF everywhere, but can be losslessly split back into its original
documents later.*

- **AC-1 (valid PDF):** `bundle` output is a valid PDF, page count equals
  the sum of inputs. **Verified:** 3 fixtures (3+2+5 pages) → 10-page
  output, `pypdf.PdfReader` parses cleanly.
- **AC-2 (manifest present):** output carries exactly one attachment named
  `pdfx-manifest.json`, matching the field schema. **Verified:** attachment
  keys == `['pdfx-manifest.json']`; parsed JSON matches expected
  `documents[].name`/`pages`.
- **AC-3 (lossless round-trip):** `unbundle` reproduces N outputs with
  original page counts, in original order. **Verified:** docA/B/C page
  counts (3/2/5) round-tripped exactly.
- **AC-4 (graceful degradation):** `unbundle` on a plain PDF with no
  manifest attachment exits 0 and passes the input through as a single
  output doc — never errors. **Verified.**
- **AC-5 (no-hang / clean failure):** missing input file → non-zero exit,
  no output written, actionable stderr message. **Verified**, both for
  `bundle` (missing member file) and for the `.venv` missing.
- **AC-6 (registered, non-destructive):** capability row declares
  `side_effect: writes-fs`, `confidence: declared` on the existing
  `pdf-tools-safe` slug (same declared-not-inferred requirement as the
  other five verbs — see the consolidation spec §3.3 for why `inferred`
  would silently exclude it from unguarded plans).

All 6 ACs verified live — 16 new assertions added to
`tests/run_tests.sh` (auto-skips if `.venv`/`pypdf` absent, same pattern as
the existing live-form-fill test). Full suite: **34 passed, 0 failed**
(`sh fleet-clis/pdf-tools/tests/run_tests.sh`).

---

## 5. Open Questions / Risks

- **Registry apply not yet run.** `seed/apply.sh` upserts the feed +
  `populate`s the live registry; not executed as part of this spec (no
  live registry process confirmed running this session). Run before relying
  on `search_cli_catalog`/`plan_cli_chain` to discover `bundle`/`unbundle`.
- **Same speculative-demand caveat as the parent spec:** no recurring
  bundle/unbundle need proven yet. Cost of being wrong here is low (pure
  Python, no idle container, no RAM cost) — unlike the Stirling verbs.
