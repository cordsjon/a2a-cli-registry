# CONTEXT — 2026-10-18-capability-map-phase0

_Generated procedurally by phase0-procedural.sh at 2026-10-18T18:26:00Z.
No LLM call — pure grep + stat. Reviewers can request deeper context on demand._

## 1. Spec under review

- **Path:** `/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/plans/2026-10-18-capability-map-phase0.md`
- **Last modified:** 2026-10-18 19:32:50
- **Lines:** 469
- **Bytes:** 34233
- **Project root:** `/Users/jcords-macmini/projects/a2a-cli-registry`

### Section index

- Hierarchy
- Global Constraints
- Review Focus
- Baseline (recorded at execution, Task 1 Step 3)
- Self-review notes

## 2. Cited artifacts — grounded existence checks

This is the **grounding layer**. Every citation extracted from the spec was checked
against the filesystem. `OK` = path exists, `MISSING` = does not exist, `GLOB` =
matches via shell glob (count > 0).

### 2.1 Tilde paths

| Path | Status | Size / kind |
|---|---|---|
| `~/.config/git/hooks/pre-commit` | OK | file, 3037B |
| `~/.hermes/cli-registry.db` | OK | file, 733184B |
| `~/.hermes/cli-registry.db.bak-$(git` | MISSING | — |
| `~/.hermes/cli-registry.db?` | MISSING | — |
| `~/.local/state/a2a-cli-registry` | MISSING | — |
| `~/.local/state/a2a-cli-registry/backfill-dryrun-` | MISSING | — |
| `~/.local/state/a2a-cli-registry/backfill-dryrun-$(date` | MISSING | — |
| `~/.local/state/a2a-cli-registry/backfill-dryrun-*.log` | MISSING | — |
| `~/projects/00_Governance` | OK | directory, 2735 entries |
| `~/projects/00_Governance/bin/foundations` | OK | file, 508B |
| `~/projects/00_Governance/scripts/register_cli.py:181` | MISSING | — |
| `~/projects/20_CONSIGLIERE/FOUNDATIONS.md` | OK | file, 1232B |
| `~/projects/20_CONSIGLIERE/docs/superpowers/specs/2026-10-18-capability-consolidation-design.md` | OK | file, 18096B |
| `~/projects/a2a-cli-registry` | OK | directory, 36 entries |
| `~/projects/a2a-cli-registry;` | MISSING | — |

### 2.2 Backticked filenames

| Filename | Status | Locations (up to 3) |
|---|---|---|
| `BACKLOG.md` | OK | ~/projects/a2a-cli-registry/BACKLOG.md |
| `DECISIONS.md` | OK | ~/projects/a2a-cli-registry/DECISIONS.md;~/.claude/skills/DECISIONS.md |
| `FOUNDATIONS.md` | MISSING | — |
| `backfill_proposals.jsonl` | OK | ~/projects/a2a-cli-registry/backfill_proposals.jsonl |
| `core/models.py` | OK | ~/projects/a2a-cli-registry/core/models.py |
| `core/populate.py` | OK | ~/projects/a2a-cli-registry/core/populate.py |
| `docs/superpowers/plans/2026-07-03-capability-backfill.md` | OK | ~/projects/a2a-cli-registry/docs/superpowers/plans/2026-07-03-capability-backfill.md |
| `docs/superpowers/plans/2026-07-10-cli-catalog-search-capability-vocab.md` | OK | ~/projects/a2a-cli-registry/docs/superpowers/plans/2026-07-10-cli-catalog-search-capability-vocab.md |
| `register_cli.py` | MISSING | — |
| `sanity_report.jsonl` | OK | ~/projects/a2a-cli-registry/sanity_report.jsonl |
| `tests/conftest.py` | OK | ~/projects/a2a-cli-registry/demo/.sandbox/venv-streamlit/lib/python3.13/site-packages/pyarrow/tests/conftest.py;~/projects/a2a-cli-registry/tests/conftest.py |
| `tests/test_backfill_capabilities.py` | OK | ~/projects/a2a-cli-registry/tests/test_backfill_capabilities.py |
| `tests/test_catalog.py` | OK | ~/projects/a2a-cli-registry/tests/test_catalog.py |
| `tests/test_populate.py` | OK | ~/projects/a2a-cli-registry/tests/test_populate.py |
| `tests/test_sanity_check.py` | OK | ~/projects/a2a-cli-registry/tests/test_sanity_check.py |
| `tests/test_server_overview.py` | OK | ~/projects/a2a-cli-registry/tests/test_server_overview.py |
| `tests/test_web_overview_view.py` | OK | ~/projects/a2a-cli-registry/tests/test_web_overview_view.py |
| `tools/backfill_capabilities.py` | OK | ~/projects/a2a-cli-registry/tools/backfill_capabilities.py |
| `tools/capability_extractor.py` | OK | ~/projects/a2a-cli-registry/tools/capability_extractor.py |
| `tools/capability_llm_fallback.py` | OK | ~/projects/a2a-cli-registry/tools/capability_llm_fallback.py |
| `tools/capability_repair.py` | OK | ~/projects/a2a-cli-registry/tools/capability_repair.py |
| `tools/description_regenerator.py` | OK | ~/projects/a2a-cli-registry/tools/description_regenerator.py |
| `tools/sanity_check.py` | OK | ~/projects/a2a-cli-registry/tools/sanity_check.py |

### 2.3 Slash-commands (skills)

| Command | Status | Path |
|---|---|---|
| `/overview` | MISSING | — |

### 2.4 sh: panel skills

| Skill | Status | Path |
|---|---|---|
| `sh:architecture-panel` | OK | ~/.claude/commands/sh/architecture-panel.md |
| `sh:spec-panel` | OK | ~/.claude/commands/sh/spec-panel.md |

## 3-6. Surrounding code, prior decisions, open questions, repo conventions

**Procedurally deferred.** This collector intentionally does not synthesize these
sections — they require judgment the grounding layer alone cannot provide.
Reviewers should pull what they need:

- For *surrounding code* of a flagged path: open the path directly.
- For *prior decisions*: check sibling specs in `/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/plans` (see section index).
- For *open questions inherited*: search the spec for "Q1", "Q2", etc.
- For *repo conventions*: read `/Users/jcords-macmini/projects/a2a-cli-registry/CLAUDE.md` and `/Users/jcords-macmini/projects/a2a-cli-registry/KNOWN_PATTERNS.md`.

## 7. What this collector did NOT check

- Function names, CLI sub-commands, and config keys (`escalation.to`, `schema_version` etc.) — these are spec-internal JSON schema fields, not external artifacts; no existence check applies.
- External URLs and resources.
- Path placeholders containing `<...>` or `...` — filtered out as noise.
- Whether file *contents* match the spec's claims about them. Only file existence is verified.
- Imports / call sites of cited code paths (would require an LSP or wider grep).

If a reviewer needs any of these, they should request explicitly.
