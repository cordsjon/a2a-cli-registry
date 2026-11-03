# `launch_spec.smoke`

`health_status` says a row launches: `<argv> --help` exits 0 with the environment a launcher can send. `work_status` says it did one piece of real work. Only `probe --smoke` writes it, and it never writes `health_status`.

```json
{"argv": ["<abs-interpreter>", "<abs-script>", "convert", "in.svg", "-o", "out.pdf"],
 "fixture": "seed/smoke/<slug>/",
 "expect_exit": 0, "expect_stdout_re": "wrote out\\.pdf", "expect_file": "out.pdf",
 "side_effects": "none", "tier": "hand", "timeout": 60}
```

| Key | Meaning |
|---|---|
| `argv` | The command, absolute paths. Runs in a throwaway cwd with no `PYTHONPATH`. |
| `fixture` | File or directory copied into that cwd. Relative paths resolve from the repo root. The original is never touched. Optional. |
| `expect_exit` | Default 0. |
| `expect_stdout_re` | Searched in stdout only, capped at 64 KB. Optional. |
| `expect_file` | Must exist in the cwd afterwards. Optional. |
| `expect_file_re` | Searched in the content of `expect_file`, capped at 64 KB. Optional. |
| `negative` | Keys merged over the smoke so the tool runs cleanly but gives another answer. Read by `scripts/verify_smoke_seed.py`, not the runner. |
| `negative_why` | Why a seed has no `negative`. Not read by the runner. |
| `cwd` | Run here instead of the throwaway cwd. Only for `tier: project-tests`, whose suite needs its checkout. Optional. |
| `side_effects` | `none` or `tmp` run unattended. `network`, `spend`, `project-tests`, or anything else needs `--allow-network`. |
| `tier` | How much a pass proves: `hand` (real work), `project-tests` (the owning project's tests for this file), `version` (import and entry only). |
| `timeout` | Seconds. Default 60. |
| `note` | What a pass does not prove. Not read by the runner. |

Seeds live in `seed/smoke/<slug>.json`, and `scripts/apply_smoke_seed.py --apply` writes them to the rows. A fixture holding a `DECISIONS.md` must sit in a dot directory, or the real `decisions` sweep of `~/projects` reads it as a live ledger.

## Sandbox

On macOS every smoke without its own `cwd` runs under `sandbox-exec`: writes go only to the throwaway cwd, temp and cache directories, and the network is denied unless `side_effects` is `network` or `spend`. A tool that hardcodes a live path fails instead of touching it. Reads are not restricted. Elsewhere `side_effects` is only a promise. `sandbox-exec` is deprecated by Apple; if it goes away the smoke runs unsandboxed.

## Regression grade

`scripts/verify_smoke_seed.py --seed-dir <dir>` refuses a seed that passes without proving anything: it must pass twice, assert output that neither `--help` nor empty output satisfies, and fail on its `negative` case. Run it before applying a hand seed.

`probe --smoke` exits 1 when any smoke fails.

## Results

- `pass`: exit, regex and file all matched.
- `fail`: any of them did not, the command could not start, it timed out, or the spec is broken.
- `unknown`: the row has no smoke.

A smoke the run was not allowed to execute leaves the row as it is and lists it under `gated_network`. So a dated operator pass on a network smoke survives later sweeps.

`populate` keeps the `smoke` key when it rewrites `launch_spec`.

## HiQual

`scripts/parity_report.py` grades every in-scope row against five gates. A row is in scope when `enabled=1`, `health_status` is not `not_standalone` or `retired`, and `launch_spec` is valid JSON.

| Gate | Holds when |
|---|---|
| H1 classified | `health_status == 'healthy'` |
| H2 proven | `work_status == 'pass'`, `smoke.tier == 'hand'`, and the smoke has `negative` or `negative_why` |
| H3 watched | `work_checked_at` is less than 8 days old |
| H4 real work | `a2a_invokable == 0`, or `smoke.proves` names the row's main job (non-empty string) |
| H5 wired | the consumer index lists at least one consumer, or `launch_spec.operator_run` is `true` |

Some rows hold an `install:<url>` placeholder in `launch_spec`, which is not JSON. Any query over `launch_spec` must guard with `json_valid()` in SQL, or a try/except around `json.loads` in Python.
