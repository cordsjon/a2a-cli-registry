## Findings — Codex

### [CRITICAL] Dry run violates the pre-approval write restriction
- What: Task 4 changes live capability data before operator approval, contradicting AC-05.
- Where: AC-05 says “no description or capability field of the live DB changes”; Task 4 says the dry run writes sanity fields and “placeholder capability rows.”
- Why it matters: Placeholder insertion writes capability fields, and sanity persistence updates existing rows before the gate. Task 5’s backup occurs after these mutations.
- Suggested fix: Run the dry run against a disposable SQLite snapshot. Persist placeholders, reviewed sanity results, descriptions, and capabilities to the live DB only after approval, with a backup taken before those writes.
- Confidence: high

### [CRITICAL] Resolving the decision as “stop” still opens the execution gate
- What: Task 5 checks that the question is no longer open without verifying that the operator approved committing.
- Where: Task 4 offers “commit from the reviewed file / tune and re-run / stop phase 0”; Task 5 Step 1 requires only `grep -c "Commit the reviewed backfill"` → `0`.
- Why it matters: Resolving the decision with either rejection option satisfies the documented execution condition. A failed decision-list command can also produce no matching output.
- Suggested fix: Retrieve the exact decision by its recorded question number, require successful retrieval, and verify both human resolution and the exact chosen outcome “commit from the reviewed file.” Every other outcome must block Task 5.
- Confidence: high

### [CRITICAL] Description protection can disappear after one populate run
- What: Task 3 preserves a backfilled description while allowing deletion of the capability row that holds its protection marker.
- Where: `test_populate_keeps_description_when_backfilled` seeds `description_provenance="llm"` without capability `provenance`; Step 3 protects capability rows only when their provenance belongs to `("manual", "static", "llm")`.
- Why it matters: A description-only backfilled row can retain its description on the first run, then lose `description_provenance` when its capability row is recreated. A subsequent populate run can overwrite that description, violating AC-06.
- Suggested fix: Carry `description_provenance` into replacement capability rows independently of capability ownership. Extend the supplied test to run populate twice and assert that both the description and its marker survive.
- Confidence: high

### [IMPORTANT] A clean working tree does not identify the approved artifacts
- What: Task 5 verifies that the JSONL files match current HEAD, not that they match the versions the operator reviewed.
- Where: Task 5 consumes files “at the HEAD the operator reviewed,” but Step 1 checks only `git status --porcelain backfill_proposals.jsonl sanity_report.jsonl`.
- Why it matters: Another commit can replace either file while leaving the working tree clean, allowing unreviewed content to be written under an earlier approval.
- Suggested fix: Record the Task 4 artifact commit and hashes of both files in the approval record. Before writing, verify those exact hashes or load both files directly from the approved commit.
- Confidence: high

### [IMPORTANT] Reviewed-file loading does not establish sanity coverage
- What: The replay path calculates a failure rate from the sibling report without specifying validation that its verdicts cover the proposals being written.
- Where: Task 2 Step 3 defines `_load_reviewed` as reading two JSONL files and derives `sanity_fail_rate` “from the loaded report.”
- Why it matters: An unrelated or incomplete report containing successful verdicts can satisfy the aggregate gate while proposals without verdicts are committed. Duplicate report entries can also distort the rate.
- Suggested fix: Validate schemas and unique slugs, require a verdict for every proposal being committed, and reject missing, conflicting, or unrelated verdicts. Calculate the failure rate over the validated proposal set and add negative tests for mismatched and incomplete reports.
- Confidence: high

### [IMPORTANT] Replay does not preserve the fallback-cap gate
- What: The new `--from-proposals` path omits the fallback-count evidence needed to enforce the stated `FALLBACK_CAP = 300` constraint.
- Where: Global Constraints says gates “stay as shipped,” including `FALLBACK_CAP = 300`; Task 2’s replay summary includes calibration and sanity failure rate but no fallback count.
- Why it matters: Skipping `run_pipeline` also skips any fallback limit enforced during generation. The specified replay path cannot distinguish an admissible run from artifacts produced by an over-limit run.
- Suggested fix: Persist a generation manifest containing completion status, fallback count, and artifact hashes. Require replay to validate that manifest and enforce the existing cap before backup or writes; test refusal of an over-limit manifest.
- Confidence: high

### [IMPORTANT] “Unknown purpose” descriptions count toward the prose target
- What: Both the proposal measurement and live acceptance query count the missing-source sentinel as a successful prose description.
- Where: Review Focus item 1 says to report these rows “instead of letting them count as prose”; Task 4 Step 4 counts descriptions containing a space and no `Error`, while the sentinel is `unknown purpose (<slug>)`.
- Why it matters: The 550-description threshold can pass partly because of descriptions that convey no capability. Printing a separate unknown count does not remove those rows from the success count.
- Suggested fix: Explicitly exclude the `unknown purpose` sentinel from both proposal and live prose counts, and align AC-02 with that predicate. Add a deterministic assertion that the sentinel never qualifies as usable prose.
- Confidence: high

NIT: (none).

## Self-flagged uncertainty

- The bundle omits implementation contents. Existing validation or gate helpers could mitigate the replay findings, but the specified replay path neither invokes nor requires such protections.
- The schema migration path is absent from the bundle. Adding `Capability.description_provenance` may require an upgrade for existing databases beyond the live registry; model initialization and migration excerpts are needed to assess this.
- The parent design and governance CLI implementation are not included. Their exact approval semantics cannot be verified; the approval findings above follow from the plan’s explicit options and commands.
