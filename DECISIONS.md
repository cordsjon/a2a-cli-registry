<!-- AI-maintained, append-only -->

## Q1 — diar1/seed — deviation

**Question:** The 75_Coaching handover of 2026-10-12 12:17 carried the item "verify that `populate` is upsert-only; if so, run `fleet-clis/diar1/seed/apply.sh` and commit the vocabulary change". `populate` is not upsert-only. What happens to the item?
**Options considered:** run `apply.sh` against the live powerbook64 config (`~/.local/share/powerbook64/cli-registry/`) / run it against the tracked `demo/config.toml` with `populate` pointed at a scratch DB and commit only the vocabulary change / carry the item a sixth session.
**Chosen:** Demo config plus `REGISTRY_DB=<scratch>`: `dir:engagement` registered in `demo/config.toml` (016c240); the seed scripts' fresh-checkout failure (mkstemp into the absent, gitignored `demo/cli-audit/`) fixed in the diar1, funroadtrip and pdf-tools clones (786c740); the live-registry half filed as automation debt (`seed-revert-on-sync`, project 00_Governance) against `bootstrap/macos/powerbook64-dagu/scripts/cli-registry-sync.py`.
**Decided-by:** agent
**Justification:** `core/populate.py` removes every CLI absent from the feed, fail-closed only at `[thresholds].mass_removal` (0.90 live, 0.30 demo). On powerbook64 the Dagu DAG `cli-registry-watchdog` (every 10 min) runs `cli-registry-sync.py`, which rewrites the feed from discovery and hard-codes the vocabulary in `write_config()`; the live feed (run `20261012T102044Z`, 48 CLIs) holds no funroadtrip, pdf-tools or `diar1-<verb>` slug, so a seed applied there is gone at the next tick and the gap is the sync script's, not this item's. The scratch DB keeps `DEFAULT_DB` (`~/.hermes/cli-registry.db`, the Mac mini's live registry under that path) untouched: tenet 4, do no harm.
**Outcome:** assumed
**Ref:** a2a-cli-registry 016c240, 786c740; `~/.local/state/automation-debt/pending.jsonl` 2026-10-12 `seed-revert-on-sync`; 75_Coaching DECISIONS Q49 (the `apply.sh` call this entry revises)


## Q2 — US-CLIREG-CAPMAP-01 — tradeoff

**Question:** The 12 provenance='manual' capability rows (send_mail, 11 bf-*) carry hand-written descriptions but description_provenance IS NULL, so the shipped write_commit would overwrite them with LLM text. Treat a manual capability row as owning its CLI's description while the description marker is NULL?
**Options considered:** yes: writer and populate keep the description / mark the 12 rows description_provenance='manual' in the live DB first / accept the overwrite
**Chosen:** yes: writer and populate keep the description
**Decided-by:** agent
**Justification:** Found in the post-panel round 2 triage (2026-10-18): all 12 descriptions are operator prose. A live-DB marker write before the gate would break AC-05; a one-clause rule in write_commit and populate needs no data change and is pinned by one test each. Trade-off: a manual row's description can no longer be refreshed by the backfill; the operator edits it by hand or clears provenance.
**Outcome:** assumed
**Ref:** docs/superpowers/plans/2026-10-18-capability-map-phase0.md Global Constraints, Task 2, Task 3; tools/backfill_capabilities.py:290
