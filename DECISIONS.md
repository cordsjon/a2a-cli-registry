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


## Q9 — US-CAPLOOP-04 plan review (Plan B, Codex-authored). Spec says the 37 enabled unknown-purpose rows have gone sources; live probe: 27 gone, 10 live tools (causa, invoice-fetcher, oc, nk, ...). — deviation

**Question:** How are the 10 placeholder rows whose source still exists resolved?
**Options considered:** a) disable them too; b) reviewed one-sentence descriptions from a committed JSON, written as manual; c) LLM regeneration run
**Chosen:** b
**Decided-by:** agent
**Justification:** Disabling hides working tools; an unreviewed LLM run is not authorized by Q7. A slug whose purpose cannot be read from source stays unresolved and blocks apply.
**Outcome:** assumed
**Ref:** docs/superpowers/plans/2026-10-20-caploop-registry-hygiene.md Task 5 Step 7b


## Q10 — Plan B Task 3 guards register_cli.py ON CONFLICT description assignment by cli.description_provenance. — tradeoff

**Question:** Which description owners does re-registration protect, and does an explicit --description override them?
**Options considered:** a) manual only; b) manual, static, llm — explicit --description does not override; c) add a --force flag
**Chosen:** b
**Decided-by:** agent
**Justification:** Matches discovery's PRESERVED_PROVENANCE policy in core/populate.py:14; no new override surface. Behavior change: --description on an owned row is now ignored silently (exit 0).
**Outcome:** assumed
**Ref:** docs/superpowers/plans/2026-10-20-caploop-registry-hygiene.md Task 3


## Q11 — Plan B Task 1 moves description_provenance from capability to cli; init_db migrates on open. — tradeoff

**Question:** How are multiple legacy capability markers collapsed onto cli, and when is the live DB backed up?
**Options considered:** a) first row wins; b) manual > llm > static > other, copied once on column creation; backup in Task 1 Step 0 before auto-migrating code lands; c) reject conflicts
**Chosen:** b
**Decided-by:** agent
**Justification:** Manual-first never loses curation; one-time copy stops stale child markers resurrecting cleared ownership; the first registry command after Task 1 migrates the live DB, so the backup must predate it.
**Outcome:** assumed
**Ref:** docs/superpowers/plans/2026-10-20-caploop-registry-hygiene.md Task 1, Decisions 3 and 10


## Q12 — US-CLIREG-MD2PDF-CATALOG-01/AC-02 — gate-resolution

**Question:** Which converter is registered so that file:md -> file:pdf becomes plannable?
**Options considered:** pandoc + weasyprint / install LaTeX for pandoc / skip the registration
**Chosen:** pandoc with --pdf-engine=weasyprint, wrapped as a registered CLI with ports file:md -> file:pdf.
**Decided-by:** human
**Justification:** Operator ruling 2026-10-30 in the unblock walk; both tools are installed and measured working, LaTeX would be a multi-GB install for a P3 story.
**Outcome:** applied
**Ref:** BACKLOG.md US-CLIREG-MD2PDF-CATALOG-01


## Q13 — US-CLIREG-QUERYGOAL-PRECISION-01/AC-02 — gate-resolution

**Question:** For query-style goals, does producer relevance filter and outrank confidence in plan_chain?
**Options considered:** relevance first and unmatched means no chain / relevance first but still guess / demote generic text and json producers / LLM selection
**Chosen:** When producer_terms are given, chains with no matching producer hop are dropped and relevance_rank sorts before min_confidence_rank; without terms the current order stands.
**Decided-by:** human
**Justification:** Operator ruling 2026-10-30 in the unblock walk. Measured: for [git, status] no candidate matches git, so a clean failure is the correct result; today relevance is advisory and never filters (core/planner/search.py:22-29, :222-246).
**Outcome:** applied
**Ref:** BACKLOG.md US-CLIREG-QUERYGOAL-PRECISION-01


## Q14 — US-CLIREG-MD2PDF-CATALOG-01/AC-02 — deviation

**Question:** Q12 ruled pandoc+weasyprint. Unsettled: how the entry reaches the live DB, and the wrapper's argv contract.
**Options considered:** fleet seed + populate (pdf-tools/funroadtrip pattern) / fleet seed + register_cli.py + manual-provenance capability row, no populate (bf-batch pattern) / register_cli.py only
**Chosen:** fleet-clis/md2pdf with seed/feed-entries.json + apply.sh that writes the feed entry, upserts the cli row via register_cli.py (lang python -> python_module + script_path, the only kind hermes-adapter dispatches) and upserts the capability row with provenance=manual; apply.sh does NOT run populate. Wrapper: md2pdf.py <in.md> [-o out.pdf], default <in>.pdf beside the input, atomic write, prints the path, pandoc exit code propagates.
**Decided-by:** agent
**Justification:** Measured 2026-10-30: populate() deletes rows absent from the feed; live DB 641 rows vs feed (2026-08-03) 479, 165 would go (134 manual-register incl. bf-batch), 25.7% is under the 30% breaker, so the sibling apply.sh scripts are a live hazard and this one must not repeat it. The manual-register + provenance=manual route is the one populate() preserves. Probe: chains planned 1 with allow=[].
**Outcome:** assumed
**Ref:** 62f70e8 (at write time)


## Q15 — US-CLIREG-QUERYGOAL-PRECISION-01/AC-02 implementation, session e24588bd 2026-10-30 — deviation

**Question:** Q13 records the ruling as 'when producer_terms are given' while the operator's question said 'for query-style requests'; and under the drop rule, what happens to a compound chain whose term matches only the action terminal?
**Options considered:** gate on producer_terms presence, as Q13 records / gate on generic goal_outputs (text,json) only / drop terminal-only matches / keep terminal-only matches
**Chosen:** Gate on producer_terms presence exactly as Q13 records, for every goal shape; a term matching only the action terminal is not a producer match, so that compound chain is dropped too (spec 2.2 producer-hop rule kept).
**Decided-by:** agent
**Justification:** Q13's Chosen line is the operator's recorded wording and names the condition the code can test; 'query-style' is not a planner input, and the adapter emits producer_terms as artifact nouns regardless of goal shape, so the generic-output reading would silently leave transform goals guessing. Terminal-only match: the §2.2 producer-hop rule already says the terminal blob must not fake artifact relevance; dropping is the consistent consequence. Tests flipped: test_unmatched_producer_terms_yield_no_chain, test_action_terminal_match_does_not_count_as_producer_match, test_plan_cli_chain_orders_by_producer_terms_and_serializes_rank.
**Outcome:** assumed
**Ref:** BACKLOG.md US-CLIREG-QUERYGOAL-PRECISION-01; DECISIONS.md Q13


## Q16 — US-CLIREG-QUERYGOAL-PRECISION-01/AC-02 implementation, session e24588bd 2026-10-30 — deviation

**Question:** Q13 says a chain is dropped when no producer hop matches ANY term, but its measured basis (terms [git, status], bf-status matches 'status', nothing matches 'git') declares a clean failure the only right answer. Under any-term semantics bf-status survives (live probe 2026-10-30: 2 chains, bf-status chain[0]). Per chain or per term?
**Options considered:** any-term: literal Q13 text, repro stays broken / every-term: each term matched by some producer hop, different hops may cover different terms / same-hop: one hop must match all terms
**Chosen:** every-term: a chain survives only if each cleaned producer_term is matched by at least one producer hop; hops may split the terms.
**Decided-by:** agent
**Justification:** The ruling's stated outcome for the measured case is the authority over its mechanism wording; any-term fails AC-03 on the very repro that opened the story. Same-hop was rejected as over-strict for 2-hop chains where the artifact noun and the format noun live on different CLIs. Cost: one spurious LLM-emitted term now yields a clean failure instead of a guess, which is the direction the ruling chose. Reversible in one line (search.py producer-match predicate). Operator to confirm or override.
**Outcome:** assumed
**Ref:** DECISIONS.md Q13, Q15; tests/test_planner.py test_every_producer_term_must_be_covered


## Q17 — US-CLIREG-QUERYGOAL-PRECISION-01/AC-02 implementation, session e24588bd 2026-10-30 — deviation

**Question:** Q13 records the ruling as 'when producer_terms are given' while the operator's question said 'for query-style requests'; and under the drop rule, what happens to a compound chain whose term matches only the action terminal?
**Options considered:** gate on producer_terms presence, as Q13 records / gate on generic goal_outputs (text,json) only / drop terminal-only matches / keep terminal-only matches
**Chosen:** Confirmed: gate on producer_terms presence for every goal shape; a term matching only the action terminal is not a producer match.
**Decided-by:** human
**Justification:** Operator ruling 2026-10-31 (/unblock walk): confirmed as-is. Clean failure over guessing is the wanted behaviour; the catalog gap behind the five failing shell-style goals is closed by a separate story (US-CLIREG-SHELLUTIL-01: git-ro + fs-read guarded wrappers), not by loosening the planner.
**Outcome:** applied
**Ref:** c7e43cb (at write time)
**Supersedes:** Q15 — resolved


## Q18 — US-CLIREG-QUERYGOAL-PRECISION-01/AC-02 implementation, session e24588bd 2026-10-30 — deviation

**Question:** Q13 says a chain is dropped when no producer hop matches ANY term, but its measured basis (terms [git, status], bf-status matches 'status', nothing matches 'git') declares a clean failure the only right answer. Under any-term semantics bf-status survives (live probe 2026-10-30: 2 chains, bf-status chain[0]). Per chain or per term?
**Options considered:** any-term: literal Q13 text, repro stays broken / every-term: each term matched by some producer hop, different hops may cover different terms / same-hop: one hop must match all terms
**Chosen:** Confirmed every-term: a chain survives only if each cleaned producer_term is matched by at least one producer hop; hops may split the terms. Any-term stays rejected.
**Decided-by:** human
**Justification:** Operator ruling 2026-10-31 (/unblock walk): confirmed as-is. Clean failure over guessing is the wanted behaviour; the catalog gap behind the five failing shell-style goals is closed by a separate story (US-CLIREG-SHELLUTIL-01: git-ro + fs-read guarded wrappers), not by loosening the planner.
**Outcome:** applied
**Ref:** c7e43cb (at write time)
**Supersedes:** Q16 — resolved


## Q19 — US-CLIREG-PROBE-VENV-01 / resume 2026-10-31 — irreversible-action

**Question:** a2a-cli-registry 'probe --dry-run' rewrote the live registry (00:13 CET): the parser accepts --dry-run globally but the probe branch never read it. 611 rows re-probed with the global interpreter; unknown 89 and stale 13 became unhealthy, all check timestamps overwritten. What now?
**Options considered:** restore from an old .bak / leave and fix the flag / fix the flag, re-probe with the venv-aware adapter, keep a backup from now on
**Chosen:** fix the flag, re-probe with the venv-aware adapter, keep a backup
**Decided-by:** agent
**Justification:** No backup of tonight's pre-state existed (newest .bak 2026-09-19), so restore was impossible; the overwritten verdicts came from the same broken probe and were replaced within 20 min by the venv-aware probe (healthy 299 -> 431, unhealthy 313 -> 180). Backup taken before the real re-probe: cli-registry.db.bak-20261031-pre-venvprobe. Fix in 5921013 with a CLI-level test that the DB stays unchanged.
**Outcome:** applied
**Ref:** a2a-cli-registry 5921013; tests/test_cli.py::test_probe_dry_run_writes_nothing


## Q20 — US-CLIREG-PROBE-VENV-01 / resume 2026-10-31 — tradeoff

**Question:** Operator asked to task Hermes with 'fixing the 213 unhealthy rows'. Measured: the probe ran every script with the global pyenv python; 138 of 281 existing-path Python rows pass with their project venv; 28 paths are gone; the rest need per-project triage. Who does what?
**Options considered:** Claude fixes probe + re-probes, Hermes triages the residual via one-shot cron / Hermes does all via cron / Claude does all / file only
**Chosen:** Claude fixes probe + re-probes, Hermes triages the residual via one-shot cron
**Decided-by:** human
**Justification:** Operator ruling 2026-10-31 00:2x CET. The probe fix is a deterministic code change with tests (token-frugality); the residual triage of ~150 scripts across projects is agent work and exercises Hermes on a CLI-heavy task. Hermes runs under hermes cron because cron_mode=deny fails closed on dangerous commands, whereas a non-interactive 'hermes chat -q' auto-approves them (tools/approval.py, historical fail-open default). Hermes writes a report, no code and no DB writes.
**Outcome:** applied
**Ref:** ~/.hermes/reports/cli-registry-unhealthy-2026-10-31.json; BACKLOG US-CLIREG-SHELLUTIL-01 (sliver of the same gap)


## Q21 — US-CLIREG-HERMES-DISCOVERY-01/unhealthy-fix — deviation

**Question:** Handover P3 said probe .sh rows with bash <path> --help. All 8 .sh rows have no help branch, so the flag is ignored and the script does its work (sync-global-*.sh, log-truncate.sh). Follow the plan?
**Options considered:** bash <path> --help as planned / probe only with a help branch or exec passthrough, else unknown
**Chosen:** Probe a shell script only if it has a help branch or an exec "$@" passthrough; otherwise health_cmd is empty and the row reads unknown or stale.
**Decided-by:** agent
**Justification:** Reading the 12 scripts statically showed the plan would execute real work on every sweep. An unprobed row is honest; an executed sync is not recoverable.
**Outcome:** applied
**Ref:** e95b9c1


## Q22 — US-CLIREG-HERMES-DISCOVERY-01/unhealthy-fix — deviation

**Question:** Handover P3 said add a [probe] fallback_interpreter pointing at the governance venv for scripts with no project venv (64 rows). Build it?
**Options considered:** build and enable as planned / build but leave unset / do not build
**Chosen:** Not built. Rows with no venv stay unhealthy when an import fails.
**Decided-by:** agent
**Justification:** Green must predict a launch. No launcher uses that venv: hermes-adapter compose_command runs python -m <slug>, and launch_spec carries no interpreter. Green from a foreign venv would tell Hermes a CLI works when its launch fails. Cost: about 25 rows stay red that the plan would have turned green. Revisit once launch_spec carries the interpreter (backlog story).
**Outcome:** assumed
**Ref:** e95b9c1; ~/.hermes/reports/cli-registry-unhealthy-residual-2026-10-31.json


## Q23 — US-CLIREG-HERMES-DISCOVERY-01/unhealthy-fix — tradeoff

**Question:** Handover P5 left open where not_standalone is set so populate does not overwrite it: feed flag or protected-path list. Also, how to treat healthy rows that classify no_parser, which every sweep has been executing?
**Options considered:** feed flag / config path list / classify statically in the prober
**Chosen:** The prober runs the existing AST classifier before executing. A no_parser script is never run: healthy keeps its status and timestamp, anything else becomes not_standalone. A subapp is only reclassified when not healthy.
**Decided-by:** agent
**Justification:** bridge/audit_to_registry.py already uses this classifier at feed build, so a refreshed feed agrees, and the prober re-derives whatever populate resets. Keeps the never-demote guard from scripts/reeval_not_standalone.py. Cost: 34 healthy rows are no longer re-verified, and their status ages.
**Outcome:** assumed
**Ref:** e95b9c1


## Q24 — US-CLIREG-HERMES-DISCOVERY-01/AC-05 — deviation

**Question:** Handover P4 assumed the 28 dead rows leave through populate. Live populate from demo/cli-audit/latest.json would also delete 6 real rows such as spec_hierarchy_onwrite. How to close AC-05?
**Options considered:** run populate / hand-edit the feed / disable with provenance, drop at next populate
**Chosen:** scripts/disable_missing_path_rows.py disables them with fixed_by provenance (dry-run first, own 30 percent limit, backup). populate gains drop_missing_paths so the next feed run removes them. search_clis and the planner now honour enabled.
**Decided-by:** agent
**Justification:** AC-05 names disabling with provenance. Search and the planner ignored enabled, so disabling alone would not have stopped Hermes being offered dead rows. Side effect: the 25 already-disabled rows also leave search results. Registry populate stays unrun until the feed is refreshed.
**Outcome:** assumed
**Ref:** 2c247e9, e95b9c1


## Q25 — US-CLIREG-LAUNCH-01 — tradeoff

**Question:** AC-01 says launch_spec carries the interpreter and PYTHONPATH. Which fields, given that 3 healthy rows are package __main__ files and 10 are shell or extensionless, where interpreter + script_path is the wrong command?
**Options considered:** interpreter field, consumer assembles / argv and env fields from the invocation the probe runs
**Chosen:** argv and env, built from the same _invocation as health_cmd. argv[0] is the project interpreter on .py rows.
**Decided-by:** agent
**Justification:** Green must predict a launch; one code path means they cannot drift. Cost: no separate interpreter field to query, consumers read argv[0].
**Outcome:** assumed
**Ref:** 8f55142


## Q26 — US-CLIREG-LAUNCH-01 — deviation

**Question:** The story and handover name compose_command as the launch gap. hermes_adapter/tools/cli_registry.py _resolve_command builds its own python3 <script_path> for run_cli. Change it too?
**Options considered:** compose_command only, as written / both launchers
**Chosen:** Both share recorded_invocation. A spec with argv also skips the python_module kind gate in _resolve_command.
**Decided-by:** agent
**Justification:** The story goal is that a healthy row runs when Hermes picks it, and run_cli is the path that picks. Specs with no argv keep their old forms.
**Outcome:** applied
**Ref:** hermes-adapter b139d1a


## Q27 — US-CLIREG-LAUNCH-01 — deviation

**Question:** Q23 says parser-less scripts never run, but classify_standalone returned standalone for no guard and no parser, so every sweep executed 11 live rows (eventlog, core_api, ics_*). Close it?
**Options considered:** leave / classify as no_parser
**Chosen:** Classify as no_parser. Those rows keep status and timestamp and are not executed.
**Decided-by:** agent
**Justification:** Restores the property Q23 claims. Cost: skipped healthy rows rose from 34 to 45, none re-verified. A guardless __main__.py that delegates its parser would stop being probed; none exists today (fails safe).
**Outcome:** assumed
**Ref:** 8f55142


## Q28 — US-CLIREG-LAUNCH-01/AC-04 — gate-resolution

**Question:** AC-04: decide the no-venv rows. Measured 105 on bare python, not the 64 in the story (64 is the healthy subset): 17 PEP 723, 88 plain.
**Options considered:** fallback interpreter / uv run --script / uv run --offline --script for PEP 723, nothing for plain
**Chosen:** PEP 723 rows use uv run --offline --script. Plain rows stay on bare python; no fallback interpreter (Q22 stands).
**Decided-by:** agent
**Justification:** All 15 unhealthy PEP 723 rows are unpinned, q3_tts wants mlx-audio==0.3.0rc1, and an unattended sweep must not fetch them. Offline, green means already cached. Re-probe: 4 of the 15 turned green, unhealthy 81 to 78 after other movement, uv cache unchanged at 7001312 kB. Cost: 11 stay red until an operator warms them with uv sync --script. A fallback venv would be green for reasons unrelated to the script, even with launch_spec able to carry it.
**Outcome:** assumed
**Ref:** c63ac3b


## Q29 — US-CLIREG-LAUNCH-01/AC-03 — deviation

**Question:** AC-03 asks for launches through the playbook route with --help, but the route has no argv binding and a real step would run each CLI with no arguments. How to measure?
**Options considered:** POST the route with temporary playbooks / call the route step seam _run_step with compose_command + --help
**Chosen:** The _run_step seam against the live gateway, scored on an EXIT=0 marker. Sample excludes no-parser rows.
**Decided-by:** agent
**Justification:** Same delegation path without the side effects of argument-less runs. Gateway status alone cannot score it: it reports success for exit 1. The route code above the seam was checked separately by resolving playbooks over live MCP, running none.
**Outcome:** applied
**Ref:** c63ac3b (at write time)


## Q30 — US-CLIREG-LAUNCH-01 — gate-resolution

**Question:** Hermes tirith holds PYTHONPATH + interpreter as interpreter_hijack_env, and the adapter cannot approve. 19 of 372 sampled healthy rows need PYTHONPATH to import. Allowlist the rule for registry-authored launches, or leave those rows failing on import (or change the projects so they need no PYTHONPATH)?
**Options considered:** allowlist the rule / leave them failing on import / install those projects into their venvs
**Chosen:** —
**Decided-by:** agent
**Justification:** It relaxes a security control on the path Hermes uses to run commands, which is the operator decision, not an agent default. Meanwhile launchers send argv only (fails safe, honest ImportError). Row list: ~/.hermes/reports/cli-registry-launch-needs-pythonpath-2026-10-31.json.
**Outcome:** escalated
**Ref:** hermes-adapter 96cec05


## Q31 — US-CLIREG-LAUNCH-01 — tradeoff

**Question:** The classifier decides what a sweep may execute, and it read m.group(1), Tk .command() and any sys.argv read as a CLI parser. Sweeps ran batch scripts for real: heise_login, apply_body_fixes, task_reconciler, inject-theme. An earlier revision of bridge/test_standalone.py called categorize_ai standalone on purpose because it reads --dry-run. Tighten, given installing deps would arm more of them?
**Options considered:** tighten / leave and rely on import crashes / per-row denylist
**Chosen:** Tighten: group/command count only as decorators; a hand-rolled sys.argv script counts only if it names --help or -h.
**Decided-by:** agent
**Justification:** Probing executes the file, so standalone must mean it answers --help, not that it takes arguments. 83 rows stop executing (21 regex/Tk false positives, 62 sys.argv). Cost: healthy ones keep a status nothing re-verifies, unhealthy ones become not_standalone, and a real CLI that handles help some other way goes unprobed. A sweep fell from about 12 min to about 1.5 min and rewrote nothing.
**Outcome:** assumed
**Ref:** a2a-cli-registry d255054


## Q32 — US-CLIREG-LAUNCH-01 — gate-resolution

**Question:** Hermes tirith holds PYTHONPATH + interpreter as interpreter_hijack_env, and the adapter cannot approve. 19 of 372 sampled healthy rows need PYTHONPATH to import. Allowlist the rule for registry-authored launches, or leave those rows failing on import (or change the projects so they need no PYTHONPATH)?
**Options considered:** allowlist the rule / leave them failing on import / install those projects into their venvs
**Chosen:** Install those projects into their venvs. No allowlist; tirith is unchanged.
**Decided-by:** human
**Justification:** Operator, 2026-10-31: 'install all missing depts or path'. Reading it as this option is the agent's interpretation. Done with a .pth carrying the row's recorded project root in each venv, which is what an editable install writes and leaves tracked files alone; governance gets symlinks for morning_brief and ytx only, because scripts/ is too wide. Launchers still send no PYTHONPATH. Lost if a venv is rebuilt; a re-probe would not catch that, because the probe still sets PYTHONPATH.
**Outcome:** applied
**Ref:** ~/.hermes/reports/cli-registry-deps-install-2026-10-31.json
**Supersedes:** Q30 — resolved


## Q33 — US-CLIREG-LAUNCH-01/AC-04 — gate-resolution

**Question:** Q28 kept plain no-venv rows on bare python and left PEP 723 caches cold pending a decision. The operator now asks for all missing deps. How, without capturing neighbouring rows or touching live venvs?
**Options considered:** new nested venvs at blessed pins / install into the bare python / add to existing project venvs
**Chosen:** 17 new nested venvs on uv-managed 3.13 at deps-registry blessed pins, as deep as each row allows; existing venvs get no third-party packages; 10 PEP 723 scripts warmed with uv sync --script.
**Decided-by:** human
**Justification:** project_interpreter walks upward, so a venv high in a tree captures every row below it, and PEP 723 rows would flip off uv. Consigliere's venv serves live processes and uv sync would prune additions, so gmaps_scraper and mint_dev_token got their own. q3_tts keeps its own mlx-audio==0.3.0rc1 pin, against the blessed 0.6.3: the script's metadata wins, and it was not edited.
**Outcome:** applied
**Ref:** ~/.hermes/reports/cli-registry-deps-install-2026-10-31.json
**Supersedes:** Q28 — superseded


## Q34 — CLIREG-UNHEALTHY-ROWS-2026-10-31 — tradeoff

**Question:** Three calls while clearing the 7 unhealthy rows: mistral_ocr pin or code fix, publish-bundle status, and how to re-probe with a job running on Consigliere
**Options considered:** pin mistralai below 2 / fix imports for blessed 3.6.0 ; fix the script / mark it not_standalone ; full sweep / named rows only
**Chosen:** Fix imports for 3.6.0 as a local unpushed commit on the simonw/tools clone; mark coaching-publish-bundle not_standalone; re-probe named rows through the prober functions
**Decided-by:** agent
**Justification:** 3.6.0 is the blessed pin, but a real OCR call is unverified and the clone now diverges from upstream by one commit. publish-bundle uploads to the live site when run bare and has no --help, so marking it means no probe touches it. A sweep would execute --help on Consigliere rows during the job.
**Outcome:** assumed
**Ref:** 4b041a3 (at write time)
