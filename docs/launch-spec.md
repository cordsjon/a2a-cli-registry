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
| `side_effects` | `none` or `tmp` run unattended. `network`, `spend`, or anything else needs `--allow-network`. |
| `tier` | How much a pass proves: `hand` (real work), `project-tests` (the owning project's tests for this file), `version` (import and entry only). |
| `timeout` | Seconds. Default 60. |
| `note` | What a pass does not prove. Not read by the runner. |

Seeds live in `seed/smoke/<slug>.json`, and `scripts/apply_smoke_seed.py --apply` writes them to the rows. A fixture holding a `DECISIONS.md` must sit in a dot directory, or the real `decisions` sweep of `~/projects` reads it as a live ledger.

## Results

- `pass`: exit, regex and file all matched.
- `fail`: any of them did not, the command could not start, it timed out, or the spec is broken.
- `unknown`: the row has no smoke.

A smoke the run was not allowed to execute leaves the row as it is and lists it under `gated_network`. So a dated operator pass on a network smoke survives later sweeps.

`populate` keeps the `smoke` key when it rewrites `launch_spec`.
