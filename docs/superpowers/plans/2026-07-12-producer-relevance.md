# Producer Relevance Rank Implementation Plan (US-CLIREG-PRODUCER-RELEVANCE-01)

> **For agentic workers:** REQUIRED: Use `/sh:execute` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compound-goal hop-1 producers are picked by semantic relevance (`producer_terms` → `relevance_rank` in `plan_chain`'s sort key, before the truncation cap), not by the alphabetical slug tie-break.

**Architecture:** Two-repo change per spec `docs/superpowers/specs/2026-07-12-producer-relevance-design.md` (panel 8.8 PASS, Codex CONFIRM). Registry half first: a leaf two-haystack match helper (`core/catalog/match.py`), `Chain.relevance_rank` slotted into `sort_key` between confidence and slugs, wrapper + ops-schema threading. Adapter half second: 5th LLM inference key `producer_terms` (free text, NOT vocab-guarded), forwarded on the `plan_cli_chain` call. Legacy ordering is invariant whenever terms are absent/empty/unmatched.

**Tech Stack:** Python 3.11, SQLModel/SQLite, pytest, MCP-over-HTTP ops.

**Read the spec first.** Every §-reference below is to `docs/superpowers/specs/2026-07-12-producer-relevance-design.md`. Prior-session lesson (Canvas-Shell): READ each target file before editing — line numbers drift.

**Repos:**
- Registry: `~/projects/a2a-cli-registry` (master, start at `d333d6c`)
- Adapter: `~/.hermes/hermes-adapter` (master, start at `d9e6a1b`)

**Commit rule:** commit-guard requires explicit paths: `git commit -m "..." -- <paths>`. Trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

## Chunk 1: Registry — shared match helper (spec §2.2 blob rule)

### Task 1: `core/catalog/match.py` leaf module + tests

**Files:**
- Create: `core/catalog/match.py`
- Create: `tests/test_match.py`
- Modify: `core/catalog/queries.py:70-86` (`search_clis` refactored onto the helper)

- [ ] **Step 1.1: Write the failing tests** — create `tests/test_match.py`:

```python
# tests/test_match.py
from core.catalog.match import clean_terms, ident_haystack, vocab_haystack, term_matches
from core.models import Capability


def _cap(**kw):
    base = dict(cli_slug="x", intent_tags="", input_types="", output_types="",
                side_effect="none", confidence="declared")
    base.update(kw)
    return Capability(**base)


def test_two_haystack_boundary_not_spanned():
    # spec §2.2: a term spanning the description-end/vocab-start boundary must
    # NOT match — a single five-field concatenation would accept it.
    ident = ident_haystack("mycli", "converts doc")
    vocab = vocab_haystack([_cap(intent_tags="convert", input_types="file:doc",
                                 output_types="text")])
    assert not term_matches("doc convert", ident, vocab)


def test_ident_and_vocab_hits():
    ident = ident_haystack("zzz_codename", "scripts/gen.py")
    vocab = vocab_haystack([_cap(intent_tags="generate", output_types="text")])
    assert term_matches("codename", ident, vocab)    # slug hit
    assert term_matches("gen.py", ident, vocab)      # description hit
    assert term_matches("generate", ident, vocab)    # vocab hit
    assert term_matches("CODENAME", ident, vocab)    # case-insensitive
    assert not term_matches("poster", ident, vocab)


def test_none_description_and_no_caps_are_safe():
    assert term_matches("mycli", ident_haystack("mycli", None), vocab_haystack([]))
    assert not term_matches("anything", ident_haystack("z", None), vocab_haystack([]))


def test_clean_terms_drops_junk():
    # spec §2.1: ops validator only checks the outer array type — this filter
    # is the real guard. Blank terms would substring-match EVERYTHING.
    assert clean_terms([42, "  ", None, " Codename ", ""]) == ["codename"]
    assert clean_terms(None) == []
    assert clean_terms([]) == []
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `cd ~/projects/a2a-cli-registry && python -m pytest tests/test_match.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'core.catalog.match'`

- [ ] **Step 1.3: Write the helper** — create `core/catalog/match.py`:

```python
# core/catalog/match.py
"""Shared term-match predicate — LEAF module (spec §2.2).

Imports nothing from catalog.queries or planner.search; BOTH import this file
(catalog.queries -> planner.search already exists, so the shared predicate must
sit below both to avoid a cycle). core/catalog/__init__.py is empty — verified,
no package-init import triggers.

Two-haystack semantics, extracted verbatim from search_clis: a term matches a
CLI iff it is a case-insensitive substring of (slug + " " + description) OR of
the aggregated capability-vocab string (intent_tags, input_types, output_types
over ALL capability rows of the slug). A single five-field concatenation would
permit synthetic matches spanning the description/vocab boundary that
search_clis cannot produce."""


def ident_haystack(slug: str, description: str | None) -> str:
    return f"{slug} {description or ''}".lower()


def vocab_haystack(caps) -> str:
    return " ".join(
        f"{c.intent_tags} {c.input_types} {c.output_types}" for c in caps
    ).lower()


def clean_terms(terms) -> list[str]:
    """Drop non-string and blank/whitespace-only elements; strip+lowercase.
    The ops schema validates only the outer array type (ops_registry custom
    validator), so this is the authoritative hygiene filter (spec §2.1/§2.3):
    a blank term would substring-match every haystack and mark every chain
    relevant, collapsing the signal."""
    return [t.strip().lower() for t in (terms or [])
            if isinstance(t, str) and t.strip()]


def term_matches(term: str, ident: str, vocab: str) -> bool:
    q = term.strip().lower()
    return bool(q) and (q in ident or q in vocab)
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `python -m pytest tests/test_match.py -v`
Expected: 4 PASS

- [ ] **Step 1.5: Refactor `search_clis` onto the helper** — in `core/catalog/queries.py`, READ the current `search_clis` (around line 70), then replace its body so both callers share one predicate (spec §2.2 "so the two cannot drift"):

```python
def search_clis(session, query: str = ""):
    rows = session.exec(select(Cli)).all()
    q = query.strip().lower()
    if not q:
        return [_search_row(c) for c in rows]
    caps_by_slug: dict[str, list] = {}
    for cap in session.exec(select(Capability)).all():
        caps_by_slug.setdefault(cap.cli_slug, []).append(cap)
    return [
        _search_row(c) for c in rows
        if term_matches(q, ident_haystack(c.slug, c.description),
                        vocab_haystack(caps_by_slug.get(c.slug, [])))
    ]
```

Add to the imports at the top of `queries.py` (it already imports `plan_chain` from `planner.search` — `match` is a leaf, no cycle):

```python
from core.catalog.match import ident_haystack, vocab_haystack, term_matches
```

- [ ] **Step 1.6: Run the catalog + mcp suites to pin behavior parity**

Run: `python -m pytest tests/test_catalog.py tests/test_mcp.py -v`
Expected: ALL PASS (refactor is behavior-preserving; any failure = haystack drift, fix the helper, not the tests)

- [ ] **Step 1.7: Commit**

```bash
git commit -m "feat(catalog): extract two-haystack match predicate to leaf module core/catalog/match.py (PRODUCER-RELEVANCE-01 §2.2)" -- core/catalog/match.py core/catalog/queries.py tests/test_match.py
```

## Chunk 2: Registry — planner relevance rank (spec §2.1, §2.2)

### Task 2: `producer_terms` + `Chain.relevance_rank` in `plan_chain`

**Files:**
- Modify: `core/planner/search.py` (Chain dataclass ~line 12-23, plan_chain ~line 119-217)
- Test: `tests/test_planner.py` (append; reuse the `db` fixture and `_fleet` helper)

- [ ] **Step 2.1: Write the failing tests** — append to `tests/test_planner.py`:

```python
# --- producer relevance (spec 2026-07-12-producer-relevance-design §3) ---

def _tied_producers(db, slugs):
    for slug in slugs:
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags="generate", input_types="file:pdf",
                          output_types="text", side_effect="none", confidence="declared"))
    db.commit()


def test_producer_terms_beat_alphabetical_tie_break(db):
    # spec §3 (a): 3 rank-tied producers; the semantic match sorts LAST.
    _tied_producers(db, ["aaa_build", "mmm_report", "zzz_codename"])
    legacy = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"])
    assert legacy[0].slugs == ["aaa_build"]            # alphabetical tie-break today
    ranked = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        producer_terms=["codename"])
    assert ranked[0].slugs == ["zzz_codename"]         # first RETURNED chain (not "selected")
    assert ranked[0].relevance_rank == 0
    assert all(c.relevance_rank == 1 for c in ranked[1:])


def test_omitted_and_empty_producer_terms_are_order_identical_to_legacy(db):
    # spec §3 (b): order-and-existing-fields invariance (slugs+hops), the same
    # comparison shape as test_empty_goal_actions_is_byte_identical_to_today.
    _fleet(db)
    legacy = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"])
    gated = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"],
                       producer_terms=[])
    assert [c.slugs for c in legacy] == [c.slugs for c in gated]
    assert [c.hops for c in legacy] == [c.hops for c in gated]


def test_unmatched_producer_terms_fall_back_to_legacy_order(db):
    # spec §3 (d)
    _tied_producers(db, ["aaa_build", "zzz_codename"])
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        producer_terms=["zzz-nothing-matches-this"])
    assert chains[0].slugs == ["aaa_build"]
    assert all(c.relevance_rank == 1 for c in chains)


def test_action_terminal_match_does_not_mark_chain_relevant(db):
    # spec §3 (e): term matches ONLY the action terminal's blob -> rank stays 1.
    db.add(Cli(slug="gen", lang="python"))
    db.add(Capability(cli_slug="gen", intent_tags="generate", input_types="file:pdf",
                      output_types="text", side_effect="none", confidence="declared"))
    db.add(Cli(slug="codename_mailer", lang="python"))
    db.add(Capability(cli_slug="codename_mailer", intent_tags="send", input_types="text",
                      output_types="text", side_effect="external", confidence="declared"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        goal_actions=["email"], producer_terms=["codename"])
    assert chains, "compound chain [gen, codename_mailer] must exist via synthesized edge"
    assert all(c.relevance_rank == 1 for c in chains)


def test_producer_terms_hygiene_non_string_and_blank_dropped(db):
    # spec §3 (f): blank "" would substring-match EVERYTHING; non-strings must
    # not crash (ops validator doesn't check item types, §2.1).
    _tied_producers(db, ["aaa_build", "zzz_codename"])
    dirty = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                       producer_terms=[42, "  ", None, ""])
    assert dirty[0].slugs == ["aaa_build"]
    assert all(c.relevance_rank == 1 for c in dirty)


def test_relevant_producer_survives_candidate_cap(db):
    # spec §3 (c), fixture modeled on
    # test_favorably_ranked_start_not_starved_by_worse_earlier_candidates:
    # 150 rank-tied producers + 'zzz_target' sorting past position 100 —
    # truncated by the legacy key, first with producer_terms.
    _tied_producers(db, [f"prod{i:03d}" for i in range(150)] + ["zzz_target"])
    legacy = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        max_candidate_chains=100)
    assert len(legacy) == 100
    assert all(c.slugs != ["zzz_target"] for c in legacy)   # truncated out today
    ranked = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        max_candidate_chains=100, producer_terms=["target"])
    assert ranked[0].slugs == ["zzz_target"]
    assert ranked[0].relevance_rank == 0
```

- [ ] **Step 2.2: Run to verify RED**

Run: `python -m pytest tests/test_planner.py -k "producer_terms or relevant_producer or action_terminal_match or unmatched_producer" -v`
Expected: ERROR on every new test — `plan_chain() got an unexpected keyword argument 'producer_terms'` (and the (a)/(c) asserts would fail even after the signature exists — that's the RED that matters)

- [ ] **Step 2.3: Implement** — in `core/planner/search.py`:

(1) Imports — extend line 4-5:

```python
from core.models import Capability, CliEdge, Cli
from core.catalog.match import clean_terms, ident_haystack, vocab_haystack, term_matches
```

(2) `Chain` dataclass — add field AFTER `hops` (defaults must trail non-defaults):

```python
    hops: list[dict] = field(default_factory=list)
    relevance_rank: int = 1        # 0 = a producer hop matches a producer_term (§2.2)
```

(3) `sort_key` — insert between confidence and slugs:

```python
    def sort_key(self):
        # length asc, side-effect count asc, min-confidence DESC (rank asc since
        # lower rank = higher confidence), relevance asc (0 = producer matches a
        # requested term — resolves formerly-arbitrary slug ties, spec §2.2),
        # slug-sequence asc (final tiebreak)
        return (self.length, self.side_effect_count, self.min_confidence_rank,
                self.relevance_rank, tuple(self.slugs))
```

(4) `plan_chain` signature:

```python
def plan_chain(session, goal_inputs, goal_outputs, allow_side_effects=None,
               max_chain_depth=4, max_candidate_chains=100, goal_actions=None,
               producer_terms=None):
```

(5) Relevance pass — insert IMMEDIATELY BEFORE `candidates.sort(key=lambda c: c.sort_key())` (currently line 216):

```python
    # §2.2 producer relevance: rank 0 iff any PRODUCER hop matches any term
    # under the shared two-haystack predicate. Producer hops = path[:-1] when
    # the final hop is an action terminal (its verb already matched, and its
    # blob must not fake artifact relevance); ALL hops otherwise. Runs before
    # the [:max_candidate_chains] cut — rank-before-cap is the point (§1.1).
    terms = clean_terms(producer_terms)
    if terms and candidates:
        descs = {c.slug: c.description or "" for c in session.exec(select(Cli)).all()}
        idents, vocabs = {}, {}

        def _slug_matches(s):
            if s not in idents:
                idents[s] = ident_haystack(s, descs.get(s, ""))
                vocabs[s] = vocab_haystack(caps.get(s, []))
            return any(term_matches(t, idents[s], vocabs[s]) for t in terms)

        for ch in candidates:
            producers = ch.slugs[:-1] if ch.slugs[-1] in action_terminals else ch.slugs
            if any(_slug_matches(s) for s in producers):
                ch.relevance_rank = 0
```

Note: `action_terminals` is `set()` when `goal_actions` is empty (line 128), so the `[:-1]` branch is naturally compound-only; no extra flag needed. `caps.get(s, [])` guards adjacency-only slugs without capability rows (pre-existing possibility).

- [ ] **Step 2.4: Run the new tests — GREEN**

Run: `python -m pytest tests/test_planner.py -v`
Expected: ALL pass, including every pre-existing pinned test (especially `test_empty_goal_actions_is_byte_identical_to_today` and `test_favorably_ranked_start_not_starved_by_worse_earlier_candidates`) — untouched and green.

- [ ] **Step 2.5: Commit**

```bash
git commit -m "feat(planner): producer_terms relevance rank in Chain.sort_key, before the candidate cap (PRODUCER-RELEVANCE-01 §2.1/§2.2)" -- core/planner/search.py tests/test_planner.py
```

## Chunk 3: Registry — wrapper + ops schema + transport (spec §2.1a)

### Task 3: thread `producer_terms` through op and serialize `relevance_rank`

**Files:**
- Modify: `core/catalog/queries.py` (`plan_cli_chain` wrapper, ~line 164-180)
- Modify: `core/ops_registry.py:37-41` (op schema)
- Test: `tests/test_mcp.py` (append; reuse `db` + `call_mcp_tool` fixtures)

- [ ] **Step 3.1: Write the failing tests** — append to `tests/test_mcp.py` (mirror `test_plan_cli_chain_accepts_goal_actions_key` at ~line 122):

```python
def test_plan_cli_chain_accepts_producer_terms_key(db):
    # spec §3 (g1): schema omission guard — without the ops-schema entry this
    # returns "unknown input keys: ['producer_terms']".
    out = call_mcp_tool(db, "plan_cli_chain",
                        {"goal_inputs": [], "goal_outputs": ["text"], "producer_terms": []})
    payload = out["content"][0]["json"]
    assert not (isinstance(payload, dict) and "unknown input keys" in str(payload.get("error", "")))


def _tied_producer_rows(db):
    from core.models import Cli, Capability
    for slug in ("aaa_build", "zzz_codename"):
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags="generate", input_types="file:pdf",
                          output_types="text", side_effect="none", confidence="declared"))
    db.commit()


def test_plan_cli_chain_orders_by_producer_terms_and_serializes_rank(db):
    # spec §3 (g2 forward + g3 serialize)
    _tied_producer_rows(db)
    out = call_mcp_tool(db, "plan_cli_chain",
                        {"goal_inputs": ["file:pdf"], "goal_outputs": ["text"],
                         "producer_terms": ["codename"]})
    chains = out["content"][0]["json"]
    assert chains[0]["slugs"] == ["zzz_codename"]
    assert chains[0]["relevance_rank"] == 0
    assert chains[1]["relevance_rank"] == 1


def test_plan_cli_chain_without_producer_terms_is_legacy_ordered(db):
    # spec §3 (g2 second half): transport-level twin of planner test (b) —
    # AC-02 invariance through the full op path.
    _tied_producer_rows(db)
    out = call_mcp_tool(db, "plan_cli_chain",
                        {"goal_inputs": ["file:pdf"], "goal_outputs": ["text"]})
    chains = out["content"][0]["json"]
    assert chains[0]["slugs"] == ["aaa_build"]          # alphabetical, as today
    assert all("relevance_rank" in ch for ch in chains)  # additive field always present
```

- [ ] **Step 3.2: Run to verify RED**

Run: `python -m pytest tests/test_mcp.py -k producer_terms -v`
Expected: FAIL — `unknown input keys: ['producer_terms']` on (g1)/(g2); KeyError `relevance_rank` on the legacy test

- [ ] **Step 3.3: Implement** — READ then modify:

`core/ops_registry.py` (~line 37-41), add the key:

```python
    Op("plan_cli_chain", queries.plan_cli_chain,
       {"type": "object", "properties": {
           "goal_inputs": _STR_ARRAY, "goal_outputs": _STR_ARRAY,
           "allow_side_effects": _STR_ARRAY, "goal_actions": _STR_ARRAY,
           "producer_terms": _STR_ARRAY},
        "required": ["goal_inputs", "goal_outputs"]}),
```

`core/catalog/queries.py` `plan_cli_chain` (~line 164) — thread-only, wrapper owns no logic (§2.1a):

```python
def plan_cli_chain(session, goal_inputs, goal_outputs, allow_side_effects=None,
                   goal_actions=None, producer_terms=None):
    chains = _plan(session, goal_inputs, goal_outputs, allow_side_effects or [],
                   goal_actions=goal_actions or [],
                   producer_terms=producer_terms or [])
```

and in its `out.append({...})` dict add:

```python
                    "relevance_rank": ch.relevance_rank,
```

- [ ] **Step 3.4: Run — GREEN, then the full registry suite**

Run: `python -m pytest tests/test_mcp.py -v && python -m pytest -q`
Expected: new tests PASS; full suite 499+ pass / 1 pre-existing unrelated fail (`test_web_render`, fails at base — do NOT chase it)

- [ ] **Step 3.5: Commit + push registry half**

```bash
git commit -m "feat(registry): thread producer_terms through plan_cli_chain op; serialize relevance_rank (PRODUCER-RELEVANCE-01 §2.1a)" -- core/ops_registry.py core/catalog/queries.py tests/test_mcp.py
git push
```

## Chunk 4: Adapter — inference 5th key (spec §2.3)

### Task 4: `producer_terms` in `_TAG_INFER_SYSTEM` + `_infer_capability_tags`

**Files:**
- Modify: `~/.hermes/hermes-adapter/hermes_adapter/tools/cli_registry.py:484-503` (`_TAG_INFER_SYSTEM`), `:534-543` (parser)
- Test: `tests/unit/test_cli_tag_inference.py` (READ its mocking convention first)

- [ ] **Step 4.1: Write the failing tests** — append to `tests/unit/test_cli_tag_inference.py`, following its existing gateway-mock pattern:

```python
def test_inference_returns_producer_terms(...):     # mock returns the 5-key JSON
    # {"goal_inputs":[],"goal_outputs":["text"],"goal_actions":["email"],
    #  "side_effects":["email"],"producer_terms":["codename"]}
    # assert tags["producer_terms"] == ["codename"]

def test_missing_producer_terms_defaults_to_empty(...):
    # mock returns the legacy 4-key JSON -> tags["producer_terms"] == []

def test_out_of_vocab_producer_terms_survive_vocab_guard(...):
    # spec §3 (i), REGRESSION PIN (expected GREEN on arrival — the vocab
    # reject set at cli_registry.py:549 reads only goal_inputs|goal_outputs):
    # vocab={"text","file:pdf"}; mock infers goal_outputs=["text"],
    # producer_terms=["codename"] -> NO retry triggered, terms intact.
```

Write these as real tests against the file's actual fixtures (the file already mocks `_call_gateway` / the router call — mirror the nearest existing test verbatim). Honest RED note: the first two are RED (KeyError / missing key); the third is a PIN and should be GREEN as soon as the parser change lands — mark it with a comment saying so.

- [ ] **Step 4.2: Run to verify RED**

Run: `cd ~/.hermes/hermes-adapter && python -m pytest tests/unit/test_cli_tag_inference.py -k producer -v`
Expected: first two FAIL (`KeyError: 'producer_terms'`), third ERRORS or FAILS for the same reason

- [ ] **Step 4.3: Implement** — in `cli_registry.py`:

(1) `_TAG_INFER_SYSTEM`: change the JSON-shape line to

```python
    "Return ONLY compact JSON: {\"goal_inputs\":[...],\"goal_outputs\":[...],"
    "\"goal_actions\":[...],\"side_effects\":[...],\"producer_terms\":[...]}. "
```

and insert AFTER the "NEVER put the action's confirmation text in goal_outputs." sentence:

```python
    "producer_terms = 1-3 short lowercase nouns naming the ARTIFACT the goal asks "
    "to produce, taken from the goal's own words (e.g. codename, cheatsheet, "
    "poster); [] when the goal names no artifact. NEVER generic type words "
    "(text, json, file, output) — producer_terms are fuzzy match hints, not "
    "vocabulary tags. "
```

(2) parser inside `_call` (~line 534-543): add

```python
        pt = [t for t in (data.get("producer_terms") or []) if isinstance(t, str)]
```

and extend the return dict:

```python
        return {"goal_inputs": gi, "goal_outputs": go, "goal_actions": ga,
                "side_effects": se, "producer_terms": pt}
```

Hygiene note (spec §2.3): the adapter does NOT blank-filter — registry-side `clean_terms` is authoritative; the adapter forwards its string-filtered list unmodified. Do not add a duplicate filter.

(3) `_TAG_INFER_MAX_TOKENS` stays 128 (the 5th key adds ~15 tokens of output; 128 has headroom — if the inference tests show truncation, bump to 160 in the same commit and say so).

- [ ] **Step 4.4: Run — GREEN**

Run: `python -m pytest tests/unit/test_cli_tag_inference.py -v`
Expected: ALL PASS (including the (i) pin)

- [ ] **Step 4.5: Commit**

```bash
git commit -m "feat(cli-registry): tag inference emits producer_terms — free-text artifact nouns, vocab-guard exempt (PRODUCER-RELEVANCE-01 §2.3)" -- hermes_adapter/tools/cli_registry.py tests/unit/test_cli_tag_inference.py
```

## Chunk 5: Adapter — forward terms + logging (spec §2.3)

### Task 5: step-4 forwarding, step-1 log, `_select_chain` rank log

**Files:**
- Modify: `hermes_adapter/tools/cli_registry.py:872-875` (step-1 log), `:949-958` (`_plan_and_select` payload), `:753` (`_select_chain` debug log)
- Test: `tests/unit/test_cli_slice_fused.py` (READ its `_mcp_call` capture convention first)

- [ ] **Step 5.1: Write the failing test** — append to `tests/unit/test_cli_slice_fused.py`, mirroring its existing captured-payload tests:

```python
def test_plan_cli_chain_payload_carries_producer_terms(...):
    # spec §3 (j): compound goal -> captured plan_cli_chain call payload
    # contains {"producer_terms": ["codename"]} verbatim (string-filtered,
    # unmodified — no adapter-side blank filter).
```

- [ ] **Step 5.2: Run to verify RED**

Run: `python -m pytest tests/unit/test_cli_slice_fused.py -k producer -v`
Expected: FAIL — payload lacks `producer_terms`

- [ ] **Step 5.3: Implement** — three edits in `cli_registry.py`:

(1) `_plan_and_select` payload (~line 950):

```python
            plan_json = await _mcp_call("plan_cli_chain", {
                "goal_inputs": t["goal_inputs"],
                "goal_outputs": t["goal_outputs"],
                "goal_actions": t.get("goal_actions") or [],
                "producer_terms": t.get("producer_terms") or [],
                "allow_side_effects": [],
            })
```

(2) step-1 log extra (~line 872): add `"producer_terms": tags.get("producer_terms") or [],`

(3) `_select_chain` debug (~line 753):

```python
    logger.debug("run_cli_command chain selected",
                 extra={"hop_count": len(slugs),
                        "relevance_rank": best.get("relevance_rank")})
```

(`best.get` — the field is additive; absence (old registry) logs `None`, never raises. This is the AC-03 evidence hook.)

- [ ] **Step 5.4: Run — GREEN, then the full adapter suite**

Run: `python -m pytest tests/unit/test_cli_slice_fused.py -v && python -m pytest -q`
Expected: new test PASS; full suite 183+ pass (182 at base + new)

- [ ] **Step 5.5: Commit + push adapter half**

```bash
git commit -m "feat(cli-registry): forward producer_terms to planner; log relevance_rank of selected chain (PRODUCER-RELEVANCE-01 §2.3)" -- hermes_adapter/tools/cli_registry.py tests/unit/test_cli_slice_fused.py
git push
```

Also push the registry if not yet pushed.

## Chunk 6: Deploy + AC-03 live E2E (spec §4)

### Task 6: ordered deploy

- [ ] **Step 6.1: Registry FIRST** (schema must land before the adapter sends the new key, else `unknown input keys: ['producer_terms']`):

```bash
launchctl kickstart -k gui/$(id -u)/ai.hermes.cli-registry
```

- [ ] **Step 6.2: Verify registry MCP initialize BEFORE touching anything else** (keepalive hazard; Host `localhost` → 421, use 127.0.0.1):

Run: `curl -s -X POST http://127.0.0.1:9113/mcp/ -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' | head -c 300`
Expected: JSON-RPC result (serverInfo), not a 421/refused

- [ ] **Step 6.3: Adapter, then gateway (ordered)**:

```bash
launchctl kickstart -k gui/$(id -u)/ai.hermes.adapter
launchctl list | grep -i hermes   # identify the gateway agent label, then kickstart it LAST
```

- [ ] **Step 6.4: Non-mutating live probe** — call `plan_cli_chain` over MCP with the incident-shaped compound goal tags plus `producer_terms` naming a real healthy producer (e.g. `["cheatsheet"]` or `["handoff"]`) and confirm: top chain's hop-1 blob matches the term, `relevance_rank: 0` serialized. This probe plans only — it executes nothing and sends no mail.

### Task 7: AC-03 single-attempt E2E (GATED)

- [ ] **Step 7.1: Pick the goal from the LIVE DB at execution time** — artifact noun must match a healthy producer (spec §1.2 candidates: `generate_content`, `create_handoff`, `governance_heatmap`, `governance_retro`). Example shape: *"generate a governance heatmap and email it to me"*.
- [ ] **Step 7.2: ONE attempt, `--max-time 600`,** via the standard test-mail flow. Single-attempt rule is HARD (user already has enough test mails; exit-124 = delivery-unknown, never re-send blindly).
- [ ] **Step 7.3: Evidence:** step-4 log shows `producer_terms` + selected `relevance_rank: 0`; mail received with hop-1 runtime token in the body. PASS → tick AC-01..03 via `backlog_add.py check-ac` + evidence comment (samwa-gate blocks direct BACKLOG edits while the adapter is up). FAIL → record evidence, file the finding, STOP (no retry).

## Execution notes

- **Model routing:** dispatch implementation tasks to `parallel-implementer` subagents (never `general-purpose` — it re-delegates and idles).
- **Parallelism:** Chunks 1→2→3 are sequential (each builds on the last). Chunk 4 can start any time (adapter tests are mocked, no registry dependency); Chunk 5 depends on 4. Chunk 6 requires 3 AND 5 pushed.
- **Do not** touch `max_candidate_chains`, `_select_chain` ordering, or the bypass guard — out of scope (spec §2.3).
- 1 pre-existing registry failure (`test_web_render`) fails at base — not yours.
