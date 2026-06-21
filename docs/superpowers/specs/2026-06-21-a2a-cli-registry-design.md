# a2a-cli-registry — Design Spec (rev 5)

**Date:** 2026-06-21
**Status:** Draft rev 5 — scope expanded to a language-agnostic, capability-driven
fleet registry with outcome-search, call-graph, and dual A2A+MCP surfaces.
Supersedes rev 3 (which passed panels at ai 7.9 / arch 7.8 / test 7.6 for the
narrower A2A-catalog design). Rev 4 cracked on re-gate (ai 7.1 / arch 6.6 FAIL /
test 6.9 FAIL) when scope 2–3×'d; rev 5 applies the full consensus punch-list and
needs a fresh panel pass.
**Author:** Jonas Cords + Claude (Opus 4.8)

> **What changed in rev 5 (re-gate fixes — consensus across ai/arch/test panels):**
> (1) Planner bounded + made falsifiable: bounded-BFS over `cli_edge` with
> `max_chain_depth`/`max_candidate_chains`, cycle guard, hub-type down-weight, and a
> strict **lexicographic** ranking order (§6.3) with golden expected-output tests.
> (2) Vocabulary governance promoted from open-question to **v1 admission control**
> (§4.5): unregistered ports quarantined/loud-fail; alias map; inferred ports
> canonicalized or excluded from edges. (3) Capability ownership precedence:
> **declared always wins over inferred**; inference scoped **Python-only +
> experimental** (§2 ↔ §11 contradiction resolved); separate `infer_capability()`
> seam; precision/recall floor eval. (4) Edge consistency: `cli_edge` is the planner's
> ONE adjacency source; incremental + atomic (shadow-swap) recompute. (5) Safety:
> inferred `side_effect` fails **UNSAFE** (excluded by default like destructive);
> per-hop + aggregate blast-radius annotation with provenance; param renamed
> `avoid_side_effects` → `allow_side_effects`. (6) MCP correctness (§6.2): capability
> model → MCP tool **INPUT** schema only; `output_types` are result *content*, not a
> declared output-schema (category-error fix); Streamable-HTTP transport + handshake;
> SDK pin. (7) A2A/MCP parity: both surfaces render from ONE in-code op registry.

> **What changed in rev 4 (product reframing):** rev 1–3 designed an internal
> A2A catalog of *Python* CLIs. Rev 4 makes it an OSS-grade, **language-agnostic,
> capability-driven** registry that answers outcome questions ("I want to achieve
> X — which CLIs chain to do it?") and exposes the fleet over BOTH A2A and MCP.
> The keystone is a **capability model** (§4.5): structured intent tags + typed
> inputs/outputs per CLI. Four features project off this one model:
> outcome-search, call-graph, MCP tool schemas, and rich A2A skill payloads.

---

## 1. Summary

`a2a-cli-registry` discovers a fleet of **local command-line tools (any
language)**, models **what each one does** (intent + typed I/O), and serves that
model as:
1. a queryable **catalog** (REST),
2. one discoverable **A2A v1.0 agent** (catalog operations as skills),
3. an **MCP server** (catalog operations as MCP tools), and
4. an **outcome planner + call-graph** ("achieve X → chain these CLIs").

It health-monitors every CLI and manages each one's lifecycle. Built **OSS-first**:
the generic engine (`core/`) is the deliverable; the operator's fleet is the
reference adapter (`examples/jonas-fleet/`).

### Why this exists (the gap)
No existing tool (verified vs awesome-a2a, 2026-06-21) serves a health-tracked,
**capability-typed** catalog of *many* local CLIs behind *both* A2A and MCP, with
outcome-driven chaining. Existing tools wrap one CLI as one agent, generate one
card, or consume agents. The novel contribution: a **capability model with four
projections** over a heterogeneous local CLI fleet.

---

## 2. Scope

### In scope (v1)
**Foundation**
- Language-agnostic discovery via a `LanguageAdapter` seam; **Python adapter ships**
  (carries US-77/80 lessons); Go/Node/shell adapters are pluggable stubs.
- `DiscoverySource` interface (cli-audit JSON + generic filesystem scan).
- **Capability model** (§4.5): per-CLI intent tags + typed inputs/outputs +
  side-effect class. **Declared by the source always wins; inference is a
  Python-only, experimental fallback** that only fills null fields (§4.5). Non-Python
  adapters are **declared-capabilities-required** (they do not infer in v1).
- SQLite store (`cli`, `capability`, `cli_edge`, `subscriber`, `delivery`).

**Surfaces**
- REST: `GET /clis`, `GET /clis/{id}`, `GET /graph`, `GET /health`.
- **A2A v1.0** agent card (small fixed skill set; CLIs + capabilities in payloads).
- **MCP server** exposing the same catalog operations as MCP tools (capability
  model serialized to JSON Schema).
- **Outcome-search**: deterministic, **bounded** type-compatible chain planner —
  goal I/O → bounded-BFS over `cli_edge` → valid orderings where A.output_type feeds
  B.input_type, capped by `max_chain_depth`/`max_candidate_chains` with a cycle
  guard, ranked by a strict lexicographic order (§6.3). No LLM.
- **Call-graph**: edges computed from I/O type compatibility (not authored), the
  planner's single adjacency source, recomputed incrementally + atomically (§6.4).
- **Vocabulary admission control** (§4.5): typed ports are validated against a
  registered vocabulary; unregistered ports are quarantined/loud-fail and excluded
  from edge computation.

**Operations**
- Health prober (per-adapter health cmd), isolated (timeout/kill/bulkhead),
  UNKNOWN/STALE + loop heartbeat.
- Webhook event bus (non-A2A extension): health_flip/new_cli/removed_cli/edge_changed.
- Self-registration to A2A brokers (startup/change/heartbeat).
- Operator CLI suite: `audit`, `discover`, `populate`, `lifecycle`, `graph`.
- launchd supervision + Dagu watchdog.

### Out of scope (v1) — named YAGNI guards
- **Live execution** of CLIs over A2A/MCP (describe + plan only; never spawn a
  managed CLI for a network caller). `a2a_invokable` reserved, default false.
- **Executing** an outcome chain — the planner *suggests* an ordered chain; it
  does not run it. (Execution is phase-2, gated behind the same exec boundary.)
- **LLM-based planning** — outcome-search is deterministic type-matching only.
- **Non-Python health/discovery heuristics beyond the seam** — only the Python
  adapter is a full impl; others are interface stubs + docs.
- **Capability inference for non-Python adapters** — inference is Python-only and
  experimental in v1; all other languages **must declare** capabilities. (Resolves
  the rev-4 §2↔§11 contradiction: inference is a scoped fallback, not a general
  in-scope capability.)
- **Multi-tenancy**, **per-CLI agent cards / broker-of-agents**.

### Acknowledged trade-off (over-scope risk, accepted)
"Everything in v1" is ~2–3× the rev-3 scope. The mitigation: all four features
are *projections of one capability model*, not independent subsystems — the
type-graph IS the call-graph IS the planner's search space IS the MCP tool
schema. Generality is concentrated in two seams (`LanguageAdapter`,
`DiscoverySource`) + the capability model; nowhere else.

---

## 3. Architecture

```
core/  (publishable, path/language-agnostic)
  discovery/
    DiscoverySource: discover() -> list[CliRecord]
    cli_audit_source.py / filesystem_source.py
  adapters/                 LanguageAdapter seam (NOT a plugin framework — one iface)
    base.py                 LanguageAdapter: detect(), launch_spec(), health_cmd(),
                            infer_capability()
    python_adapter.py       reference impl — US-77 filter + US-80 python -m
    (go|node|shell)_adapter.py  STUBS — interface + docs, OSS-contributable
  capability/               intent tags + typed I/O model; capability inference
  catalog/                  single query layer (search/describe/health/graph)
  planner/                  outcome-search: type-compatible chain finder (deterministic)
  graph/                    call-graph: edges = I/O type compatibility, recomputed
  cardgen/                  ONE A2A v1.0 card (small fixed skills)
  mcp/                      MCP server surface (same ops as MCP tools)
  prober/                   isolated health checks (timeout/kill/bulkhead/heartbeat)
  store/                    SQLite: cli/capability/cli_edge/subscriber/delivery
  server/                   REST + A2A (POST /a2a) ; mounts mcp/
  notifier/                 non-A2A webhook bus (HMAC, schema_version, event_id, seq)
  announcer/                self-register card URL to brokers
  cli/                      audit | discover | populate | lifecycle | graph

examples/jonas-fleet/  config.toml (buckets, cli-audit path, port, brokers, thresholds)
```

Both A2A and MCP surfaces, and REST `/clis`+`/graph`, render from `catalog/` +
`planner/` + `graph/` — one source of truth. Stack: Python 3.11+ / FastAPI /
SQLModel / SQLite. MCP via the official Python MCP SDK, mounted on the same app.

---

## 4. Data model (registry.db)

### cli
| Field | Notes |
|---|---|
| slug (PK) | opaque stable id |
| lang | adapter id (python/go/node/shell/...) |
| bucket, project, path | path is data, not identity |
| launch_spec | typed: {kind, entrypoint, args_schema} — replaces python-only `invocation` |
| description | one-line |
| source_class | opaque; engine never branches on it |
| health_cmd | resolved by the adapter |
| health_status / health_checked_at | healthy/unhealthy/UNKNOWN/STALE |
| enabled / a2a_invokable | a2a_invokable default false, unread in v1 |
| source_run_id / last_seen_at / updated_at | reconciliation |

### capability (1 cli : N capabilities)
| Field | Notes |
|---|---|
| id (PK) | |
| cli_slug (FK) | |
| intent_tags | CSV of controlled-vocab verbs (e.g. convert, extract, summarize, publish) |
| input_types | CSV of **registered** typed input ports (e.g. file:pdf, text, url, json:invoice); unregistered → quarantined (§4.5) |
| output_types | CSV of registered typed output ports; unregistered → quarantined, excluded from edges |
| side_effect | none / writes-fs / network / destructive / **unknown**. Planner excludes `destructive` AND `unknown`/inferred-side-effect by default (fail-UNSAFE, §8) |
| confidence | declared (source emitted) vs inferred (adapter guessed). **Declared always wins**; inferred only fills null fields and is excluded from edges when its ports are `unverified:` (§4.5) |

### cli_edge (computed, not authored)
| Field | Notes |
|---|---|
| from_slug, to_slug | A.output_types ∩ B.input_types is non-empty |
| via_type | the matched type port |
| recomputed_at | refreshed on populate / capability change |

### subscriber / delivery
As rev 3 (HMAC, schema_version, event_id, per-subscriber seq, dead-letter N=5),
plus `edge_changed` event type.

### 4.5 Capability model — the keystone
Each CLI carries one or more **capabilities**: a typed declaration of *what it
does*. **Scope note (L1):** "capability" / "intent" here means **structured
metadata extraction** (controlled-vocab tags + typed ports from manifests, `--help`,
argparse) — NOT semantic understanding of program behavior. The registry matches
*declared/extracted port strings*, it does not reason about what a CLI semantically
means. Two provenance levels with a strict precedence rule:
- **Declared** — the `DiscoverySource`/CLI manifest emits `intent_tags`,
  `input_types`, `output_types`, `side_effect` (high confidence).
- **Inferred** — the `LanguageAdapter` guesses (low confidence, flagged).

**Provenance precedence (A1/A3 — declared-wins).** Declared capabilities ALWAYS
win over inferred. Inference runs only to **fill null fields** on a declared record;
it never overrides a declared `intent_tag`/port/`side_effect`. Inference is a
**Python-only, experimental** path in v1 (the Python adapter reuses the US-77/80
`--help`/argparse parsing it already does for discovery); **all non-Python adapters
require declared capabilities** and do not infer. The inference logic lives in a
dedicated `infer_capability()` seam, kept **separate from discovery parsing** so the
contract is not Python-shaped — a non-Python adapter satisfies the interface by
returning declared records and a no-op inferer.

#### Type-port vocabulary — admission control (v1, was §11)
Types are a **registered, namespaced controlled vocabulary** (string ports like
`file:pdf`, `json:invoice`, `text`, `url`) declared in config so two CLIs agree on
what `file:pdf` means. Admission is enforced at populate time — this is the single
mechanism underneath outcome-search, call-graph, and MCP tool schemas, so a typo'd
port silently breaks all four. Rules:
- **Registered ports only form edges.** A port not in the config vocabulary is
  **quarantined**: the capability is stored but its unregistered ports are marked
  `unverified:` and **excluded from `cli_edge` computation** and from the planner's
  search space. Quarantine is a **loud-fail event** (same posture as the cli_audit
  schema-drift gate): logged + counted, surfaced in `/health`, never silently dropped.
- **Alias / normalization map.** Config carries a canonicalization map (e.g.
  `pdf → file:pdf`, `PDF → file:pdf`) applied before admission so declared synonyms
  converge instead of fragmenting the graph.
- **Inferred ports are `unverified:`-namespaced** and excluded from edges until a
  human/declared source promotes them into the registered vocabulary. This prevents
  low-confidence inference from polluting the call-graph.
- **Inference quality floor.** The Python inferer is held to a measured
  precision/recall floor (§9 `inference_precision_recall_floor`, e.g. ≥0.6) against a
  hand-labeled golden ground-truth; below floor, inference is disabled for that adapter.

---

## 5. Session lessons baked into core/ (Python adapter + regression tests)
US-80 (python -m), US-77 (two-stage filter), US-78/79 (fail-closed, no auto-flip),
A/B disposition — all carried by `python_adapter.py` and pinned by per-lesson
regression tests (§9). Other adapters are NOT required to implement these
Python-specific rules.

---

## 6. Surfaces

### 6.1 A2A v1.0 (as rev 3, verified-correct)
One card at `/.well-known/agent-card.json`; PascalCase `SendMessage`/`GetTask`;
`pushNotifications:false`; webhook bus declared under `capabilities.extensions[]`;
bearer `securityScheme`; **describe-only** (never spawns a CLI). Skills:
`search-cli-catalog`, `describe-cli`, `get-cli-health`, `list-buckets`,
`plan-cli-chain`, `get-cli-graph`. CLIs + capabilities returned in payloads.

**A2A↔MCP parity (B4/M4).** Both surfaces render from **ONE in-code operation
registry** — a single list of catalog ops, each with its handler + input schema.
A2A skills and MCP tools are two projections of that registry, so the surfaces
cannot drift. Naming transform is mechanical: **kebab-case for A2A skills**
(`plan-cli-chain`) ↔ **snake_case for MCP tools** (`plan_cli_chain`), derived from
one canonical op id. A test asserts the two surfaces expose the same op set.

### 6.2 MCP server (new)
Mounts an MCP server exposing the SAME catalog operations as MCP tools:
`search_cli_catalog`, `describe_cli`, `get_cli_health`, `plan_cli_chain`,
`get_cli_graph`. Describe-only (tools return catalog/plan data, never execute a CLI).
Lets Claude Code / Copilot / any MCP client discover the fleet natively. Auth +
the untrusted-catalog-text rule (§8) apply identically to MCP responses.

**Schema mapping (M1/F4 — category-error fix).** The capability model maps to each
tool's **input JSON Schema only** (the query parameters: goal I/O, slug, filters).
A CLI's `output_types` are **NOT** a declared MCP tool output-schema — they describe
what the *catalogued CLI* produces, which is *result content*, not the registry
tool's return contract. The registry tool returns its catalog/plan payload as a
**structured JSON content block** (`content` of type structured/`json`); the
capability model appears *inside* that content as data, never as the tool's declared
`outputSchema`. Pinning `output_types` to a tool output-schema would assert the
registry tool emits PDFs/summaries, which it does not — it emits catalog rows.

**Transport (M1).** Streamable HTTP (not stdio) so the server is reachable by
Claude Code / Copilot over the network on the same ASGI app as REST+A2A. The MCP
`initialize` capabilities handshake and session management are implemented per spec;
MCP auth composes with the A2A bearer `securityScheme` on the one app (a single
`Authorization` bearer gates both surfaces; unauth omits `launch_spec` on both).
The MCP SDK version is **pinned** in `pyproject.toml` (exact version recorded at
plan time; verify §6.2 against the live MCP spec via MCP docs tooling before impl).

### 6.3 Outcome-search / planner (new)
`plan-cli-chain(goal_inputs, goal_outputs, [allow_side_effects])` →
**deterministic, bounded** search over the call-graph. **No LLM; no execution —
suggests the chain.**

**Search (F1/H1/B2 — bounded).** Bounded-BFS over `cli_edge` (the planner's ONLY
adjacency source, §6.4) from CLIs consuming `goal_inputs` toward CLIs producing
`goal_outputs`, each hop's `output_types` feeding the next hop's `input_types`.
Bounds (config, §10):
- `max_chain_depth` (default 4–5) — caps chain length; deeper paths pruned.
- `max_candidate_chains` — caps enumerated candidates to prevent combinatorial blow-up.
- **Cycle guard** — a slug may appear at most once per chain; revisits pruned.
- **Hub-type down-weight** — bare hub types (`text`, `json`) do NOT form an edge on
  their own; an edge via a hub type requires a matching `intent_tag` between the two
  CLIs, so `text`-everywhere doesn't make the graph complete.

**Ranking (F2 — strict lexicographic, falsifiable).** Candidates are ordered by a
total, deterministic comparator (each key breaks ties of the previous):
1. **chain length** ascending (fewer hops first),
2. **aggregate side-effect count** ascending (fewer side-effects first),
3. **minimum hop confidence** descending (declared-only chains beat inferred),
4. **slug sequence** ascending lexicographically (final deterministic tiebreak —
   guarantees a unique ordering for golden tests).

**Safety (M2/M3).** Default `allow_side_effects = []` ⇒ chains containing any
`destructive` OR `unknown`/inferred-side-effect hop are **excluded** (fail-UNSAFE,
§8). Allowed classes are opted into explicitly. Each returned chain carries an
**aggregate blast-radius** plus **per-hop side-effect annotation with provenance**
(e.g. "writes-fs (declared)", "destructive (inferred, unverified)"). Explains each
hop ("CLI A: file:pdf → text, then CLI B: text → text:summary").

### 6.4 Call-graph (new)
`get-cli-graph` / `GET /graph` returns `cli_edge` rows: a directed graph where an
edge A→B exists iff A.output_types ∩ B.input_types ≠ ∅ **over registered ports**
(unverified/quarantined ports never form edges, §4.5). Edges are **computed** from
the capability model, never hand-authored.

**Single adjacency source (A2).** `cli_edge` is the ONE read path for adjacency: the
planner (§6.3), `GET /graph`, and the A2A/MCP graph ops all read `cli_edge` and
nothing else. No component recomputes adjacency on the fly — there is exactly one
edge-construction code path.

**Incremental recompute (B1).** On a capability change for slug S, only edges where S
is an endpoint are recomputed (not the whole graph). A populate batch debounces into
**one** recompute pass (N capability changes → one batched recompute, not N).

**Atomic recompute (B3).** Recompute builds a **shadow edge set and swaps it in**
(single transaction); `cli_edge` reads never observe a half-rebuilt graph. A
query-during-recompute sees either the old complete graph or the new complete graph.

**Delta + events (D2).** `edge_changed` fires only on a real delta — the set-diff of
`(from, to, via_type)` tuples; a no-op recompute (identical edge set) emits nothing.

This graph IS the planner's search space (§6.3) — one structure, two views.
**Complexity note (L2):** naive recompute is O(n²) in CLI count; bounded by
`graph_recompute_max_clis` (§10) which warns past the threshold. Incremental
recompute keeps the common path well under the full O(n²).

---

## 7. Data flow

```
discover() [DiscoverySource] --records--> LanguageAdapter.detect()/launch_spec()
        |                                       |
        |                                  infer_capability() (or declared)
        v                                       v
   populate --upsert--> cli + capability tables  --recompute--> cli_edge (graph)
        |   stale/malformed -> FAIL CLOSED ; >=30% removal -> circuit breaker
        |   events: new_cli/removed_cli/health_flip/edge_changed (+schema_version,event_id,seq)
        v
   catalog/ + planner/ + graph/  (one source of truth)
        |-> REST /clis /clis/{id} /graph /health
        |-> A2A card + SendMessage (skills incl. plan-cli-chain, get-cli-graph)
        |-> MCP tools (search/describe/health/plan/graph)
        `-> notifier (webhook bus) ; announcer (self-register)

prober (bounded concurrency) --> adapter.health_cmd, 10s timeout + SIGKILL
        --> healthy/unhealthy/UNKNOWN/STALE ; loop heartbeat in /health
```

---

## 8. Error handling & safety
As rev 3, plus:
- **Describe + plan only** across A2A *and* MCP: no surface spawns a managed CLI;
  the planner returns a suggested chain, never runs it. Pinned by spawn-spy tests
  on both surfaces.
- **Untrusted catalog text** (description, intent_tags, inferred capabilities)
  returned inert as data on every surface (A2A + MCP), never as instruction.
- **Capability confidence** surfaced: inferred capabilities flagged so a planner
  consumer can discount them.
- **Inferred side-effect fails UNSAFE (M2/M3).** An inferred or `unknown`
  side-effect class is treated like `destructive`: **excluded from chains by default**
  (`allow_side_effects` must opt it in). Chains carry aggregate + per-hop blast-radius
  with provenance, so a consumer sees "destructive (inferred, unverified)" and can
  refuse it. The fail-safe default is exclude, not include.
- Prober isolation (10s/SIGKILL/concurrency=8/output cap/heartbeat); stale-input
  fail-closed; ≥0.30 mass-removal breaker; outbound timeouts; SSRF guard; atomic
  fail-closed migrations; portalocker; no hardcoded paths.

---

## 9. Testing strategy (pytest) — every behavior bound to a named test
Fixtures: `golden_clis/` (multi-language: python + a go + a shell sample, plus an
adversarial prompt-injection description), `cli_audit_sample.json`, vendored
`a2a_agent_card_v1.0.schema.json`, vendored MCP tool-schema fixtures,
`webhook_event_v1.schema.json`, fake consumer/broker/subscriber, injectable clock.

**Regression (session lessons, Python adapter):** test_rules python_m / two_stage_filter;
test_populate drift_no_autoflip / vanished_retagged_not_dropped.

**Capability model:** test_capability::declared_vs_inferred_flagged;
test_capability::types_namespaced_and_matched;
test_capability::declared_wins_over_inferred (inferred only fills null fields, never
overrides a declared value);
test_capability::unregistered_port_quarantined (unregistered port stored as
`unverified:`, loud-fail event emitted, excluded from edges);
test_capability::namespaced_types_distinct_ports_do_not_match (`json:invoice` ≠
`json:resume`);
test_capability::alias_map_canonicalizes (`pdf` and `PDF` → `file:pdf` before admission);
test_capability::inference_precision_recall_floor (Python inferer ≥ stated floor vs
hand-labeled golden ground-truth; below floor disables inference);
test_capability::non_python_adapter_requires_declared (a non-Python adapter with no
declared caps yields no inferred caps).

**Lang-agnostic seam:** test_adapter::python_adapter_carries_us77_us80;
test_adapter::stub_adapter_registers_non_python_cli (a shell CLI gets a
launch_spec without python rules); test_adapter::unknown_lang_fails_closed.

**Outcome-search (expected-output golden tests — F1/F2):**
test_planner::chain_links_output_to_input_types;
test_planner::known_goal_yields_expected_chain (goal file:pdf → text:summary over
golden_clis MUST return [pdf2text, summarize] ranked first — exact expected output);
test_planner::unsatisfiable_goal_returns_no_path;
test_planner::terminates_on_cyclic_typegraph (cycle guard; bounded, no hang);
test_planner::ambiguous_match_tie_break_is_deterministic (asserts FULL lexicographic
ordering of a 4-chain example: length → side-effect count → min-confidence → slug);
test_planner::caps_candidate_explosion (respects max_chain_depth / max_candidate_chains);
test_planner::hub_type_requires_intent_tag (bare `text` edge needs matching intent_tag);
test_planner::excludes_destructive_unless_allowed;
test_planner::inferred_sideeffect_treated_as_unsafe (excluded by default);
test_planner::no_chain_returns_empty_not_error;
test_planner::is_deterministic_no_llm.

**Call-graph (A2/B1/B3/D2):** test_graph::edge_iff_type_overlap;
test_graph::planner_reads_only_cli_edge (single adjacency source — no on-the-fly
recompute path exists);
test_graph::recomputed_on_capability_change;
test_graph::incremental_recompute_touches_only_endpoint_edges;
test_graph::batched_recompute_one_pass_per_populate;
test_graph::atomic_swap_no_partial_read (query-during-recompute sees old-complete or
new-complete, never half-built);
test_graph::edge_changed_event_emitted;
test_graph::noop_recompute_emits_nothing (identical edge set → no event);
test_graph::unverified_ports_excluded_from_edges.

**A2A contract:** card validates v1.0 (+neg); skills_are_catalog_ops;
sendmessage_returns_catalog_not_execution; invokable_false_never_spawns (spawn-spy==0);
gettask status/unknown-id; unauth_omits_launch_specs; version_negotiation_patch;
injected_prompt_returned_inert.

**MCP contract (M1/F4/B4/M4):** test_mcp::tool_schema_is_valid_jsonschema (input
schema validates);
test_mcp::capability_maps_to_input_schema_only (output_types are NOT a declared tool
outputSchema — category-error guard);
test_mcp::result_is_structured_content_block (catalog/plan payload returned as
structured JSON content, capability model inside it as data);
test_mcp::malformed_capability_rejected_neg;
test_mcp::tool_call_returns_data_not_execution (spawn-spy==0 on MCP path too);
test_mcp::unauth_omits_launch_specs (MCP parity with A2A auth rule);
test_mcp::injected_prompt_returned_inert;
test_contract::a2a_skills_and_mcp_tools_share_one_registry (parity — same op set);
test_contract::parity_with_a2a_same_query (same query → equivalent payload on both
surfaces);
test_contract::kebab_a2a_snake_mcp_naming_transform.

**Failure modes:** prober hang/kill, flap debounce, output cap, bulkhead, loop-stall;
populate stale_no_removal, mass_removal_breaker; notifier event_id/seq/dead-letter/
hmac-tamper/ssrf/payload-schema; announcer timeout/heartbeat/fleet-change; store
concurrent-write/failed-migration-atomic.

**E2E:** test_e2e::discover_multi_lang_to_a2a_and_mcp_query_roundtrip;
test_e2e::goal_to_suggested_chain (filesystem_source over golden_clis → populate →
plan-cli-chain returns a valid typed chain).

CI gate: pytest green + coverage floor on core/; cli_audit_source schema-drift loud-fail.

---

## 10. Reference adapter (examples/jonas-fleet/)
`config.toml`: buckets, cli-audit path, portmgr port, broker list, and all
thresholds (probe interval 300s / timeout 10s / dead-letter N 5 / backoff 2s-60s /
staleness TTL 3600s / mass-removal 0.30 / max_probe_output_bytes 65536 /
probe_concurrency 8 / max_inflight_deliveries 16). **Planner/graph bounds:**
`max_chain_depth` (default 4–5) / `max_candidate_chains` / `graph_recompute_max_clis`
(O(n²) warn threshold). **Vocabulary admission (§4.5):** the registered type-port
vocabulary, the alias/normalization map (`pdf → file:pdf`), and the inference
precision/recall floor (e.g. 0.6).
Ships `cli_audit_source` + `python_adapter`; a stranger uses `filesystem_source`
+ the language adapter matching their fleet.

---

## 11. Open questions / deferred
> Resolved into v1 since rev 4: capability **inference scope** (now Python-only +
> experimental, declared-wins, §2/§4.5) and **type-port vocabulary governance** (now
> v1 admission control with quarantine + alias map, §4.5). They are no longer open
> questions — they are specified mechanisms.

- **Inference quality on the real fleet** — the precision/recall floor (§9) states a
  target (≥0.6); the actual achievable number on Jonas's fleet is measured at impl
  time and may move the floor. (Mechanism is fixed; the calibration value is open.)
- Which **tagged A2A release** the vendored schema tracks; **MCP SDK version pin** —
  decided at plan time (verify §6.2 vs live MCP spec via MCP docs tooling first).
- Non-Python adapter **completeness** — which of go/node/shell gets the first full
  impl after Python (driven by real demand).
- **MCP fast-follow toggle (C3)** — config flag to ship the A2A path first and gate
  the MCP surface behind a toggle, so a capability/MCP regression can't block the
  A2A path. Default on; flips off if MCP integration lands late.
- **Chain execution** (run the suggested chain) + live CLI execution — phase-2,
  behind the exec boundary.
