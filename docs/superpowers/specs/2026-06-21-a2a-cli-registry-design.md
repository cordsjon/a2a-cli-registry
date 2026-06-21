# a2a-cli-registry — Design Spec (rev 3)

**Date:** 2026-06-21
**Status:** Draft rev 3 — panels PASS (ai 7.9 / arch 7.8 / test 7.6); residual fixes folded in
**Author:** Jonas Cords + Claude (Opus 4.8)

> **Rev history:**
> - **rev 1** → 5-reviewer pass (ai 5.1 / arch 6.6 / test 4.6, all FAIL; Gemini 429).
> - **rev 2** → fixed A2A wire protocol (PascalCase SendMessage/GetTask, full v1.0
>   card), pushNotifications=false + webhook bus as non-A2A extension, one-agent
>   small-skill-set + catalog-payload model, prober isolation, stale-input guards,
>   idempotency, opaque IDs, SSRF guard, concrete thresholds, per-lesson
>   regression tests, defined CliRecord seam. Re-review: ai 7.9 / arch 7.8 /
>   test 7.6 — all PASS.
> - **rev 3** → folded consensus residual fixes: pinned all deferred thresholds to
>   config numbers, `schema_version` on webhook payload, injectable clock for
>   tests, webhook bus declared under `capabilities.extensions[]`, prompt-injection
>   note on untrusted catalog text, GetTask/announcer/heartbeat tests.

---

## 1. Summary

`a2a-cli-registry` is a self-hosted service that **discovers a fleet of local
command-line tools, serves them as a queryable catalog, exposes that catalog
through one A2A-discoverable agent, and manages each CLI's lifecycle and
health.**

The manager is **one A2A agent** whose skills are catalog *operations*
(`search-cli-catalog`, `describe-cli`, `get-cli-health`, `list-buckets`) — NOT
one-skill-per-CLI. The CLI fleet is returned in skill *response payloads*. Single
discoverable entry point: an agent finds the registry agent, reads a small valid
card, queries the fleet via `SendMessage`.

Built **OSS-first**: generic engine (`core/`) is the deliverable; the operator's
fleet is the reference adapter (`examples/jonas-fleet/`).

### Why this exists (the gap)
Research against awesome-a2a (2026-06-21) confirmed **no existing tool** serves a
health-tracked catalog of *many* local CLIs behind one A2A agent. Existing tools
wrap *one* CLI as *one* agent, generate *one* card, or *consume* agents. Operator
already holds discovery (cli-audit) + correct invocation (python -m,
US-CLIAUDIT-80); the novel contribution is the catalog + health loop + A2A query
surface.

---

## 2. Scope

### In scope (v1)
- Discover CLIs via pluggable `DiscoverySource` (two impls: cli-audit JSON,
  generic filesystem scan).
- Persist in SQLite (`cli`, `subscriber`, `delivery`).
- REST: `GET /clis`, `GET /clis/{id}`, `GET /health`.
- **One** A2A v1.0 agent card at `/.well-known/agent-card.json` with a SMALL
  fixed skill set (catalog operations). CLIs returned in `SendMessage` response
  payloads, NOT as individual skills.
- A2A v1.0 JSON-RPC: `SendMessage`, `GetTask` (PascalCase). **Describe-only** —
  the agent returns catalog facts; it NEVER spawns a managed CLI.
- Background health prober (python -m aware) with isolation (timeout, kill,
  bulkhead) and `UNKNOWN`/`STALE` states + probe-loop liveness heartbeat.
- Webhook event bus (**declared non-A2A extension** via `capabilities.extensions[]`)
  on `health_flip`/`new_cli`/`removed_cli` — HMAC-signed, `schema_version` +
  `event_id` + per-subscriber `seq`, retried, dead-lettered, SSRF-guarded.
- Self-registration: announce card URL to brokers on startup, fleet change, and
  periodic heartbeat (idempotent upsert keyed on card URL).
- Operator CLI suite: `audit`, `discover`, `populate`, `lifecycle`.
- launchd supervision + Dagu watchdog DAG (cloned from portmgr).

### Out of scope (v1) — named YAGNI guards
- **Live A2A execution of CLIs.** Describe-only in v1; execution is phase 2,
  behind `cli.a2a_invokable` (default false) + auth + arg-allowlisting. No v1
  code path runs a managed CLI for a network caller. Pinned by a negative test.
- **Plugin-loading framework** — exactly two `DiscoverySource` impls in
  `core/discovery/`; no separate `adapters/` layer.
- **Multi-tenancy / per-user catalogs.**
- **Per-CLI individual agent cards / broker-of-agents.**

### Acknowledged trade-off
OSS-first builds the `DiscoverySource` generality now (deliberate YAGNI exception
for external value), confined to that seam + flat TOML config.

---

## 3. Architecture

```
core/  (publishable, path-agnostic — ships all 4 session lessons as default rules)
  discovery/   DiscoverySource interface: discover() -> list[CliRecord]
    rules.py            two-stage filter (US-77) + python -m heuristic (US-80)
    cli_audit_source.py parses cli-audit JSON output (freshness-checked)
    filesystem_source.py generic --scan <dirs>, day-1 usable with no cli-audit
  cardgen/     builds the ONE manager AgentCard (small fixed skill set; v1.0 shape)
  catalog/     SINGLE query layer (search/describe/health) — source of truth for
               BOTH the REST and A2A read paths
  prober/      isolated health checks (timeout, kill, bulkhead), UNKNOWN/STALE,
               loop heartbeat
  store/       SQLite: cli / subscriber / delivery (atomic fail-closed migrations)
  server/      REST + A2A (well-known card, POST /a2a SendMessage/GetTask)
  notifier/    non-A2A webhook bus (HMAC, schema_version, event_id, seq, retry,
               dead-letter)
  announcer/   self-register card URL into brokers (startup + change + heartbeat)
  cli/         operator suite (python -m a2a_cli_registry <cmd>)
    audit      run/ingest cli-audit          [US-80 python -m]
    discover   find CLIs                      [US-77 two-stage filter]
    populate   upsert + diff + emit events    [A/B disposition; fail-closed; stale-guard]
    lifecycle  enabled/deprecated/removed,    [US-78/79 drift->deliberate
               health history, last-seen        reconcile, never auto-flip]

examples/jonas-fleet/
  config.toml  buckets, cli-audit path, portmgr port, broker list, all thresholds
               — reference consumer, NOT part of publishable core
```

Two concrete `DiscoverySource` impls live in `core/discovery/` (no orphan
`adapters/`). REST `/clis` and A2A `SendMessage` payloads both render from
`catalog/` — one source of truth, each carrying a `catalog_schema_version`.

Stack: Python 3.11+ / FastAPI / SQLModel / SQLite (portmgr skeleton cloned).
Port: portmgr-allocated, never hardcoded. Config via TOML.

### CliRecord (the discovery seam contract)
A `DiscoverySource` MUST emit per CLI: `slug` (opaque stable id), `bucket`,
`project`, `path`, `invocation`, `description`, `source_class` (opaque str the
engine does NOT interpret), `health_cmd`. Engine derives/owns: `health_status`,
`health_checked_at`, `enabled`, `a2a_invokable`, `source_run_id`, `last_seen_at`,
`updated_at`.

---

## 4. Data model (registry.db)

### cli
| Field | Notes |
|---|---|
| slug (PK) | opaque stable id; survives path moves |
| bucket, project, path | path is data, NOT identity |
| invocation | `python -m <module.path>` or bare-file (US-80) |
| description | one-line; used by describe-cli responses |
| source_class | opaque; engine never branches on it |
| health_cmd | command used by the prober |
| health_status | healthy / unhealthy / UNKNOWN / STALE |
| health_checked_at | last probe time; staleness surfaced in responses |
| enabled | operator lifecycle state |
| a2a_invokable | default false — written-false/unread in v1; reserved for phase-2 |
| source_run_id, last_seen_at | reconciliation primitives |
| updated_at | |

### subscriber
slug, callback_url (SSRF-validated), events (CSV), secret (HMAC), seq (monotonic
per-subscriber, assigned at delivery-enqueue), created_at, last_delivery_at,
failure_count (dead-letter at N=5; dead-letter does NOT roll back seq).

### delivery (append-only)
id (= event_id, in payload), subscriber_slug, event, schema_version, payload,
status, attempts, created_at.

---

## 5. Session lessons baked into core/ (default rules + regression tests)

1. **python -m invocation (US-CLIAUDIT-80).** rules.py detects package-resident
   CLIs (adjacent __init__.py / relative imports), derives the dotted module
   path by walking to the package root, records `python -m <module.path>`. Prober
   uses the same form. Prevents the 38-false-positive class.
2. **Two-stage discovery filter (US-CLIAUDIT-77).** AND filter (real arg-parsing
   call form AND not an if __name__ self-test / docstring match).
3. **Fail-closed state guard (US-CLIAUDIT-78/79).** populate/lifecycle fail CLOSED
   on missing deps, DB drift, OR stale/malformed source; surface drift for
   deliberate reconcile; never auto-flip lifecycle state.
4. **A/B disposition discipline.** populate classifies a vanished/broken CLI as
   genuinely-gone (remove) vs wrong-invocation (re-tag, keep) — never silently
   dropped.

---

## 6. A2A surface (v1.0-correct)

- **Self-card** at `GET /.well-known/agent-card.json`. v1.0 shape: `name`,
  `description`, `version`, `protocolVersion`, `supportedInterfaces[]` (each
  `url`/`protocolBinding`/`protocolVersion`, preferred-first), `capabilities`
  (`streaming:false`, `pushNotifications:false`, `extensions[]` declaring the
  webhook bus with a stable `uri` + `required:false`), `defaultInputModes`,
  `defaultOutputModes`, `securitySchemes` (`{"type":"http","scheme":"bearer"}`)
  + `security`, and a SMALL fixed `skills[]`: `search-cli-catalog`,
  `describe-cli`, `get-cli-health`, `list-buckets`. Health does NOT live on the
  public card. Card carries `version`/`ETag`; `Cache-Control` set.
- **Methods** (`POST /a2a`, JSON-RPC v1.0 PascalCase): `SendMessage`, `GetTask`,
  with declared input/output modes. A skill call returns catalog data in the
  response payload, NOT a managed-CLI execution. Version negotiation: `Major.Minor`
  compare per-interface (patch ignored).
- **Describe-only invariant.** No `SendMessage` path spawns a managed CLI;
  `a2a_invokable=false` CLIs (all, in v1) are never executed by network-facing
  code. Pinned by a spawn-spy negative test (§9).
- **Auth boundary.** Unauthenticated `SendMessage` returns skill metadata only;
  authenticated (bearer) returns full invocation strings. Public card never
  exposes the 250 invocation strings.
- **Webhook bus = declared non-A2A extension** (`capabilities.extensions[].uri`).
  `POST /subscribe` (NOT under `/a2a`) registers `callback_url` + `events` +
  `secret`. Payloads carry `schema_version` + `event_id` + per-subscriber `seq`;
  subscribers dedupe on `event_id`, detect reorder via `seq`. `notifier/`
  HMAC-signs a pinned canonical form, delivers at-least-once (backoff 2s base,
  60s cap), dead-letters at N=5. Callback URLs SSRF-validated.
- **Self-registration.** `announcer/` PUT-upserts (idempotent, keyed on card URL)
  to `[announce].brokers` on startup, fleet change, and heartbeat. Retries w/
  backoff; failure non-fatal; attempts persisted; degraded state in `GET /health`.

### Untrusted-input note (threat model)
Catalog free-text (`description`, `source_class`) originates from discovered CLIs
and is **untrusted**. It is returned as data, never as instruction; downstream
agents must treat it as inert. An adversarial golden fixture (description
containing "ignore previous instructions") asserts pass-through, not action.

---

## 7. Data flow

```
cli-audit (or filesystem scan)
   | discover() -> list[CliRecord]   [US-77 filter, US-80 invocation, freshness check]
   v
populate --upsert + diff--> registry.db
   |   stale/malformed source -> FAIL CLOSED, no removals (US-78)
   |   >=30% removal in one run -> circuit-breaker, operator confirm
   |                            | events: new_cli / removed_cli / health_flip
   |                            |   (+schema_version, event_id, seq)
   |                            v
   |                        notifier --HMAC POST--> subscribers (non-A2A bus)
   v
catalog/ (one source of truth) -> cardgen (small fixed skills)
   |-> GET /clis, GET /clis/{id}        (REST poll; catalog_schema_version)
   |-> GET /.well-known/agent-card.json (A2A discovery; ETag)
   |-> POST /a2a SendMessage            (A2A query -> catalog payload, describe-only)
   `-> announcer --> brokers (self-register: startup + change + heartbeat)

prober (periodic, bounded concurrency=8) --> run health_cmd, timeout 10s + SIGKILL
   --> healthy/unhealthy/UNKNOWN(timeout)/STALE(probe too old)
   --> emit health_flip once per real transition (debounced)
   --> loop heartbeat surfaced in GET /health
```

---

## 8. Error handling & safety

- Atomic writes (tempfile + Path.replace); no bare except Exception; no bare
  .json() after fetch — status-checked first.
- **Prober isolation:** per-probe timeout 10s, process-group SIGKILL on timeout,
  bounded concurrency (`probe_concurrency=8`), `max_probe_output_bytes=65536`; a
  hung probe -> `UNKNOWN`, never stalls the loop; loop heartbeat detects a wedged
  loop (all-STALE drift) and surfaces it in `GET /health`.
- **Stale-input guard:** reject malformed source JSON fail-closed; require source
  run timestamp + complete-run marker; refuse removals from input older than
  `staleness_ttl=3600s` or marked partial. `>=mass_removal_threshold=0.30`
  single-run removal trips a circuit breaker (operator confirm).
- **Outbound timeouts:** connect+read timeout on all notifier/announcer POSTs;
  `max_inflight_deliveries=16`.
- **Idempotency/order:** every event carries `schema_version` + `event_id` +
  per-subscriber `seq`.
- **SSRF:** callback URLs validated against a deny-list
  (localhost/link-local/metadata/private ranges) unless allowlisted.
- **Migrations:** atomic — a failed migration leaves the DB unmodified.
- Cross-platform: no hardcoded paths in core/; portalocker (not fcntl).

---

## 9. Testing strategy (pytest) — every behavior bound to a named test

Fixtures in `tests/fixtures/`: `golden_clis/` (labeled samples, incl. an
adversarial prompt-injection description), `cli_audit_sample.json`, vendored
`a2a_agent_card_v1.0.schema.json` (pinned to a tagged A2A release, derived from
a2a.proto), vendored `webhook_event_v1.schema.json`, `fake_consumer`,
`fake_broker` (up + timeout), `fake_subscriber` (200/500/slow). **Time is
injectable — no real sleeps; retry/backoff/timeout tests use a clock seam** so
CI is deterministic.

**Regression — one per session lesson:**
- `test_rules::test_package_resident_cli_gets_dotted_module` (US-80)
- `test_rules::test_two_stage_filter_rejects_selftest_and_docstring` (US-77)
- `test_populate::test_drift_surfaces_not_autoflips` (US-78/79)
- `test_populate::test_vanished_cli_retagged_not_dropped` (A/B)

**A2A contract:**
- `test_cardgen::test_card_validates_against_v1_0_schema` (+ negative: missing field)
- `test_cardgen::test_skills_are_catalog_ops_not_per_cli`
- `test_a2a::test_sendmessage_returns_catalog_not_execution`
- `test_a2a::test_invokable_false_never_spawns_subprocess` (spawn-spy == 0)
- `test_a2a::test_gettask_returns_task_status` (+ `test_gettask_unknown_id_returns_jsonrpc_error`)
- `test_a2a::test_unauth_sendmessage_omits_invocation_strings`
- `test_a2a::test_version_negotiation_accepts_patch_rev`
- `test_a2a::test_injected_prompt_in_description_returned_inert`

**Failure modes:**
- `test_prober::test_hanging_health_cmd_killed_after_timeout`
- `test_prober::test_no_duplicate_flip_on_unchanged_status`
- `test_prober::test_output_truncated_at_cap`
- `test_prober::test_bulkhead_caps_concurrent_probes`
- `test_prober::test_loop_stall_surfaces_in_health`
- `test_populate::test_stale_source_drives_no_removals`
- `test_populate::test_mass_removal_trips_circuit_breaker` (asserts the 0.30 default)
- `test_notifier::test_redelivery_carries_stable_event_id`
- `test_notifier::test_seq_gap_detected_on_redelivery`
- `test_notifier::test_dead_letters_after_5th_failure`
- `test_notifier::test_tampered_payload_fails_hmac_verify`
- `test_notifier::test_ssrf_callback_url_rejected`
- `test_notifier::test_payload_matches_pinned_event_schema`
- `test_announcer::test_broker_timeout_non_fatal`
- `test_announcer::test_reannounces_on_heartbeat_interval`
- `test_announcer::test_announces_on_fleet_change`
- `test_store::test_concurrent_write_serialized_via_portalocker`
- `test_store::test_failed_migration_leaves_db_unmodified`

**E2E:**
- `test_e2e::test_discover_to_a2a_query_roundtrip`

CI gate: pytest green + coverage floor on `core/`;
`test_cli_audit_source::test_parses_pinned_sample_schema` fails loudly on
upstream cli-audit format drift.

---

## 10. Reference adapter (examples/jonas-fleet/)

Not part of publishable core. `config.toml`: cli-audit bucket list, cli-audit
JSON path, portmgr-allocated port, probe interval (300s), probe timeout (10s),
dead-letter N (5), backoff (2s/60s), staleness TTL (3600s), mass-removal
threshold (0.30), `max_probe_output_bytes` (65536), `probe_concurrency` (8),
`max_inflight_deliveries` (16), broker list (http://127.0.0.1:9114 VPS-A2A
gateway, hermes). Demonstrates `cli_audit_source`; a stranger uses
`filesystem_source --scan`.

---

## 11. Open questions / deferred

- Exact portmgr port — assigned at implementation via portmgr.
- A2A protocol version pin: which tagged A2A release the vendored schema tracks —
  pick at implementation; `Major.Minor` compare, reject-unknown-major.
- Live execution (a2a_invokable) auth + arg-allowlisting — phase-2 spec.
