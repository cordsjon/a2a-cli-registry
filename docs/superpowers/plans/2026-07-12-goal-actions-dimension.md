# goal_actions Dimension Implementation Plan (US-CLIREG-GOALACTIONS-01)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make compound side-effect goals ("produce a report AND email it") plannable by modeling the terminal action as its own `goal_actions` dimension, per the 7-Codex-pass spec `docs/superpowers/specs/2026-07-12-goal-actions-dimension-design.md` (commit `0453122`).

**Architecture:** Registry-first (a2a-cli-registry): a tag-keyed action→verb map with a max-one-verb-per-live-terminal invariant (multi-match = hard `ValueError`), a new terminal predicate (artifact hop strictly before action hop), planning-time terminal-edge synthesis, a pure-action start gate, and slug-scoped final-position self-authorization. Then adapter (hermes-adapter, atomic): tag inference emits `goal_actions`, discovery survives empty `goal_outputs`, structured planner errors decode into typed exceptions (`UnknownActionVerbError` → ONE corrective reinference; `PlannerStructuredError` → verbatim pass-through), and the single-candidate bypass defers to the planner for compound goals.

**Tech Stack:** Python 3.11, SQLModel/SQLite, pytest. Registry repo `~/projects/a2a-cli-registry` (venv: `.venv`). Adapter repo `~/.hermes/hermes-adapter` (venv: `.venv`). Live DB `~/.hermes/cli-registry.db`.

## Global Constraints

- **Deploy order (§8):** registry schema lands BEFORE the adapter forwards `goal_actions` — else ops_registry rejects it as an unknown input key. Tasks 1–7 (registry) strictly before Tasks 8–12 (adapter). Task 13 restarts services in that order.
- **Byte-identical when `goal_actions` is empty (§2.3):** every planner change is gated behind non-empty `goal_actions`; test (c) is the regression guard.
- **Live DB is NOT the repo DB:** the repo's `registry.db` is a different dataset (no `send_mail`). All live assertions run against `~/.hermes/cli-registry.db`, skipif-guarded.
- **Live-DB mutations:** backup first, row-count-asserted UPDATE, re-read verify (AC-03 runbook).
- **Multi-action is OUT (§7):** `goal_actions` accepts a list; the planner raises `ValueError` on `len > 1`.
- **Persisted `CliEdge` table and `core/graph/edges.py`: unchanged.** `_hop_excluded` signature/logic: unchanged.
- No new packages. No bare `except Exception` additions. Commit after each task with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`, and ALWAYS commit with explicit paths (`git commit -m "..." -- <paths>`) — a repo hook blocks whole-index commits.
- Registry tests: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py -v` (full: `.venv/bin/python -m pytest`). Adapter tests: `cd ~/.hermes/hermes-adapter && .venv/bin/python -m pytest tests/unit -v`. One pre-existing unrelated failure exists in the registry suite (`test_web_render`) — it fails at base; ignore it, everything else must pass.

---

### Task 1: Action map + action-terminal computation (registry)

**Files:**
- Modify: `~/projects/a2a-cli-registry/core/planner/search.py` (add after `_slug_consumes`, line 78)
- Test: `~/projects/a2a-cli-registry/tests/test_planner.py`

**Interfaces:**
- Consumes: existing `_slug_consumes`/`_slug_produces` helpers and the `caps` dict shape `{slug: [Capability, ...]}` from `_cap_index`.
- Produces: `_ACTION_REQUIRES_TAG: dict[str, set[str]]`; `_slug_intent_tags(caps_for_slug) -> set[str]`; `_action_terminals(caps: dict, goal_actions: list[str]) -> set[str]` which raises `ValueError("unknown action verb: <v>; known: [...]")` for out-of-map verbs and `ValueError("action verb integrity: terminal '<slug>' matches multiple verbs [...]")` when ANY slug's intent tags match >1 map verb. Tasks 3–6 call `_action_terminals`; Task 7 threads its ValueErrors to the transports.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_planner.py` (it already imports `Cli, Capability, CliEdge` and `plan_chain`; the `db` fixture comes from `tests/conftest.py`):

```python
# --- US-CLIREG-GOALACTIONS-01: §2.2 action map -------------------------------
from core.planner.search import _action_terminals, _cap_index


def _mail_fleet(db, mailer_tags="send"):
    """Producer (text) + a mail-terminal CLI. NO persisted edge between them —
    edge synthesis (§2.5) is what must connect them."""
    for slug, intag, ins, outs, se, conf in [
        ("report_gen", "report", "file:pdf", "text", "none", "declared"),
        ("mailer", mailer_tags, "text", "text", "external", "declared"),
    ]:
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags=intag, input_types=ins,
                          output_types=outs, side_effect=se, confidence=conf))
    db.commit()


def test_action_terminals_matches_email_via_send_tag(db):
    _mail_fleet(db)
    caps = _cap_index(db)
    assert _action_terminals(caps, ["email"]) == {"mailer"}


def test_unknown_action_verb_raises_structured_valueerror(db):
    # spec §2.2/§2.8 test (f): never silently dropped, never routed wrong
    _mail_fleet(db)
    caps = _cap_index(db)
    with _pytest.raises(ValueError, match=r"unknown action verb: telegram; known:"):
        _action_terminals(caps, ["telegram"])


def test_multi_match_terminal_is_hard_integrity_error(db):
    # spec §2.2 + test (h) hermetic twin: a double-tagged terminal (notify,send)
    # matches both 'email' and 'notify' — hard error, never a silent pick.
    _mail_fleet(db, mailer_tags="notify,send")
    caps = _cap_index(db)
    with _pytest.raises(ValueError,
                        match=r"action verb integrity: terminal 'mailer' matches multiple verbs"):
        _action_terminals(caps, ["email"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py -k "action_terminals or unknown_action or multi_match" -v`
Expected: 3 FAIL/ERROR with `ImportError: cannot import name '_action_terminals'`

- [ ] **Step 3: Implement** — in `core/planner/search.py`, insert after `_slug_consumes` (line 78):

```python
# --- goal_actions dimension (spec 2026-07-12-goal-actions-dimension-design §2.2) ---
# Action verbs are matched to terminal intent tags. Map values are pairwise
# disjoint (necessary), but the real guard is the max-one-verb-per-live-terminal
# invariant enforced in _action_terminals (sufficient): a multi-tagged terminal
# matching >1 verb is a hard integrity error, never a silent pick.
_ACTION_REQUIRES_TAG = {
    "email":      {"send"},       # send_mail carries 'send' post-retag (§8 step 0)
    "notify":     {"notify"},     # a pure-notification terminal (none live today)
    "webhook":    {"webhook"},
    "file_write": {"persist"},
}


def _slug_intent_tags(caps_for_slug) -> set[str]:
    return {t for c in caps_for_slug for t in c.intent_tags.split(",") if t}


def _action_terminals(caps, goal_actions) -> set[str]:
    """Slugs satisfying a requested action verb (§2.2). Raises ValueError on an
    unknown verb (§2.8 structured-error contract) or on any slug whose intent
    tags match more than one map verb (max-one-verb-per-live-terminal)."""
    unknown = [a for a in goal_actions if a not in _ACTION_REQUIRES_TAG]
    if unknown:
        raise ValueError(
            f"unknown action verb: {unknown[0]}; known: {sorted(_ACTION_REQUIRES_TAG)}")
    terminals = set()
    for slug, caps_for_slug in caps.items():
        tags = _slug_intent_tags(caps_for_slug)
        verbs = [a for a in _ACTION_REQUIRES_TAG if _ACTION_REQUIRES_TAG[a] & tags]
        if len(verbs) > 1:
            raise ValueError(
                f"action verb integrity: terminal '{slug}' matches multiple verbs "
                f"{sorted(verbs)}")
        if verbs and verbs[0] in goal_actions:
            terminals.add(slug)
    return terminals
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py -v`
Expected: all PASS (new 3 + all pre-existing)

- [ ] **Step 5: Commit**

```bash
cd ~/projects/a2a-cli-registry
git add core/planner/search.py tests/test_planner.py
git commit -m "feat(planner): _ACTION_REQUIRES_TAG map + action-terminal computation with integrity invariant (GOALACTIONS-01 §2.2)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/planner/search.py tests/test_planner.py
```

---

### Task 2: Live invariant test (h) RED → live-DB retag → GREEN (§8 step 0)

**Files:**
- Modify: `~/projects/a2a-cli-registry/tests/test_planner.py` (append after the existing live probe, line 284)
- Mutate: `~/.hermes/cli-registry.db` (backed-up UPDATE)

**Interfaces:**
- Consumes: `_ACTION_REQUIRES_TAG`, `_slug_intent_tags` from Task 1; the existing `_LIVE_REGISTRY_DB` / `skipif` pattern at `tests/test_planner.py:250-255`.
- Produces: live `send_mail.intent_tags == 'send'`; a permanent live-DB tripwire test. Nothing downstream imports from this task.

- [ ] **Step 1: Write the failing live test** — append to `tests/test_planner.py` (the `_os`/`_pytest`/`_LIVE_REGISTRY_DB` imports already exist at lines 247-251):

```python
@_pytest.mark.skipif(not _os.path.exists(_LIVE_REGISTRY_DB),
                     reason="live registry ~/.hermes/cli-registry.db not present")
def test_max_one_verb_per_live_terminal():
    # spec §5 test (h), RED-first: for EVERY live terminal, at most one verb in
    # _ACTION_REQUIRES_TAG matches its actual intent_tags. Reproduces the
    # send_mail double-match ('notify,send' -> email AND notify) as RED, goes
    # GREEN after the §8-step-0 retag, and stays as the permanent tripwire: a
    # feed re-run reintroducing 'notify' (populate.py delete+recreate) or a new
    # multi-tagged terminal turns it RED again, forcing a fresh design decision.
    from sqlmodel import Session, create_engine
    from core.planner.search import _ACTION_REQUIRES_TAG, _slug_intent_tags

    engine = create_engine(f"sqlite:///{_LIVE_REGISTRY_DB}")
    with Session(engine) as session:
        caps = _cap_index(session)
    offenders = {}
    for slug, caps_for_slug in caps.items():
        tags = _slug_intent_tags(caps_for_slug)
        verbs = [a for a in _ACTION_REQUIRES_TAG if _ACTION_REQUIRES_TAG[a] & tags]
        if len(verbs) > 1:
            offenders[slug] = sorted(verbs)
    assert not offenders, (
        f"live terminals matching >1 action verb: {offenders} — the §2.2 "
        f"max-one-verb-per-live-terminal invariant is violated; decide a fresh "
        f"disambiguation (do NOT silently pick)"
    )
```

- [ ] **Step 2: Run to verify RED against the current live row**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py::test_max_one_verb_per_live_terminal -v`
Expected: FAIL with `live terminals matching >1 action verb: {'send_mail': ['email', 'notify']}`

- [ ] **Step 3: Retag the live DB (backup → UPDATE → verify)**

```bash
cp ~/.hermes/cli-registry.db ~/.hermes/cli-registry.db.bak-goalactions-retag
sqlite3 ~/.hermes/cli-registry.db "UPDATE capability SET intent_tags='send' WHERE cli_slug='send_mail' AND intent_tags='notify,send'; SELECT changes();"
sqlite3 ~/.hermes/cli-registry.db "SELECT cli_slug, intent_tags, side_effect, confidence FROM capability WHERE cli_slug='send_mail';"
```

Expected: `SELECT changes()` prints `1`; re-read prints `send_mail|send|external|declared`. If `changes()` != 1, STOP — the row drifted from `notify,send`; restore the backup and investigate before re-running.

- [ ] **Step 4: Run tests to verify GREEN (including the existing AC-02 live probe — the retag must not break send_mail reachability)**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py -v`
Expected: all PASS, including `test_send_mail_reachable_at_default_cap_live` and `test_max_one_verb_per_live_terminal`

- [ ] **Step 5: Commit**

```bash
cd ~/projects/a2a-cli-registry
git add tests/test_planner.py
git commit -m "feat(planner): live max-one-verb-per-terminal invariant test + send_mail retag notify,send->send (GOALACTIONS-01 §8 step 0)

Live DB backed up at ~/.hermes/cli-registry.db.bak-goalactions-retag;
row-count-asserted UPDATE, re-read verified. Test (h) was RED against
notify,send and is GREEN post-retag.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- tests/test_planner.py
```

---

### Task 3: `goal_actions` param + terminal predicate + short-circuit edit (§2.3, §2.4)

**Files:**
- Modify: `~/projects/a2a-cli-registry/core/planner/search.py:81-124` (`plan_chain`)
- Test: `~/projects/a2a-cli-registry/tests/test_planner.py`

**Interfaces:**
- Consumes: `_action_terminals` from Task 1.
- Produces: `plan_chain(session, goal_inputs, goal_outputs, allow_side_effects=None, max_chain_depth=4, max_candidate_chains=100, goal_actions=None)` — the keyword param Tasks 4–7 build on. With `goal_actions` empty the BFS body is literally today's code path (test c).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_planner.py`:

```python
def test_compound_goal_plans_producer_then_mailer_via_persisted_edge(db):
    # §2.3/§2.4 core predicate, isolated from §2.5 synthesis by a PERSISTED edge.
    _mail_fleet(db)
    db.add(CliEdge(from_slug="report_gen", to_slug="mailer", via_type="text"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        goal_actions=["email"])
    assert any(c.slugs == ["report_gen", "mailer"] for c in chains)


def test_producer_does_not_short_circuit_when_goal_actions_set(db):
    # spec §5 test (b): with goal_actions, a bare producer path is NOT terminal.
    _mail_fleet(db)
    db.add(CliEdge(from_slug="report_gen", to_slug="mailer", via_type="text"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        goal_actions=["email"])
    assert all(c.slugs != ["report_gen"] for c in chains)


def test_empty_goal_actions_is_byte_identical_to_today(db):
    # spec §5 test (c): regression guard — goal_actions=[] output == legacy output.
    _fleet(db)
    legacy = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"])
    gated = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"],
                       goal_actions=[])
    assert [c.slugs for c in legacy] == [c.slugs for c in gated]
    assert [c.hops for c in legacy] == [c.hops for c in gated]


def test_dual_capable_cli_does_not_satisfy_compound_in_one_hop(db):
    # spec §5 test (e) / §2.3: artifact must come from an EARLIER hop.
    db.add(Cli(slug="dual", lang="python"))
    db.add(Capability(cli_slug="dual", intent_tags="send", input_types="text",
                      output_types="text", side_effect="external", confidence="declared"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["text"], goal_outputs=["text"],
                        goal_actions=["email"])
    assert all(c.slugs != ["dual"] for c in chains)


def test_more_than_one_action_verb_raises(db):
    # spec §7: multi-action-per-goal is OUT — explicit error, not silent.
    _mail_fleet(db)
    with _pytest.raises(ValueError, match="multiple action verbs"):
        plan_chain(db, goal_inputs=["text"], goal_outputs=[],
                   goal_actions=["email", "webhook"])
```

- [ ] **Step 2: Run to verify failures**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py -k "compound or short_circuit or byte_identical or dual_capable or more_than_one" -v`
Expected: FAIL — `TypeError: plan_chain() got an unexpected keyword argument 'goal_actions'` (byte_identical and more_than_one included)

- [ ] **Step 3: Implement** — replace `plan_chain` (search.py:81-124) with:

```python
def plan_chain(session, goal_inputs, goal_outputs, allow_side_effects=None,
               max_chain_depth=4, max_candidate_chains=100, goal_actions=None):
    allow_side_effects = set(allow_side_effects or [])
    goal_actions = list(goal_actions or [])
    if len(goal_actions) > 1:
        # §7: one final action hop per goal; forward-compatible list, explicit cap
        raise ValueError(f"multiple action verbs not supported: {sorted(goal_actions)}")
    caps = _cap_index(session)
    # §2.2: validates verbs and enforces max-one-verb-per-live-terminal.
    action_terminals = _action_terminals(caps, goal_actions) if goal_actions else set()
    adjacency = {}
    for e in session.exec(select(CliEdge)).all():
        adjacency.setdefault(e.from_slug, []).append((e.to_slug, e.via_type))

    goal_in, goal_out = set(goal_inputs), set(goal_outputs)
    # An empty goal_in means "no input constraint" (a query-only goal like
    # "list files" or "check status"). `_slug_consumes(c) & goal_in` is always
    # empty/falsy when goal_in is empty, which used to make EVERY CLI —
    # including the ones with input_types="" that exist specifically for this
    # case — permanently unreachable. Only match no-declared-input CLIs when
    # goal_in is empty; a CLI with a real declared input type still requires
    # the caller to name it (goal_in non-empty and intersecting).
    if goal_in:
        starts = [s for s, c in caps.items() if _slug_consumes(c) & goal_in]
    else:
        starts = [s for s, c in caps.items() if not _slug_consumes(c)]
    candidates = []

    for start in starts:
        # BFS state: (path, visited, hops). Cycle guard via visited set.
        q = deque([([start], {start}, [])])
        while q:
            path, visited, hops = q.popleft()
            tail = path[-1]
            if not goal_actions:
                # legacy path — byte-identical to the pre-goal_actions planner
                # (§2.3: "the new clauses are gated behind non-empty goal_actions")
                if _hop_excluded(caps[tail], allow_side_effects):
                    continue
                if _slug_produces(caps[tail]) & goal_out:
                    candidates.append(_finalize(path, caps, hops))
                    continue
            else:
                if _hop_excluded(caps[tail], allow_side_effects):
                    continue
                if tail in action_terminals:
                    # §2.3 terminal predicate: the final hop is the action; the
                    # artifact must come from an EARLIER hop (path[:-1]), so a
                    # dual-capable CLI never satisfies a compound goal in 1 hop.
                    artifact_met = (not goal_out) or any(
                        _slug_produces(caps[s]) & goal_out for s in path[:-1])
                    if artifact_met:
                        candidates.append(_finalize(path, caps, hops))
                    # action terminals are FINAL-position only (§2.6/§2.7):
                    # never expand through one — its confirmation output must
                    # not feed a later hop as a fake artifact.
                    continue
                # §2.4: a producer hop does NOT short-circuit when an action is
                # requested — fall through to neighbor expansion.
            if len(path) >= max_chain_depth:
                continue
            for (nxt, via) in adjacency.get(tail, []):
                if nxt in visited:
                    continue                       # cycle guard
                q.append((path + [nxt], visited | {nxt},
                          hops + [{"from": tail, "to": nxt, "via_type": via}]))

    candidates.sort(key=lambda c: c.sort_key())
    return candidates[:max_candidate_chains]
```

- [ ] **Step 4: Run the full planner suite**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py -v`
Expected: all PASS (the 5 new tests + every pre-existing test — the legacy branch is untouched code)

- [ ] **Step 5: Commit**

```bash
cd ~/projects/a2a-cli-registry
git add core/planner/search.py tests/test_planner.py
git commit -m "feat(planner): goal_actions param, artifact-before-action terminal predicate, short-circuit edit (GOALACTIONS-01 §2.3/§2.4)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/planner/search.py tests/test_planner.py
```

---

### Task 4: Planning-time terminal edge synthesis (§2.5)

**Files:**
- Modify: `~/projects/a2a-cli-registry/core/planner/search.py` (`plan_chain`, right after the adjacency build from Task 3)
- Test: `~/projects/a2a-cli-registry/tests/test_planner.py`

**Interfaces:**
- Consumes: Task 3's `plan_chain` structure (`adjacency` dict of `(to_slug, via_type)` lists, `action_terminals`).
- Produces: in-memory adjacency entries `(terminal, hub)` for every producer whose outputs intersect the terminal's inputs — scoped strictly to `action_terminals`. The persisted `CliEdge` table is untouched.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_planner.py`:

```python
def test_compound_goal_reaches_mailer_with_zero_persisted_edges(db):
    # spec §5 test (a) + §2.5: live send_mail has ZERO persisted incoming edges
    # (edges.py down-weights bare hub types); synthesis must connect
    # producer -> mailer at plan time. _mail_fleet adds NO CliEdge rows.
    _mail_fleet(db)
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        goal_actions=["email"])
    assert any(c.slugs == ["report_gen", "mailer"] for c in chains)
    # via_type preserved for hop tracing (§2.5)
    two_hop = next(c for c in chains if c.slugs == ["report_gen", "mailer"])
    assert two_hop.hops[1]["via_type"] == "text"


def test_synthesis_does_not_create_chains_into_non_requested_terminals(db):
    # spec §5 test (d): a 'webhook' terminal exists, only 'email' is requested —
    # no chain may end in the webhook CLI.
    _mail_fleet(db)
    db.add(Cli(slug="webhooker", lang="python"))
    db.add(Capability(cli_slug="webhooker", intent_tags="webhook", input_types="text",
                      output_types="text", side_effect="external", confidence="declared"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        goal_actions=["email"])
    assert chains, "email chain must still plan"
    assert all("webhooker" not in c.slugs for c in chains)
```

- [ ] **Step 2: Run to verify failures**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py -k "zero_persisted or non_requested" -v`
Expected: `test_compound_goal_reaches_mailer_with_zero_persisted_edges` FAILS (no chain — no edge exists); `test_synthesis_does_not_create_chains_into_non_requested_terminals` FAILS on `assert chains`

- [ ] **Step 3: Implement** — in `plan_chain`, insert directly after the `adjacency` build loop (`adjacency.setdefault(e.from_slug, ...)`):

```python
    # §2.5: planning-time terminal edge synthesis — send_mail-class terminals
    # have zero persisted incoming edges (edges.py:30 down-weights bare hub
    # types). Synthesize (producer -> terminal, via H) IN MEMORY, scoped
    # strictly to terminals matching a requested action; the general hub
    # down-weight and the persisted CliEdge table are untouched.
    if goal_actions:
        for term in sorted(action_terminals):
            term_in = _slug_consumes(caps[term])
            for prod, prod_caps in caps.items():
                if prod == term:
                    continue
                for hub in sorted(_slug_produces(prod_caps) & term_in):
                    pairs = adjacency.setdefault(prod, [])
                    if (term, hub) not in pairs:
                        pairs.append((term, hub))
```

- [ ] **Step 4: Run the full planner suite**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd ~/projects/a2a-cli-registry
git add core/planner/search.py tests/test_planner.py
git commit -m "feat(planner): planning-time terminal edge synthesis scoped to requested actions (GOALACTIONS-01 §2.5)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/planner/search.py tests/test_planner.py
```

---

### Task 5: Pure-action start gate (§2.6)

**Files:**
- Modify: `~/projects/a2a-cli-registry/core/planner/search.py` (`plan_chain` starts block)
- Test: `~/projects/a2a-cli-registry/tests/test_planner.py`

**Interfaces:**
- Consumes: Task 3/4 `plan_chain` (`starts` list, `action_terminals`, `goal_out`).
- Produces: action terminals admitted as starts ONLY when `goal_outputs` is empty (pure action). Compound goals reach them only via synthesized final hops.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_planner.py`:

```python
def test_pure_action_goal_starts_at_action_terminal(db):
    # spec §5 test (g) / §2.6: empty goal_outputs + goal_actions -> the terminal
    # itself is a valid 1-hop chain even though its input_types='text' would
    # normally exclude it from empty-goal_in starts.
    _mail_fleet(db)
    chains = plan_chain(db, goal_inputs=[], goal_outputs=[], goal_actions=["email"])
    assert any(c.slugs == ["mailer"] for c in chains)


def test_compound_goal_does_not_admit_action_terminal_as_start(db):
    # spec §5 test (i) / §2.6 3rd-pass gate: with goal_outputs non-empty, no
    # returned chain may START at the action terminal (its confirmation text
    # must never masquerade as the artifact).
    _mail_fleet(db)
    chains = plan_chain(db, goal_inputs=["text"], goal_outputs=["text"],
                        goal_actions=["email"])
    assert all(c.slugs[0] != "mailer" for c in chains)


def test_notify_goal_does_not_route_to_send_tagged_mailer(db):
    # spec §5 test (k), hermetic twin of the post-retag semantics: 'notify' is a
    # VALID verb that matches zero terminals (mailer carries only 'send') — the
    # goal plans NO chain rather than mis-routing to mail. The live half of (k)
    # is pinned by Task 2's invariant test + the retag itself.
    _mail_fleet(db)
    chains = plan_chain(db, goal_inputs=[], goal_outputs=[], goal_actions=["notify"])
    assert chains == []
```

- [ ] **Step 2: Run to verify the RED one fails**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py -k "pure_action or admit_action_terminal" -v`
Expected: `test_pure_action_goal_starts_at_action_terminal` FAILS (starts=[] finds no no-input CLI); `test_compound_goal_does_not_admit_action_terminal_as_start` PASSES already (guard test — keep it; it pins the §2.6 gate against future edits)

- [ ] **Step 3: Implement** — in `plan_chain`, insert directly after the `starts = ...` if/else block:

```python
    # §2.6: ONLY a pure-action goal (empty goal_outputs) admits action
    # terminals as starts, regardless of their declared inputs. For a compound
    # goal the terminal is reachable ONLY as a synthesized final hop (§2.5)
    # downstream of a real producer — starting there would let its
    # confirmation output masquerade as the artifact (3rd-pass fix).
    if goal_actions and not goal_out:
        starts = sorted(set(starts) | action_terminals)
```

- [ ] **Step 4: Run the full planner suite**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py -v`
Expected: all PASS. Note: the pure-action 1-hop `[mailer]` path terminates via Task 3's predicate (`artifact_met` is trivially true when `goal_out` is empty).

- [ ] **Step 5: Commit**

```bash
cd ~/projects/a2a-cli-registry
git add core/planner/search.py tests/test_planner.py
git commit -m "feat(planner): pure-action start gate — action terminals start only when goal_outputs empty (GOALACTIONS-01 §2.6)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/planner/search.py tests/test_planner.py
```

---

### Task 6: Slug-scoped final-position self-authorization (§2.7)

**Files:**
- Modify: `~/projects/a2a-cli-registry/core/planner/search.py` (`plan_chain` goal_actions branch from Task 3)
- Test: `~/projects/a2a-cli-registry/tests/test_planner.py`

**Interfaces:**
- Consumes: Task 3's goal_actions BFS branch.
- Produces: an excluded-by-default hop (e.g. inferred `writes-fs`) is admitted iff it is in `action_terminals` AND terminal position. `_hop_excluded` itself is UNCHANGED — the planner wraps its result.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_planner.py`:

```python
def test_action_terminal_self_authorized_at_final_position_only(db):
    # spec §5 test (j) / §2.7: an inferred writes-fs action terminal (excluded
    # by default) is allowed as the FINAL hop without widening allow_side_effects...
    for slug, intag, ins, outs, se, conf in [
        ("gen", "report", "file:pdf", "text", "none", "declared"),
        ("fs_writer", "persist", "text", "text", "writes-fs", "inferred"),
    ]:
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags=intag, input_types=ins,
                          output_types=outs, side_effect=se, confidence=conf))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        goal_actions=["file_write"])
    assert any(c.slugs == ["gen", "fs_writer"] for c in chains)


def test_action_self_auth_does_not_admit_other_writes_fs_mid_chain(db):
    # ...and the self-auth is SLUG-scoped: a DIFFERENT inferred writes-fs CLI
    # mid-chain stays excluded (no class-wide allow widening — the 3rd-pass
    # security fix).
    for slug, intag, ins, outs, se, conf in [
        ("gen", "report", "file:pdf", "text:mid", "none", "declared"),
        ("dirty_mid", "transform", "text:mid", "text", "writes-fs", "inferred"),
        ("fs_writer", "persist", "text", "text", "writes-fs", "inferred"),
    ]:
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags=intag, input_types=ins,
                          output_types=outs, side_effect=se, confidence=conf))
    db.add(CliEdge(from_slug="gen", to_slug="dirty_mid", via_type="text:mid"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        goal_actions=["file_write"])
    # the only route to a 'text' artifact runs through dirty_mid (excluded) —
    # so NO chain may exist; dirty_mid must not be admitted by fs_writer's auth
    assert all("dirty_mid" not in c.slugs for c in chains)
    assert chains == []
```

- [ ] **Step 2: Run to verify failures**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py -k "self_auth" -v`
Expected: `test_action_terminal_self_authorized_at_final_position_only` FAILS (fs_writer pruned by `_hop_excluded`); the mid-chain test PASSES already (guard — keep it)

- [ ] **Step 3: Implement** — in Task 3's goal_actions branch, replace these three lines:

```python
            else:
                if _hop_excluded(caps[tail], allow_side_effects):
                    continue
                if tail in action_terminals:
```

with:

```python
            else:
                # §2.7: slug-scoped, final-position-only self-authorization.
                # _hop_excluded is consulted unchanged with the caller's
                # allow_side_effects; the ONLY relaxation is an action terminal
                # at terminal position (the branch below never expands through
                # one, so reaching it here IS final position). No other hop and
                # no other CLI of the same side-effect class is admitted.
                if _hop_excluded(caps[tail], allow_side_effects) \
                        and tail not in action_terminals:
                    continue
                if tail in action_terminals:
```

- [ ] **Step 4: Run the full planner suite**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_planner.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd ~/projects/a2a-cli-registry
git add core/planner/search.py tests/test_planner.py
git commit -m "feat(planner): slug-scoped final-position self-auth for action terminals (GOALACTIONS-01 §2.7)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/planner/search.py tests/test_planner.py
```

---

### Task 7: Wrapper + ops schema + transport structuring (registry half of test (n))

**Files:**
- Modify: `~/projects/a2a-cli-registry/core/catalog/queries.py:164-165` (`plan_cli_chain`)
- Modify: `~/projects/a2a-cli-registry/core/ops_registry.py:37-41` (op schema)
- Test: `~/projects/a2a-cli-registry/tests/test_mcp.py`

**Interfaces:**
- Consumes: Task 3's `plan_chain(..., goal_actions=...)`; `_error_block` shape `{"content": [{"type": "json", "json": {"error": msg}}]}` (core/mcp/server.py:21-23); `call_mcp_tool` catches `(TypeError, ValueError)` and wraps as `_error_block(f"invalid input: {exc}")`.
- Produces: `plan_cli_chain(session, goal_inputs, goal_outputs, allow_side_effects=None, goal_actions=None)`; ops schema accepts the `goal_actions` key (else ops_registry.py:101 rejects it as unknown). The adapter (Task 8) decodes exactly the payload string `"invalid input: unknown action verb: <v>; known: ['email', 'file_write', 'notify', 'webhook']"` and `"invalid input: action verb integrity: terminal '<slug>' matches multiple verbs [...]"`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_mcp.py` (follow that file's existing imports/fixtures; it already exercises `call_mcp_tool` with the `db` fixture; add `from core.models import Cli, Capability` if not present):

```python
def test_plan_cli_chain_accepts_goal_actions_key(db):
    # schema omission guard (§3): without the ops-schema entry this returns
    # "unknown input keys: ['goal_actions']" (ops_registry.py:101)
    out = call_mcp_tool(db, "plan_cli_chain",
                        {"goal_inputs": [], "goal_outputs": ["text"], "goal_actions": []})
    payload = out["content"][0]["json"]
    assert not (isinstance(payload, dict) and "unknown input keys" in str(payload.get("error", "")))


def test_plan_cli_chain_unknown_verb_is_structured_error(db):
    # §2.8: unknown verb -> structured op error with the known-verbs vocabulary
    out = call_mcp_tool(db, "plan_cli_chain",
                        {"goal_inputs": [], "goal_outputs": [], "goal_actions": ["telegram"]})
    err = out["content"][0]["json"]["error"]
    assert "unknown action verb: telegram" in err and "known:" in err


def test_plan_cli_chain_multi_match_integrity_error_is_structured(db):
    # registry half of §5 test (n): the §2.2 integrity ValueError surfaces as a
    # structured _error_block, not an unstructured exception
    db.add(Cli(slug="dual_mail", lang="python"))
    db.add(Capability(cli_slug="dual_mail", intent_tags="notify,send", input_types="text",
                      output_types="text", side_effect="external", confidence="declared"))
    db.commit()
    out = call_mcp_tool(db, "plan_cli_chain",
                        {"goal_inputs": [], "goal_outputs": [], "goal_actions": ["email"]})
    err = out["content"][0]["json"]["error"]
    assert "action verb integrity" in err and "dual_mail" in err
```

- [ ] **Step 2: Run to verify failures**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest tests/test_mcp.py -k "goal_actions or unknown_verb or multi_match" -v`
Expected: all 3 FAIL with `unknown input keys: ['goal_actions']` in the error payload

- [ ] **Step 3: Implement — ops schema.** In `core/ops_registry.py:37-41` replace the `plan_cli_chain` Op entry with:

```python
    Op("plan_cli_chain", queries.plan_cli_chain,
       {"type": "object", "properties": {
           "goal_inputs": _STR_ARRAY, "goal_outputs": _STR_ARRAY,
           "allow_side_effects": _STR_ARRAY, "goal_actions": _STR_ARRAY},
        "required": ["goal_inputs", "goal_outputs"]}),
```

- [ ] **Step 4: Implement — wrapper.** In `core/catalog/queries.py:164-165` replace the signature and `_plan` call with (keep the rest of the function body unchanged):

```python
def plan_cli_chain(session, goal_inputs, goal_outputs, allow_side_effects=None,
                   goal_actions=None):
    chains = _plan(session, goal_inputs, goal_outputs, allow_side_effects or [],
                   goal_actions=goal_actions or [])
```

(`_plan` is this module's existing import alias for `core.planner.search.plan_chain` — keep the alias; ValueErrors from `_action_terminals` propagate through here to the transports, which structure them.)

- [ ] **Step 5: Run the FULL registry suite**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest`
Expected: everything passes except the pre-existing unrelated `test_web_render` failure

- [ ] **Step 6: Commit**

```bash
cd ~/projects/a2a-cli-registry
git add core/ops_registry.py core/catalog/queries.py tests/test_mcp.py
git commit -m "feat(registry): thread goal_actions through ops schema + plan_cli_chain wrapper; structured verb/integrity errors (GOALACTIONS-01 §2.8/§3)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- core/ops_registry.py core/catalog/queries.py tests/test_mcp.py
```

---

### Task 8: Adapter typed errors + structured-error decode (tests (l) + adapter half of (n))

**Files:**
- Modify: `~/.hermes/hermes-adapter/hermes_adapter/tools/cli_registry.py` (add above `_unwrap_mcp_json`, line 573; `import re` may need adding to the module imports)
- Test: `~/.hermes/hermes-adapter/tests/unit/test_cli_plan_selection.py`

**Interfaces:**
- Consumes: `_unwrap_mcp_json` (cli_registry.py:573) which normalizes the registry's `_error_block` (`{"content":[{"type":"json","json":{"error": msg}}]}`) into `[{"error": msg}]`; the exact registry payload strings from Task 7.
- Produces: `UnknownActionVerbError(verb: str, known: list[str])` and `PlannerStructuredError(message)` (both subclass `ValueError`); `_decode_planner_error(plan_json: str) -> None` which raises one of them for structured-error payloads and returns silently otherwise. Task 10 calls `_decode_planner_error` BEFORE `_select_chain`.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_cli_plan_selection.py` (it already has `_plan(chains)` building the MCP envelope and imports `cli_registry`, `pytest`, `json`):

```python
def _error_envelope(msg):
    return json.dumps({"content": [{"type": "json", "json": {"error": msg}}]})


def test_decode_unknown_verb_raises_typed_error_with_vocab():
    # spec §5 test (l): decoded BEFORE _select_chain flattens it to a generic
    # "no healthy chain" — verb + known vocabulary preserved for reinference
    raw = _error_envelope(
        "invalid input: unknown action verb: telegram; known: ['email', 'file_write', 'notify', 'webhook']")
    with pytest.raises(cli_registry.UnknownActionVerbError) as exc:
        cli_registry._decode_planner_error(raw)
    assert exc.value.verb == "telegram"
    assert exc.value.known == ["email", "file_write", "notify", "webhook"]


def test_decode_integrity_error_raises_planner_structured_verbatim():
    # adapter half of spec §5 test (n): exact type + verbatim message
    msg = "invalid input: action verb integrity: terminal 'dual_mail' matches multiple verbs ['email', 'notify']"
    with pytest.raises(cli_registry.PlannerStructuredError) as exc:
        cli_registry._decode_planner_error(_error_envelope(msg))
    assert str(exc.value) == msg


def test_decode_is_silent_for_normal_chains_and_empty_plans():
    plan = _plan([{"slugs": ["a"], "hops": [{"slug": "a", "health_status": "healthy"}]}])
    assert cli_registry._decode_planner_error(plan) is None
    assert cli_registry._decode_planner_error(_plan([])) is None
```

- [ ] **Step 2: Run to verify failures**

Run: `cd ~/.hermes/hermes-adapter && .venv/bin/python -m pytest tests/unit/test_cli_plan_selection.py -k "decode" -v`
Expected: FAIL with `AttributeError: ... has no attribute 'UnknownActionVerbError'`

- [ ] **Step 3: Implement** — in `hermes_adapter/tools/cli_registry.py`, ensure `import re` is in the module imports, then insert directly above `_unwrap_mcp_json` (line 573):

```python
class UnknownActionVerbError(ValueError):
    """plan_cli_chain rejected an action verb; carries the registry's known
    vocabulary so ONE corrective reinference can name it (spec §2.8)."""
    def __init__(self, verb: str, known: list[str]):
        self.verb = verb
        self.known = known
        super().__init__(f"unknown action verb: {verb}; known: {known}")


class PlannerStructuredError(ValueError):
    """Any OTHER structured planner error (e.g. §2.2 'action verb integrity')
    — reinference cannot fix it, so it passes through verbatim: never retried,
    never degraded to the generic 'no healthy chain' (spec §2.8, 7th pass)."""


_UNKNOWN_VERB_RE = re.compile(
    r"unknown action verb: (?P<verb>[^;]+); known: \[(?P<known>[^\]]*)\]")


def _decode_planner_error(plan_json: str) -> None:
    """Raise a typed error if the plan payload is the registry's structured
    {'error': ...} envelope instead of a chain list. MUST run before
    _select_chain: _unwrap_mcp_json normalizes the error dict into a 1-element
    list and _select_chain would degrade the detail to a generic 'no healthy
    chain' (686/706), swallowing the verb (spec §2.8, 4th pass)."""
    rows = _unwrap_mcp_json(plan_json)
    if len(rows) != 1 or not isinstance(rows[0], dict) or set(rows[0]) != {"error"}:
        return
    msg = rows[0]["error"]
    if not isinstance(msg, str):
        return
    m = _UNKNOWN_VERB_RE.search(msg)
    if m:
        known = [v.strip().strip("'\"") for v in m.group("known").split(",") if v.strip()]
        raise UnknownActionVerbError(m.group("verb").strip(), known)
    raise PlannerStructuredError(msg)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd ~/.hermes/hermes-adapter && .venv/bin/python -m pytest tests/unit/test_cli_plan_selection.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd ~/.hermes/hermes-adapter
git add hermes_adapter/tools/cli_registry.py tests/unit/test_cli_plan_selection.py
git commit -m "feat(cli-registry): typed structured-planner-error decode — UnknownActionVerbError + PlannerStructuredError (GOALACTIONS-01 §2.8)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- hermes_adapter/tools/cli_registry.py tests/unit/test_cli_plan_selection.py
```

---

### Task 9: Tag inference emits `goal_actions`; empty `goal_outputs` allowed for pure actions

**Files:**
- Modify: `~/.hermes/hermes-adapter/hermes_adapter/tools/cli_registry.py:478-570` (`_TAG_INFER_SYSTEM`, `_infer_capability_tags`)
- Test: `~/.hermes/hermes-adapter/tests/unit/test_cli_tag_inference.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_infer_capability_tags` returns `{"goal_inputs", "goal_outputs", "goal_actions", "side_effects"}` — `goal_outputs` MAY be empty iff `goal_actions` is non-empty; raises `ValueError` when BOTH are empty. `side_effects` is kept (discovery still uses it). Tasks 10–12 read `tags["goal_actions"]`.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_cli_tag_inference.py` (follow that file's existing pattern for stubbing the gateway call — it monkeypatches the `_call_gateway` seam; reuse its helper/fixture for setting the model's raw JSON response):

```python
@pytest.mark.anyio
async def test_infer_parses_goal_actions(gateway_stub):
    gateway_stub('{"goal_inputs":[],"goal_outputs":["text"],"goal_actions":["email"],"side_effects":["email"]}')
    tags = await cli_registry._infer_capability_tags("write a report and email it")
    assert tags["goal_actions"] == ["email"]
    assert tags["goal_outputs"] == ["text"]


@pytest.mark.anyio
async def test_infer_allows_empty_outputs_for_pure_action(gateway_stub):
    # §2.1/§2.5 back-compat: pure action goal — no artifact, only the action
    gateway_stub('{"goal_inputs":["text"],"goal_outputs":[],"goal_actions":["email"],"side_effects":["email"]}')
    tags = await cli_registry._infer_capability_tags("email me the text I pasted")
    assert tags["goal_outputs"] == [] and tags["goal_actions"] == ["email"]


@pytest.mark.anyio
async def test_infer_rejects_empty_outputs_and_empty_actions(gateway_stub):
    gateway_stub('{"goal_inputs":[],"goal_outputs":[],"goal_actions":[],"side_effects":[]}')
    with pytest.raises(ValueError, match="neither goal_outputs nor goal_actions"):
        await cli_registry._infer_capability_tags("do nothing")
```

(If `test_cli_tag_inference.py` has no reusable stub fixture named `gateway_stub`, add one at the top of the file following how its existing tests stub `_call_gateway`/`_fn` — same mechanism, extracted into a fixture that takes the raw content string. Match the file's existing async-test decorator style: if existing tests use `@pytest.mark.asyncio` or plain `async def` under an anyio config, use exactly that instead of `@pytest.mark.anyio`.)

- [ ] **Step 2: Run to verify failures**

Run: `cd ~/.hermes/hermes-adapter && .venv/bin/python -m pytest tests/unit/test_cli_tag_inference.py -v`
Expected: new tests FAIL — `KeyError: 'goal_actions'` / `ValueError: tag inference produced no goal_outputs`

- [ ] **Step 3: Implement — system prompt.** Replace `_TAG_INFER_SYSTEM` (cli_registry.py:478-497) with:

```python
_TAG_INFER_SYSTEM = (
    "You translate a user's plain-language goal into CLI capability tags. "
    "Return ONLY compact JSON: {\"goal_inputs\":[...],\"goal_outputs\":[...],"
    "\"goal_actions\":[...],\"side_effects\":[...]}. "
    "Tags use the registry's <category>:<subtype> vocabulary (e.g. file:pdf, text:doc, "
    "file:png) — never plain words or snake_case compounds. "
    "goal_inputs = capability tags the user already has (e.g. file:svg). "
    "goal_outputs = capability tags for the produced ARTIFACT only (e.g. file:png; "
    "'text' or 'json' for a report or an answer). "
    "For a QUERY goal that asks a question rather than requesting a file (e.g. "
    "'check git status', 'count lines in a file') the answer's format ('text' or "
    "'json') is the artifact — put it in goal_outputs. "
    "goal_actions = the terminal ACTION VERB the goal demands (e.g. email) — at most "
    "one. For a PURE ACTION goal with no artifact to produce first ('email me X I "
    "already have') goal_outputs MAY be empty. For a COMPOUND goal ('produce a report "
    "AND email it') put the artifact in goal_outputs AND the verb in goal_actions. "
    "NEVER put the action's confirmation text in goal_outputs. "
    "side_effects = side-effect classes the goal explicitly asks for (e.g. email, file_write). "
    "No prose, no code fences."
)
```

- [ ] **Step 4: Implement — parser.** In `_infer_capability_tags`'s inner `_call` (cli_registry.py:522-539), replace from `gi = data.get("goal_inputs") or []` through the `return {...}` with:

```python
        gi = [t for t in (data.get("goal_inputs") or []) if isinstance(t, str)]
        go = [t for t in (data.get("goal_outputs") or []) if isinstance(t, str)]
        ga = [t for t in (data.get("goal_actions") or []) if isinstance(t, str)]
        se = [t for t in (data.get("side_effects") or []) if isinstance(t, str)]
        # §2.1: goal_outputs may be empty ONLY for a pure-action goal — a goal
        # naming neither an artifact nor an action is unusable (never fabricate).
        if not go and not ga:
            raise ValueError("tag inference produced neither goal_outputs nor goal_actions")
        return {"goal_inputs": gi, "goal_outputs": go, "goal_actions": ga,
                "side_effects": se}
```

And in the post-retry quarantine block (cli_registry.py:564-569), replace `if not tags["goal_outputs"]:` with:

```python
        if not tags["goal_outputs"] and not tags["goal_actions"]:
```

- [ ] **Step 5: Run the adapter unit suite** (existing inference tests may assert the old 3-key dict or the old "no goal_outputs" error — update any such assertion to the 4-key shape / new error message; that is the only sanctioned edit to existing tests)

Run: `cd ~/.hermes/hermes-adapter && .venv/bin/python -m pytest tests/unit -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
cd ~/.hermes/hermes-adapter
git add hermes_adapter/tools/cli_registry.py tests/unit/test_cli_tag_inference.py
git commit -m "feat(cli-registry): tag inference emits goal_actions; empty goal_outputs valid for pure actions (GOALACTIONS-01 §2.1)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- hermes_adapter/tools/cli_registry.py tests/unit/test_cli_tag_inference.py
```

---

### Task 10: Tool schema + planner call forwards `goal_actions` + one-shot reinference (test (m))

**Files:**
- Modify: `~/.hermes/hermes-adapter/hermes_adapter/tools/cli_registry.py:387-419` (`PLAN_CLI_CHAIN_SCHEMA`) and `:897-908` (planner call in `handle_run_cli_command`)
- Test: `~/.hermes/hermes-adapter/tests/unit/test_cli_slice_fused.py`

**Interfaces:**
- Consumes: Task 8's `_decode_planner_error`/exceptions; Task 9's `tags["goal_actions"]`; `_infer_capability_tags`, `_mcp_call`, `_select_chain` seams (all monkeypatchable module attributes).
- Produces: planner call payload `{"goal_inputs", "goal_outputs", "goal_actions", "allow_side_effects": []}` — allow_side_effects is NO LONGER pre-resolved from `side_effects` (§2.7: planner owns resolution). `UnknownActionVerbError` drives EXACTLY ONE corrective reinference then one re-plan; `PlannerStructuredError` propagates to the handler's failed JSON with the message verbatim and zero reinference.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_cli_slice_fused.py` (follow the file's existing monkeypatch style for `cli_registry._mcp_call` / `cli_registry._infer_capability_tags` / `cli_registry._full_catalog_vocab`; use its existing async-test convention):

```python
def _tags(gi=(), go=("text",), ga=("email",), se=("email",)):
    return {"goal_inputs": list(gi), "goal_outputs": list(go),
            "goal_actions": list(ga), "side_effects": list(se)}


def _envelope(obj):
    import json as _json
    return _json.dumps({"content": [{"type": "json", "json": obj}]})


async def test_unknown_verb_drives_exactly_one_reinference(monkeypatch):
    # spec §5 test (m): corrective message names the rejected verb + known list;
    # ONE reinference, ONE re-plan; second failure raises (no loop)
    import json as _json
    infer_calls, plan_calls = [], []

    async def fake_infer(goal, vocab=None):
        infer_calls.append(goal)
        return _tags(ga=("telegram",)) if len(infer_calls) == 1 else _tags(ga=("email",))

    async def fake_mcp(tool, args):
        if tool == "search_cli_catalog":
            return _envelope([{"slug": "report_gen", "health_status": "healthy"},
                              {"slug": "send_mail", "health_status": "healthy"}])
        if tool == "plan_cli_chain":
            plan_calls.append(args)
            if args["goal_actions"] == ["telegram"]:
                return _envelope({"error": "invalid input: unknown action verb: telegram; "
                                           "known: ['email', 'file_write', 'notify', 'webhook']"})
            return _envelope([{"slugs": ["report_gen", "send_mail"],
                               "hops": [{"slug": "report_gen", "health_status": "healthy"},
                                        {"slug": "send_mail", "health_status": "healthy"}]}])
        raise AssertionError(f"unexpected tool {tool}")

    async def fake_vocab():
        return None

    async def fake_resolve(slug):
        return f"run-{slug}"

    async def fake_gateway(cmd, base_url=None, client=None, api_key=None):
        return {"status": "success", "stdout": "ok", "exit_code": 0}

    monkeypatch.setattr(cli_registry, "_infer_capability_tags", fake_infer)
    monkeypatch.setattr(cli_registry, "_mcp_call", fake_mcp)
    monkeypatch.setattr(cli_registry, "_full_catalog_vocab", fake_vocab)
    monkeypatch.setattr(cli_registry, "_resolve_command", fake_resolve)
    monkeypatch.setattr(cli_registry, "run_on_gateway", fake_gateway)

    out = _json.loads(await cli_registry.handle_run_cli_command(
        {"goal": "write a report and email it"}, _budget()))
    assert out["status"] == "success"
    assert len(infer_calls) == 2, "exactly ONE corrective reinference"
    assert "telegram" in infer_calls[1] and "email" in infer_calls[1], \
        "corrective message names rejected verb + known vocabulary"
    assert len(plan_calls) == 2
    assert plan_calls[1]["goal_actions"] == ["email"]
    assert plan_calls[1]["allow_side_effects"] == []


async def test_integrity_error_passes_through_verbatim_zero_reinference(monkeypatch):
    # adapter half of spec §5 test (n)
    import json as _json
    infer_calls = []
    msg = "invalid input: action verb integrity: terminal 'dual_mail' matches multiple verbs ['email', 'notify']"

    async def fake_infer(goal, vocab=None):
        infer_calls.append(goal)
        return _tags()

    async def fake_mcp(tool, args):
        if tool == "search_cli_catalog":
            return _envelope([{"slug": "a", "health_status": "healthy"},
                              {"slug": "b", "health_status": "healthy"}])
        return _envelope({"error": msg})

    async def fake_vocab():
        return None

    monkeypatch.setattr(cli_registry, "_infer_capability_tags", fake_infer)
    monkeypatch.setattr(cli_registry, "_mcp_call", fake_mcp)
    monkeypatch.setattr(cli_registry, "_full_catalog_vocab", fake_vocab)

    out = _json.loads(await cli_registry.handle_run_cli_command(
        {"goal": "write a report and email it"}, _budget()))
    assert out["status"] == "failed"
    assert msg in out["error"], "message preserved verbatim, not 'no healthy chain'"
    assert len(infer_calls) == 1, "ZERO corrective reinference for integrity errors"
```

(`_budget()`: reuse the OutputBudget construction already used by this file's existing `handle_run_cli_command` tests — if none exists, `from hermes_adapter.budget import OutputBudget` and construct with that class's default/large limit as its existing callers do. Match the file's async-test decorator convention exactly.)

- [ ] **Step 2: Run to verify failures**

Run: `cd ~/.hermes/hermes-adapter && .venv/bin/python -m pytest tests/unit/test_cli_slice_fused.py -k "reinference or verbatim" -v`
Expected: FAIL — planner payload lacks `goal_actions` (KeyError in fake_mcp) and/or generic "no healthy chain" instead of the verbatim message

- [ ] **Step 3: Implement — tool schema.** In `PLAN_CLI_CHAIN_SCHEMA` properties (cli_registry.py:401-417), add after `goal_outputs`:

```python
                "goal_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Terminal action verbs the goal demands (e.g. 'email'). At most one.",
                },
```

- [ ] **Step 4: Implement — planner call.** Replace the step-4 planner else-branch body (cli_registry.py:897-908, the `try:` through `return json.dumps({"status": "failed", ...})`) with:

```python
        async def _plan_and_select(t: dict) -> list[str]:
            plan_json = await _mcp_call("plan_cli_chain", {
                "goal_inputs": t["goal_inputs"],
                "goal_outputs": t["goal_outputs"],
                "goal_actions": t.get("goal_actions") or [],
                # §2.7: planner owns side-effect resolution (slug-scoped
                # final-position self-auth) — the adapter no longer pre-resolves
                # allow_side_effects from inferred side_effects terms.
                "allow_side_effects": [],
            })
            logger.debug("run_cli_command step4 plan", extra={"plan_json": plan_json})
            _decode_planner_error(plan_json)
            return _select_chain(plan_json)

        try:
            try:
                chain = await _plan_and_select(tags)
            except UnknownActionVerbError as e:
                # §2.8: ONE corrective reinference naming verb + vocabulary,
                # then one re-plan; a second failure propagates (no loop).
                corrective = (
                    f"{goal}\n\nYour previous answer used action verb '{e.verb}', "
                    f"which the registry does not know. Choose goal_actions ONLY "
                    f"from: {sorted(e.known)}."
                )
                tags = await _infer_capability_tags(corrective, vocab=full_vocab)
                chain = await _plan_and_select(tags)
        except Exception as e:  # noqa: BLE001
            logger.debug("run_cli_command step4 plan/select failed", extra={"error": str(e)})
            return json.dumps({"status": "failed", "error": str(e)})
```

- [ ] **Step 5: Run the adapter unit suite**

Run: `cd ~/.hermes/hermes-adapter && .venv/bin/python -m pytest tests/unit -v`
Expected: all PASS (existing fused tests exercising step 4 may need their fake `_mcp_call` signatures to tolerate the new `goal_actions`/`allow_side_effects` keys — update those fakes only, not assertions about behavior)

- [ ] **Step 6: Commit**

```bash
cd ~/.hermes/hermes-adapter
git add hermes_adapter/tools/cli_registry.py tests/unit/test_cli_slice_fused.py
git commit -m "feat(cli-registry): forward goal_actions to planner; one-shot reinference on unknown verb; verbatim integrity pass-through (GOALACTIONS-01 §2.7/§2.8)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- hermes_adapter/tools/cli_registry.py tests/unit/test_cli_slice_fused.py
```

---

### Task 11: Discovery restructure — empty `goal_outputs` must not crash (§3 discovery row)

**Files:**
- Modify: `~/.hermes/hermes-adapter/hermes_adapter/tools/cli_registry.py:830-865` (step-1 logging + step-2 discovery in `handle_run_cli_command`)
- Test: `~/.hermes/hermes-adapter/tests/unit/test_cli_slice_fused.py`

**Interfaces:**
- Consumes: Task 9's 4-key tags dict.
- Produces: discovery term priority `side_effect_term → action_term → output_term`; `output_term` is `None`-safe (Codex-VERIFIED crash today: `tags["goal_outputs"][0]` IndexErrors on a pure action). Step-3 vocab guard unchanged (it iterates sets — empty is fine).

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_cli_slice_fused.py`:

```python
async def test_pure_action_goal_discovers_via_action_term_without_crashing(monkeypatch):
    # §3 discovery row: goal_outputs=[] + goal_actions=['email'] — today this
    # IndexErrors on tags["goal_outputs"][0]; it must discover via the action term.
    import json as _json
    queries = []

    async def fake_infer(goal, vocab=None):
        return _tags(gi=("text",), go=(), ga=("email",), se=())

    async def fake_mcp(tool, args):
        if tool == "search_cli_catalog":
            queries.append(args["query"])
            return _envelope([{"slug": "send_mail", "health_status": "healthy"},
                              {"slug": "other", "health_status": "healthy"}])
        if tool == "plan_cli_chain":
            return _envelope([{"slugs": ["send_mail"],
                               "hops": [{"slug": "send_mail", "health_status": "healthy"}]}])
        raise AssertionError(f"unexpected tool {tool}")

    async def fake_vocab():
        return None

    async def fake_resolve(slug):
        return f"run-{slug}"

    async def fake_gateway(cmd, base_url=None, client=None, api_key=None):
        return {"status": "success", "stdout": "sent", "exit_code": 0}

    monkeypatch.setattr(cli_registry, "_infer_capability_tags", fake_infer)
    monkeypatch.setattr(cli_registry, "_mcp_call", fake_mcp)
    monkeypatch.setattr(cli_registry, "_full_catalog_vocab", fake_vocab)
    monkeypatch.setattr(cli_registry, "_resolve_command", fake_resolve)
    monkeypatch.setattr(cli_registry, "run_on_gateway", fake_gateway)

    out = _json.loads(await cli_registry.handle_run_cli_command(
        {"goal": "email me the pasted text"}, _budget()))
    assert out["status"] == "success"
    assert queries and queries[0] == "email", "discovery searched by the action term"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/.hermes/hermes-adapter && .venv/bin/python -m pytest tests/unit/test_cli_slice_fused.py -k "pure_action_goal_discovers" -v`
Expected: FAIL — `IndexError: list index out of range` (surfaced inside the handler's failed JSON or as the raw exception, depending on where the crash lands)

- [ ] **Step 3: Implement.** In `handle_run_cli_command`: extend the step-1 debug log extras (line 830-832) with `"goal_actions": tags["goal_actions"]`. Then replace the step-2 term selection (lines 842-844):

```python
    side_effect_term = tags["side_effects"][0] if tags.get("side_effects") else None
    output_term = tags["goal_outputs"][0]
    all_slugs, healthy, query_term = set(), set(), output_term
```

with:

```python
    side_effect_term = tags["side_effects"][0] if tags.get("side_effects") else None
    action_term = tags["goal_actions"][0] if tags.get("goal_actions") else None
    # §3 discovery row: goal_outputs may now be empty (pure action) — the
    # action term is then the discovery signal; never index an empty list.
    output_term = tags["goal_outputs"][0] if tags["goal_outputs"] else None
    discovery_term = side_effect_term or action_term
    all_slugs, healthy, query_term = set(), set(), output_term or discovery_term
    if discovery_term:
        try:
            se_catalog = await _mcp_call("search_cli_catalog", {"query": discovery_term})
            se_all, se_healthy = _candidate_slugs(se_catalog)
        except Exception:  # noqa: BLE001 — fall through to the output-term search
            se_all, se_healthy = set(), set()
        if se_all:
            all_slugs, healthy, query_term = se_all, se_healthy, discovery_term
    if not all_slugs and output_term is not None:
        try:
            catalog_json = await _mcp_call("search_cli_catalog", {"query": output_term})
        except Exception as e:  # noqa: BLE001
            logger.debug("run_cli_command step2 discovery failed", extra={"query": output_term, "error": str(e)})
            return json.dumps({"status": "failed", "error": f"discovery failed: {e}"})
        all_slugs, healthy = _candidate_slugs(catalog_json)
```

Delete the OLD `if side_effect_term:` block and the old `if not all_slugs:` search block that this replaces (lines 845-859) — the code above is their replacement, not an addition. The following `logger.debug("run_cli_command step2 candidates", ...)` and `if not all_slugs:` failure return (lines 860-865) stay as they are.

- [ ] **Step 4: Run the adapter unit suite**

Run: `cd ~/.hermes/hermes-adapter && .venv/bin/python -m pytest tests/unit -v`
Expected: all PASS (existing side-effect-discovery tests keep passing: `side_effect_term` still wins the priority order)

- [ ] **Step 5: Commit**

```bash
cd ~/.hermes/hermes-adapter
git add hermes_adapter/tools/cli_registry.py tests/unit/test_cli_slice_fused.py
git commit -m "feat(cli-registry): discovery survives empty goal_outputs — action-term discovery for pure-action goals (GOALACTIONS-01 §3)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- hermes_adapter/tools/cli_registry.py tests/unit/test_cli_slice_fused.py
```

---

### Task 12: Compound-goal bypass guard (AC-04, RED-first)

**Files:**
- Modify: `~/.hermes/hermes-adapter/hermes_adapter/tools/cli_registry.py:893` (the bypass condition)
- Test: `~/.hermes/hermes-adapter/tests/unit/test_cli_slice_fused.py`

**Interfaces:**
- Consumes: Tasks 9–11 (tags shape, `_plan_and_select`, discovery terms).
- Produces: the `len(healthy)==1` bypass defers to the planner when `goal_actions` AND `goal_outputs` are both non-empty (compound). Pure-action and legacy side-effect bypasses unchanged.

- [ ] **Step 1: Write the failing test (AC-04: reproduce the swallow FIRST)** — append to `tests/unit/test_cli_slice_fused.py`:

```python
async def test_compound_goal_bypass_defers_to_planner_and_retains_producer(monkeypatch):
    # AC-04 RED-first: compound goal + single healthy side-effect candidate —
    # the bypass used to swallow the producer sub-goal into a send-only 1-hop
    # chain. Assert the exact planner args AND the exact selected chain.
    import json as _json
    plan_calls, executed = [], []

    async def fake_infer(goal, vocab=None):
        return _tags(gi=("file:pdf",), go=("text",), ga=("email",), se=("email",))

    async def fake_mcp(tool, args):
        if tool == "search_cli_catalog":
            # the side-effect-term search isolates exactly ONE healthy slug —
            # the precondition that used to trigger the bypass
            return _envelope([{"slug": "send_mail", "health_status": "healthy"}])
        if tool == "plan_cli_chain":
            plan_calls.append(args)
            return _envelope([{"slugs": ["report_gen", "send_mail"],
                               "hops": [{"slug": "report_gen", "health_status": "healthy"},
                                        {"slug": "send_mail", "health_status": "healthy"}]}])
        raise AssertionError(f"unexpected tool {tool}")

    async def fake_vocab():
        return None

    async def fake_resolve(slug):
        return f"run-{slug}"

    async def fake_gateway(cmd, base_url=None, client=None, api_key=None):
        executed.append(cmd)
        return {"status": "success", "stdout": "ok", "exit_code": 0}

    monkeypatch.setattr(cli_registry, "_infer_capability_tags", fake_infer)
    monkeypatch.setattr(cli_registry, "_mcp_call", fake_mcp)
    monkeypatch.setattr(cli_registry, "_full_catalog_vocab", fake_vocab)
    monkeypatch.setattr(cli_registry, "_resolve_command", fake_resolve)
    monkeypatch.setattr(cli_registry, "run_on_gateway", fake_gateway)

    out = _json.loads(await cli_registry.handle_run_cli_command(
        {"goal": "produce the report and email it to me"}, _budget()))
    assert out["status"] == "success"
    assert plan_calls, "bypass must DEFER to the planner for a compound goal"
    assert plan_calls[0]["goal_actions"] == ["email"], "goal_actions forwarded"
    assert len(executed) == 2 and executed[0].startswith("run-report_gen"), \
        "producer retained as hop 1 (not swallowed into a send-only chain)"
```

- [ ] **Step 2: Run to verify RED (the bypass swallows the producer)**

Run: `cd ~/.hermes/hermes-adapter && .venv/bin/python -m pytest tests/unit/test_cli_slice_fused.py -k "bypass_defers" -v`
Expected: FAIL — `plan_calls` is empty and only 1 command executed (`run-send_mail`)

- [ ] **Step 3: Implement.** Replace the bypass condition (cli_registry.py:893):

```python
    if side_effect_term and query_term == side_effect_term and len(healthy) == 1:
```

with:

```python
    # AC-04: a COMPOUND goal (artifact AND action) must never bypass — the
    # single discovered action terminal would swallow the producer sub-goal.
    compound = bool(tags.get("goal_actions")) and bool(tags["goal_outputs"])
    if (not compound) and discovery_term and query_term == discovery_term \
            and len(healthy) == 1:
```

(Note: Task 11 renamed the winning search term to `discovery_term`; the bypass keys on it so pure-action single-candidate goals still bypass correctly.)

- [ ] **Step 4: Run the adapter unit suite**

Run: `cd ~/.hermes/hermes-adapter && .venv/bin/python -m pytest tests/unit -v`
Expected: all PASS — including the pre-existing planner-bypass tests (they use action-less side-effect tags, so `compound` is False for them)

- [ ] **Step 5: Commit**

```bash
cd ~/.hermes/hermes-adapter
git add hermes_adapter/tools/cli_registry.py tests/unit/test_cli_slice_fused.py
git commit -m "feat(cli-registry): compound-goal bypass guard — defer to planner when goal_actions AND goal_outputs present (GOALACTIONS-01 AC-04)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- hermes_adapter/tools/cli_registry.py tests/unit/test_cli_slice_fused.py
```

---

### Task 13: Deploy (registry FIRST, then adapter) + AC-05 live E2E (single attempt)

**Files:**
- No source changes. Services: `ai.hermes.cli-registry` (runs `~/projects/a2a-cli-registry`), `ai.hermes.adapter` (uvicorn :9109).

**Interfaces:**
- Consumes: everything above, merged and pushed on both repos.
- Produces: AC-05 evidence — a live producer→send_mail 2-hop chain, proof-of-handoff via a runtime-generated token in the received mail body.

- [ ] **Step 1: Full suites green on both repos**

Run: `cd ~/projects/a2a-cli-registry && .venv/bin/python -m pytest` then `cd ~/.hermes/hermes-adapter && .venv/bin/python -m pytest tests/unit`
Expected: registry all pass except pre-existing `test_web_render`; adapter unit all pass

- [ ] **Step 2: Restart REGISTRY first (§8 ordering), then adapter; verify both**

```bash
launchctl kickstart -k gui/$(id -u)/ai.hermes.cli-registry
sleep 3
launchctl kickstart -k gui/$(id -u)/ai.hermes.adapter
sleep 3
curl -s localhost:9109/status
tail -5 ~/.hermes/logs/cli-registry.log
```

Expected: `/status` returns healthy JSON; registry log shows a clean start (no traceback)

- [ ] **Step 3: AC-05 live E2E — SINGLE attempt, `--max-time 600`.** The goal must make hop 1 generate a runtime token ABSENT from the goal string (spec AC-05: goal text is injected into every hop, so only a hop-1-generated token proves hop-1 stdout actually reached hop 2). Use the adapter's chat endpoint with the cli slice exactly as the prior E2E did (memory: `project_hermes_3step_test_progress` — planner-bypass mail run), with a compound goal, e.g.:

`"Generate a two-word random codename for this test run, then email it to me (subject: GOALACTIONS-01 E2E)."`

Rules: ONE attempt only. exit-124 = delivery-unknown — check the inbox, NEVER blindly re-send. Verify: (a) adapter log line `run_cli_command step4 selected` shows an ordered 2-hop chain ending in `send_mail` (this is the AC-05 instrumentation — `extra={"chain": ...}` at cli_registry.py:909); (b) the mail arrives; (c) the codename in the mail body does NOT appear in the goal string.

- [ ] **Step 4: Record the evidence** — quote the selected-chain log line and the mail-body token in the session notes / handover. If the E2E fails, STOP and diagnose (systematic-debugging); do not loop attempts.

- [ ] **Step 5: Governance close-out**

```bash
# tick ACs in 00_Governance/BACKLOG.md (AC lines only — State stays CLI-managed),
# note evidence per AC, commit with explicit path:
cd ~/projects/00_Governance
git add BACKLOG.md && git commit -m "backlog(clireg): GOALACTIONS-01 ACs verified — planner+adapter shipped, AC-05 E2E evidence

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" -- BACKLOG.md
git push
# push both repos
cd ~/projects/a2a-cli-registry && git push
cd ~/.hermes/hermes-adapter && git push
```

---

## Self-Review Notes (spec → task map)

- §2.1 three-list data flow → Task 9. §2.2 map + invariant + integrity error → Tasks 1, 2, 7. §2.3 predicate → Task 3. §2.4 short-circuit → Task 3. §2.5 synthesis → Task 4. §2.6 start gate → Task 5. §2.7 self-auth + stop pre-resolving allow → Tasks 6, 10. §2.8 decode + one-shot reinference + pass-through → Tasks 8, 10. §3 discovery/tool-schema/ops-schema rows → Tasks 7, 10, 11. §8 step 0 retag → Task 2; registry-before-adapter → task order + Task 13 restart order.
- Spec §5 tests: (a) T4, (b) T3, (c) T3, (d) T4, (e) T3, (f) T1+T7, (g) T5, (h) T1 (hermetic twin) + T2 (live), (i) T5, (j) T6, (k) T5 (hermetic `test_notify_goal_does_not_route_to_send_tagged_mailer`) + T2 (live retag), (l) T8, (m) T10, (n) T7 (registry) + T8/T10 (adapter).
- AC-04 → Task 12 (RED-first). AC-05 → Task 13.
