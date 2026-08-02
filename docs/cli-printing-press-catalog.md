# cli-printing-press catalog — on-demand CLI generation source

**Source repo:** `~/projects/cli-printing-press` (fork of [`mvanhorn/cli-printing-press`](https://github.com/mvanhorn/cli-printing-press), Apache-2.0, actively maintained upstream)
**Relationship to this registry:** producer, not a fleet member. Nothing here is
wired into `registry.db` / `tools.json` — these are 27 unreached API specs a
generator can turn into a real CLI **on demand**. Only after a spec is actually
generated, built, and verified should it move into `fleet-clis/<name>/`
following the `pdf-tools/` pattern (own README, own design spec, own tests).

## Why this exists

`cli-printing-press` reads an API's OpenAPI spec (or reverse-engineers one via
browser-sniffing for APIs with no public spec) and prints a token-efficient Go
CLI + a Claude Code skill + an MCP server for it. It solves the "agent has to
re-learn an API from docs every session" problem that this registry solves for
*local* tools — the two are complementary, not overlapping: this registry
catalogs and health-tracks what's already installed; cli-printing-press is
how you get a new one onto the machine in the first place.

## Generate a CLI from the catalog

```bash
cd ~/projects/cli-printing-press
go install github.com/mvanhorn/cli-printing-press/v4/cmd/cli-printing-press@latest
cli-printing-press install <name>   # e.g. stripe, github, twilio
```

Verify with `cli-printing-press --version`; auth issues → `cli-printing-press auth doctor`.
After a spec is generated and the resulting CLI is verified working, register
it in `fleet-clis/` and this registry's `tools.json` like any other fleet tool.

## Available specs (27, as of 2026-08-02)

| Name | Category | Tier | Description |
|---|---|---|---|
| asana | project-management | official | Work management and project tracking API |
| digitalocean | cloud | official | Cloud infrastructure and developer platform API |
| discord | social-and-messaging | official | Chat and community platform API |
| elevenlabs | ai | official | Generate, transform, transcribe, dub, and manage AI audio, voices, music, and conversational agents |
| front | social-and-messaging | official | Customer communication platform API |
| github | developer-tools | official | Software development platform API |
| google-cloud-run | cloud | community | Cloud Run Admin API — serverless container services, revisions, jobs, executions |
| google-flights | travel | community | Flight search via reverse-engineered wrappers (no public API) |
| hubspot | sales-and-crm | official | CRM contacts API |
| itglue | productivity | official | IT Glue JSON:API — orgs, contacts, passwords, configs, docs; MSP automation write endpoints |
| jira | project-management | official | Issue tracking and project management API for Jira Cloud |
| kayak | other | community | Flight/hotel/car aggregator — scraping embedded JSON, no maintained wrappers |
| launchdarkly | developer-tools | community | Feature flag management — flags, environments, segments, experiments, audit logs |
| mercury | payments | official | Business banking API — accounts, transactions, payments, cards, invoices, treasury, webhooks |
| openrouteservice | maps | community | Routing, geocoding, matrix, isochrones, VRP optimization on OSM data |
| petstore | example | official | Canonical OpenAPI example |
| pipedrive | sales-and-crm | official | CRM for sales teams — deals, contacts, pipelines, activities, orgs |
| plaid | payments | community | Banking API — account linking, transactions, identity verification, income |
| postman-explore | developer-tools | community | Public API network directory |
| producthunt | marketing | community | Find/monitor/export Product Hunt launches — no official API required |
| quo | social-and-messaging | community | Business phone system (formerly OpenPhone) — contacts, SMS, call transcripts, inbox |
| sentry | monitoring | community | Error tracking and performance monitoring — projects, issues, events, releases |
| stripe | payments | official | Payment processing and financial infrastructure API (~500 endpoints, generator truncates) |
| stytch | auth | official | Authentication and user management API |
| supercut | media-and-entertainment | official | AI video recording/clipping — recordings, stacks, transcripts, frames, comments |
| telegram | social-and-messaging | community | Telegram Bot API — messages, chats, webhooks, stickers |
| twilio | social-and-messaging | official | Communication APIs — SMS, voice, messaging |

## Portfolio relevance (spot-check before generating)

Likely near-term candidates given the active project portfolio: **stripe**
(PosterEngine payments), **github** (repo automation across the fleet),
**twilio**/**telegram** (Hermes notification channels beyond ntfy), **sentry**
(error tracking — currently unmeasured per multiple `about.md` SLO blocks).
Not a commitment to generate any of these — just where the catalog and actual
need are most likely to intersect.
