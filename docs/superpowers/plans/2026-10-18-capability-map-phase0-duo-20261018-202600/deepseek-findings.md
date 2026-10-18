## Findings — DEEPSEEK

### [CRITICAL] Task 2 test asserts a `description_provenance` column that Task 3 introduces, but Task 2 ships first
- What: `test_commit_inserts_capability_row_when_missing` selects `description_provenance` from `capability` and asserts `cap == ("path", "static", "llm")`, but `description_provenance` is only added to the `Capability` model in Task 3 Step 3. Task 2's commit lands before Task 3's.
- Where: Task 2 Step 1, `test_commit_inserts_capability_row_when_missing` — `SELECT input_types, provenance, description_provenance FROM capability WHERE cli_slug='orphan'` and `assert cap == ("path", "static", "llm")`.
- Why it matters: The `drifted_db` fixture is built from `SQLModel.metadata.create_all` (per Task 3's Interfaces note), so at Task 2 time the `capability` table has no `description_provenance` column. The test will fail with `sqlite3.OperationalError: no such column` — and worse, the assertion `("path", "static", "llm")` also encodes a `provenance = "static"` value that the writer's `_ensure_capability_row` inserts as `provenance NULL` (per Task 2's own interface spec: "inserts `('', '', '', 'unknown', 'inferred')` with `provenance NULL`"). The test as written cannot pass under Task 2's implementation even ignoring the missing column.
- Suggested fix: Either (a) move the `description_provenance` model change into Task 2 (it's a schema addition, not a populate change), or (b) drop `description_provenance` from this test's SELECT and assert only `(input_types, provenance) == ("path", None)` — matching what `_ensure_capability_row` actually inserts. Also reconcile: the interface says `provenance NULL`, the test expects `"static"`.
- Confidence: high

### [CRITICAL] `_ensure_capability_row` inserts `provenance NULL`, but the test expects `"static"` — the writer's contract is self-contradictory
- What: Task 2's Interfaces block says `_ensure_capability_row` "inserts `('', '', '', 'unknown', 'inferred')` with `provenance NULL`", but the test `test_commit_inserts_capability_row_when_missing` asserts `provenance == "static"` and `description_provenance == "llm"`.
- Where: Task 2 Interfaces (`_ensure_capability_row(con, slug) -> bool` description) vs. Task 2 Step 1 test `assert cap == ("path", "static", "llm")`.
- Why it matters: The placeholder row is created by `_ensure_capability_row` with `provenance NULL`; then `write_commit` presumably updates it with the proposal's `provenance` (which the test's `_patch_pipeline` fixture must supply as `"static"`). If `write_commit` only UPDATEs existing rows and the placeholder was just INSERTed, the UPDATE path must run for the newly-inserted row too. The spec never states that `write_commit` re-reads and updates the placeholder it just created — it only says "Call it at the top of the per-row loop in `_persist_sanity` and in `write_commit`; in both, `continue` when the slug has no `cli` row." That `continue` semantics is ambiguous: does `continue` skip the update, or only skip the insert?
- Suggested fix: Clarify in the Interfaces block that `_ensure_capability_row` returns True and the caller proceeds to UPDATE the (now-existing) row with the proposal's fields; only the "slug not in cli" case `continue`s. Then make the test's expected `provenance` match the fixture's proposal value explicitly (state what `_patch_pipeline` returns for `provenance`).
- Confidence: high

### [IMPORTANT] `--from-proposals` skips `run_pipeline` but the spec never says how `sanity_fail_rate` is computed from the loaded report
- What: Task 2 Interfaces says `--from-proposals` "still runs `_run_calibration()` and the fail-rate gate from the loaded report", but the shipped `SANITY_FAILURE_THRESHOLD = 0.10` gate presumably compares `sanity_fail_rate` against the threshold. The spec doesn't say whether the fail rate is `fails / len(report)` or `fails / total_rows`, nor whether `total_rows` comes from the report or from a fresh `cli` count.
- Where: Task 2 Interfaces, `main` bullet: "`sanity_fail_rate` from the loaded report, then fall through to the existing two REFUSED gates".
- Why it matters: If the reviewed report was generated against a 612-row corpus but the live DB has drifted (a CLI added between Task 4 and Task 5), the fail-rate denominator is ambiguous. A reviewer/operator reading the gate output can't tell whether the gate is measuring the reviewed corpus or the current one. This is exactly the "what the operator reviewed is not what gets written" failure mode Task 2 is trying to close — but the gate re-derivation reintroduces it.
- Suggested fix: State explicitly: `sanity_fail_rate = sum(1 for r in report if not r["ok"]) / len(report)`, and add a guard that `len(report) == count(cli WHERE enabled=1)` at commit time, refusing otherwise (or logging the delta). Pin it in a test.
- Confidence: medium

### [IMPORTANT] Task 3's `PRESERVED_PROVENANCE` includes `"static"` but the design's provenance vocabulary is not shown to include it
- What: Task 3 introduces `PRESERVED_PROVENANCE = ("manual", "static", "llm")` and `description_provenance` values `"llm"`. The Global Constraints section only names `provenance = 'manual'` as protected and `confidence = 'inferred'` for backfilled rows. `"static"` and `"llm"` as `provenance` values are not defined anywhere in the spec.
- Where: Task 3 Interfaces (`PRESERVED_PROVENANCE = ("manual", "static", "llm")`) vs. Global Constraints ("Provenance guard: a capability row with `provenance = 'manual'` is never overwritten").
- Why it matters: The writer (Task 2) inserts `provenance NULL` placeholders and the test expects `provenance = "static"`. If `"static"` is a real provenance value the extractor emits, the spec should say so; if it's invented for this plan, the `populate()` guard is protecting a value that nothing writes. Either way, a reader can't tell whether `"static"` is a shipped vocabulary term or a new one this plan introduces.
- Suggested fix: Add one line to Global Constraints defining the provenance vocabulary (`manual | static | llm | NULL`) and cite where `"static"` comes from (the extractor? the July plan?). If `"static"` is new, say so and note it's a schema-vocabulary extension.
- Confidence: medium

### [IMPORTANT] Task 4 Step 4's `prose` count uses `" " in p["description"]` but AC-02 uses `LIKE '% %'` — these diverge on newlines/tabs
- What: AC-02 is defined as "description contains a space and no `Error`" and the Baseline table uses `LIKE '% %' AND NOT LIKE '%Error%'`. Task 4 Step 4's Python check uses `" " in p["description"] and "Error" not in p["description"]`. SQL `LIKE '% %'` matches any single space character; Python `" " in s` matches the same. But `NOT LIKE '%Error%'` is case-sensitive in SQLite by default, while `"Error" not in s` is also case-sensitive — so those agree. The divergence is subtler: SQL `LIKE` treats `%` and `_` as wildcards in the *pattern*, not the value, so they agree on the value side. However, the Baseline table's prose predicate is scoped to `enabled = 1`, while Task 4 Step 4 iterates all proposals — which after Task 2's `_fetch_all_cli_rows` fix are all enabled, so this is consistent. The real gap: Task 4 Step 4 counts `prose` over `backfill_proposals.jsonl`, but AC-02 is measured against the *live DB after commit* in Task 5 Step 3. A proposal whose description is prose but whose write is skipped (e.g., a `manual`-provenance row the writer refuses to overwrite) inflates the Step 4 estimate.
- Where: Task 4 Step 4 (`prose = sum(1 for p in P if " " in p["description"] and "Error" not in p["description"])`) vs. AC-02 and Task 5 Step 3's SQL.
- Why it matters: The operator gate in Task 4 Step 5 is justified by "prose=<n>/612" from the proposals file. If the writer will skip some of those rows (manual provenance, or slugs that vanished between dry run and commit), the number the operator approves is not the number that lands. AC-05 says no field changes before resolution, but nothing pins the proposals-to-DB delta.
- Suggested fix: In Task 4 Step 4, also compute `prose_writable = sum(1 for p in P if " " in p["description"] and "Error" not in p["description"] and p["slug"] not in manual_slugs)` where `manual_slugs` is queried from the live DB's `provenance = 'manual'` rows. Report both numbers in the DECISIONS entry.
- Confidence: medium

### [IMPORTANT] Task 5 Step 2's backup filename uses `git rev-parse --short HEAD` but the backup is taken *before* the commit, so the SHA is the pre-commit HEAD — the `ls` check is correct but the naming convention is fragile
- What: `backup_db` is called inside `main` before `write_commit`; the spec's `ls -la ~/.hermes/cli-registry.db.bak-$(git rev-parse --short HEAD)` runs *after* the commit command returns, so `HEAD` is still the pre-commit SHA (the commit is a DB write, not a git commit). This works, but only because Task 5 Step 2 does not `git commit` between the backup and the `ls`. If a future edit inserts a `git commit` there, the check silently passes against the wrong file.
- Where: Task 5 Step 2, `ls -la ~/.hermes/cli-registry.db.bak-$(git rev-parse --short HEAD)`.
- Why it matters: The backup is the only rollback artifact for the first live write. A check that can silently validate the wrong file is a weak gate on the highest-stakes step.
- Suggested fix: Capture the SHA before the commit command: `SHA=$(git rev-parse --short HEAD); .venv/bin/python -m tools.backfill_capabilities ... ; ls -la ~/.hermes/cli-registry.db.bak-$SHA`. Or have `backup_db` print the backup path and grep the command output for it.
- Confidence: medium

### [IMPORTANT] Task 1 Step 3's "stop and report" threshold (`cli` row count below 600, `manual` count other than 12) is not justified and may be too tight
- What: Task 1 Step 3 says "a `cli` row count below 600 or a `manual` count other than 12 is not: stop and report before continuing." The Baseline table records 636 `cli` rows / 612 enabled and 12 `manual`. The spec doesn't say why 600 is the floor or why `manual` must be exactly 12.
- Where: Task 1 Step 3, "a `cli` row count below 600 or a `manual` count other than 12 is not: stop and report".
- Why it matters: If a legitimate re-register or a manual capability edit lands between plan-writing and Task 1 execution (the plan is dated 2026-10-18 and the DB is live), the operator gets a spurious stop. Conversely, a `manual` count of 13 could be a *good* sign (someone added a manual row) that the plan treats as a failure. The threshold encodes an assumption about DB stability that isn't stated.
- Suggested fix: Either justify the thresholds (e.g., "600 = 636 − 5% drift tolerance; 12 = the count at plan-writing time, any change means a manual edit landed and the operator should review") or soften to "report the delta and proceed unless the operator says otherwise."
- Confidence: medium

### [NIT] Task 2 Step 2's expected-failure list omits `test_persist_sanity_creates_placeholder_row_for_cli_without_capability`
- What: Step 2 says "The others FAIL: `AttributeError: _ensure_capability_row`, `total_rows == 3`, `row is None`, and argparse rejecting `--from-proposals`." The `row is None` covers `test_persist_sanity_creates_placeholder_row_for_cli_without_capability`, but the `-k` filter in Step 2 is `"disabled or placeholder or unknown_slug or inserts_capability or from_proposals or fence"` — `placeholder` matches the test name, good. But `test_ensure_capability_row_refuses_unknown_slug` matches `unknown_slug`, and `test_commit_from_proposals_ignores_slug_not_in_cli` matches `from_proposals`. All 8 new tests are covered. No issue — but the mapping from failure mode to test is loose enough that a reader can't verify coverage without cross-referencing.
- Where: Task 2 Step 2.
- Why it matters: Minor; the `-k` filter is correct but the prose doesn't enumerate which test fails how.
- Suggested fix: List the 8 tests and their expected failure mode in a table.
- Confidence: high

### [NIT] Task 3 Step 2's expected failure for `test_populate_preserves_backfilled_capability_row` is `TypeError` on `description_provenance`, but that test doesn't pass `description_provenance`
- What: `test_populate_preserves_backfilled_capability_row` constructs `Capability(..., provenance="llm")` with no `description_provenance` argument. The `TypeError` on `description_provenance` would come from `test_populate_keeps_description_when_backfilled`, which does pass it. The spec's Step 2 says "the first two FAIL (`TypeError` on `description_provenance`, then provenance `None` / description overwritten once the model has the field)" — the parenthetical maps the first failure to the first test, which is wrong.
- Where: Task 3 Step 2.
- Why it matters: Cosmetic; a reader following the expected-failure list will be confused when the first test fails with an assertion error (provenance `None`), not a `TypeError`.
- Suggested fix: Reword: "the first FAILS on the provenance assertion (`None != 'llm'`); the second FAILS with `TypeError` on `description_provenance`."
- Confidence: high

### [NIT] Task 4 Step 3's `tail -14` assumes the summary JSON is exactly 14 lines
- What: "Run: `tail -14 ~/.local/state/a2a-cli-registry/backfill-dryrun-*.log`" — the summary JSON's line count is not pinned anywhere.
- Where: Task 4 Step 3.
- Why it matters: If the summary is 12 or 16 lines, the operator sees a truncated or padded view. Minor, but this is the gate-reading step.
- Suggested fix: Use `tail -n 50` or `grep -A100 '"elapsed_seconds"'` or `python -c 'import json,sys; print(json.dumps(json.loads(sys.stdin.read().splitlines()[-1]), indent=2))'`.
- Confidence: high

### [NIT] Task 5 Step 3's expected `third ≥ 551 (90 % of 612)` — 90% of 612 is 550.8, so 551 is correct, but the AC-04 wording says "≥ 90 %" which would be 550.8 → 551 rows. Consistent, but the arithmetic is worth pinning.
- What: AC-04: "`sanity_ok IS NOT NULL` on ≥ 90 % of enabled CLIs' capability rows." Task 5 Step 3 expects `third ≥ 551`. 0.90 × 612 = 550.8, so ≥ 551 is the correct integer floor. No error — flagging for the record.
- Where: AC-04 vs. Task 5 Step 3.
- Why it matters: None; the arithmetic is right. Noting so the co-reviewer doesn't flag it as a mismatch.
- Suggested fix: None.
- Confidence: high

### [NIT] Review Focus item 5 cites `~/projects/00_Governance/scripts/register_cli.py:181` but the context collector reports that path as MISSING
- What: Review Focus item 5 says "`register_cli.py` re-registering an existing slug rewrites its description (`~/projects/00_Governance/scripts/register_cli.py:181`)". The context collector's grounding table lists `~/projects/00_Governance/scripts/register_cli.py:181` as MISSING and `register_cli.py` (bare filename) as MISSING.
- Where: Review Focus item 5.
- Why it matters: The spec cites a file that the grounding layer could not find. Either the path is wrong (maybe it's `bin/register_cli.py` or a different subdir) or the file was moved/removed. The claim "carried to phase 1, not fixed here" rests on this citation.
- Suggested fix: Verify the path and correct it, or note that the file has moved and cite the current location. If the file genuinely doesn't exist, the carried-forward risk may be moot.
- Confidence: medium (the collector may have missed it; `~/projects/00_Governance` has 2735 entries and the collector only checked exact paths)

### [NIT] Task 1 Step 1's FOUNDATIONS.md entry cites the 07-03 plan, not this plan
- What: The single entry is `- capability map with real can-do descriptions | open | docs/superpowers/plans/2026-07-03-capability-backfill.md`. But this plan (2026-10-18) is the one that closes the foundation. The 07-03 plan's Task 7 is executed *by* this plan.
- Where: Task 1 Step 1.
- Why it matters: The foundation's "evidence" pointer points at a plan whose checkboxes were never ticked (per Task 5 Step 5's own note: "Checkboxes below were never ticked and are left as written"). A reader following the pointer lands on a plan that looks incomplete. Minor, but it's the artifact the operator will open to verify the foundation.
- Suggested fix: Point at this plan (`docs/superpowers/plans/2026-10-18-capability-map-phase0.md`) or list both.
- Confidence: medium

## Self-flagged uncertainty

- **Task 2's `_patch_pipeline` fixture contents**: I don't have the fixture body, so I can't verify whether it returns `provenance = "static"` for the `orphan` slug (which the test expects) or something else. The CRITICAL finding about `provenance NULL` vs `"static"` assumes the interface description is accurate; if `_patch_pipeline` overrides the placeholder's provenance, the test may pass. Flagging because the interface text and the test assertion directly contradict.
- **`description_provenance` column existence at Task 2 time**: I'm inferring from Task 3's Interfaces note ("schema from `SQLModel.metadata.create_all`, so the new model field appears automatically") that the column does not exist until Task 3. If the `drifted_db` fixture uses a hand-written schema rather than `create_all`, the column might exist earlier — but Task 3's note strongly implies `create_all`.
- **`register_cli.py:181` path**: The context collector reports MISSING, but it only checked exact paths and the repo has 2735 entries. The file may exist under a different name or the collector may have missed it. I did not re-explore per instructions.
- **Task 4 Step 4's `prose` count vs. AC-02**: I'm assuming the proposals file contains one row per enabled CLI after Task 2's `_fetch_all_cli_rows` fix. If `run_pipeline` emits proposals for disabled rows too (before the fix lands), the count is inflated — but Task 2 ships before Task 4, so this should be fine. Low confidence on whether any other path emits proposals for non-enabled rows.
- **`sanity_fail_rate` denominator**: I don't know the shipped `main`'s current computation. The IMPORTANT finding assumes it's `fails / total_rows`; if it's `fails / len(report)`, the ambiguity is smaller but still present for the `--from-proposals` path.