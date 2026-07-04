# CONTEXT — 2026-07-03-capability-backfill-design

_Generated procedurally by phase0-procedural.sh at 2026-07-03T07:16:37Z.
No LLM call — pure grep + stat. Reviewers can request deeper context on demand._

## 1. Spec under review

- **Path:** `/Users/jcords-macmini/projects/a2a-cli-registry/docs/superpowers/specs/2026-07-03-capability-backfill-design.md`
- **Last modified:** 2026-07-03 09:16:09
- **Lines:** 330
- **Bytes:** 21528
- **Project root:** `/Users/jcords-macmini/projects/a2a-cli-registry`

### Section index

- Goal
- Context (verified against live data + code)
- Scope
- Architecture
- Testing
- Out of scope (future, unblocked by this)

## 2. Cited artifacts — grounded existence checks

This is the **grounding layer**. Every citation extracted from the spec was checked
against the filesystem. `OK` = path exists, `MISSING` = does not exist, `GLOB` =
matches via shell glob (count > 0).

### 2.1 Tilde paths

| Path | Status | Size / kind |
|---|---|---|
| `~/projects/a2a-cli-registry` | OK | directory, 27 entries |

### 2.2 Backticked filenames

| Filename | Status | Locations (up to 3) |
|---|---|---|
| `backfill_capabilities.py` | MISSING | — |
| `backfill_proposals.jsonl` | MISSING | — |
| `bridge/llm_infer.py` | OK | ~/projects/a2a-cli-registry/bridge/llm_infer.py |
| `capability_extractor.py` | MISSING | — |
| `capability_llm_fallback.py` | MISSING | — |
| `core/playbooks/signature.py` | OK | ~/projects/a2a-cli-registry/core/playbooks/signature.py |
| `description_regenerator.py` | MISSING | — |
| `out.json` | MISSING | — |
| `sanity_check.py` | MISSING | — |
| `sanity_report.jsonl` | MISSING | — |
| `tests/test_backfill_capabilities.py` | MISSING | — |
| `tests/test_capability_extractor.py` | MISSING | — |
| `tests/test_capability_llm_fallback.py` | MISSING | — |
| `tests/test_description_regenerator.py` | MISSING | — |
| `tests/test_sanity_check.py` | MISSING | — |
| `tools/backfill_capabilities.py` | MISSING | — |
| `tools/capability_extractor.py` | MISSING | — |
| `tools/capability_llm_fallback.py` | MISSING | — |
| `tools/description_regenerator.py` | MISSING | — |
| `tools/sanity_check.py` | MISSING | — |

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
