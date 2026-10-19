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


## Q3 — US-CLIREG-CAPMAP-01 — gate-resolution

**Question:** The 12 provenance='manual' capability rows (send_mail, 11 bf-*) have hand-written descriptions and description_provenance NULL, so the first live backfill write replaces all 12 with LLM text. Q2 (assumed) coupled the two guards in code; that contradicts the 07-03 plan ('each field's guard must be checked separately, never coupled', :1878) and the shipped test test_manual_capability_provenance_protected_independently_of_description, so Q2 is withdrawn. How should the 12 descriptions be treated?
**Options considered:** mark the 12 rows description_provenance='manual' in Task 5 Step 2, after the pre-write snapshot and before the writer / accept the overwrite (the sanity judge and the head -40 review cover quality) / couple the guards in code after all (reverses the 07-03 design)
**Chosen:** —
**Decided-by:** human
**Justification:** Found at Task 2 execution 2026-10-18: the July design keeps the guards independent on purpose and a shipped test pins it, so an agent cannot settle this by assumption. Marking is a 12-row data write on the live DB, which AC-05 reserves for the operator; it needs no code change and keeps the July design. Task 2 shipped without the coupling; Task 4 Step 4 projects with the shipped rule.
**Outcome:** escalated
**Ref:** docs/superpowers/plans/2026-07-03-capability-backfill.md:1878; tests/test_backfill_capabilities.py:153; docs/superpowers/plans/2026-10-18-capability-map-phase0.md Global Constraints
**Supersedes:** Q2 — superseded


## Q4 — US-CLIREG-CAPMAP-01 — gate-resolution

**Question:** The 12 provenance='manual' capability rows (send_mail, 11 bf-*) have hand-written descriptions and description_provenance NULL, so the first live backfill write replaces all 12 with LLM text. Q2 (assumed) coupled the two guards in code; that contradicts the 07-03 plan ('each field's guard must be checked separately, never coupled', :1878) and the shipped test test_manual_capability_provenance_protected_independently_of_description, so Q2 is withdrawn. How should the 12 descriptions be treated?
**Options considered:** mark the 12 rows description_provenance='manual' in Task 5 Step 2, after the pre-write snapshot and before the writer / accept the overwrite (the sanity judge and the head -40 review cover quality) / couple the guards in code after all (reverses the 07-03 design)
**Chosen:** mark the 12 rows description_provenance='manual' in Task 5 Step 2, after the pre-write snapshot and before the writer
**Decided-by:** human
**Justification:** Operator accepted the agent's stated recommendation (option 1) with /youdrive on 2026-10-18 at about 22:25. Keeps the 07-03 independent-guard design and the 12 hand-written descriptions; the write is one UPDATE on the live DB inside Task 5, after the rollback snapshot.
**Outcome:** applied
**Ref:** docs/superpowers/plans/2026-10-18-capability-map-phase0.md Task 5 Step 2
**Supersedes:** Q3 — resolved


## Q5 — US-CLIREG-CAPMAP-01 — deviation

**Question:** populate() reverts backfilled descriptions and capability rows on its next run; change populate although the design says the 07-03 plan is the design?
**Options considered:** extend populate's preserved provenance set to static/llm and keep llm descriptions / leave populate alone and re-run the backfill after every populate / accept the risk
**Chosen:** extend populate
**Decided-by:** agent
**Justification:** populate is not scheduled on this host today but one run would undo 612 descriptions; the feed's inference is what produced the path-shaped descriptions, so it is the weaker source for these rows. Trade-off: feed-side capability inference never refreshes a backfilled slug.
**Outcome:** assumed
**Ref:** core/populate.py, tests/test_populate.py, design section 5


## Q6 — US-CLIREG-CAPMAP-01 — gate-resolution

**Question:** Commit the reviewed backfill proposals to ~/.hermes/cli-registry.db? Dry run 2026-10-18 22:41 on snapshot ~/.local/state/a2a-cli-registry/registry-snapshot-20261018-2241.db: rows=612 projected_prose=553/612 kept_owned=0 fallback=297 sanity_fail_rate=0.0637 calibration_ok=true unknown_purpose=37; sha256 backfill_proposals.jsonl=e2aa9b55fd1c2d8e0c692447c4a5903d7e2c33c8c73fa442895aff4ff639a1cf sanity_report.jsonl=ca2f323067958dc13fef6d523ac15a132a44bfc60059cb136c91fc061bf81011
**Options considered:** commit from the reviewed file / tune and re-run / stop phase 0
**Chosen:** —
**Decided-by:** human
**Justification:** First live write of LLM-generated descriptions into the registry; design section 9 gates it on this report. Review: backfill_proposals.jsonl (head -40), sanity_report.jsonl ok:false rows, log at ~/.local/state/a2a-cli-registry/backfill-dryrun-20261018-2241.log. Later runs write unattended through the sanity gate.
**Outcome:** escalated
**Ref:** docs/superpowers/plans/2026-10-18-capability-map-phase0.md Task 4


## Q7 — US-CLIREG-CAPMAP-01 — gate-resolution

**Question:** Commit the reviewed backfill proposals to ~/.hermes/cli-registry.db? Dry run 2026-10-18 22:41 on snapshot ~/.local/state/a2a-cli-registry/registry-snapshot-20261018-2241.db: rows=612 projected_prose=553/612 kept_owned=0 fallback=297 sanity_fail_rate=0.0637 calibration_ok=true unknown_purpose=37; sha256 backfill_proposals.jsonl=e2aa9b55fd1c2d8e0c692447c4a5903d7e2c33c8c73fa442895aff4ff639a1cf sanity_report.jsonl=ca2f323067958dc13fef6d523ac15a132a44bfc60059cb136c91fc061bf81011
**Options considered:** commit from the reviewed file / tune and re-run / stop phase 0
**Chosen:** commit from the reviewed file
**Decided-by:** human
**Justification:** Resolves Q6.
**Outcome:** applied
**Ref:** 7282178 (at write time)
**Supersedes:** Q6 — resolved


## Q8 — US-CLIREG-CAPMAP-01 — deviation

**Question:** Task 5 Step 4 live search probe returned 0 (expected >=1): 'overview --query file:pdf' does not list generate_pdf/generate-pdf. The backfill writes coarse capability types (path 201, text 136, json 51 rows; only 8/614 rows carry file:<ext>), so a file:pdf vocab query cannot reach backfilled producers. The plan does not say whether Step 4 blocks Steps 5-6.
**Options considered:** flip the foundation on AC-02..AC-04 and record Step 4 as failed / hold FOUNDATIONS open until typed vocabulary lands
**Chosen:** flip the foundation on AC-02..AC-04 and record Step 4 as failed
**Decided-by:** agent
**Justification:** Plan self-review names AC-02..AC-04 as the foundation's done-when triple (all pass: 557/0/612); Step 3, not Step 4, is the step that blocks Steps 5-6. The foundation is 'real can-do descriptions', which landed. The 07-10 plan's AC-05 (file:pdf finds generate_pdf) is recorded as NOT met and carried to phase 1: the type vocabulary needs file:<ext> output, which is a regeneration, not a phase 0 write. Reversible: one FOUNDATIONS line.
**Outcome:** assumed
**Ref:** docs/superpowers/plans/2026-10-18-capability-map-phase0.md Task 5 Step 4
