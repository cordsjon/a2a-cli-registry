# CLI Catalog Search: Match Capability Vocabulary — Design

> **US-CLIREG-DISCOVERY-QUALITY-01** — follow-up to US-CLIREG-PLAN-HOP-02
> (`hermes-adapter`). Fixes the discovery-layer gap found during HOP-02 Task 7 live
> verify so AC-07 of the resolver spec (the live gate) can be demonstrated end-to-end.
> Two-repo change: Part A here (`a2a-cli-registry`), Part B in `hermes-adapter`.

## Problem

HOP-02's live verify (Task 7) found `hermes-adapter`'s `handle_run_cli_command` cannot
discover CLIs from a natural, verbose model-generated goal
(`"generate a pdf from a document"` → 0 catalog rows), while a single bare word
(`"pdf"`) → 9 rows. This was originally assumed to be an adapter-side query-phrasing
problem, fixable by having the adapter search with capability tags instead of raw
prose.

**Live investigation found the real cause is registry-side.** `search_clis`
(`core/catalog/queries.py:70-75`):

```python
def search_clis(session, query: str = ""):
    rows = session.exec(select(Cli)).all()
    q = query.lower()
    return [{"slug": c.slug, "lang": c.lang, "description": c.description,
             "health_status": _norm_health(c.health_status)}
            for c in rows if q in (c.slug + " " + c.description).lower()]
```

This is a **substring containment check against `slug + " " + description` only**.
Two consequences, both confirmed against the live registry (474 CLIs,
`~/.hermes/cli-registry.db`):

1. **`description` is frequently not prose.** For `generate_pdf`, `description` is
   `"50_KETO/scripts/generate_pdf.py"` — a file path. `"pdf"` matches only because it's
   a substring of that path, not because the registry understood the capability.
2. **`Capability.intent_tags`/`input_types`/`output_types` are never searched**, even
   though this data is correct and already exposed by `describe_cli`:
   ```json
   "capabilities": [{"intent_tags": ["generate"],
                      "input_types": ["file:pdf", "text:doc"],
                      "output_types": ["file:pdf"], ...}]
   ```
   Querying the exact value `"file:pdf"` or `"text:doc"` — the correct capability for
   this exact CLI — returns **zero** hits, live-confirmed:
   ```
   query='file:pdf'   all=0 healthy=0
   query='text:doc'   all=0 healthy=0
   ```

3. **The match is substring, not keyword/BM25** — a query only matches if it appears
   *verbatim* (exact characters, exact word order/spacing) inside the target blob,
   live-confirmed:
   ```
   query='pdf'              all=9 healthy=6
   query='document'         all=1 healthy=1
   query='document pdf'     all=0 healthy=0   (no CLI's blob contains this exact phrase)
   query='png_image'        all=0 healthy=0   (no literal such string anywhere)
   ```
   A multi-term query joined with a separator (e.g. `"png_image svg_file"`) will only
   match a CLI whose blob happens to contain that literal joined string — in practice,
   effectively never, since the blob is built from independent fields. The safe query
   contract for a caller is **one term, substring-matched** — joining terms is not a
   reliable way to broaden a match.

Net effect: no query construction strategy on the adapter side can make discovery
reliable while the registry only indexes `slug + description`. The fix belongs here.

## Approach

**Part A (this repo, primary fix):** extend `search_clis` to also substring-match the
query against each CLI's capability vocabulary — the union of `intent_tags`,
`input_types`, and `output_types` across all its `Capability` rows, joined as raw CSV
strings (not split into a list — see implementation sketch) and lowercased. A CLI
matches if the query is a substring of the existing `slug + description` blob **or**
the capability-vocabulary blob.

**Part B (`hermes-adapter`, dependent):** once Part A ships, reorder
`handle_run_cli_command` to call `_infer_capability_tags(goal)` before
`search_cli_catalog`, then search using `tags["goal_outputs"][0]` (the single most
distinctive term) instead of the raw goal. Single term only — per the confirmed
substring-match contract, a joined multi-term query would regress to zero hits. Full
detail in that repo's own spec/plan (written after Part A ships and its real search
behavior is re-probed).

### Part A implementation sketch

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

`intent_tags`/`input_types`/`output_types` are stored as raw CSV strings on
`Capability` (e.g. `"convert,extract"`) — matching against the CSV blob directly
(without splitting into a list) is sufficient for substring containment and mirrors
the existing style (`slug + " " + description` is also matched as one blob, not
token-split). No behavior change for CLIs with no `Capability` rows (empty vocab
string, no match contribution — falls through to the existing slug/description check).

**Known limitation, not a regression:** substring matching against unsplit CSV can
false-positive across field/token boundaries — e.g. query `"file:pdf"` would also match
a stored value `"file:pdfa"`, and a query landing on a comma boundary could match across
two unrelated CSV entries. The existing `slug + description` check already has this
class of imprecision (e.g. `"svg"` matches 60 CLIs live, far more than intended). Not
fixed here — token-exact matching would require splitting and is a larger change with
no evidence today's imprecision causes real false positives in practice.

### Preserved contracts

- `query=""` returns all rows (existing behavior — `tests/test_catalog.py:23`'s
  `test_search_returns_inert_dicts` and `tests/test_catalog.py:42`'s
  `test_readers_normalize_legacy_uppercase_health` both call `search_clis(db, "")`
  and depend on the inserted row coming back) — the empty-query branch is unchanged,
  added explicitly above to avoid computing vocab for the common list-everything case.
- `query="  "` (whitespace-only, non-empty): falls through to the non-empty branch
  today and would continue to. The sketch's `" ".join([...])` on an empty-`Capability`
  CLI produces a two-space string, which a whitespace-only query could match — a new
  spurious match not present today. Guard by stripping the query
  (`q = query.strip().lower()`) before the `if not q` check, so whitespace-only queries
  fall into the same "return everything" branch as truly empty ones. Minor, accepted
  side effect: a query with meaningful leading/trailing whitespace (e.g. `" pdf "`)
  today requires that literal padded substring; after stripping it matches like `"pdf"`
  — no existing test exercises this case, and it only ever makes a match *more*
  permissive, never drops an existing match.
- Output row shape (`slug, lang, description, health_status`) is unchanged —
  `search_clis` still does not return `capabilities` (that stays `describe_cli`-only,
  per the existing MVA boundary from HOP-02).
- Case-insensitive substring match, same as today.

## Non-goal

The model sometimes never invokes `run_cli_command` at all (asks clarifying questions
instead) — a distinct failure mode observed in HOP-02's Task 7 live run. That is a
system-prompt / tool-description concern on the adapter side, not a search-index
defect. Out of scope here.

## Scope (MVA)

**In scope:**
- Extend `search_clis` to also match `Capability.intent_tags`/`input_types`/
  `output_types` (Part A, this repo).
- Document the adapter-side reorder (Part B) as dependent follow-up work — not
  implemented in this repo, not implemented until Part A ships and is re-verified live.

**Out of scope:**
- Any change to `describe_cli`, `plan_cli_chain`, `cli_health`, or `overview_rows`.
- Token/BM25-style multi-word ranking — the substring contract is preserved, only the
  searched fields are extended. A real search engine (ranking, tokenization) is a
  larger change with no evidence it's needed yet.
- The adapter-side `handle_run_cli_command` reorder itself (Part B implementation —
  separate spec/plan in `hermes-adapter`, after Part A ships).
- The "model never calls the tool" failure mode (see Non-goal above).
- `US-CLIREG-SIDEEFFECT-GUARD-01` (already filed separately, unrelated).

## Acceptance Criteria

- **AC-01** — `search_clis(session, "file:pdf")` returns a row for `generate_pdf`
  (or the live-equivalent slug at test time) when that CLI has a `Capability` row with
  `output_types` containing `"file:pdf"`.
- **AC-02** — `search_clis(session, "")` and `search_clis(session, "  ")` both return
  all rows, unchanged from today for the empty case (regression guard for
  `tests/test_catalog.py:23`, `tests/test_catalog.py:42`) and newly-correct for the
  whitespace-only case (previously would have fallen into the non-empty branch).
- **AC-03** — A CLI with no `Capability` rows is matched only by the existing
  `slug + description` check — no crash, no spurious match from an empty vocab blob.
- **AC-04** — `search_clis` output row shape is unchanged (`slug, lang, description,
  health_status` — no `capabilities` key added).
- **AC-05 (live)** — Re-probe the live registry post-deploy: `search_cli_catalog`
  with query `"file:pdf"` returns a non-empty `all_slugs`/`healthy` set including
  `generate_pdf`.
- **AC-06** — Full registry unit suite green, zero new failures.

## Files touched

- Modify: `core/catalog/queries.py` — `search_clis` (lines 70-75).
- Test: `tests/test_catalog.py` (existing `search_clis` coverage — `test_search_returns_inert_dicts` at line 23, `test_readers_normalize_legacy_uppercase_health` at line 42 — both must stay green; new tests added for capability-vocab matching).
