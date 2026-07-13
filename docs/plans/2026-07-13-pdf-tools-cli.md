# pdf-tools CLI Implementation Plan

> **For agentic workers:** REQUIRED: Use `/sh:execute` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a self-contained `pdf-tools` shell CLI that fills the 5 PDF-manipulation gaps (split, redact, compress, form-fill, convert) via a self-managed local Stirling PDF Docker backend, and register it in the a2a-cli-registry so agents discover it on-demand.

**Architecture:** A single POSIX-`sh` script (`lang: shell`, declaration-only — the registry has no shell adapter, it uses `stub_adapter`, so capability is declared in the feed, not probed by executing code). The script exposes 5 subcommands, each POSTing multipart to Stirling's REST API on **port 8091** (dagu holds 8080). `ensure_backend()` starts the container on demand with a bounded health-wait and never hangs. Registration is via a feed entry appended to the cli-audit JSON, then `populate` + `probe`. No PDF generation (WeasyPrint/ReportLab keep that); no merge (SVG-PAINT pypdf keeps that).

**Tech Stack:** POSIX sh, `curl`, `jq`, Docker (`stirlingtools/stirling-pdf`), Python (registry `populate`/`probe`), `bats` or shell-assertion tests.

**Spec:** `docs/specs/2026-07-13-pdf-manipulation-consolidation-design.md` (panel-passed 8.6).

---

## Pre-flight (read before Task 1)

- **Grounded facts** (verified 2026-07-13, cite before trusting):
  - Port 8080 is held by dagu (`lsof -iTCP:8080`). Use **8091**.
  - `file:pdf`, `file:png`, `file:docx` are already in `[vocabulary].registered` — `demo/config.toml:7`. No vocab edit needed.
  - Feed `confidence` defaults to `"declared"` when omitted — `core/discovery/cli_audit_source.py:41`. Only an explicit `"inferred"` gets pruned by `_hop_excluded` (`core/planner/search.py:71-74`). Set `confidence:"declared"` explicitly for self-documentation; never set `"inferred"`.
  - Feed entry required keys: `slug`, `lang`, `path` — `cli_audit_source.py:10`. Optional: `bucket`, `project`, `description`, `not_standalone`, `capability`.
  - `capability` may be a single object OR the plan uses **two rows** (safe vs destructive). NOTE: verify the feed loader accepts a *list* under `capability` — the golden feed uses a single object (`tests/golden_clis/fleet.json`). See Task 5 Step 0.
  - `populate` is invoked as `python -m core.cli.main populate --config <cfg>` (entrypoint `core/cli/main.py:272`).
- **Config target:** the live feed path is `cli_audit_path` in the active config TOML. `demo/config.toml:1` → `demo/cli-audit/latest.json`. The plan writes the entry into the demo feed for testing; the operator points it at the production feed at rollout.

---

## File Structure

| File | Responsibility |
|---|---|
| `<fleet>/pdf-tools/pdf-tools` | The CLI executable (POSIX sh). Fleet dir, not the registry repo. Registry indexes it by absolute `path`. |
| `<fleet>/pdf-tools/lib/backend.sh` | `ensure_backend()` + health-wait + idle-reap. Sourced by the CLI. |
| `<fleet>/pdf-tools/README.md` | Usage, the 5 verbs, backend lifecycle, port note. |
| `<fleet>/pdf-tools/tests/test_pdf_tools.bats` | bats tests for arg parsing, ensure_backend fail-paths, each verb (mocked curl). |
| `<fleet>/pdf-tools/tests/fixtures/sample.pdf` | 3-page fixture PDF for split/convert tests. |
| `demo/cli-audit/latest.json` (registry repo) | Append the `pdf-tools` feed entry (test scope). |

`<fleet>` = the fleet root where loose CLIs live. **Task 0 resolves the exact path** — the golden feed uses `/g/<slug>` placeholders, which is not a real path. Do not guess; resolve it.

---

## Chunk 1: Backend lifecycle + endpoint discovery

### Task 0: Resolve fleet path + start Stirling once to capture its live API

**Files:**
- Create: scratch notes only (no committed file yet)

- [ ] **Step 1: Resolve where fleet CLIs actually live**

Query the live registry DB for existing fleet CLIs' real (non-placeholder) paths:
```bash
sqlite3 /Users/jcords-macmini/.hermes/cli-registry.db \
  "select slug, path from cli where path not like '/g/%' and path != '' limit 10;"
```
Expected: real absolute paths. Pick the common parent dir → that is `<fleet>`. Record it. If all paths are heterogeneous, choose `~/projects/<sensible>/pdf-tools` and note the decision.

- [ ] **Step 2: Start Stirling on 8091**

Run:
```bash
docker run -d --name stirling-pdf --restart unless-stopped -p 8091:8091 \
  -e SERVER_PORT=8091 stirlingtools/stirling-pdf:latest
```
Expected: a container id. (`SERVER_PORT` env re-homes Stirling off its internal 8080 to 8091 so host and container agree.)

- [ ] **Step 3: Wait for health, then capture the OpenAPI spec**

Run:
```bash
for i in $(seq 1 60); do curl -fsS http://localhost:8091/api/v1/info/status && break; sleep 2; done
curl -fsS http://localhost:8091/v1/api-docs -o /tmp/stirling-openapi.json
jq -r '.paths | keys[]' /tmp/stirling-openapi.json | grep -Ei 'split|compress|img|image|password|redact|form|fill'
```
Expected: the exact endpoint paths for split, compress, pdf-to-image, add/remove-password, redact, fill-form. **Record each path + its multipart field names** (`jq '.paths["<path>"].post.requestBody' /tmp/stirling-openapi.json`). These are the ground truth for Tasks 2-4; do not use doc-site guesses.

- [ ] **Step 4: Record health endpoint**

Confirm `/api/v1/info/status` returns 200 (used by `ensure_backend`). If it 404s, find the real health path in the OpenAPI keys and use that everywhere below.

- [ ] **Step 5: Commit the captured endpoint map**

```bash
mkdir -p <fleet>/pdf-tools/docs
cp /tmp/stirling-openapi.json <fleet>/pdf-tools/docs/stirling-openapi-snapshot.json
git -C <fleet-repo> add pdf-tools/docs/stirling-openapi-snapshot.json
git -C <fleet-repo> commit -- pdf-tools/docs/stirling-openapi-snapshot.json \
  -m "chore(pdf-tools): snapshot Stirling OpenAPI for endpoint pinning"
```
(If `<fleet>` is not a git repo, skip the commit and keep the snapshot in place; note it.)

---

### Task 1: `ensure_backend()` with bounded, non-hanging health wait

**Files:**
- Create: `<fleet>/pdf-tools/lib/backend.sh`
- Test: `<fleet>/pdf-tools/tests/test_pdf_tools.bats`

- [ ] **Step 1: Write the failing test**

```bash
# tests/test_pdf_tools.bats
setup() { export PDF_BACKEND_URL="http://localhost:8091"; export PDF_BACKEND_TIMEOUT=4; }

@test "ensure_backend fails fast and non-zero when docker is absent" {
  PATH="$BATS_TEST_DIRNAME/mocks/no-docker:$PATH"   # docker -> exit 127 shim
  run bash -c 'source ../lib/backend.sh; ensure_backend'
  [ "$status" -ne 0 ]
  [[ "$output" == *"Docker"* ]]
}

@test "ensure_backend returns 0 when status endpoint already healthy" {
  PATH="$BATS_TEST_DIRNAME/mocks/healthy:$PATH" # curl shim returns 200
  run bash -c 'source ../lib/backend.sh; ensure_backend'
  [ "$status" -eq 0 ]
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd <fleet>/pdf-tools/tests && bats test_pdf_tools.bats`
Expected: FAIL — `backend.sh` not found / functions undefined.

- [ ] **Step 3: Write minimal `backend.sh`**

```sh
# lib/backend.sh — POSIX sh
: "${PDF_BACKEND_URL:=http://localhost:8091}"
: "${PDF_BACKEND_TIMEOUT:=60}"
: "${PDF_IMAGE:=stirlingtools/stirling-pdf:latest}"

_die() { echo "pdf-tools: $1" >&2; exit "${2:-1}"; }

_backend_healthy() {
  curl -fsS "$PDF_BACKEND_URL/api/v1/info/status" >/dev/null 2>&1
}

ensure_backend() {
  _backend_healthy && return 0
  command -v docker >/dev/null 2>&1 || _die "Docker not found. Install Docker Desktop, then retry." 3
  if ! docker ps --format '{{.Names}}' | grep -qx stirling-pdf; then
    docker run -d --name stirling-pdf --restart unless-stopped \
      -p 8091:8091 -e SERVER_PORT=8091 "$PDF_IMAGE" >/dev/null 2>&1 \
      || _die "failed to start Stirling container" 4
  fi
  i=0
  while [ "$i" -lt "$PDF_BACKEND_TIMEOUT" ]; do
    _backend_healthy && return 0
    i=$((i+2)); sleep 2
  done
  _die "Stirling not healthy after ${PDF_BACKEND_TIMEOUT}s. Last logs:
$(docker logs --tail 20 stirling-pdf 2>&1)" 5
}
```

- [ ] **Step 4: Add the mock shims, run tests to pass**

Create `tests/mocks/no-docker/docker` (chmod +x, `exit 127`) and `tests/mocks/healthy/curl` (chmod +x, `echo '{"status":"UP"}'; exit 0`).
Run: `bats test_pdf_tools.bats`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git -C <fleet-repo> add pdf-tools/lib/backend.sh pdf-tools/tests/
git -C <fleet-repo> commit -- pdf-tools/lib/backend.sh pdf-tools/tests/ \
  -m "feat(pdf-tools): self-managed Stirling backend with bounded health wait"
```

---

## Chunk 2: The 5 verbs

### Task 2: Verb dispatch + atomic output + `split`

**Files:**
- Create: `<fleet>/pdf-tools/pdf-tools`
- Test: `<fleet>/pdf-tools/tests/test_pdf_tools.bats` (extend)

- [ ] **Step 1: Write the failing test**

```bash
@test "split posts to the pinned endpoint and writes output atomically" {
  PATH="$BATS_TEST_DIRNAME/mocks/split-ok:$PATH"  # curl shim writes a fake pdf, exit 0
  run ../pdf-tools split fixtures/sample.pdf --pages 1-3 -o /tmp/out.pdf
  [ "$status" -eq 0 ]
  [ -f /tmp/out.pdf ]
  [ ! -f /tmp/out.pdf.tmp ]           # tmp cleaned up
  [[ "$output" == *"/tmp/out.pdf"* ]] # prints the path
}

@test "no output file remains when curl fails" {
  PATH="$BATS_TEST_DIRNAME/mocks/curl-500:$PATH"
  run ../pdf-tools split fixtures/sample.pdf --pages 1-3 -o /tmp/out2.pdf
  [ "$status" -ne 0 ]
  [ ! -f /tmp/out2.pdf ]
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `bats test_pdf_tools.bats`
Expected: FAIL — `pdf-tools` not found.

- [ ] **Step 3: Write minimal `pdf-tools` with dispatch + `_run_op` + split**

```sh
#!/bin/sh
# pdf-tools — PDF manipulation via local Stirling. Verbs: split redact compress form-fill convert
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$HERE/lib/backend.sh"

usage() { echo "usage: pdf-tools {split|redact|compress|form-fill|convert} <in.pdf> [opts] -o <out.pdf>" >&2; exit 2; }

# _run_op <endpoint> <out> <curl-form-args...>
_run_op() {
  endpoint=$1; out=$2; shift 2
  ensure_backend
  tmp="$out.tmp"
  if curl -fsS -X POST "$PDF_BACKEND_URL$endpoint" "$@" -o "$tmp"; then
    [ -s "$tmp" ] || { rm -f "$tmp"; _die "empty response from $endpoint" 6; }
    mv -f "$tmp" "$out"
    echo "$out"
  else
    rc=$?; rm -f "$tmp"; _die "Stirling op failed ($endpoint), rc=$rc" 6
  fi
}

cmd=${1:-}; [ -n "$cmd" ] || usage; shift || true
case "$cmd" in
  split)
    infile=$1; shift
    pages=""; out=""
    while [ $# -gt 0 ]; do case $1 in
      --pages) pages=$2; shift 2;;
      -o) out=$2; shift 2;;
      *) usage;; esac; done
    [ -f "$infile" ] || _die "input not found: $infile" 2
    [ -n "$out" ] || usage
    # ENDPOINT + field names come from Task 0 snapshot. Placeholder below —
    # replace /api/v1/general/split-pages + fields with the pinned values.
    _run_op "/api/v1/general/split-pages" "$out" \
      -F "fileInput=@$infile" -F "pageNumbers=$pages"
    ;;
  redact|compress|form-fill|convert) _die "verb '$cmd' implemented in later task" 2;;
  *) usage;;
esac
```

- [ ] **Step 4: Add split mock shims + fixture, run tests to pass**

Generate `tests/fixtures/sample.pdf` (3 pages): `python3 -c "from reportlab.pdfgen import canvas; c=canvas.Canvas('fixtures/sample.pdf'); [ (c.drawString(72,720,f'p{n}'), c.showPage()) for n in (1,2,3)]; c.save()"` (reportlab is already in the fleet). Add `mocks/split-ok/curl` (writes `%PDF-1.4\n...` to the `-o` target, exit 0), `mocks/curl-500/curl` (exit 22).
Run: `bats test_pdf_tools.bats`
Expected: PASS.

- [ ] **Step 5: Replace placeholder endpoint with the Task 0 pinned value, re-run against LIVE backend**

Run (real backend up): `../pdf-tools split fixtures/sample.pdf --pages 1-2 -o /tmp/live.pdf && pdfinfo /tmp/live.pdf | grep Pages`
Expected: `Pages: 2`. If the endpoint/field names differ from the placeholder, fix from the snapshot. **This is the AC-1/AC-2 evidence for split.**

- [ ] **Step 6: Commit**

```bash
git -C <fleet-repo> add pdf-tools/pdf-tools pdf-tools/tests/
git -C <fleet-repo> commit -- pdf-tools/pdf-tools pdf-tools/tests/ \
  -m "feat(pdf-tools): verb dispatch, atomic output, split verb"
```

---

### Task 3: `compress` + `convert` (writes-fs verbs)

**Files:**
- Modify: `<fleet>/pdf-tools/pdf-tools` (add two `case` arms)
- Test: extend bats

- [ ] **Step 1: Write failing tests** for `compress in.pdf -o out.pdf` and `convert in.pdf --to png -o out.png` (mock curl returns bytes; assert atomic write + path echo).
- [ ] **Step 2: Run → FAIL** (`_die "implemented in later task"`).
- [ ] **Step 3: Implement** both arms calling `_run_op` with the **Task 0 pinned** compress + pdf-to-image endpoints and their field names. `convert --to` maps `png|jpg|docx` → the right Stirling endpoint (image vs. pdf-to-word are different endpoints — read the snapshot).
- [ ] **Step 4: Run mocked tests → PASS.**
- [ ] **Step 5: Live check** — compress a real PDF (assert output smaller: `[ $(stat -f%z out.pdf) -lt $(stat -f%z in.pdf) ]`), convert to png (assert `file out.png` says PNG). **AC-2 evidence.**
- [ ] **Step 6: Commit** `-- pdf-tools/pdf-tools pdf-tools/tests/ -m "feat(pdf-tools): compress + convert verbs"`.

---

### Task 4: `redact` + `form-fill` (destructive verbs)

**Files:**
- Modify: `<fleet>/pdf-tools/pdf-tools`
- Test: extend bats

- [ ] **Step 1: Write failing tests** for `redact in.pdf --words "SECRET" -o out.pdf` and `form-fill in.pdf --data fields.json -o out.pdf`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** both arms via `_run_op` with pinned endpoints. form-fill reads a JSON of field→value and maps to Stirling's fill-form multipart shape (per snapshot).
- [ ] **Step 4: Mocked tests → PASS.**
- [ ] **Step 5: Live check** — redact a known word, assert the word is absent from `pdftotext out.pdf -` (true removal, not overlay). **AC-2 evidence + validates the redact-removes-text claim.**
- [ ] **Step 6: Commit** `-- ... -m "feat(pdf-tools): redact + form-fill destructive verbs"`.

- [ ] **Step 7: Assert `--help` lists exactly the 5 verbs, no generate/merge** (AC-6):
Run: `../pdf-tools 2>&1 | grep -Eo 'split|redact|compress|form-fill|convert|generate|merge'`
Expected: the 5 verbs only; no `generate`/`merge`.

---

## Chunk 3: Registry integration + end-to-end

### Task 5: Feed entry + populate + discoverability

**Files:**
- Modify: `demo/cli-audit/latest.json` (registry repo — the feed)
- Test: `tests/test_pdf_tools_registration.py` (registry repo)

- [ ] **Step 0: VERIFY the loader accepts a capability LIST (blocking check)**

The golden feed uses a single `capability` object; this plan needs two rows. Confirm the loader path handles a list before authoring the entry:
```bash
grep -n "capability" core/discovery/cli_audit_source.py core/populate.py core/capability/*.py
```
If `capability` is read as a single dict (`entry["capability"]` → one `CapabilityRecord`), then EITHER (a) the feed schema supports a list and populate iterates it, or (b) it does not. **If it does not, fall back to one merged row** with `intent_tags` = all 6 verbs and `side_effect: "destructive"` (the safe conservative default — everything gets gated, caller passes `allow_side_effects`), and log a follow-up to add per-verb side-effect granularity. Record which branch you took.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pdf_tools_registration.py
def test_pdf_tools_discoverable(tmp_registry):  # fixture: populated demo DB
    from core.catalog.queries import search_cli_catalog
    hits = search_cli_catalog(tmp_registry, "pdf")
    assert any(c.slug == "pdf-tools" for c in hits)

def test_safe_verbs_included_unguarded(tmp_registry):
    from core.catalog.queries import plan_cli_chain
    plan = plan_cli_chain(tmp_registry, ["file:pdf"], ["file:pdf"], allow_side_effects=None)
    slugs = {h for chain in plan for h in chain}
    assert "pdf-tools" in slugs   # split/compress/convert must survive (confidence=declared)
```

- [ ] **Step 2: Run → FAIL** (entry not in feed yet).

- [ ] **Step 3: Append the feed entry** (from spec §3.3, with `confidence:"declared"`):

```json
{
  "slug": "pdf-tools",
  "lang": "shell",
  "path": "<fleet>/pdf-tools/pdf-tools",
  "description": "PDF manipulation: split, redact, compress, form-fill, convert (Stirling-backed, local)",
  "not_standalone": false,
  "capability": [
    {"intent_tags":["split","compress","convert"],"input_types":["file:pdf"],
     "output_types":["file:pdf","file:png","file:docx"],"side_effect":"writes-fs","confidence":"declared"},
    {"intent_tags":["redact","fill","encrypt"],"input_types":["file:pdf"],
     "output_types":["file:pdf"],"side_effect":"destructive","confidence":"declared"}
  ]
}
```
(If Task 5 Step 0 said single-row, use the merged fallback entry instead.)

- [ ] **Step 4: Populate + probe, run tests to pass**

Run:
```bash
python -m core.cli.main populate --config demo/config.toml
python -m core.cli.main probe --config demo/config.toml   # shell lang → stub_adapter, declared-only
pytest tests/test_pdf_tools_registration.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Prove the side-effect gate BOTH directions** (AC-4):

```bash
python -m core.cli.main graph --config demo/config.toml 2>/dev/null | grep -i redact || echo "redact absent unguarded (correct)"
```
Then a guarded `plan_cli_chain(..., allow_side_effects=["destructive"])` includes redact. Assert in a test.
Expected: redact excluded unguarded, included guarded; split/compress/convert included unguarded.

- [ ] **Step 6: Commit** `-- demo/cli-audit/latest.json tests/test_pdf_tools_registration.py -m "feat(pdf-tools): register in cli-audit feed; discoverability + gate tests"`.

---

### Task 6: End-to-end verification + README + idle-reaper note

**Files:**
- Create: `<fleet>/pdf-tools/README.md`
- Modify: `<fleet>/pdf-tools/lib/backend.sh` (optional idle-reap, v1.1 — documented not built if it complicates)

- [ ] **Step 1: Cold-start E2E** (backend DOWN → verb → output) — the AC-1 headline:

```bash
docker rm -f stirling-pdf 2>/dev/null || true
../pdf-tools split fixtures/sample.pdf --pages 1-3 -o /tmp/e2e.pdf
pdfinfo /tmp/e2e.pdf | grep Pages    # expect Pages: 3, container auto-started on 8091
```
Expected: output produced from a cold start. Quote the result.

- [ ] **Step 2: No-Docker fail path E2E** (AC-5): temporarily shadow docker with the no-docker mock, run a verb, assert non-zero + actionable message + no hang (wrap in `timeout 15`).

- [ ] **Step 3: Write README** — the 5 verbs, examples, backend lifecycle, the 8091 port rationale, and "this CLI never generates PDFs (see WeasyPrint) and never merges (see SVG-PAINT)".

- [ ] **Step 4: Decide idle-reaper** — if a simple `--reap-after N` background check is clean, add it + a test; else document the RAM trade-off ("~1-2GB JVM container stays warm until manually `docker stop stirling-pdf`") and defer to v1.1. Record the decision.

- [ ] **Step 5: Full AC sweep** — walk AC-1..AC-7 from the spec, quote one command+result per AC. Any red = fix before done.

- [ ] **Step 6: Commit + finish** `-- pdf-tools/README.md pdf-tools/lib/backend.sh -m "docs(pdf-tools): README + backend lifecycle; complete AC sweep"`. Then `/sh:finish` for merge/PR.

---

## Verification Matrix (spec AC → plan step)

| AC | Proven by |
|---|---|
| AC-1 self-start | Task 6 Step 1 (cold-start E2E) |
| AC-2 five verbs atomic | Task 2 S5, Task 3 S5, Task 4 S5 (live checks) |
| AC-3 discoverable | Task 5 S4 |
| AC-4 gate both directions | Task 5 S5 |
| AC-5 no-hang failure | Task 6 Step 2 |
| AC-6 no generate/merge | Task 4 Step 7 |
| AC-7 capability map committed | spec already committed (`d593c3b`) |

## Risks carried from spec §8

- **Speculative demand** — do not build until a concrete PDF task lands (invoice batching / scan redaction). This plan is execute-ready; parking it is the recommended default.
- **Capability-list schema** — Task 5 Step 0 is a real blocking unknown; the single-row fallback keeps the plan shippable either way.
- **Stirling endpoint drift** — mitigated by Task 0 snapshotting the running instance's own OpenAPI rather than trusting doc-site paths.
