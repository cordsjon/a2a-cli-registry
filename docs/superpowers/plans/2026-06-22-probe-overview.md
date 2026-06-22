# probe + overview Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-shot `probe` command (writes real CLI health, wires the reserved prober config keys live) and a read-only `overview` command (renders the catalog with `rich`), plus per-hop health annotation in the planner.

**Architecture:** Producer/presenter split — `probe` runs the existing `probe_fleet` and persists health; `overview` reads existing catalog queries and renders via an isolated `core/tui/` module. The planner gains a per-hop health annotation (no ranking change). Health-status casing is normalized to lowercase across the codebase. `probe` writes are guarded against cross-process SQLite contention via the existing `with_file_lock` + a DB busy-timeout.

**Tech Stack:** Python 3.11+, SQLModel/SQLite, argparse CLI, `rich` (NEW runtime dep, approved), pytest. venv is uv-managed.

**Spec:** `docs/superpowers/specs/2026-06-22-a2a-cli-registry-probe-overview-design.md`

## Global Constraints

- venv is uv-managed. Run tests with `.venv/bin/python -m pytest`. **No pip.** `rich` is the ONLY new package (approved); add it to `pyproject.toml` AND install into the venv via `uv pip install rich` (or `uv sync`) — confirm the install command with the operator if `uv pip` is unavailable.
- Commit by explicit path: `git commit -m "<msg>" -- <paths>`. **Never whole-index.**
- Trailer on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Branch off `master` (currently @ `6058a0b`); do not work on `master` directly.
- Baseline before changes: **136 tests passing.** No regression permitted.
- No bare `except Exception` that swallows (the existing prober `except Exception` for per-CLI isolation is pre-existing and in-scope-untouched). No bare `.json()` after fetch.
- `rich` may be imported ONLY in `core/tui/`. An isolation guard test enforces this.
- Health states are lowercase canonical: `healthy` / `unhealthy` / `stale` / `unknown`.
- `do-no-harm`: do not change planner *ranking*, the `serve`/MCP surfaces, or existing command behavior beyond what each task specifies.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Declare `rich` dep; version → `1.1.0`. |
| `core/store/db.py` | Add SQLite busy-timeout to the engine. |
| `core/prober/prober.py` | `probe_fleet` gains `probe_timeout`/`max_output_bytes`/`staleness_ttl` params + `enabled` filter; forwards to `probe_one`; lowercase health states. |
| `core/catalog/queries.py` | Lowercase `cli_health` fallback; enrich `plan_cli_chain` hops with `health_status`. |
| `core/cli/main.py` | `_probe_config(cfg)` reader; `probe` + `overview` command branches + choices. |
| `core/tui/__init__.py`, `core/tui/overview.py` | `render_overview(clis, graph, *, console=None)` — the only `rich`-importing module. |
| `examples/reference-fleet/config.toml` | Promote 4 prober keys reserved→live under `[probe]`. |
| `README.md`, `SECURITY.md`, `CHANGELOG.md` | Document commands, health semantics, trust boundary, config. |
| tests (`test_prober.py`, `test_cli.py`, `test_tui.py` new, `test_planner.py`, `test_packaging.py`, `test_models.py`) | Behavioral coverage + updated casing assertions. |

---

## Task 1: Dependency + version bump + DB busy-timeout

Foundation: declare `rich`, bump version, add the SQLite busy-timeout that the `probe` concurrency policy needs. Grouped because all three are tiny config/setup edits gated by the same packaging test.

**Files:**
- Modify: `pyproject.toml` (dependencies + version)
- Modify: `core/store/db.py:17-21` (engine connect_args)
- Test: `tests/test_packaging.py` (version assertion)

**Interfaces:**
- Produces: `rich` importable in the venv; `init_db` engine has a busy-timeout so concurrent writers wait instead of failing.

- [ ] **Step 1: Update the version assertion test (it currently pins 1.0.0)**

In `tests/test_packaging.py`, change `test_version_is_1_0_0`:
```python
def test_version_is_1_1_0():
    cfg = tomllib.loads(_PYPROJECT.read_text())
    assert cfg["project"]["version"] == "1.1.0"
```

- [ ] **Step 2: Add a failing test for the rich dependency**

Add to `tests/test_packaging.py`:
```python
def test_rich_is_declared_runtime_dependency():
    cfg = tomllib.loads(_PYPROJECT.read_text())
    deps = cfg["project"]["dependencies"]
    assert any(d == "rich" or d.startswith("rich>") or d.startswith("rich=")
               or d.startswith("rich ") for d in deps)
```

- [ ] **Step 3: Run the two tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_packaging.py -k "version or rich" -v`
Expected: FAIL (version is 1.0.0; no rich dep).

- [ ] **Step 4: Edit pyproject.toml**

In `pyproject.toml`: set `version = "1.1.0"`. Add to the `dependencies` list (after the `mcp` pin):
```toml
  "rich>=13,<15",
```

- [ ] **Step 5: Install rich into the venv**

Run: `uv pip install 'rich>=13,<15'` (if `uv pip` is unavailable, run `uv sync` or ask the operator). Verify: `.venv/bin/python -c "import rich; print(rich.__version__)"`

- [ ] **Step 6: Add busy-timeout to init_db**

In `core/store/db.py`, change the `create_engine` call (lines 17-21) to add a SQLite busy timeout so a write that hits a read-lock from another process waits rather than raising `SQLITE_BUSY`:
```python
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 5.0},
        poolclass=StaticPool,
    )
```
(The `timeout` connect arg is SQLite's busy-timeout in seconds; StaticPool + in-memory `sqlite://` tests are unaffected since they never contend cross-process.)

- [ ] **Step 7: Run packaging tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_packaging.py -v && .venv/bin/python -m pytest -q`
Expected: packaging tests PASS; full suite 136 passing (no regression — the busy-timeout doesn't change in-memory test behavior).

- [ ] **Step 8: Commit**

```bash
git commit -m "build: add rich dep, bump to 1.1.0, add SQLite busy-timeout

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" -- pyproject.toml core/store/db.py tests/test_packaging.py
```

---

## Task 2: probe_fleet — config passthrough, enabled gate, lowercase casing

Extend `probe_fleet` to accept + forward the 3 probe knobs, gate on `enabled`, and normalize ALL health states to lowercase. The casing change breaks existing uppercase assertions — update them here (this is the single source of the casing invariant).

**Files:**
- Modify: `core/prober/prober.py` (`probe_fleet` signature + body, lines 113-188)
- Modify: `tests/test_prober.py` (existing uppercase assertions + `_seed_cli` default + new tests)
- Modify: `tests/test_models.py:7` (uppercase `health_status="UNKNOWN"` literal in a Cli fixture)
- Modify: `core/catalog/queries.py:37` (the `cli_health` `"UNKNOWN"` fallback → lowercase)

**Interfaces:**
- Consumes: `probe_one(cmd, timeout=10.0, max_output_bytes=_DEFAULT_MAX_OUTPUT_BYTES)` (unchanged, `core/prober/prober.py:39`).
- Produces: `probe_fleet(session, adapters, clock, concurrency=8, probe_timeout=10.0, max_output_bytes=_DEFAULT_MAX_OUTPUT_BYTES, staleness_ttl=_STALE_TTL_SECONDS) -> dict`. Health states emitted are lowercase: `healthy`/`unhealthy`/`stale`/`unknown`. Skips `Cli.enabled is False`.

- [ ] **Step 1: Update existing tests for lowercase + write new failing tests**

In `tests/test_prober.py`:
- Change `_seed_cli`'s default `health_status="UNKNOWN"` → `health_status="unknown"`.
- Line 152: `assert bad.health_status == "UNKNOWN"` → `"unknown"`.
- Line 168: `assert cli.health_status == "STALE"` → `"stale"`.
- Line 182: `assert cli.health_status == "UNKNOWN"` → `"unknown"`.
In `tests/test_models.py` line 7: change the `health_status="UNKNOWN"` literal → `"unknown"` (it's a model-construction fixture; lowercase keeps it consistent with the new canonical form).

Then ADD new tests to `tests/test_prober.py` (the `_TrueAdapter`, `_RaisingAdapter`, `_seed_cli`, `db`, `clock` helpers already exist):
```python
def test_probe_fleet_custom_staleness_ttl_marks_stale(db, clock):
    """A custom (small) staleness_ttl marks STALE a CLI that would NOT be stale
    under the default — proves the param drives the cutoff, not the constant."""
    # 90s old: stale under ttl=60, NOT stale under the default 3600
    old_ts = clock.now() - 90
    _seed_cli(db, "edge", lang="unknown-lang",
              health_checked_at=old_ts, health_status="healthy")
    probe_fleet(db, [_TrueAdapter()], clock, staleness_ttl=60)
    db.expire_all()
    assert db.get(Cli, "edge").health_status == "stale"

def test_probe_fleet_default_ttl_does_not_mark_recent_stale(db, clock):
    """The SAME 90s-old CLI stays 'unknown' under the default TTL."""
    old_ts = clock.now() - 90
    _seed_cli(db, "edge2", lang="unknown-lang",
              health_checked_at=old_ts, health_status="healthy")
    probe_fleet(db, [_TrueAdapter()], clock)  # default staleness_ttl
    db.expire_all()
    assert db.get(Cli, "edge2").health_status == "unknown"

def test_probe_fleet_forwards_timeout_and_max_output(db, clock, monkeypatch):
    """probe_timeout + max_output_bytes are forwarded into probe_one."""
    captured = {}
    def fake_probe_one(cmd, timeout=10.0, max_output_bytes=65536):
        captured["timeout"] = timeout
        captured["max_output_bytes"] = max_output_bytes
        return "healthy"
    monkeypatch.setattr("core.prober.prober.probe_one", fake_probe_one)
    _seed_cli(db, "x", lang="true")
    probe_fleet(db, [_TrueAdapter()], clock, probe_timeout=3.0, max_output_bytes=1234)
    assert captured == {"timeout": 3.0, "max_output_bytes": 1234}

def test_probe_fleet_concurrency_sets_max_workers(db, clock, monkeypatch):
    """probe_concurrency sets ThreadPoolExecutor(max_workers=...)."""
    captured = {}
    import core.prober.prober as prober_mod
    RealPool = prober_mod.ThreadPoolExecutor
    def spy_pool(max_workers=None, **kw):
        captured["max_workers"] = max_workers
        return RealPool(max_workers=max_workers, **kw)
    monkeypatch.setattr(prober_mod, "ThreadPoolExecutor", spy_pool)
    _seed_cli(db, "y", lang="true")
    probe_fleet(db, [_TrueAdapter()], clock, concurrency=3)
    assert captured["max_workers"] == 3

def test_probe_fleet_skips_disabled_cli(db, clock, monkeypatch):
    """A CLI with enabled=False is never spawned (probe_one not called for it)."""
    spawned = []
    def fake_probe_one(cmd, timeout=10.0, max_output_bytes=65536):
        spawned.append(cmd)
        return "healthy"
    monkeypatch.setattr("core.prober.prober.probe_one", fake_probe_one)
    cli = _seed_cli(db, "off", lang="true")
    cli.enabled = False
    db.add(cli); db.commit()
    summary = probe_fleet(db, [_TrueAdapter()], clock)
    assert spawned == []                 # never spawned
    assert summary["probed"] == 0
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_prober.py -k "custom_staleness or default_ttl or forwards_timeout or concurrency_sets or skips_disabled" -v`
Expected: FAIL (probe_fleet lacks the params/gate; staleness uses the constant; states are uppercase).

- [ ] **Step 3: Update probe_fleet in core/prober/prober.py**

Replace the signature (line 113) and the relevant body lines:
```python
def probe_fleet(session, adapters, clock, concurrency: int = 8,
                probe_timeout: float = 10.0,
                max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
                staleness_ttl: int = _STALE_TTL_SECONDS) -> dict:
```
- After `clis = session.exec(select(Cli)).all()`, filter disabled CLIs:
```python
    clis = [c for c in clis if c.enabled]
```
  (keep selecting all rows then filter in Python, to avoid changing the query shape — `Cli.enabled` exists at `core/models.py:17`).
- Change the submit (line 154) to forward the knobs:
```python
            pool.submit(probe_one, cmd, probe_timeout, max_output_bytes): cli.slug
```
- The fallback on a crashed future (line 163) stays `"unhealthy"` (already lowercase).
- In Phase 3, change the no_cmd loop's UPPERCASE states to lowercase and use the param:
```python
    for cli in no_cmd:
        checked = cli.health_checked_at
        if checked is not None and (now - checked) > staleness_ttl:
            cli.health_status = "stale"
            session.add(cli)
            counts["stale"] += 1
        else:
            cli.health_status = "unknown"
            session.add(cli)
            counts["unknown"] += 1
```
(The `to_probe` loop already writes lowercase `healthy`/`unhealthy` from `probe_one`; the `counts` dict keys are already lowercase.)

- [ ] **Step 4: Lowercase the cli_health fallback in queries.py**

In `core/catalog/queries.py` line 37, change the null-CLI fallback:
```python
        return {"slug": slug, "health_status": "unknown"}
```

- [ ] **Step 5: Run prober + queries + models tests**

Run: `.venv/bin/python -m pytest tests/test_prober.py tests/test_models.py -v`
Expected: PASS (existing updated to lowercase + 5 new pass).

- [ ] **Step 6: Full suite — catch any other uppercase assumption**

Run: `.venv/bin/python -m pytest -q`
Expected: 136 + 5 new passing. If any test fails on an uppercase health string, update that assertion to lowercase (the canonical form) — note which in the commit.

- [ ] **Step 7: Commit**

```bash
git commit -m "feat(prober): config-driven timeout/output/staleness, enabled gate, lowercase health states

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" -- core/prober/prober.py core/catalog/queries.py tests/test_prober.py tests/test_models.py
```

---

## Task 3: Planner per-hop health annotation

Each plan hop gains the hop CLI's `health_status`. Done in `queries.plan_cli_chain` (keep `search.py` DB-light per the spec): after `_plan` returns Chains, enrich each hop dict with the slug's health from the DB.

**Files:**
- Modify: `core/catalog/queries.py:47-50` (`plan_cli_chain`)
- Test: `tests/test_planner.py` (hop carries health) — but note `plan_cli_chain` is in queries; an existing planner/queries test file covers it. Add the test where `plan_cli_chain` is already tested (search `tests/` for `plan_cli_chain`; if only `core/planner/search.py` is tested directly, add a new `tests/test_plan_health.py`).

**Interfaces:**
- Consumes: `_plan(...)` returns `Chain` objects whose `.hops` are dicts `{slug, side_effect, provenance, [from/to/via_type]}` (`core/planner/search.py:127`). `Cli.health_status` per slug.
- Produces: `plan_cli_chain` output hops each include `"health_status"`.

- [ ] **Step 1: Locate where plan_cli_chain is tested**

Run: `grep -rn "plan_cli_chain" tests/`
Use the file that already exercises it (likely `tests/test_catalog.py` or `tests/test_planner.py`). Put the new test there. If none exists, create `tests/test_plan_health.py` importing `from core.catalog.queries import plan_cli_chain` and seeding via the patterns in `tests/test_catalog.py`.

- [ ] **Step 2: Write the failing test**

Seed a 2-CLI chain (a producer + consumer with a shared type so an edge forms — mirror an existing planner test's seeding), set one CLI's `health_status="unhealthy"`, plan the chain, assert each hop dict has `health_status` and the unhealthy CLI's hop reflects it:
```python
def test_plan_hops_carry_health_status(db):
    # ... seed two CLIs forming one chain (reuse existing seeding helper) ...
    # set the first hop's CLI health to a known value
    cli = db.get(Cli, "<first-slug>")
    cli.health_status = "unhealthy"; db.add(cli); db.commit()
    chains = plan_cli_chain(db, ["file:pdf"], ["text:summary"])
    assert chains, "expected at least one chain"
    for hop in chains[0]["hops"]:
        assert "health_status" in hop
    first = chains[0]["hops"][0]
    assert first["health_status"] == "unhealthy"
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest <that test> -v`
Expected: FAIL (`KeyError: 'health_status'`).

- [ ] **Step 4: Enrich hops in plan_cli_chain**

In `core/catalog/queries.py`, update `plan_cli_chain` to annotate each hop with its slug's health (one DB lookup per distinct slug):
```python
def plan_cli_chain(session, goal_inputs, goal_outputs, allow_side_effects=None):
    chains = _plan(session, goal_inputs, goal_outputs, allow_side_effects or [])
    health_by_slug = {}
    def _health(slug):
        if slug not in health_by_slug:
            c = session.get(Cli, slug)
            health_by_slug[slug] = c.health_status if c else "unknown"
        return health_by_slug[slug]
    out = []
    for ch in chains:
        hops = [{**hop, "health_status": _health(hop["slug"])} for hop in ch.hops]
        out.append({"slugs": ch.slugs, "length": ch.length,
                    "side_effect_count": ch.side_effect_count, "hops": hops})
    return out
```
Ensure `Cli` is imported in `queries.py` (it imports models already — verify the import line includes `Cli`).

- [ ] **Step 5: Run the test + planner suite**

Run: `.venv/bin/python -m pytest tests/test_planner.py <that test> -v`
Expected: PASS. Ranking unchanged (no Chain.sort_key edit) — existing planner tests stay green.

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(planner): annotate plan hops with per-hop health_status (no ranking change)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" -- core/catalog/queries.py <test file>
```

---

## Task 4: Config promotion — [probe] live table

Move the 4 prober keys out of `[thresholds.reserved_prober]` into a live `[probe]` table; update the config-honesty guard tests.

**Files:**
- Modify: `examples/reference-fleet/config.toml`
- Modify: `tests/test_cli.py` (config-honesty guards)

**Interfaces:**
- Produces: config exposes `[probe]` with `probe_timeout`, `max_probe_output_bytes`, `probe_concurrency`, `staleness_ttl`; `[thresholds.reserved_prober]` no longer exists; `[planner.reserved]` still exists.

- [ ] **Step 1: Update the config-honesty guard tests**

In `tests/test_cli.py`, find `test_reference_config_has_no_dead_keys` and the load test. Add/adjust:
```python
def test_reference_config_probe_section_is_live():
    cfg = load_config(str(Path(__file__).parent.parent / "examples/reference-fleet/config.toml"))
    assert cfg["probe"]["max_probe_output_bytes"] == 65536
    assert cfg["probe"]["probe_timeout"] == 10
    assert cfg["probe"]["probe_concurrency"] == 8
    assert cfg["probe"]["staleness_ttl"] == 3600

def test_reference_config_reserved_prober_section_removed():
    text = (Path(__file__).parent.parent / "examples/reference-fleet/config.toml").read_text()
    assert "reserved_prober" not in text          # renamed to [probe]
    assert "[planner.reserved]" in text           # planner stays reserved
```
The existing `test_load_config_reads_planner_bounds_and_vocab` reads `cfg["planner"]["reserved"]["max_chain_depth"]` — leave it; `[planner.reserved]` is unchanged.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k "probe_section or reserved_prober_section" -v`
Expected: FAIL (`[probe]` doesn't exist yet; `reserved_prober` still present).

- [ ] **Step 3: Edit examples/reference-fleet/config.toml**

Replace the `[thresholds.reserved_prober]` block with a live `[probe]` table. The file currently has (from the v1.1 work): a header, `cli_audit_path`, `[thresholds] mass_removal`, `[thresholds.reserved_prober]` (4 keys), `[planner.reserved]`, `[vocabulary]`. Change to:
```toml
# --- live ---
[probe]
probe_timeout = 10            # per-CLI health-probe wall-time budget (seconds)
max_probe_output_bytes = 65536  # cap on captured probe output (bytes)
probe_concurrency = 8        # parallel probes
staleness_ttl = 3600         # unprobeable CLI older than this reads 'stale' (seconds)
```
Remove the `# reserved — ... probe/health command lands` comment and the `[thresholds.reserved_prober]` table. Keep `[thresholds] mass_removal`, `[planner.reserved]`, `[vocabulary]`, and the live/reserved header comment (now only planner is reserved).

- [ ] **Step 4: Run config tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k "config" -v && .venv/bin/python -m pytest -q`
Expected: PASS, no regression.

- [ ] **Step 5: Commit**

```bash
git commit -m "docs(config): promote prober keys reserved->live under [probe]

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" -- examples/reference-fleet/config.toml tests/test_cli.py
```

---

## Task 5: probe command

Wire the `probe` CLI command: read `[probe]` config (one helper), call `probe_fleet` under a file lock, print the summary.

**Files:**
- Modify: `core/cli/main.py` (choices, `_probe_config`, `probe` branch)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `probe_fleet(session, adapters, clock, concurrency, probe_timeout, max_output_bytes, staleness_ttl)` (Task 2); `with_file_lock(path)` (`core/store/db.py:43`); `load_config`, `_RealClock`, `init_db`, `get_session`, `PythonAdapter` (all in `main.py`).
- Produces: `a2a-cli-registry probe` writes health + prints JSON summary.

- [ ] **Step 1: Write failing tests**

In `tests/test_cli.py` (reuse `_write_fleet_and_cfg` + spy patterns already there):
```python
def _capture_probe_fleet(monkeypatch):
    captured = {}
    def fake_probe_fleet(session, adapters, clock, concurrency=8,
                         probe_timeout=10.0, max_output_bytes=65536,
                         staleness_ttl=3600):
        captured.update(concurrency=concurrency, probe_timeout=probe_timeout,
                        max_output_bytes=max_output_bytes, staleness_ttl=staleness_ttl)
        return {"probed": 0, "healthy": 0, "unhealthy": 0, "stale": 0, "unknown": 0}
    monkeypatch.setattr("core.cli.main.probe_fleet", fake_probe_fleet)
    return captured

def test_probe_passes_config_values(tmp_path, monkeypatch, capsys):
    captured = _capture_probe_fleet(monkeypatch)
    cfg = _write_fleet_and_cfg(tmp_path, extra=(
        "[probe]\nprobe_timeout = 3\nmax_probe_output_bytes = 222\n"
        "probe_concurrency = 2\nstaleness_ttl = 99\n"))
    rc = main(["probe", "--db", str(tmp_path / "r.db"), "--config", str(cfg)])
    assert rc == 0
    assert captured == {"concurrency": 2, "probe_timeout": 3,
                        "max_output_bytes": 222, "staleness_ttl": 99}
    out = _json.loads(capsys.readouterr().out)
    assert out["probed"] == 0

def test_probe_falls_back_to_defaults_when_no_probe_section(tmp_path, monkeypatch):
    captured = _capture_probe_fleet(monkeypatch)
    cfg = _write_fleet_and_cfg(tmp_path)  # no [probe]
    rc = main(["probe", "--db", str(tmp_path / "r.db"), "--config", str(cfg)])
    assert rc == 0
    assert captured == {"concurrency": 8, "probe_timeout": 10.0,
                        "max_output_bytes": 65536, "staleness_ttl": 3600}
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k "probe_passes or probe_falls" -v`
Expected: FAIL (`probe` not a valid command choice).

- [ ] **Step 3: Add probe to choices + the _probe_config reader + the branch**

In `core/cli/main.py`:
- Add `"probe"` and `"overview"` to the `choices=[...]` list (line 47). (Add both now so Task 6/7 don't re-touch this line.)
- Import the lock + probe_fleet at the top with the other core imports:
```python
from core.store.db import init_db, get_session, with_file_lock
from core.prober.prober import probe_fleet
```
- Add the config reader near `_mass_removal_threshold`:
```python
_PROBE_DEFAULTS = {"probe_timeout": 10.0, "max_probe_output_bytes": 65536,
                   "probe_concurrency": 8, "staleness_ttl": 3600}

def _probe_config(cfg: dict) -> dict:
    """Read the [probe] table, falling back to code defaults per key."""
    p = cfg.get("probe", {})
    return {k: p.get(k, d) for k, d in _PROBE_DEFAULTS.items()}
```
- Add the `probe` branch (after the `populate` branch, before the final `graph` fallthrough). `init_db` already ran at line 76 for non-discover/audit commands:
```python
    if args.command == "probe":
        cfg = load_config(args.config)
        pc = _probe_config(cfg)
        with with_file_lock(args.db):
            with get_session(engine) as session:
                summary = probe_fleet(
                    session, [PythonAdapter()], _RealClock(),
                    concurrency=pc["probe_concurrency"],
                    probe_timeout=pc["probe_timeout"],
                    max_output_bytes=pc["max_probe_output_bytes"],
                    staleness_ttl=pc["staleness_ttl"],
                )
        print(json.dumps(summary))
        return 0
```

- [ ] **Step 4: Run probe tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k "probe" -v && .venv/bin/python -m pytest -q`
Expected: PASS, no regression.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(cli): add probe command (config-driven, file-locked health sweep)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" -- core/cli/main.py tests/test_cli.py
```

---

## Task 6: overview renderer (core/tui/overview.py)

The `rich` render function, fully isolated and unit-testable on plain data.

**Files:**
- Create: `core/tui/__init__.py`, `core/tui/overview.py`
- Test: `tests/test_tui.py` (new)

**Interfaces:**
- Produces: `render_overview(clis: list[dict], graph: list[dict], *, console=None) -> None`. `clis` are enriched rows: `{slug, lang, description, health_status, capabilities}` where `capabilities` is a list of `{intent_tags, input_types, output_types, side_effect, confidence}`. `graph` is a list of `{from, to, via_type}`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_tui.py`:
```python
from rich.console import Console
from core.tui.overview import render_overview

def _console():
    return Console(record=True, width=120)

_CLI = {"slug": "pdf2text", "lang": "python", "description": "pdf to text",
        "health_status": "healthy",
        "capabilities": [{"intent_tags": ["convert"], "input_types": ["file:pdf"],
                          "output_types": ["text:doc"], "side_effect": "none",
                          "confidence": "declared"}]}

def test_renders_cli_slug_and_health():
    c = _console(); render_overview([_CLI], [], console=c)
    text = c.export_text()
    assert "pdf2text" in text and "healthy" in text

def test_renders_capability_confidence_word():
    c = _console(); render_overview([_CLI], [], console=c)
    assert "declared" in c.export_text()

def test_renders_inferred_distinctly():
    inferred = {**_CLI, "capabilities": [{**_CLI["capabilities"][0], "confidence": "inferred"}]}
    c = _console(); render_overview([inferred], [], console=c)
    assert "inferred" in c.export_text()

def test_renders_edge_line():
    c = _console()
    render_overview([_CLI], [{"from": "pdf2text", "to": "summarize", "via_type": "text:doc"}], console=c)
    text = c.export_text()
    assert "pdf2text" in text and "summarize" in text and "text:doc" in text

def test_empty_catalog_message():
    c = _console(); render_overview([], [], console=c)
    assert "empty" in c.export_text().lower()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tui.py -v`
Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Create the module**

`core/tui/__init__.py`: empty file.
`core/tui/overview.py`:
```python
"""Read-only rich render of the catalog. The ONLY module importing rich."""
from rich.console import Console
from rich.table import Table

_HEALTH_STYLE = {"healthy": "green", "unhealthy": "red",
                 "stale": "yellow", "unknown": "dim"}


def render_overview(clis: list[dict], graph: list[dict], *, console=None) -> None:
    console = console or Console()
    if not clis:
        console.print("Registry is empty — run `populate` first.")
        return

    cli_table = Table(title="CLIs")
    for col in ("slug", "lang", "health", "description"):
        cli_table.add_column(col)
    for c in clis:
        hs = (c.get("health_status") or "unknown").lower()
        style = _HEALTH_STYLE.get(hs, "dim")
        cli_table.add_row(c["slug"], c.get("lang", ""),
                          f"[{style}]{hs}[/{style}]", c.get("description", ""))
    console.print(cli_table)

    cap_table = Table(title="Capabilities")
    for col in ("slug", "intent", "in -> out", "side_effect", "confidence"):
        cap_table.add_column(col)
    for c in clis:
        for cap in c.get("capabilities", []):
            conf = cap.get("confidence", "")
            conf_style = "cyan" if conf == "declared" else "magenta"
            cap_table.add_row(
                c["slug"],
                ", ".join(cap.get("intent_tags", [])),
                f"{', '.join(cap.get('input_types', []))} -> {', '.join(cap.get('output_types', []))}",
                cap.get("side_effect", ""),
                f"[{conf_style}]{conf}[/{conf_style}]",
            )
    console.print(cap_table)

    if graph:
        edge_table = Table(title="Call-graph edges")
        for col in ("from", "to", "via_type"):
            edge_table.add_column(col)
        for e in graph:
            edge_table.add_row(e["from"], e["to"], e["via_type"])
        console.print(edge_table)
    else:
        console.print("No edges.")
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_tui.py -v`
Expected: PASS. (rich markup tags like `[green]` do NOT appear in `export_text()`; the words `healthy`/`declared`/`inferred` do.)

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(tui): rich overview renderer (isolated, data-driven)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" -- core/tui/__init__.py core/tui/overview.py tests/test_tui.py
```

---

## Task 7: overview command + rich import-isolation guard

Wire the `overview` CLI branch (reads + enriches + renders) and add the guard test that `rich` lives only in `core/tui/`.

**Files:**
- Modify: `core/cli/main.py` (`overview` branch + `--query` arg)
- Test: `tests/test_cli.py`, `tests/test_packaging.py` (isolation guard)

**Interfaces:**
- Consumes: `search_clis`, `describe_cli`, `cli_graph` (`core/catalog/queries.py`); `render_overview` (Task 6).
- Produces: `a2a-cli-registry overview [--query ...]`.

- [ ] **Step 1: Write failing tests**

In `tests/test_cli.py`:
```python
def test_overview_renders_populated_catalog(tmp_path, capsys):
    # reuse the populate path to seed a real CLI, then overview it
    fleet = tmp_path / "fleet.json"
    fleet.write_text(_json.dumps({"clis": [
        {"slug": "pdf2text", "lang": "python", "path": "/x/pdf2text",
         "capability": {"intent_tags": ["convert"], "input_types": ["file:pdf"],
                        "output_types": ["text:doc"], "side_effect": "none"}}]}))
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'cli_audit_path = "{fleet}"\n[vocabulary]\nregistered = ["file:pdf","text:doc"]\n[vocabulary.aliases]\n')
    db = tmp_path / "r.db"
    assert main(["populate", "--db", str(db), "--config", str(cfg)]) == 0
    capsys.readouterr()  # drop populate output
    rc = main(["overview", "--db", str(db)])
    assert rc == 0
    assert "pdf2text" in capsys.readouterr().out

def test_overview_empty_db(tmp_path, capsys):
    rc = main(["overview", "--db", str(tmp_path / "empty.db")])
    assert rc == 0
    assert "empty" in capsys.readouterr().out.lower()
```
In `tests/test_packaging.py`:
```python
def test_rich_imported_only_in_core_tui():
    import pathlib
    root = pathlib.Path(__file__).parent.parent / "core"
    offenders = []
    for p in root.rglob("*.py"):
        if "tui" in p.parts:
            continue
        if "import rich" in p.read_text() or "from rich" in p.read_text():
            offenders.append(str(p))
    assert offenders == [], f"rich imported outside core/tui/: {offenders}"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k overview tests/test_packaging.py -k rich_imported -v`
Expected: FAIL (overview branch missing; guard passes trivially now but will protect later — if it fails, a stray import exists).

- [ ] **Step 3: Add the --query arg + overview branch**

In `core/cli/main.py`:
- Add the arg near the others (after `--port`): `parser.add_argument("--query", default="")`.
- Add the `overview` branch (after `probe`, uses `engine` from line 76):
```python
    if args.command == "overview":
        from core.tui.overview import render_overview
        with get_session(engine) as session:
            rows = queries.search_clis(session, args.query)
            for r in rows:
                desc = queries.describe_cli(session, r["slug"])
                r["capabilities"] = desc["capabilities"] if desc else []
            graph = queries.cli_graph(session)
        render_overview(rows, graph)
        return 0
```
(Import `render_overview` lazily inside the branch so a missing `rich` only affects `overview`, not the whole CLI — and the isolation guard stays satisfied since the import is in `main.py` referencing the tui module, not `rich` directly.)

- [ ] **Step 4: Run tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k overview tests/test_packaging.py -v && .venv/bin/python -m pytest -q`
Expected: PASS, no regression.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(cli): add overview command + rich import-isolation guard

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" -- core/cli/main.py tests/test_cli.py tests/test_packaging.py
```

---

## Task 8: Documentation — README, SECURITY, CHANGELOG

Document the two commands, health-state semantics + agent contract, the probe trust boundary, and the config promotion.

**Files:**
- Modify: `README.md`, `SECURITY.md`, `CHANGELOG.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: README — commands + health table + config**

In `README.md`:
- Add `probe` and `overview` to the command list / Quickstart (e.g. `a2a-cli-registry probe` after `populate`; `a2a-cli-registry overview` as the human view).
- Add a "Health states" table (from the spec Component 6): healthy/unhealthy/stale/unknown with meaning + recommended agent action, including the `stale` = "unprobeable, last seen > TTL" caveat.
- Update the Configuration table: the 4 `[probe]` keys are now live; note `staleness_ttl` affects agent-visible health.

- [ ] **Step 2: SECURITY.md — probe trust boundary**

Add a note: `probe` executes each enabled CLI's health_cmd under prober isolation (timeout + SIGKILL + bounded output). It trusts operator-populated, `enabled=True` entries; disable a CLI to exclude it from probing. Isolation bounds resource blast radius, not authorization.

- [ ] **Step 3: CHANGELOG.md — Unreleased entries**

Under `## [Unreleased]`: Added `probe` + `overview` commands, `rich` runtime dep; Changed health states to lowercase canonical form + `[probe]` config table now live; planner hops now carry per-hop health.

- [ ] **Step 4: Sanity-check docs render + full suite still green**

Run: `.venv/bin/python -m pytest -q`
Expected: full suite green (docs don't affect tests, but confirm nothing drifted).

- [ ] **Step 5: Commit**

```bash
git commit -m "docs: probe/overview commands, health-state semantics, trust boundary

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" -- README.md SECURITY.md CHANGELOG.md
```

---

## Final Verification (after all tasks)

```bash
cd ~/projects/a2a-cli-registry
.venv/bin/python -m pytest -q                       # all green (~136 + ~20 new)

# probe writes health that overview + get_cli_health surface (manual smoke):
#   populate a fleet, run `probe`, run `overview` (see health badges),
#   confirm get_cli_health via a quick A2A/MCP call returns non-unknown.

# config override provably works:
#   set [probe] max_probe_output_bytes low, confirm it reaches probe_one (test);
# rich isolated:
grep -rln "import rich\|from rich" core/ | grep -v "core/tui/"   # expect empty
# casing canonical:
grep -rn '"STALE"\|"UNKNOWN"\|"HEALTHY"' core/                   # expect empty
```

**Done when:** probe produces lowercase health; overview renders it via rich; plan hops carry health; the 4 `[probe]` keys are live (only `[planner.reserved]` reserved); rich confined to core/tui/; version 1.1.0; full suite green.
