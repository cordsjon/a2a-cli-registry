# pdf-tools

Local PDF **manipulation** for the agent fleet, backed by a self-managed
[Stirling PDF](https://stirlingpdf.com) Docker container.

> This CLI **never generates** PDFs (WeasyPrint / ReportLab own generation)
> and **never merges plain PDFs** (SVG-PAINT's pypdf owns merge). It fills the
> fleet's five manipulation gaps, plus `bundle`/`unbundle` (see below). See
> `docs/specs/2026-07-13-pdf-manipulation-consolidation-design.md`.

## Verbs

| Verb | Usage | Stirling endpoint |
|---|---|---|
| `split` | `pdf-tools split in.pdf --pages 1,3-5 -o out` | `/api/v1/general/split-pages` |
| `compress` | `pdf-tools compress in.pdf [--level 1-9] -o out.pdf` | `/api/v1/misc/compress-pdf` |
| `convert` | `pdf-tools convert in.pdf [--to png\|jpg] -o out.png` | `/api/v1/convert/pdf/img` |
| `redact` | `pdf-tools redact in.pdf --words "A,B" -o out.pdf` | `/api/v1/security/auto-redact` |
| `form-fill` | `pdf-tools form-fill in.pdf --data fields.json -o out.pdf` | `/api/v1/form/fill` |
| `bundle` | `pdf-tools bundle a.pdf b.pdf c.pdf -o out.pdf [--title T]` | none — local pypdf |
| `unbundle` | `pdf-tools unbundle out.pdf -o outdir/` | none — local pypdf |

Every verb prints the output path on success and exits non-zero (with no
partial output) on failure.

**Note on `split`:** splitting into multiple parts returns a **ZIP** of the
resulting PDFs, not a single PDF. Name the output accordingly (`-o out.zip`).

**Note on `redact`:** performs *true* redaction — the underlying text is
removed, not just visually covered (verified: a redacted word is absent from
the output's text layer).

**Note on `bundle`/`unbundle`:** stolen from
[github.com/AlexandrosGounis/pdfx](https://github.com/AlexandrosGounis/pdfx)'s
format spec (not the Electron app — just the idea). `bundle` concatenates
pages and embeds a `pdfx-manifest.json` file attachment (ISO 32000-1:2008
§7.11.4) recording each source document's name and page count. The output is
a fully valid PDF — any standard reader shows all pages in sequence.
`unbundle` reads the manifest back and re-splits pages exactly. A PDF with no
manifest attachment degrades to "one document" (`unbundle` copies it through
unchanged — the pdfx spec's graceful-degradation rule). Pure Python
(`pypdf`, via `.venv` in this directory) — no Stirling backend involved. See
`docs/specs/2026-07-20-pdf-bundle-manifest.md`.

Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
(one-time; `.venv/` is gitignored, not committed).

## Backend lifecycle

`pdf-tools` self-manages the Stirling container via `lib/backend.sh`:

1. On each call it probes `http://localhost:9141/api/v1/info/status`.
2. If down, it `docker run`s `stirlingtools/stirling-pdf`, **bound to
   `127.0.0.1:9141`** (not `0.0.0.0`) with `SECURITY_ENABLELOGIN=false`.
   Stirling 2.14.2 enforces an `X-API-KEY` header on all operations;
   disabling login is safe **only because the port is not LAN-reachable**.
3. It waits (bounded, `PDF_BACKEND_TIMEOUT`, default 60s) for health, then
   runs the op. It **never hangs** — on timeout it fails with the container
   log tail; if Docker is absent it exits with an actionable message.

**Port 9141 is portmgr-allocated** (service `stirling-pdf`). It is the
authority — never hardcode a different port. Re-derive with:
`curl -s http://localhost:9000/allocations | jq '.allocations["stirling-pdf"]'`.

**RAM cost:** the Stirling JVM container stays warm (~1–2 GB) until manually
stopped (`docker stop stirling-pdf`). An idle-reaper is deferred to v1.1.

Environment overrides: `PDF_BACKEND_URL`, `PDF_BACKEND_TIMEOUT`,
`PDF_BACKEND_PORT`, `PDF_IMAGE`, `PDF_CONTAINER`.

## Registry integration

Registered in the a2a-cli-registry as **two slugs sharing this one binary**,
because the registry's feed loader binds one capability row per slug and the
planner's side-effect gate must treat safe and destructive verbs differently:

- `pdf-tools-safe` → `side_effect: writes-fs` → split, compress, convert
- `pdf-tools-redact` → `side_effect: destructive` → redact, form-fill

So `redact`/`form-fill` are excluded from an unguarded plan and included only
when the caller passes `allow_side_effects=["destructive"]`.

### Reproducing the registry state on a new machine

The live feed (`demo/cli-audit/latest.json`) and `registry.db` are **gitignored
generated state** — the two `pdf-tools` entries and the `registry.db`
`not_standalone` migration do **not** travel with git. The committed
source-of-truth is `seed/feed-entries.json`; apply it (idempotent) with:

```sh
sh fleet-clis/pdf-tools/seed/apply.sh
```

This resolves the binary path, ensures the `not_standalone` column exists
(backing up `registry.db` first), allocates the `stirling-pdf` port via portmgr
(if reachable), upserts both entries into the live feed, and runs `populate`.
Re-running is a safe no-op.

## Tests

Dependency-free POSIX shell harness (no bats):

```sh
sh tests/run_tests.sh   # 12 assertions, mocked curl/docker
```

Live verification requires the backend; see the AC sweep in
`docs/plans/2026-07-13-pdf-tools-cli.md`.
