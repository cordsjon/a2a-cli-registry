# Contributing

PRs welcome. Maintained by Jonas Cords.

## Dev setup
```bash
pip install -e ".[dev]"
pytest -q
```

## Adding a language adapter (the main contribution path)
Non-Python languages currently use a stub (declared-capabilities-required). To add
a real adapter, implement the `LanguageAdapter` protocol (`core/adapters/base.py`):
`detect(rec)`, `launch_spec(rec)`, `health_cmd(rec)`, `infer_capability(rec)`.
- Inference is **optional** and experimental — return `None` to require declared
  capabilities (recommended for a first adapter).
- Add a regression test mirroring `tests/test_adapters.py`.
- Declared capabilities ALWAYS win over inferred — do not override declared fields.

## Rules
- TDD: failing test → minimal impl → pass → commit.
- No new runtime deps without discussion (open an issue first).
- `pytest -q` green + coverage floor on `core/` before a PR.
