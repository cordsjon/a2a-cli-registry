# US-REMED-MODULEMODE-01 — Module-mode awareness for the remediation classifier

## Problem

`core/remediation/classify.py` classifies a CLI's probe-failure note into a
`RemediationProposal`. When the note is a `ModuleNotFoundError`/`No module
named 'X'`, the classifier currently has two outcomes:

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
if _proven_module_mode(path, top):
    -> WRONG_CWD, evidence names the python -m invocation
    (NEW: project-root case)
-> PIP_UNKNOWN (unchanged, true fallback)
```

`_proven_module_mode(path, top)` = call `_project_root(path)` from the new
shared module; if a root is found, check whether `top.py` or
`top/__init__.py` exists directly under that root. This is a **proof**, same
philosophy as the existing `_proven_local` docstring — only classify
`WRONG_CWD` when the module demonstrably exists at the derived root, never as
a guess.

Evidence string names the concrete fix so a human/SafeFixer downstream sees
the exact command: e.g. `"No module named 'syllabus_v2' | proven module-mode:
python -m syllabus_v2... from <root>"`.

**Guardrails (non-negotiable, from the ticket):**
- `IMPORT_TO_PACKAGE` is not touched — it stays PyPI-only. This fix never
  proposes installing a local import from PyPI.
- `_proven_module_mode` only fires on a demonstrated file/package on disk,
  same purity contract as the rest of `classify.py` (no subprocess).

## Testing

- New unit tests in `core/remediation/` (mirroring the existing
  `classify_failure` test file) covering:
  - A `ModuleNotFoundError` for a module that exists at a derived project
    root two directories up -> `WRONG_CWD`, evidence contains the `python -m`
    form.
  - The existing adjacent-file case still resolves via `_proven_local`
    (regression, unchanged behavior).
  - A genuinely unknown/unmappable import still falls to `PIP_UNKNOWN`
    (regression).
  - `IMPORT_TO_PACKAGE` membership still short-circuits before the new check
    (regression on `PIP_3RD_PARTY` path).
- `bridge/`'s existing test suite re-run after the extraction, to confirm the
  move didn't change `capture_help`'s behavior.

## Out of scope

- Re-probing the 46 live-fleet rows against this fix (that's the ticket's
  AC-02, a follow-up data-migration step after the code lands and is
  reviewed — not bundled into this change).
- Any change to `IMPORT_TO_PACKAGE` or PyPI-mapping behavior.
