# a2a-cli-registry — BACKLOG

## Critical Path

## Ideation

### US-CLIREG-PIPELINE-CLI-01: Expose the discover→probe→capture→remediate pipeline as thin CLI subcommands

> Origin: Automation debt analysis (2026-07-20) — 3 pending.jsonl entries (2026-06-25 populate→probe→capture→extract→set-health run-by-hand; 2026-06-25 audit-md→json inline transform; 2026-06-26 remediate-run.sh ran `python3 -c 'from core.cli import main'` 4×) all share one root cause: the registry's real pipeline logic lives in internal modules (core/populate.py, core/prober/prober.py, core/discovery/, core/remediation/, core/capability/) with no thin CLI wrappers, so each run is hand-assembled inline Python instead of one reproducible command.

**As a** maintainer running the registry discover/probe/remediate pipeline,
**I want** first-class `a2a-cli-registry` subcommands that drive populate → probe → capture-help → extract-descriptions → set-health and a remediate wrapper (backup-DB → dry-run → apply), with relative→absolute path resolution done natively,
**so that** the full pipeline stops being re-implemented as inline `python3 -c`/heredoc scripts every session and is reproducible from one invocation.

**Acceptance Criteria:**
- [ ] AC-01: A `discover` (or equivalent) subcommand sequences populate → probe → capture-help-for-capability → extract-descriptions → set-health against a given registry DB, resolving relative CLI paths to absolute internally
- [ ] AC-02: A `remediate` wrapper subcommand copies/backs-up the DB, runs a dry-run, then applies — replacing the 4× manual `python3 -c 'from core.cli import main; main([...])'` invocations and PATH setup
- [ ] AC-03: The all-clis.md wiki table (00_Governance/wiki/export_md/cli-tools/all-clis.md) is ingested natively (subcommand or scripts/audit_md_to_json.py) instead of inline transform code repeated per session
- [ ] AC-04: Test: running the discover subcommand against demo/registry.db reproduces the populate→…→set-health result that the inline scripts produced, and remediate dry-run leaves the DB unchanged

**Size:** M · **Tags:** `[a2a-cli-registry]` `[pipeline]` `[cli]` `[automation-debt]`

### US-CLIREG-INSPECT-CLI-01: Read-only registry-inspect / plan-probe CLI for schema, coverage, and reachability recon

> Origin: Automation debt analysis (2026-07-20) — 2 pending.jsonl entries (2026-07-03 repeated `python3 - <<PY` blocks profiling schema/tag/type coverage + path resolution during design recon; 2026-07-12 repeated `python3 -c` probes against ~/.hermes/cli-registry.db checking plan_chain/plan_cli_chain slug reachability + _hop_excluded during VOCAB-01 grounding, re-run 4+ times and independently re-run by Codex). Root cause: no exposed read-only inspection surface, so every recon/grounding check is hand-rolled and non-reproducible.

**As a** developer or reviewer doing design recon and spec grounding,
**I want** a read-only `registry-inspect` command (coverage stats, schema-vs-model diff, path-resolution check) and a `plan-probe` command (`--slug send_mail --goal-inputs text --goal-outputs text [--allow-side-effects …]` printing presence + position + hop-exclusion),
**so that** grounding and coverage checks are one reproducible command that both I and Codex can re-run identically, instead of divergent ad-hoc heredocs against whichever registry DB.

**Acceptance Criteria:**
- [ ] AC-01: `registry-inspect` prints schema/tag-coverage/type-coverage/path-resolution stats for an explicitly-named DB path (help text names the two DBs — a2a-cli-registry/registry.db vs ~/.hermes/cli-registry.db — to prevent wrong-DB recon)
- [ ] AC-02: `plan-probe --slug <s> --goal-inputs <t> --goal-outputs <t> [--allow-side-effects …]` prints the slug's presence, chain position, and _hop_excluded decision via plan_chain/plan_cli_chain
- [ ] AC-03: Both commands are strictly read-only (no writes to the registry DB)
- [ ] AC-04: Test: `plan-probe` reproduces the VOCAB-01 grounding result (a known slug's presence/position) that the inline probes returned

**Size:** M · **Tags:** `[a2a-cli-registry]` `[cli]` `[read-only]` `[automation-debt]`

### US-CLIREG-GOLDEN-AUDIT-CLI-01: golden-audit CLI to flag false-positive trigger leaks in labeled ground-truth

> Origin: Automation debt analysis (2026-07-20) — 1 pending.jsonl entry (2026-06-22): repeated `python3 -c` to load a labeled golden/ground-truth JSON and scan negative examples for positive trigger keywords (false-positive trap check). No exposed command for this recurring check.

**As a** maintainer validating trigger/keyword classifiers against a labeled set,
**I want** a `golden-audit <ground_truth.json> --triggers …` CLI that scans the negative examples for positive trigger keywords and reports leaking negatives,
**so that** false-positive trap checks are one reproducible command instead of an inline script rewritten each time.

**Acceptance Criteria:**
- [ ] AC-01: CLI loads a labeled ground-truth JSON and a trigger set, then reports negatives that contain positive trigger keywords
- [ ] AC-02: Exit status / output distinguishes "clean" from "leaks found" so it can gate in CI
- [ ] AC-03: Test: run against a fixture with a known planted leak and confirm it is reported; a clean fixture reports zero leaks

**Size:** S · **Tags:** `[a2a-cli-registry]` `[cli]` `[validation]` `[automation-debt]`

### US-CLIREG-CODEX-SPEC-REVIEW-SKILL-01: codex-spec-review skill — one-invocation codex-exec spec grounding

> Origin: Automation debt analysis (2026-07-20) — 1 pending.jsonl Skill-Missing entry (2026-07-12): the codex-exec spec-grounding-review cycle was run 3× in one session with the same hand-assembled scaffold each pass — write prompt file, background `codex exec --skip-git-repo-check … </dev/null`, poll a `.done` sentinel via Monitor, read `.out`, fold VERIFIED/REFUTED findings back into the spec. No skill wraps this; `sh-spec-review` is a separate spec-panel skill, not the codex-exec scaffold.

**As a** session author grounding a spec against Codex,
**I want** a `codex-spec-review` skill that takes a spec path + prior findings, runs codex exec headless with the `</dev/null` + background + `.done`-sentinel scaffold baked in, and returns a structured verdict (PLAN-READY / NOT-PLAN-READY + findings),
**so that** grounding a spec is one invocation instead of 4 hand-assembled steps repeated per pass.

**Acceptance Criteria:**
- [ ] AC-01: New skill file created (e.g. ~/.claude/skills/codex-spec-review/SKILL.md) that accepts a spec path and optional prior-findings and returns a structured PLAN-READY / NOT-PLAN-READY verdict with findings
- [ ] AC-02: The `</dev/null` stdin-drain guard, background launch, and `.done` sentinel poll are baked into the skill (references the known codex-exec invocation gotchas — reference_codex_exec_invocation.md / reference_codex_exec_output_last_message.md — for the `-o`/output-last-message parse, not raw stdout)
- [ ] AC-03: MEMORY.md pointer added for the new skill
- [ ] AC-04: Test: invoking the skill on a real spec path produces a structured verdict file/message in one call, with no manual prompt-file assembly

**Size:** M · **Tags:** `[a2a-cli-registry]` `[skill-missing]` `[codex]` `[automation-debt]`
