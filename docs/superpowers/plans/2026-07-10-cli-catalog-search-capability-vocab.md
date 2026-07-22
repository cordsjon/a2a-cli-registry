# CLI Catalog Search: Match Capability Vocabulary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `search_clis` (`core/catalog/queries.py`) so a query also matches a CLI's `Capability.intent_tags`/`input_types`/`output_types`, not just its `slug`/`description` — fixing the registry-side root cause of US-CLIREG-DISCOVERY-QUALITY-01.

**Architecture:** Single-function change. `search_clis` gains a second lookup path: build an in-memory `{slug: lowercased_vocab_blob}` map from all `Capability` rows, then OR it into the existing substring check. No schema change, no new endpoint, no change to `describe_cli` or any other reader.

**Tech Stack:** Python 3.13, SQLModel, pytest, `.venv/bin/pytest` as the test runner (plain `pytest` on PATH lacks the project's dependencies).

## Global Constraints

- Query matching stays **case-insensitive substring containment** — no tokenization, no ranking, no ordering by relevance (spec "Out of scope").
- `query=""` and `query="  "` (whitespace-only) both return **all** rows, unchanged output shape from today.
- `search_clis` output row shape stays exactly `{slug, lang, description, health_status}` — never add a `capabilities` key (that stays `describe_cli`-only, MVA boundary from HOP-02).
- No N+1 query pattern: at most one extra `SELECT` on `Capability` per non-empty-query call, not one per `Cli` row.
- Do not modify `describe_cli`, `plan_cli_chain`, `cli_health`, `overview_rows`, or any file other than `core/catalog/queries.py` and its test file.
- Full spec: `docs/superpowers/specs/2026-07-10-cli-catalog-search-capability-vocab-design.md` (commits `bbc92cc`, `d93adf8`, `bb69fbb`).

---

### Task 1: Extend `search_clis` to match capability vocabulary

**Files:**
- Modify: `core/catalog/queries.py:70-75` (the `search_clis` function)
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `core.models.Cli`, `core.models.Capability` (already imported in `queries.py:3`); `core.health.norm_health` (imported as `_norm_health`, `queries.py:4`).
- Produces: `search_clis(session, query: str = "") -> list[dict]` — same public signature as today. Output dict shape: `{"slug": str, "lang": str, "description": str, "health_status": str}`. No new public names — the row-building helper (`_search_row`) is a private module-level function, not exported.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_catalog.py` (after the existing `test_search_returns_inert_dicts` at line 23-27):

```python
def test_search_matches_capability_output_types(db):
    """AC-01: a query matching an exact capability value (not present in
    slug/description) still finds the CLI via its Capability row."""
    db.add(Cli(slug="pdfgen", lang="python", description="scripts/pdfgen.py"))
    db.add(Capability(cli_slug="pdfgen", intent_tags="generate",
                      input_types="text:doc", output_types="file:pdf",
                      side_effect="none", confidence="inferred"))
    db.commit()
    rows = search_clis(db, "file:pdf")
    assert [r["slug"] for r in rows] == ["pdfgen"]


def test_search_capability_match_ignores_unrelated_cli(db):
    """A CLI whose capability vocab does NOT contain the query is excluded,
    even though another CLI in the same table matches."""
    db.add(Cli(slug="pdfgen", lang="python", description="scripts/pdfgen.py"))
    db.add(Capability(cli_slug="pdfgen", intent_tags="generate",
                      input_types="text:doc", output_types="file:pdf",
                      side_effect="none", confidence="inferred"))
    db.add(Cli(slug="imgconv", lang="python", description="scripts/imgconv.py"))
    db.add(Capability(cli_slug="imgconv", intent_tags="convert",
                      input_types="file:svg", output_types="file:png",
                      side_effect="none", confidence="inferred"))
    db.commit()
    rows = search_clis(db, "file:pdf")
    assert [r["slug"] for r in rows] == ["pdfgen"]


def test_search_no_capability_rows_falls_back_to_slug_description(db):
    """AC-03: a CLI with zero Capability rows is still matched by the
    existing slug/description check, and does not crash or spuriously
    match an empty vocab blob."""
    db.add(Cli(slug="legacycli", lang="shell", description="a legacy tool"))
    db.commit()
    rows = search_clis(db, "legacy")
    assert [r["slug"] for r in rows] == ["legacycli"]
    # a query that matches nothing in slug/description and there's no
    # capability vocab to match either -> no crash, empty result
    assert search_clis(db, "file:pdf") == []


def test_search_empty_query_returns_all_rows_unchanged(db):
    """AC-02 (empty case, regression guard): query="" still returns every
    row regardless of Capability data, same shape as today."""
    db.add(Cli(slug="a", lang="python", description="d1"))
    db.add(Cli(slug="b", lang="python", description="d2"))
    db.add(Capability(cli_slug="a", intent_tags="x", input_types="y",
                      output_types="z", side_effect="none", confidence="declared"))
    db.commit()
    rows = search_clis(db, "")
    assert {r["slug"] for r in rows} == {"a", "b"}
    assert rows[0].keys() == {"slug", "lang", "description", "health_status"}


def test_search_whitespace_only_query_returns_all_rows(db):
    """AC-02 (whitespace case, new correctness fix): query="  " must return
    all rows too, not fall into the non-empty branch and spuriously match
    on the joined-blob's internal spaces."""
    db.add(Cli(slug="a", lang="python", description="d1"))
    db.add(Cli(slug="b", lang="python", description="d2"))
    db.commit()
    rows = search_clis(db, "  ")
    assert {r["slug"] for r in rows} == {"a", "b"}


def test_search_output_shape_unchanged(db):
    """AC-04: capability-matched rows have the exact same shape as
    slug/description-matched rows -- no 'capabilities' key leaks through."""
    db.add(Cli(slug="pdfgen", lang="python", description="scripts/pdfgen.py"))
    db.add(Capability(cli_slug="pdfgen", intent_tags="generate",
                      input_types="text:doc", output_types="file:pdf",
                      side_effect="none", confidence="inferred"))
    db.commit()
    rows = search_clis(db, "file:pdf")
    assert rows[0] == {
        "slug": "pdfgen", "lang": "python",
        "description": "scripts/pdfgen.py", "health_status": "unknown",
    }
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/pytest tests/test_catalog.py -k "search_matches_capability or search_capability_match_ignores or search_no_capability_rows or search_empty_query_returns_all_rows_unchanged or search_whitespace_only or search_output_shape_unchanged" -v`

Expected: `test_search_matches_capability_output_types`, `test_search_capability_match_ignores_unrelated_cli`, and `test_search_whitespace_only_query_returns_all_rows` FAIL (capability vocab isn't searched yet; whitespace-only query currently falls into the non-empty branch, but with today's code an all-whitespace query still returns all rows by accident since `" " in blob` is true for every row — verify by reading the actual failure, don't assume). `test_search_no_capability_rows_falls_back_to_slug_description`, `test_search_empty_query_returns_all_rows_unchanged`, and `test_search_output_shape_unchanged` should already PASS against today's code (they exercise behavior that isn't changing) — confirm they pass now, so a later regression is visible.

- [ ] **Step 3: Implement the minimal change**

Replace `core/catalog/queries.py:70-75`:

```python
def search_clis(session, query: str = ""):
    rows = session.exec(select(Cli)).all()
    q = query.strip().lower()
    if not q:
        return [_search_row(c) for c in rows]
    caps = session.exec(select(Capability)).all()
    vocab_by_slug: dict[str, str] = {}
    for cap in caps:
        blob = " ".join([cap.intent_tags, cap.input_types, cap.output_types])
        vocab_by_slug[cap.cli_slug] = (
            vocab_by_slug.get(cap.cli_slug, "") + " " + blob
        ).lower()
    return [
        _search_row(c) for c in rows
        if q in (c.slug + " " + c.description).lower()
        or q in vocab_by_slug.get(c.slug, "")
    ]


def _search_row(c) -> dict:
    return {"slug": c.slug, "lang": c.lang, "description": c.description,
            "health_status": _norm_health(c.health_status)}
```

This is the spec's implementation sketch verbatim (`docs/superpowers/specs/2026-07-10-cli-catalog-search-capability-vocab-design.md:88-109`), already reviewed by Codex and spec-panel.

- [ ] **Step 4: Run the full test_catalog.py suite to verify all pass**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/pytest tests/test_catalog.py -v`

Expected: all tests PASS, including the 6 new ones and every pre-existing test in the file (`test_describe_flags_inferred_and_hides_launch_spec_by_default`, `test_describe_includes_launch_spec_when_requested`, `test_search_returns_inert_dicts`, `test_readers_preserve_not_standalone_health`, `test_readers_normalize_legacy_uppercase_health`, `test_overview_rows_returns_project_caps_edges_and_no_launch_spec`, and any others in the file — read the full pass count, don't assume).

- [ ] **Step 5: Run the full registry unit suite (AC-06)**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/pytest -x -q`

Expected: PASS, zero new failures compared to the pre-change baseline. If any test outside `test_catalog.py` fails, read it before assuming it's pre-existing — `search_clis` is called from `core/ops_registry.py:26` (the `search_cli_catalog` MCP/A2A op), `core/server/app.py:90`, and `core/cli/main.py:306` (per the spec's "Files touched" section), so a regression could surface in `tests/test_mcp.py`, `tests/test_mcp_http.py`, `tests/test_server_a2a.py`, `tests/test_e2e.py`, or `tests/test_cli.py`.

- [ ] **Step 6: Commit**

```bash
git add core/catalog/queries.py tests/test_catalog.py
git commit -m "$(cat <<'EOF'
fix(catalog): search_clis matches capability vocabulary, not just slug/description

search_clis only substring-matched query against slug+description, so a
query for a CLI's own correct output_types/input_types/intent_tags (e.g.
"file:pdf") returned zero hits even when describe_cli confirmed the CLI
had that exact capability. Root cause of US-CLIREG-DISCOVERY-QUALITY-01's
discovery-quality gap (hermes-adapter HOP-02 Task 7 live verify).

Extends the match to also check a per-CLI capability-vocabulary blob
(intent_tags + input_types + output_types, joined and lowercased). Output
row shape, empty-query behavior, and case-insensitive substring semantics
are unchanged; a whitespace-only query is now also treated as empty
(previously fell into the non-empty branch).

Spec: docs/superpowers/specs/2026-07-10-cli-catalog-search-capability-vocab-design.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Live verification (AC-05, AC-07)

**Files:** none modified — this task runs read-only probes against the live registry after Task 1 is deployed/reloaded.

**Interfaces:**
- Consumes: `hermes_adapter.tools.cli_registry._mcp_call` (existing helper, `~/.hermes/hermes-adapter/hermes_adapter/tools/cli_registry.py:409`) — used as a probe client, not modified.
- Produces: a recorded probe transcript (pasted into the task report, not a new file) confirming AC-05 and AC-07.

**Prerequisite:** Task 1 is committed AND the live `ai.hermes.cli-registry` launchd service has reloaded the new code (`launchctl kickstart -k gui/$(id -u)/ai.hermes.cli-registry`, or equivalent restart — confirm with whoever owns that deploy step; this task does not restart the service itself, only probes it after a restart has happened).

- [ ] **Step 1: Confirm the live service picked up the change**

Run: `launchctl print gui/$(id -u)/ai.hermes.cli-registry 2>&1 | grep -i state`

Expected: service is running. This step only confirms the process is up — it does NOT confirm the new code is loaded. Ask the human operator to confirm the restart happened before proceeding, since this plan cannot restart a launchd service itself (out of scope — deploy step, not implementation).

- [ ] **Step 2: Probe AC-05 (the original bug is fixed)**

Run (from `~/.hermes/hermes-adapter`, using the token read via `launchctl print gui/$(id -u)/ai.hermes.adapter | grep A2A_BEARER_TOKEN` as in the prior session):

```bash
cd ~/.hermes/hermes-adapter && A2A_BEARER_TOKEN="<token>" .venv/bin/python -c "
import asyncio
from hermes_adapter.tools.cli_registry import _mcp_call, _candidate_slugs

async def main():
    raw = await _mcp_call('search_cli_catalog', {'query': 'file:pdf'})
    all_slugs, healthy = _candidate_slugs(raw)
    print(f'file:pdf -> all={len(all_slugs)} healthy={len(healthy)} includes_generate_pdf={\"generate_pdf\" in all_slugs}')

asyncio.run(main())
"
```

Expected: `all` and `healthy` are non-zero, and `includes_generate_pdf=True`. If `all=0`, the live service has not reloaded the new code — stop and confirm the restart before continuing (do not treat this as a code defect without first confirming the deploy happened).

- [ ] **Step 3: Probe AC-07 (record cardinality, no fix required)**

Run the same probe pattern with `query` set to `"generate"`, `"convert"`, `"query"` in turn, recording each `all`/`healthy` count in the task report. Compare against the spec's pre-fix baseline (`"generate"` was untested pre-fix since it returned matches via slug substring already — the AC-07 numbers in the spec, 67/28/27, are `Capability` row counts, not `search_clis` result counts; record what `search_clis` actually returns post-fix as the true observation). No pass/fail threshold — this step's output IS the deliverable, feeding whichever Part B plan gets written next.

- [ ] **Step 4: Record results in the task report, no commit**

This task produces no code change — its report (probe outputs for AC-05 and AC-07) is the artifact. Append it to the plan's progress ledger or hand it directly to whoever writes Part B's spec next.

---

## Post-plan

Part B (`hermes-adapter` — reorder `handle_run_cli_command` to search with a single capability tag) is **not** started by this plan. Per the design spec's sequencing, write Part B's own spec (in `hermes-adapter/docs/superpowers/specs/`) only after Task 2's live probes are in hand, using AC-07's real cardinality numbers to decide whether "single most distinctive tag" needs any refinement before it's built.
