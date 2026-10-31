# Does Real Work — Implementation Plan

> **For agentic workers:** REQUIRED: Use `/sh:execute` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every enabled registry row either proves it launches *and* does one piece of real work the way an agent would invoke it, or is visibly marked as not proven. "healthy" stops covering both.

**Architecture:** Two separate statuses. `health_status` keeps meaning "launches": the probe runs `env <argv> --help` with exactly the environment a launcher can send (no injected `PYTHONPATH`). A new `work_status` means "does real work": a per-row `launch_spec.smoke` command runs against a fixture in a throwaway cwd and is scored on exit code and an output regex. Smoke specs are authored in tiers: hand-written for the 6 agent-invokable rows, derived automatically where a parser exposes `--version`, proxied through the owning project's tests where those exist, and otherwise left `unknown` and filed per project.

**Tech Stack:** Python 3.13, SQLModel/SQLite (`~/.hermes/cli-registry.db`), pytest (`tests/`, `bridge/`), the hermes-adapter gateway for launch measurement.

**Operator rulings this plan rests on (2026-10-31):** bar = "does real work"; the 205 unregistered reference CLIs are a separate plan; gateway measurement may run now, serially. Decisions the spec left to me are in DECISIONS.md Q35.

**Baseline (measured 2026-10-31 22:3x, do not re-derive):** enabled 590; healthy 492 (python 483, shell 8, node 1); healthy rows whose `launch_spec.env` carries `PYTHONPATH` 466; healthy rows with no `argv` 9; healthy python rows the classifier calls `no_parser` 82, `subapp` 23; `a2a_invokable` 6 (`ytx invoice-fetcher decisions_cli gmail_attachments consigliere-gaps wa-bridge`); stale 8; not_standalone 90.

---

## Chunk 1: "healthy" means "launches the way an agent launches it"

### Task 1: Probe with the launcher's environment

The probe injects `PYTHONPATH` (`core/adapters/python_adapter.py:142-149`); Tirith blocks launchers from sending it (DECISIONS Q32). So a row can be green and fail on import at launch. Q33 moved projects into their own venvs with `.pth` files, which makes the injection unnecessary. Remove it, re-probe, and fix what turns red with a `.pth`, never by restoring the injection.

**Files:**
- Modify: `core/adapters/python_adapter.py:84-100` (`launch_fields`, stop writing `env.PYTHONPATH`) and `:142-149` (`health_env` returns `{}`)
- Test: `tests/test_python_adapter.py` (create if absent; follow `tests/test_prober.py` style)

- [ ] **Step 1: Failing test**

```python
from core.adapters.python_adapter import PythonAdapter
from core.adapters.base import CliRecord

def _rec(tmp_path):
    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / ".venv/bin/python").write_text("")
    script = tmp_path / "tool.py"; script.write_text("import argparse\n")
    return CliRecord(slug="t", lang="python", path=str(script), bucket=None, project=None,
                     description="", declared_capability=None, source_class=None, source_run_id=None)

def test_probe_env_matches_launch_env(tmp_path):
    a = PythonAdapter(); rec = _rec(tmp_path)
    assert a.health_env(rec) == {}
    assert "env" not in a.launch_fields(rec)
```

- [ ] **Step 2: Run it** — `.venv/bin/python -m pytest tests/test_python_adapter.py -q` — expect FAIL on `health_env` returning a `PYTHONPATH` dict.
- [ ] **Step 3: Implement** — `health_env` returns `{}`; in `launch_fields` delete the `fields["env"] = {...}` branch. Leave `_project_pythonpath` in place only if another caller uses it (`grep -n _project_pythonpath core`); otherwise delete it.
- [ ] **Step 4: Suite** — `.venv/bin/python -m pytest tests/ bridge/ -q` — expect the 677 to pass minus any test that asserted the old `env` field; update those assertions, do not skip them.
- [ ] **Step 5: Measure before writing** — `REGISTRY_DB=$HOME/.hermes/cli-registry.db .venv/bin/a2a-cli-registry probe --dry-run --config $PWD/examples/reference-fleet/config.toml` from a throwaway cwd. Record the healthy→unhealthy count. **Do not run a live sweep while a job runs on 20_CONSIGLIERE** (operator, 2026-10-31); use `probe --slug` from Task 7 for named rows until lifted.
- [ ] **Step 6: Fix each newly red row with a `.pth`** in its project venv (`zz_registry_project_root.pth`, pattern in `~/.hermes/reports/cli-registry-deps-install-2026-10-31.json`), re-probe, until the count is 0 or each remainder has a named cause.
- [ ] **Step 7: Commit** — `git commit -F - -- core/adapters/python_adapter.py tests/` with subject `fix(prober): probe with the environment a launcher can send`.

### Task 2: Shell and node rows get an `argv`

9 healthy rows have no `argv`, so launchers fall back to old forms (`compose_command`, hermes-adapter `cli_registry.py:863-866`).

**Files:** Modify `core/adapters/stub_adapter.py` (add `launch_fields` returning `{"argv": [path]}` when `os.access(path, os.X_OK)`); Test `tests/test_stub_adapter.py`.

- [ ] Failing test: executable path → `argv == [path]`; non-executable → no `argv`.
- [ ] Implement, suite, re-probe the 9 rows with `probe --slug`, assert `SELECT COUNT(*) FROM cli WHERE enabled=1 AND health_status='healthy' AND json_extract(launch_spec,'$.argv') IS NULL` → 0.
- [ ] Commit `feat(adapters): executable rows carry argv`.

### Task 3: A healthy row without a parser is not a CLI

82 healthy python rows are `no_parser`: they are green because old sweeps executed them for real. The prober keeps their status (`prober.py:216-218`, Q27). Under this plan's bar that status is a lie. Set them `not_standalone` and clear `a2a_invokable`.

**Files:** Modify `core/prober/prober.py:211-221`; Test `tests/test_prober.py` (add next to the existing Phase-1 tests).

- [ ] Failing test: a healthy `no_parser` row leaves `probe_fleet` with `health_status == "not_standalone"`, `not_standalone is True`, and is not executed (use the existing fake-adapter pattern in the file).
- [ ] Implement: replace the `skipped_no_parser` branch with the `not_standalone_rows.append(cli)` path; keep the summary key, now counting rows demoted.
- [ ] Suite; run against the live DB once with `--dry-run`, expect `skipped_no_parser 82 → not_standalone +82`; then live (Task 1 Step 5 caveat applies).
- [ ] Commit `fix(prober): parser-less rows are not_standalone, never healthy`.

**Review of chunk 1:** after Tasks 1–3, `health_status='healthy'` means: has a parser, has an `argv`, exits 0 on `--help` with no injected environment. Expected healthy count drops; that is the point. Record the new baseline in the story comment.

---

## Chunk 2: `work_status`, a second status that cannot be confused with the first

### Task 4: Schema and the `smoke` convention

**Files:** Modify `core/store/migrations.py` (pattern at `:18-28`), `core/models.py` (`Cli`: `work_status: str = "unknown"`, `work_checked_at: Optional[float] = None`); Test `tests/test_migrations.py`.

`launch_spec.smoke` convention (document in `docs/launch-spec.md`, create):

```json
{"argv": ["<abs-interpreter>", "<abs-script>", "convert", "in.svg", "-o", "out.pdf"],
 "fixture": "seed/smoke/<slug>/",
 "expect_exit": 0, "expect_stdout_re": "wrote out\\.pdf", "expect_file": "out.pdf",
 "side_effects": "none", "tier": "hand|version|project-tests"}
```

`side_effects` ∈ `none | tmp | network | spend`. `tier` says how much the pass proves.

- [ ] Failing test: `migrate(con)` on a DB without the columns adds both; running twice is a no-op (`PRAGMA table_info(cli)` lists each once).
- [ ] Implement with the existing `_has_column` guard; suite; commit `feat(store): work_status columns`.

### Task 5: `core/prober/smoke.py`

- [ ] Failing tests (`tests/test_smoke.py`, fake scripts under `tmp_path`): pass on matching exit+regex+file; fail on wrong exit; fail on missing `expect_file`; `unknown` when no `smoke` key; refuses `side_effects in {network, spend}` unless `allow_network=True`; fixture is copied, the original untouched (assert mtime/hash); runs in a throwaway cwd with no `PYTHONPATH` (assert via a script that prints `os.environ.get("PYTHONPATH")`).
- [ ] Implement `run_smoke(spec: dict, *, timeout: float, allow_network: bool = False) -> str` reusing `probe_one`'s `_kill_tree` and output cap (import, do not copy — grep before define).
- [ ] Suite; commit `feat(prober): smoke runner`.

### Task 6: `probe --smoke`, `probe --slug`, `--allow-network`

`probe --slug` also retires the scratch `probe_slugs.py` filed as debt on 2026-10-31.

**Files:** Modify `core/cli/main.py:115-131, 378-390`; `core/prober/prober.py` (a `probe_slugs(session, adapters, clock, slugs, ...)` entry that shares Phase 1/2 with `probe_fleet` — refactor the loop body into a helper rather than duplicating it); Test `tests/test_cli.py`.

- [ ] Failing tests: `--slug a --slug b` touches only those rows; `--smoke` writes `work_status`/`work_checked_at` and never `health_status`; without `--allow-network` a `network` smoke stays `unknown` and is listed in the summary.
- [ ] Implement; suite; commit `feat(cli): probe --slug and --smoke`.

### Task 7: Counts that show both statuses

**Files:** Modify `core/catalog/queries.py` (overview counts), `core/tui/overview.py` (one column), the `probe` summary print in `core/cli/main.py`.

- [ ] Failing test in `tests/test_cli.py`: `overview` output contains `works: pass N fail N unknown N`.
- [ ] Implement, suite, commit `feat(overview): work_status counts`. Restart the service on :9109/:9113 (`launchctl kickstart -k gui/$(id -u)/ai.hermes.cli-registry`) and `curl` health → 200.

---

## Chunk 3: Author smoke specs, by tier

### Task 8: Tier `hand` — the 6 agent-invokable rows

**Files:** Create `seed/smoke/<slug>.json` + fixtures; Create `scripts/apply_smoke_seed.py` (upserts `launch_spec.smoke` by slug, `--dry-run` default, refuses a slug not in the DB).

| slug | smoke command | side_effects | note |
|---|---|---|---|
| `ytx` | transcript of a fixture `.vtt` file, not a URL | none | network verb stays unproven |
| `decisions_cli` | `open -p <fixture DECISIONS.md>` | none | |
| `invoice-fetcher` | its offline/list verb on a fixture inbox dump | none | if no offline verb exists, `network` and operator-run |
| `gmail_attachments` | `network` | network | operator runs `--allow-network` once; pass recorded with date |
| `wa-bridge` | `status` against the bridge | network | same |
| `consigliere-gaps` | blocked | — | 20_CONSIGLIERE off limits until the operator lifts it |

- [ ] One failing test per seed in `tests/test_smoke_seed.py`: the seed parses, `fixture` exists, `argv[0]` is absolute and executable.
- [ ] Author seeds; `scripts/apply_smoke_seed.py --apply`; `probe --smoke --slug <each>`; expect `pass` for the `none` rows.
- [ ] Commit per slug: `feat(smoke): <slug>`.

### Task 9: Tier `version` — derive from the parser

For healthy python rows whose `--help` lists `--version`, smoke = `--version`, `expect_exit 0`, `tier: version`. It proves import plus entry; it is labelled so nobody reads it as more.

**Files:** Create `scripts/derive_smoke.py --tier version` (runs `env <argv> --help` serially in a throwaway cwd, regex `(^|\s)--version\b`, writes seeds under `seed/smoke/derived/`); Test `tests/test_derive_smoke.py` with two fake scripts.

- [ ] Failing test; implement; run; record how many of the ~378 standalone rows got a seed (unmeasured until run); apply; `probe --smoke`; commit `feat(smoke): derive --version smokes`.

### Task 10: Tier `project-tests` — proxy through the owning project's suite

For rows still `unknown` whose project has a test file importing or invoking the script: smoke = the project's canonical test command restricted to that file, `tier: project-tests`, `side_effects: tmp`.

**Files:** Extend `scripts/derive_smoke.py --tier project-tests` (`git grep -l <script-basename> -- 'tests/**' 'test/**'` in the row's project root); Test with a fixture repo under `tmp_path`.

- [ ] Failing test; implement; run; apply; `probe --smoke` (long: batch it, `feedback_batch_long_runs`); commit.

### Task 11: The remainder becomes visible work

- [ ] Create `scripts/smoke_gaps.py`: per project, rows with `work_status='unknown'`, printed as a table and as `backlog_add.py`-ready story bodies.
- [ ] File one story per project with ≥10 unknown rows (`backlog_add.py add --path "$(readlink -f ~/projects/00_Governance/BACKLOG.md)"`), each with AC-01 "every row in the list has a `smoke` with tier `hand`" and the row list in the body. Below 10 rows, a TODO line in the project's BACKLOG.
- [ ] Commit `docs(smoke): gap report`.

**Review of chunk 3:** after Task 11 no row is silently unproven. Expected shape (guess, to be measured): hand 5, version 100–200, project-tests 50–150, unknown 150–300 across ~25 projects. The `unknown` tail is the months-long part and is now a backlog, not a hidden property of "healthy".

---

## Chunk 4: Launch through the real gateway, serially

### Task 12: `scripts/launch_measure.py`

Promotes the scratch harness filed as debt in findings `r-774a46b91`/`r-c414d6b`. Samples healthy rows by seed, sends `<command> --help` through `_run_step` on the live gateway one at a time, scores on the `EXIT=` marker (never on gateway `success`, gotcha 11), writes `~/.hermes/reports/cli-registry-launch-<date>.json` with the same keys as the 2026-10-31 artefact (`date, method, sample_seed, rows`).

- [ ] Failing test with a fake gateway client: a row whose output lacks `EXIT=0` scores fail; the report file has the keys above.
- [ ] Implement; run `--sample 60 --seed 20261101`; every fail becomes a row fix (`.pth`, argv, or demotion) before the next sample.
- [ ] Full run over all healthy rows as a background batch (`run_in_background`, per `feedback_batch_long_runs`), after the Consigliere job ends if the gateway is shared; record pass rate in the story comment.
- [ ] Commit `feat(scripts): launch_measure`.

### Task 13: Close the loop in the backlog

- [ ] New story in `00_Governance/BACKLOG.md`: `US-CLIREG-WORKS-01` with ACs = Tasks 1–12's measurable end states (healthy ⇒ parser+argv+help-without-env; `work_status` exists; 6 invokable rows `pass` or operator-dated network pass; gap stories filed; gateway pass rate recorded). File through `backlog_add.py`, never by hand-editing State.
- [ ] Each task's commit subject carries `US-CLIREG-WORKS-01` so the status-alignment hook can tick ACs.

---

## Not in this plan (deliberately)

- The 205 unregistered reference CLIs: separate plan (operator, 2026-10-31).
- `a2a_invokable` policy: whether more than 6 rows should be invokable is a product decision, not a correctness fix. Flag it when Task 11's gap report lands.
- `q3_tts` pin, termux rows, whatsapp gateway platform: carried from the 2026-10-31 21:37 handover, unchanged.
- Stale 8 and enabled-but-`not_standalone` 90: they are already excluded from "healthy"; a lifecycle pass is a separate small task.

## Cost, honestly

Chunk 1: one session. Chunk 2: one to two sessions. Chunk 3 Tasks 8–10: two to three sessions plus operator time for the two network smokes. Task 11's tail: unmeasured; hundreds of hand-written smokes across ~25 projects, done project by project as those projects are touched. Chunk 4: one session plus gateway spend (unmeasured per call).
