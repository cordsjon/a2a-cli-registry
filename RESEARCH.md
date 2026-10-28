<!-- AI-maintained, append-only -->

## R1 — Show HN: Yello. Let your agents chat with other people's agents — reject

**Artifact:** Show HN: Yello. Let your agents chat with other people's agents — https://news.ycombinator.com/item?id=49758895
**Question:** does it enhance a2a-cli-registry?
**What it does:** [inference] Reject for now: evidence is only a tagline ("connect your agent with other people's agents") with no protocol, stack, self-host, privacy or pricing details. Overlaps a2a-cli-registry and project_a2a_mesh_spike, which already cover agent-to-agent connectivity.
**Evidence:** stored snapshot SHA-256 47438cfe98c959bb4a4cd12102935f5e50d5eaf3b4316d1a0250df129afa3ebb; runtime capability [unmeasured].
**Verdict:** reject
**Justification:** [inference] Candidate claims cross-owner agent-to-agent chat (agents talking to other people's agents). The resolved project a2a-cli-registry and related project_a2a_mesh_spike already target agent-to-agent connectivity and discovery. The nearest registry match (main-7, ASES CLI for skill/agent registry) is only a lexical 'agents' hit and does not cover cross-owner messaging, so a narrow augment gap could exist for federated/cross-tenant agent messaging. However, the source gives no protocol (A2A, MCP, custom), no stack, no self-host option, no rights-management or data-privacy model (an HN commenter raises exactly this open question), and no interoperability story for heterogeneous agent frameworks. Without these, fit against the Python/FastAPI/SQLite stack and the existing a2a-cli-registry design cannot be assessed, and adopting an opaque hosted service for sensitive agent traffic costs more than the unverified gap is worth.
**Cost if adopted:** n/a
**Revisit-if:** —
**Ref:** gap:38 rev:05b9f601e8d34acfba2d83cce1646d03
source: gap 38
drafted-by: gap loop (claude-opus-5-5, from untrusted evidence)
