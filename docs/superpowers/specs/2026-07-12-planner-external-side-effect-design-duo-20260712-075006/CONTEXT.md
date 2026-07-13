# CONTEXT — 2026-07-12-planner-external-side-effect-design

_Generated procedurally by phase0-procedural.sh at 2026-07-12T05:50:06Z.
No LLM call — pure grep + stat. Reviewers can request deeper context on demand._

## 1. Spec under review

- **Path:** `/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/specs/2026-07-12-planner-external-side-effect-design.md`
- **Last modified:** 2026-07-12 07:49:12
- **Lines:** 167
- **Bytes:** 8170
- **Project root:** `/Users/jcords-macmini/projects/a2a-cli-registry`

### Section index

- Problem
- Scope narrowing (this session)
- Fix
- Non-goals
- Testing
- Rollback
- Files touched
- Acceptance Criteria

## 2. Cited artifacts — grounded existence checks

This is the **grounding layer**. Every citation extracted from the spec was checked
against the filesystem. `OK` = path exists, `MISSING` = does not exist, `GLOB` =
matches via shell glob (count > 0).

### 2.1 Tilde paths

| Path | Status | Size / kind |
|---|---|---|
| `~/.hermes/cli-registry.db` | OK | file, 589824B |

### 2.2 Backticked filenames

| Filename | Status | Locations (up to 3) |
|---|---|---|
| `capability_llm_fallback.py` | OK | ~/projects/a2a-cli-registry/tools/capability_llm_fallback.py |
| `core/models.py` | OK | ~/projects/a2a-cli-registry/core/models.py |
| `core/planner/search.py` | OK | ~/projects/a2a-cli-registry/core/planner/search.py |
| `hermes-adapter/cli_registry.py` | MISSING | — |
| `tests/test_planner.py` | OK | ~/projects/a2a-cli-registry/tests/test_planner.py |
| `tools/capability_llm_fallback.py` | OK | ~/projects/a2a-cli-registry/tools/capability_llm_fallback.py |

### 2.3 Slash-commands (skills)

| Command | Status | Path |
|---|---|---|

### 2.4 sh: panel skills

| Skill | Status | Path |
|---|---|---|

## 3-6. Surrounding code, prior decisions, open questions, repo conventions

**Procedurally deferred.** This collector intentionally does not synthesize these
sections — they require judgment the grounding layer alone cannot provide.
Reviewers should pull what they need:

- For *surrounding code* of a flagged path: open the path directly.
- For *prior decisions*: check sibling specs in `/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/specs` (see section index).
- For *open questions inherited*: search the spec for "Q1", "Q2", etc.
- For *repo conventions*: read `/Users/jcords-macmini/projects/a2a-cli-registry/CLAUDE.md` and `/Users/jcords-macmini/projects/a2a-cli-registry/KNOWN_PATTERNS.md`.

## 7. What this collector did NOT check

- Function names, CLI sub-commands, and config keys (`escalation.to`, `schema_version` etc.) — these are spec-internal JSON schema fields, not external artifacts; no existence check applies.
- External URLs and resources.
- Path placeholders containing `<...>` or `...` — filtered out as noise.
- Whether file *contents* match the spec's claims about them. Only file existence is verified.
- Imports / call sites of cited code paths (would require an LSP or wider grep).

If a reviewer needs any of these, they should request explicitly.
