## Findings — Codex

### CRITICAL ambiguous storage for independent description provenance
- What: The spec requires independent overwrite protection for `cli.description` but never defines a durable DB field that can store `description_provenance`.
- Where: `"Per-field provenance, not a shared flag"` and `"This needs no new DB column ... plus a lightweight description_provenance value co-located in the same capability row"`; later `"checking capability_provenance and description_provenance separately"`.
- Why it matters: The writer cannot reliably know whether an existing DB description is `manual` on a later run, so the stated manual-protection invariant is not implementable as written.
- Suggested fix: Add an explicit guarded migration for `capability.description_provenance TEXT` or a small per-slug metadata table, then define exact read/write semantics for `static`/`llm`/`manual`/NULL.
- Confidence: high

### IMPORTANT stale dry-run artifacts can be committed against the wrong DB state
- What: `--commit` is specified to read `sanity_report.jsonl`, but the spec does not require it to validate that the report and proposals match the current DB, git revision, model run, or source files.
- Where: `"--dry-run is the DEFAULT. Writes all proposed rows ... to backfill_proposals.jsonl"` and `"--commit reads sanity_report.jsonl and refuses to proceed if the failure rate exceeds ~10%"`.
- Why it matters: A user could commit an old sanity report after source/DB/proposal changes, bypassing the intended safety gate while still satisfying the letter of the implementation.
- Suggested fix: Store a run id plus DB checksum/path, git sha, generated timestamp, proposal hash, and sanity report hash in both files; `--commit` must refuse if any value is missing or mismatched.
- Confidence: high

### IMPORTANT fallback cap and acceptance target conflict with partial-failure routing
- What: The design routes to LLM fallback whenever either inputs or outputs are empty, while also capping fallback at ~30 CLIs and expecting ~440+/471 typed coverage, but the bundle gives no evidence that most CLIs will have statically detectable outputs.
- Where: `"Routes to the LLM fallback when EITHER inputs OR outputs come back empty"`; `"Cap: if more than ~30 CLIs need fallback"`; `"typed-port coverage jumps from 0/474 toward ~440+/471"`.
- Why it matters: Many valid CLIs may only read, only print indirectly, dispatch to helper functions, or produce side effects not visible in the top-level parser source, causing the batch to stop even if input extraction works well.
- Suggested fix: Split coverage targets and fallback triggers: require fallback for missing inputs only when a parser exists but cannot be typed, and treat missing outputs as `unknown` or `text` only under defined evidence; alternatively justify the ~30 cap with sampled output-detection data.
- Confidence: medium

### IMPORTANT side-effect semantics are under-specified for implementation
- What: The spec says `writes-fs` applies only when modifying an input path in place, but does not define enough data-flow rules to distinguish same input, derived paths, output arguments, constants, and helper-function writes.
- Where: `"writes-fs ONLY when the source modifies an input path in place (writes back to a path read from the same argument/variable)"`.
- Why it matters: Implementers may produce inconsistent or brittle AST heuristics, either over-pruning chainable converters or missing actual in-place mutation.
- Suggested fix: Define a narrow accepted heuristic, for example: only infer `writes-fs` when the same argparse/click/Typer parameter name is used in both a read call and a write call in the same function; otherwise emit `unknown` or `none` per explicit rules.
- Confidence: high

### IMPORTANT sanity threshold conflicts with final out-of-scope statement
- What: The architecture makes `--commit` refuse when sanity failures exceed ~10%, but the out-of-scope section says persistent failures become a manual backlog “not a blocker for this plan’s commit.”
- Where: `"refuses --commit if sanity-check failures exceed a threshold"` and `"persistent failures after tuning become a manual curation backlog item, not a blocker for this plan's commit"`.
- Why it matters: This leaves implementers unclear whether a high failure rate blocks the backfill or can be accepted as backlog.
- Suggested fix: Clarify that commit is blocked above 10% until either the tools are tuned or explicit manual overrides reduce failures below threshold; persistent below-threshold failures become backlog.
- Confidence: high

### NIT approximate thresholds should be made exact
- What: Several gates use approximate language despite being intended as hard stops.
- Where: `"more than ~30 CLIs"`, `"more than ~10% of rows fail (~47)"`, and `"toward ~440+/471"`.
- Why it matters: Tests and CLI behavior need exact pass/fail criteria.
- Suggested fix: Replace with exact constants, e.g. `fallback_cap = 30`, `sanity_failure_rate > 0.10`, and define whether the denominator is 471 or all proposed rows.
- Confidence: high

## Self-flagged uncertainty
- I could not verify the referenced live semantics in `bridge/llm_infer.py:56-67`; per instruction, I treated the quoted spec claim as unverified bundle context rather than re-opening the file.
- The concern about fallback volume depends on how many CLIs have statically detectable outputs; the bundle gives parser framework counts but not output-pattern counts.
