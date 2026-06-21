# a2a-cli-registry — Design Spec (rev 4)

**Date:** 2026-06-21
**Status:** Draft rev 4 — scope expanded to a language-agnostic, capability-driven
fleet registry with outcome-search, call-graph, and dual A2A+MCP surfaces.
Supersedes rev 3 (which passed panels at ai 7.9 / arch 7.8 / test 7.6 for the
narrower A2A-catalog design). Rev 4 needs a fresh panel pass.
**Author:** Jonas Cords + Claude (Opus 4.8)

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
  side-effect class, emitted by the source or inferred by the adapter.
- SQLite store (`cli`, `capability`, `cli_edge`, `subscriber`, `delivery`).

**Surfaces**
- REST: `GET /clis`, `GET /clis/{id}`, `GET /graph`, `GET /health`.
- **A2A v1.0** agent card (small fixed skill set; CLIs + capabilities in payloads).
- **MCP server** exposing the same catalog operations as MCP tools (capability
  model serialized to JSON Schema).
- **Outcome-search**: deterministic type-compatible chain planner — goal I/O →
  candidate CLIs → valid orderings where A.output_type feeds B.input_type. No LLM.
- **Call-graph**: edges computed from I/O type compatibility (not authored).

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
| input_types | CSV of typed input ports (e.g. file:pdf, text, url, json:invoice) |
| output_types | CSV of typed output ports |
| side_effect | none / writes-fs / network / destructive (planner avoids destructive by default) |
| confidence | declared (source emitted) vs inferred (adapter guessed) |

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
does*. Two provenance levels:
- **Declared** — the `DiscoverySource`/CLI manifest emits `intent_tags`,
  `input_types`, `output_types`, `side_effect` (high confidence).
- **Inferred** — the `LanguageAdapter` guesses from `--help`/argparse/docstrings
  (low confidence, flagged). The Python adapter reuses the US-77/80 parsing it
  already does for discovery.

Types are an **open controlled vocabulary** (string ports like `file:pdf`,
`json:invoice`, `text`, `url`), namespaced, with a registry of known ports in
config so two CLIs agree on what `file:pdf` means. This is the single mechanism
underneath outcome-search, call-graph, and MCP tool schemas.

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

### 6.2 MCP server (new)
Mounts an MCP server exposing the SAME catalog operations as MCP tools:
`search_cli_catalog`, `describe_cli`, `get_cli_health`, `plan_cli_chain`,
`get_cli_graph`. Each tool's input/output JSON Schema is the capability model
serialized. Describe-only (tools return catalog/plan data, never execute a CLI).
Lets Claude Code / Copilot / any MCP client discover the fleet natively. Auth +
the untrusted-catalog-text rule (§8) apply identically to MCP responses.

### 6.3 Outcome-search / planner (new)
`plan-cli-chain(goal_inputs, goal_outputs, [avoid_side_effects])` →
deterministic search over the capability type-graph: find ordered CLI sequences
where the chain consumes `goal_inputs` and produces `goal_outputs`, each hop's
output types feeding the next hop's input types. Returns ranked candidate chains
(shorter + higher-confidence + fewer side-effects first). **No LLM; no execution
— suggests the chain.** Destructive side-effects excluded unless explicitly
allowed. Explains each hop ("CLI A: pdf → text, then CLI B: text → summary").

### 6.4 Call-graph (new)
`get-cli-graph` / `GET /graph` returns `cli_edge` rows: a directed graph where an
edge A→B exists iff A.output_types ∩ B.input_types ≠ ∅. Edges are **computed**
from the capability model on every populate / capability change, never hand-
authored. `edge_changed` webhook fires on graph delta. This graph IS the
planner's search space (§6.3) — one structure, two views.

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
test_capability::types_namespaced_and_matched.

**Lang-agnostic seam:** test_adapter::python_adapter_carries_us77_us80;
test_adapter::stub_adapter_registers_non_python_cli (a shell CLI gets a
launch_spec without python rules); test_adapter::unknown_lang_fails_closed.

**Outcome-search:** test_planner::chain_links_output_to_input_types;
test_planner::excludes_destructive_unless_allowed;
test_planner::ranks_shorter_higher_confidence_first;
test_planner::no_chain_returns_empty_not_error;
test_planner::is_deterministic_no_llm.

**Call-graph:** test_graph::edge_iff_type_overlap;
test_graph::recomputed_on_capability_change;
test_graph::edge_changed_event_emitted.

**A2A contract:** card validates v1.0 (+neg); skills_are_catalog_ops;
sendmessage_returns_catalog_not_execution; invokable_false_never_spawns (spawn-spy==0);
gettask status/unknown-id; unauth_omits_launch_specs; version_negotiation_patch;
injected_prompt_returned_inert.

**MCP contract:** test_mcp::tools_expose_capability_schema;
test_mcp::tool_call_returns_data_not_execution (spawn-spy==0 on MCP path too);
test_mcp::injected_prompt_returned_inert.

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
`config.toml`: buckets, cli-audit path, portmgr port, broker list, type-port
vocabulary registry, and all thresholds (probe interval 300s / timeout 10s /
dead-letter N 5 / backoff 2s-60s / staleness TTL 3600s / mass-removal 0.30 /
max_probe_output_bytes 65536 / probe_concurrency 8 / max_inflight_deliveries 16).
Ships `cli_audit_source` + `python_adapter`; a stranger uses `filesystem_source`
+ the language adapter matching their fleet.

---

## 11. Open questions / deferred
- Capability **inference quality** for the Python adapter — how much can be
  derived from --help/argparse vs needs a declared manifest. Start
  declared-preferred, inferred-as-fallback; measure on the real fleet.
- The **type-port vocabulary** — seed set in config; governance of new ports as
  the fleet grows (avoid `file:pdf` vs `pdf` drift).
- Which **tagged A2A release** the vendored schema tracks; MCP SDK version pin.
- Non-Python adapter **completeness** — which of go/node/shell gets the first
  full impl after Python (driven by real demand).
- **Chain execution** (run the suggested chain) + live CLI execution — phase-2,
  behind the exec boundary.
