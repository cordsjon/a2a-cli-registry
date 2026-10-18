## Findings — Codex

CRITICAL: (none).

### [IMPORTANT] Populate still overwrites manually owned descriptions
- What: Task 3 protects descriptions marked `llm` but leaves descriptions marked `manual` subject to feed replacement.
- Where: Global Constraints defines `description_provenance = 'manual'` as operator ownership; Task 3 Step 3 assigns the feed description “only when no `old_caps` row has `description_provenance == "llm"`.”
- Why it matters: A manual description that survives the backfill writer can be overwritten by the next populate run, even while its capability row and manual ownership marker remain.
- Suggested fix: Protect descriptions marked either `manual` or `llm`, independently of capability provenance. Add a repeated-populate test proving that a manual description and its marker survive.
- Confidence: high

### [IMPORTANT] Reviewed artifacts are pinned, but their destination records are not
- What: Replay validates artifact identity without checking whether surviving CLI records still represent the tools reviewed during generation.
- Where: Task 4 generates from a snapshot during a “multi-hour run”; Task 5 Step 1 checks artifact hashes; Task 2 checks only whether each proposal slug still exists.
- Why it matters: A CLI can change path, language, source, or enabled state before approval. Replay can then install an old description and sanity verdict on the changed tool. Newly enabled records can also remain outside the reviewed set and prevent AC-03.
- Suggested fix: Record generation-time fingerprints of relevant CLI fields and source content alongside the reviewed artifacts. Under the registry lock, reject changed surviving targets and report newly enabled targets requiring another run. Preserve the explicitly specified handling of deleted slugs.
- Confidence: high

### [IMPORTANT] Ordinary commit mode still writes before acquiring the lock and taking its backup
- What: The proposed protection covers the ordinary commit tail, while its preceding `run_pipeline` still persists sanity data and creates placeholders.
- Where: Task 4 states that the dry run writes sanity fields and placeholder rows; Task 2 Step 3 says “Nothing else about the loops changes” and moves only the shipped `--commit` tail, “`backup_db`, `write_commit`,” inside the lock.
- Why it matters: Calling the retained `--commit` mode without `--from-proposals` still mutates its target before backup and outside the registry lock. Its backup therefore cannot restore the original state, contradicting Task 2’s promise that “the first live write of any kind sits behind the backup.”
- Suggested fix: Make generation defer database persistence in ordinary commit mode, then perform backup, sanity persistence, and proposal writes under the lock. Alternatively, require replay for commits. Add a test asserting that no target mutation occurs before backup and lock acquisition.
- Confidence: high

### [IMPORTANT] The designated rollback snapshot is not run-unique
- What: The timestamped backup can be overwritten by a retry within the same minute.
- Where: Task 5 Step 2 uses `STAMP=$(date +%Y%m%d-%H%M)` and names `registry-prewrite-$STAMP.db` as “the rollback artifact”; the architecture panel describes this as a “run-unique backup.”
- Why it matters: If the first attempt fails between the two transactions, a same-minute retry can replace the original rollback snapshot with the partially written database—the exact failure the additional backup is intended to prevent.
- Suggested fix: Allocate a collision-resistant snapshot filename, refuse replacement, and retain the first attempt’s snapshot as the rollback artifact across retries. Record its path before starting the first write.
- Confidence: high

### [IMPORTANT] Preflight prose measurement does not predict the acceptance result
- What: `prose_writable` uses different matching semantics from the acceptance query and omits valid descriptions that will remain untouched.
- Where: Task 4 Step 4 uses Python `"Error" not in d`, `"Traceback" not in d`, and excludes every manual-description slug; it states that below 550 “AC-02 cannot be met.” Task 5 Step 3 uses SQLite `NOT LIKE` and counts all qualifying enabled descriptions.
- Why it matters: With SQLite’s default ASCII case-insensitive `LIKE`, a description containing lowercase `error` can pass the Python preflight but fail acceptance. Conversely, 545 qualifying writable descriptions plus 12 qualifying preserved manual descriptions would satisfy AC-02, despite the preflight declaring a shortfall.
- Suggested fix: Calculate the projected post-write description set using the writer’s ownership and target-selection rules, including preserved descriptions, and evaluate it with the exact acceptance SQL predicates. Test lowercase error text and preserved manual prose.
- Confidence: high

### [IMPORTANT] The live-write procedure can conceal an unsuccessful commit
- What: The documented command and expected result do not require a successful writer exit.
- Where: Task 5 Step 2 pipes the writer into `tail -5` and expects “no `REFUSED` line; both backup files exist.”
- Why it matters: A writer exception after backup or sanity persistence can satisfy both checks. The pipeline normally returns `tail`’s success status, and truncation can hide relevant output. The plan explicitly acknowledges that failure between the two transactions leaves partial state.
- Suggested fix: Capture the writer’s exit status independently of output truncation, retain its complete log, and stop on any nonzero exit before acceptance or bookkeeping. Specify that failed acceptance checks also block foundation closure and identify the retained rollback snapshot.
- Confidence: high

NIT: (none).

## Self-flagged uncertainty

- The bundle omits implementation bodies. The ordinary-commit finding follows the stated persistence behavior and prescribed changes; an existing, unmentioned commit-mode persistence guard could alter it.
- Database connection settings are absent. A deliberate `case_sensitive_like` setting could remove the case-matching discrepancy, but not the omission of preserved manual descriptions.
- Migration support for existing databases other than the named live registry is not supplied. The bundle establishes that the live database already has `description_provenance`, but does not establish compatibility for other existing databases.
- Source fingerprints and generation inputs are not included. Their precise scope needs implementation excerpts; the replay requirement currently specifies only slug existence.
