## Findings — DEEPSEEK (post-panel)

### [CRITICAL] Task 5 Step 1's `grep -cE` pattern cannot match the `bin/decisions show` output it is checking
- What: The gate command greps for three lines with `^\*\*` anchors, but `bin/decisions show` output format is not established anywhere in the bundle, and the pattern mixes `**Chosen:**` (colon inside the bold) with `**Decided-by:**` (colon outside) — one of the two is almost certainly wrong.
- Where: Task 5 Step 1 — `grep -cE '^\*\*(Chosen:\*\* commit from the reviewed file|Decided-by:\*\* human|Supersedes:\*\* Q<n> — resolved)$'` → `3`.
- Why it matters: This is the *only* gate between "operator resolved the decision" and "first live write of LLM-generated descriptions into the registry." If the pattern is wrong, `grep -c` returns `0`, the step blocks — safe but a hard stop on the highest-stakes step with no diagnostic. Worse, if the operator "fixes" the grep to make it pass, the gate is defeated. The pattern also hard-codes `Q<n>` as a literal string; the spec never says whether the operator substitutes the number or whether `bin/decisions show` prints the literal `Q<n>`.
- Suggested fix: Replace the grep with a structured check: `bin/decisions show -p a2a-cli-registry <m>` piped to a small Python one-liner that parses the fields, or `bin/decisions show --json` if the CLI supports it. At minimum, pin the exact output format of `bin/decisions show` in the spec (paste a sample) and make the pattern match that sample. Also state whether `<n>` and `<m>` are substituted by the operator or by the tool.
- Confidence: high (the pattern is internally inconsistent regardless of output format)

### [CRITICAL] Task 5 Step 1's `Supersedes: Q<n> — resolved` check depends on `resolve` semantics the spec never verifies
- What: The spec asserts that `bin/decisions resolve` "closes Q<n> by appending a superseding entry Q<m> (`**Supersedes:** Q<n> — resolved`)" and gates Task 5 on that exact string. The bundle contains no evidence that `resolve` emits this format, and the pre-panel triage (Codex finding 2) applied this fix without verifying the CLI's actual behavior.
- Where: Task 5 Step 1 — "`resolve` closes Q<n> by appending a superseding entry Q<m> (`**Supersedes:** Q<n> — resolved`); read that entry."
- Why it matters: If `resolve` instead mutates Q<n> in place, or appends an entry with different wording, or uses `Superseded-by:` instead of `Supersedes:`, the gate either blocks forever (safe) or — if the operator adapts the grep — admits an unresolved decision. The whole point of Codex's finding 2 was to prevent "stop" from opening the gate; a format mismatch reintroduces the same class of bug through a different door.
- Suggested fix: Before Task 5 ships, run `bin/decisions resolve` against a scratch project and paste the resulting `show` output into the spec as the canonical format. If the format is not stable, gate on `bin/decisions show --json` and check `chosen == "commit from the reviewed file" and decided_by == "human" and supersedes == <n>` structurally.
- Confidence: high

### [IMPORTANT] Task 4 Step 4's `prose_writable` excludes `manual` *descriptions* but not `manual` *capability rows* whose description is feed-owned
- What: `prose_writable` subtracts slugs in `manual_desc` (rows with `description_provenance='manual'`), but the writer's guard is on `provenance` (capability ownership), not `description_provenance`. A row with `provenance='manual'` and `description_provenance=NULL` will be skipped by `write_commit`'s UPDATE guard, yet counted as writable in Step 4.
- Where: Task 4 Step 4 — `manual_desc = {r[0] for r in con.execute("SELECT cli_slug FROM capability WHERE description_provenance='manual'")}` and `prose_writable = sum(1 for p in P if is_prose(p["description"]) and p["slug"] not in manual_desc)`.
- Why it matters: The operator approves a `prose_writable` number that overstates what will land. If any of the 12 `manual` capability rows have `description_provenance IS NULL` (likely — the column was added recently and manual rows predate it), the delta is silent. AC-02's ≥550 threshold could pass in Step 4 and fail in Task 5 Step 3.
- Suggested fix: Compute `manual_slugs` as the union of `provenance='manual'` and `description_provenance='manual'` rows, and subtract that union. Or better: run the writer's own guard predicate (`provenance in (None,'static','llm')`) against the live DB in Step 4 so the count matches what `write_commit` will actually do.
- Confidence: medium (depends on whether any manual rows have NULL `description_provenance`; the bundle does not show the live DB's per-row values)

### [IMPORTANT] `_load_reviewed` refuses "extra" verdicts, but Task 4's dry run writes verdicts for *all* enabled rows — including ones the operator may want to exclude from the commit
- What: `_load_reviewed` refuses unless "the report holds exactly one verdict per proposal slug and none for any other slug." But Task 4's dry run generates proposals for all 612 enabled rows, and the operator's review (`head -40`) may lead them to want to drop specific rows. There is no mechanism to commit a subset.
- Where: Task 2 Interfaces — `_load_reviewed(path) -> tuple[list[dict], list[dict]]` … "refuses … unless the report holds exactly one verdict per proposal slug and none for any other slug."
- Why it matters: The operator gate is all-or-nothing. If the operator sees 3 bad proposals in `head -40` and wants to commit the other 609, the only path is "tune and re-run" (re-running the whole multi-hour pipeline) or "stop." This is a design weakness in the gate: the operator cannot exercise judgment at row granularity, only at corpus granularity.
- Suggested fix: Either (a) document explicitly that the gate is all-or-nothing and the operator's only row-level control is editing `backfill_proposals.jsonl` before commit (and then `_load_reviewed` must accept a proposals file that is a subset of the report, refusing only *missing* verdicts, not *extra* ones), or (b) add a `--exclude-slug` flag. Option (a) is smaller and matches the "reviewed file is what gets written" principle.
- Confidence: medium (the spec may intend all-or-nothing; if so, it should say so)

### [IMPORTANT] Task 3's `PRESERVED_PROVENANCE` change makes `populate()` never refresh capability rows for backfilled slugs — the DECISIONS justification acknowledges this but the AC-06 test does not pin the trade-off
- What: Task 3's DECISIONS entry says "Trade-off: feed-side capability inference never refreshes a backfilled slug." But no test asserts that a feed-side capability change for a backfilled slug is *ignored* — only that the backfilled row survives. A future refactor could "fix" the trade-off by refreshing non-description fields, and no test would catch it.
- Where: Task 3 Step 1 — `test_populate_preserves_backfilled_capability_row` asserts `(provenance, intent_tags, input_types) == ("llm", "export", "path")` after populate, but does not assert that a *changed* feed record leaves the row untouched.
- Why it matters: The trade-off is the load-bearing decision of Task 3. If it silently regresses, the operator's `assumed` decision is violated without a test failure.
- Suggested fix: Add a test where the feed record for a backfilled slug carries different `intent_tags` (e.g., `["text"]` instead of `["export"]`) and assert the capability row still reads `"export"`. This pins the trade-off as intentional, not incidental.
- Confidence: medium

### [IMPORTANT] Task 2's `run_pipeline` progress line is asserted only for the disabled-rows test, not for the sanity loop
- What: The spec says `run_pipeline` prints one `[i/n] <slug>` line "as the first statement of the proposal loop … and of the sanity loop." The test `test_pipeline_skips_disabled_rows` asserts `"[2/2] " in capsys.readouterr().err`, which covers the proposal loop only. No test asserts the sanity-loop progress line.
- Where: Task 2 Step 1 — `assert "[2/2] " in capsys.readouterr().err  # per-row progress line, so a live run can be watched for stalls`.
- Why it matters: The stall rule in Task 4 Step 2 ("if the last progress line is older than 10 minutes, probe the router") depends on *both* loops emitting progress. The sanity loop is the one that makes router calls with retries (`sanity_check.py:125`), so it is the more likely stall point. If the sanity-loop print is dropped in implementation, the stall rule silently degrades to "no progress for 10 minutes" during the proposal loop only.
- Suggested fix: Add an assertion that the sanity loop also emits a progress line — e.g., capture stderr after `run_pipeline` and assert `"[1/2] "` appears at least twice (once per loop), or add a dedicated test that patches the sanity checker to sleep and asserts a progress line appears before the sleep.
- Confidence: medium

### [NIT] Task 4 Step 2's `nohup … &` with `echo "$! $SNAP"` does not survive shell exit for the Monitor
- What: The spec says "Then wait with a Monitor on the log for the line `"elapsed_seconds"`." But `nohup … &` backgrounds the process and `echo "$! $SNAP"` prints the PID to the *current* shell's stdout. If the operator's shell exits (or the tool call returns), the Monitor has no handle on the process.
- Where: Task 4 Step 2 — `nohup .venv/bin/python -m tools.backfill_capabilities --db "$SNAP" > … 2>&1 &` followed by `echo "$! $SNAP"`.
- Why it matters: The spec's own Global Constraints say "Long router runs go to the background with a log file, never in a foreground tool call." The `nohup` is correct for surviving shell exit, but the Monitor instruction assumes the operator can watch the log — which requires either a separate terminal or a `tail -f` in the same shell. The spec does not say which.
- Suggested fix: State explicitly: "In a second terminal, run `tail -f <log>` and watch for `elapsed_seconds`." Or use `wait $!` in the same shell after the `nohup` (which blocks the shell but keeps the Monitor in scope). The current wording is ambiguous about where the Monitor runs.
- Confidence: medium

### [NIT] Task 5 Step 2's `ls -la ~/.hermes/cli-registry.db.bak-$SHA` will fail if `backup_db` uses a different naming convention
- What: The spec asserts the tool's backup is named `.bak-<sha>` and checks for it with `ls`. But `backup_db` (`tools/backfill_capabilities.py:99-113`) is not shown in the bundle, and the spec's own note says it is "keyed by git SHA and overwritten on a re-run at the same HEAD." The `ls` check is a proxy for "the backup exists," but if the naming convention changes (e.g., `.bak-<sha>-<timestamp>`), the check fails silently.
- Where: Task 5 Step 2 — `ls -la ~/.hermes/cli-registry.db.bak-$SHA ~/.local/state/a2a-cli-registry/registry-prewrite-$STAMP.db`.
- Why it matters: The `ls` is the only verification that the rollback artifact exists. A naming mismatch makes the check a false negative, and the operator may proceed without a backup.
- Suggested fix: Have `backup_db` print the backup path to stdout, and grep the command output for it: `.venv/bin/python -m tools.backfill_capabilities … 2>&1 | tee /tmp/backfill.log; grep -q 'backup: ' /tmp/backfill.log`. Or assert the file exists with `test -f` and a glob: `ls ~/.hermes/cli-registry.db.bak-* | grep -q "$SHA"`.
- Confidence: low (the naming convention is likely stable, but the spec does not pin it)

### [NIT] Task 1 Step 3's "stop and report" for `manual` count ≠ 12 conflates "operator hand-edit landed" with "plan is stale"
- What: The spec says a `manual` count other than 12 means "an operator hand-edit landed after the plan was written and the operator should know before the writer runs." But a `manual` count of 11 could also mean a manual row was *deleted* (e.g., a CLI was retired), which is a different signal.
- Where: Task 1 Step 3 — "a `manual` count other than 12 … is not [fine]: stop and report."
- Why it matters: The stop is correct in both directions, but the *reason* stated is one-sided. An operator reading "an operator hand-edit landed" when the count went *down* will be confused.
- Suggested fix: Reword: "a `manual` count other than 12 means the manual corpus changed since the plan was written (an edit landed or a row was removed); stop and report the delta."
- Confidence: high

### [NIT] AC-02's "≥ 550 of 612" is stated as a fraction but Task 5 Step 3 checks `≥ 550` against a live count that may differ from 612
- What: AC-02 says "count ≥ 550 of 612." Task 5 Step 3's query returns a count and the expected is "first ≥ 550." If the live enabled count drifted to 610 between Task 1 and Task 5, the threshold 550 is still checked but the "of 612" is stale.
- Where: AC-02 vs. Task 5 Step 3.
- Why it matters: Minor; the threshold is absolute (550), not a percentage, so drift does not change the gate. But the "of 612" in AC-02 is a snapshot that Task 1 Step 3 explicitly allows to differ ("A number that differs from the pre-plan column is fine").
- Suggested fix: Reword AC-02 to "count ≥ 550 (of the enabled corpus at Task 1 baseline)" or make it a percentage (≥ 90% of enabled, matching AC-04's style).
- Confidence: high

## Self-flagged uncertainty

- **`bin/decisions show` output format**: I have no sample of the actual output. The CRITICAL findings about the grep pattern assume the format is not `**Chosen:**` / `**Decided-by:**` as written; if it is, the pattern may still fail on the `Q<n>` literal. The spec should paste a sample.
- **`backup_db` naming convention**: The bundle does not show `tools/backfill_capabilities.py:99-113`. The NIT about `.bak-$SHA` assumes the convention is stable; if it is, the check is fine.
- **Whether any `manual` capability rows have `description_provenance IS NULL`**: The IMPORTANT about `prose_writable` depends on this. The bundle shows 12 manual rows but not their `description_provenance` values. If all 12 have `description_provenance='manual'`, the finding is moot.
- **Whether the operator gate is intended to be all-or-nothing**: The IMPORTANT about `_load_reviewed` refusing extra verdicts assumes the operator might want row-level control. If the design intends all-or-nothing, the finding is a documentation gap, not a design weakness.
- **Task 4 Step 2's Monitor semantics**: I'm not certain whether "Monitor" refers to a specific tool (e.g., a Claude Code Monitor primitive) or a generic `tail -f`. If it is a specific tool with its own process-handle semantics, the NIT may be wrong.
- **`register_cli.py:181`**: The pre-panel triage says the file exists and the collector resolved `~` literally. I did not re-verify; the pre-panel finding stands.