# US-REMED-MODULEMODE-01 — Module-mode awareness for the remediation classifier

## Problem

`core/remediation/classify.py` classifies a CLI's probe-failure note into a
`RemediationProposal`. When the note is a `ModuleNotFoundError`/`No module
named 'X'`, the classifier currently has three outcomes:

- `X` is in `IMPORT_TO_PACKAGE` (a curated import-name -> PyPI-distribution
  map) -> `PIP_3RD_PARTY`, auto-installable.
- `X` is not in the map, and `_proven_local()` finds a sibling `X.py`/`X/`
  directory next to the CLI's own file -> `WRONG_CWD`.
- Otherwise -> `PIP_UNKNOWN`, treated as an unfixable third-party gap.

`_proven_local()` only looks *adjacent* to the failing file. It misses the
dominant real-world case: a local package (`syllabus_v2`, `engine`, `app`,
`meeting_processor`, ...) that lives at a **project root** several
directories above the CLI, importable via `python -m pkg.module` but not
`python file.py`. 46 CLIs in the live fleet are mislabeled `PIP_UNKNOWN` for
exactly this reason — they are not third-party gaps at all, just wrong
invocation mode.

`bridge/llm_infer.py` already solved this exact derivation for its own probe
ladder (`capture_help`'s module-mode branch): `_project_root()` walks up to
the nearest directory containing a root sentinel (`pyproject.toml`,
`setup.py`, `setup.cfg`, `.git`, `requirements.txt`); `_dotted_module()`
turns a file path relative to that root into a dotted module path. This
logic should be reused, not re-derived (abstract-on-third; also the ticket's
explicit instruction).

## Constraint: layering

`bridge/` already imports from `core/` (`bridge/llm_infer.py` imports
`core.capability.model`). Nothing in `core/` imports from `bridge/`.
`classify.py` is documented as pure — "NEVER runs a subprocess." The shared
logic must live in `core/`, so `classify.py` can depend on it without
reversing the existing dependency direction, and without pulling
`bridge/llm_infer.py`'s subprocess-oriented imports into a component that
promises purity.

## Design

**1. Extract shared pure module: `core/paths/module_root.py`**

Move `_project_root(path: str) -> str | None` and `_dotted_module(path: str,
root: str) -> str | None` out of `bridge/llm_infer.py` into this new module,
verbatim (same `_ROOT_SENTINELS` tuple, same relpath logic). Pure path math —
`os.path`/`os.sep` only, no subprocess, no network.

**2. Update `bridge/llm_infer.py`**

Replace its local `_project_root`/`_dotted_module` definitions with an import
from `core.paths.module_root`. No behavior change — `bridge`'s existing test
suite (`test_capture_help.py` etc.) is the regression check that this move
didn't alter anything.

**3. Extend `classify.py`'s missing-module branch**

In `classify_failure`, in the `MNFE_RE` match arm (currently: map lookup,
then `_proven_local`, then fall to `PIP_UNKNOWN`), add a third check between
"unmapped" and "give up":

```
if top in IMPORT_TO_PACKAGE:
    -> PIP_3RD_PARTY (unchanged)
if _proven_local(path, top):
    -> WRONG_CWD (unchanged, adjacent-file case)
if _proven_module_mode(path, dotted):
    -> WRONG_CWD, evidence names the python -m invocation
    (NEW: project-root case; note this takes the FULL dotted
    name from the regex match, e.g. "localpkg.missing", not
    the truncated `top` used by the two checks above)
-> PIP_UNKNOWN (unchanged, true fallback)
```

`_proven_module_mode(path, dotted)` (takes the full dotted name, NOT `top`):
- Guard first: if `path` is falsy, return `False` immediately — matches
  `_proven_local`'s existing empty-path guard (`classify.py:73`).
  `_project_root` walks up from `dirname(abspath(path))`; an empty path
  would resolve against the process cwd and could "prove" an unrelated
  module by accident.
- Call `_project_root(path)` from the new shared module. If no root is
  found, return `False`.
- **Dotted-submodule correctness:** the regex that extracts `top` already
  truncates a dotted failure (`No module named 'localpkg.missing'`) down to
  its first segment (`classify.py:88`, `top = m.group(1).split(".")[0]`).
  Truncating to `top` and then only checking `top/__init__.py` exists would
  wrongly call `localpkg.missing` "proven" when `localpkg` exists but
  `missing` genuinely doesn't. To avoid this false proof, `_proven_module_mode`
  takes the **full dotted name** from the regex match (not the
  pre-truncated `top`), and calls `_dotted_module`-style path construction
  in reverse: build the expected file path
  (`root/<part>/<part>/.../<last_part>.py` or
  `root/<part>/.../<last_part>/__init__.py`) from the *entire* dotted name
  and check that exact path exists. Only a full, exact match proves the
  specific missing thing is real — a partial match on just the top segment
  is not a proof.
- On proof, return the concrete dotted module name (not just a bool) so the
  caller can build the `python -m <dotted>` evidence string per AC-01. (This
  changes the earlier signature from bool-only to `str | None`, since a
  bare boolean can't carry the invocation string needed for evidence.)

Evidence string names the concrete fix so a human/SafeFixer downstream sees
the exact command: e.g. `"No module named 'syllabus_v2' | proven module-mode:
python -m syllabus_v2 (from <root>)"`.

**Guardrails (non-negotiable, from the ticket):**
- `IMPORT_TO_PACKAGE` is not touched — it stays PyPI-only. This fix never
  proposes installing a local import from PyPI.
- `_proven_module_mode` only fires on a demonstrated file/package on disk,
  same purity contract as the rest of `classify.py` (no subprocess), and
  only on an exact full-dotted-path match (no partial/prefix proofs).

## Testing

- New unit tests in `tests/test_remediation_classify.py` (the existing
  classifier test file — not a new location) covering:
  - A `ModuleNotFoundError` for a module that exists at a derived project
    root two directories up -> `WRONG_CWD`, evidence contains the `python -m`
    form.
  - A dotted failure (`No module named 'localpkg.missing'`) where `localpkg`
    exists at the root but `missing` does not -> still `PIP_UNKNOWN` (proves
    the full-dotted-path check, not just a top-segment check).
  - An empty `path` -> `_proven_module_mode` returns `False`/`None` without
    touching the filesystem outside the guard (regression for the empty-path
    guard).
  - The existing adjacent-file case still resolves via `_proven_local`
    (regression, unchanged behavior).
  - A genuinely unknown/unmappable import still falls to `PIP_UNKNOWN`
    (regression).
  - `IMPORT_TO_PACKAGE` membership still short-circuits before the new check
    (regression on `PIP_3RD_PARTY` path).
- `bridge/`'s existing test suite re-run after the extraction, to confirm the
  move didn't change `capture_help`'s behavior.

## Re-probing the 46 live-fleet rows (ticket AC-02 — in scope)

The ticket's AC-02 requires the 46 currently-affected CLIs to be re-probed
under module-mode once the classifier fix lands, flipping the ones that pass
to healthy — no PyPI install involved. This is part of `US-REMED-MODULEMODE-01`
and belongs in this change's scope as a distinct final step, run only after
the classifier fix (above) is implemented, tested, and reviewed:

1. Re-run classification (`classify_fleet`) against the live registry's
   current `unhealthy`/`pip-unknown` rows.
2. For rows now classified `WRONG_CWD` via the new module-mode path, re-probe
   each with the derived `python -m <dotted>` invocation (reusing the
   existing prober, not a new one).
3. Rows that pass re-probe flip to `healthy` in the registry; rows that still
   fail keep their prior status — this step only flips CLIs proven to work,
   never forces a status.
4. Take a DB backup before the run (same pattern as the earlier
   not-standalone flip: `cli-registry.db.bak-<timestamp>-pre-modulemode`),
   since this is a live-data mutation, not just a code change.

## Out of scope

- Any change to `IMPORT_TO_PACKAGE` or PyPI-mapping behavior.
- Re-probing CLIs that don't match the module-mode pattern (i.e., anything
  that isn't newly classified `WRONG_CWD` by this fix) — those stay exactly
  as they are today.
