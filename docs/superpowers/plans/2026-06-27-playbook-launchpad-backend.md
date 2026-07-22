# Playbook Launchpad — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a curated "playbook" layer to the a2a-cli-registry so a natural-language goal can be matched to one or more named, runnable CLI recipes — exposed via A2A/MCP ops and a `/playbooks` HTTP catalog — that two native clients (macOS Swift appbar, HermesAndroid tab) will later consume.

**Architecture:** A playbook's source of truth is a `SKILL.md` file (Agent Skills open standard) holding a CWL-style ordered step list that references registry CLI slugs. A rebuildable SQLite index (FTS5 + optional vectors) ranks playbooks for a goal. Two new `Op`s (`list_playbooks`, `suggest_playbook`) plug into the existing `OPS` dispatch table — they reuse the already-shipped `plan_cli_chain` typed-graph path-finder for drift validation. Nothing in this plan executes a CLI; the registry returns data only (mirrors the existing `SendMessage` contract: "data only; never executes a CLI").

**Tech Stack:** Python 3.11+, FastAPI, SQLModel/SQLite, FTS5 (built-in), pytest. One new runtime dep only if Phase 4 (vectors) is built: none in Phases 1–3.

## Global Constraints

- Python floor: **3.11+** (repo uses `tomllib`; `str | None` unions in signatures).
- Dependency limit: **no new runtime deps in Phases 1–3.** FTS5 ships with SQLite. `sentence-transformers`/`sqlite-vec` are Phase 4 only and gated behind a separate approval (per CLAUDE.md "No new packages without approval").
- New ops follow the existing `Op` dataclass: `canonical_id` snake_case, `input_schema` JSON-Schema, `handler(session, **input)`. Register in `OPS` list — never edit `handle_a2a`.
- Atomic writes only (tempfile + `Path.replace`). No bare `except Exception`. Cross-platform locks via `portalocker` (already a dep), never `fcntl`.
- The registry **returns data, never executes a CLI.** A playbook "run" is out of scope for the registry backend — execution belongs to the client/bot. `suggest_playbook` and `list_playbooks` return recipe data + a resolved (validated) plan; they do not spawn processes.
- Test command: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest <path> -v`. Testpaths are `["tests", "bridge"]`.
- Drift rule (Dagster-style, not mtime): a playbook is **stale** if any referenced CLI's interface signature `sha256(sorted(input_types) + "|" + sorted(output_types))` differs from the signature cached in the playbook's index row at author/reindex time.
- Favourites are **client-side state**, NOT registry state. No favourites table in this plan.

---

## File Structure

| File | Responsibility |
|---|---|
| `core/playbooks/__init__.py` | package marker |
| `core/playbooks/skillmd.py` | Parse one `SKILL.md` → `Playbook` dataclass (frontmatter + steps). Pure, no DB. |
| `core/playbooks/loader.py` | Discover `playbooks/*/SKILL.md`, parse all, return `list[Playbook]`. |
| `core/playbooks/signature.py` | Compute a CLI's interface signature + a playbook's drift status against the live registry. |
| `core/playbooks/index.py` | Build/rebuild the FTS5 index table; keyword-retrieve top-N candidate slugs for a query. |
| `core/playbooks/queries.py` | `list_playbooks(session, ...)` and `suggest_playbook(session, ...)` op handlers. Compose loader + index + signature + existing `plan_cli_chain`. |
| `core/ops_registry.py` (modify) | Append two `Op`s to `OPS`. |
| `core/server/app.py` (modify) | Add `GET /playbooks` and `GET /playbooks/{slug}` HTTP routes. |
| `playbooks/svg-enrich-publish/SKILL.md` | One real seed playbook (proves the loader + drift end-to-end). |
| `tests/playbooks/test_*.py` | One test module per source module above. |

A `Playbook` is a frozen dataclass (defined in Task 1, consumed everywhere):

```python
@dataclass(frozen=True)
class PlaybookStep:
    id: str            # e.g. "s1"
    cli: str           # registry CLI slug
    inputs: dict       # {port_name: "raw" | "s1/out"}  CWL-style source binding
    out_type: str      # declared output port type

@dataclass(frozen=True)
class Playbook:
    slug: str
    description: str
    tags: tuple[str, ...]
    allowed_tools: tuple[str, ...]   # CLI slugs this recipe may use
    steps: tuple[PlaybookStep, ...]
    status: str = "draft"            # draft | verified
```

---

## Task 1: SKILL.md parser → Playbook dataclass

**Files:**
- Create: `core/playbooks/__init__.py` (empty)
- Create: `core/playbooks/skillmd.py`
- Test: `tests/playbooks/__init__.py` (empty), `tests/playbooks/test_skillmd.py`

**Interfaces:**
- Produces: `PlaybookStep`, `Playbook` (dataclasses above); `parse_skillmd(text: str, slug: str) -> Playbook`.

- [ ] **Step 1: Write the failing test**

```python
# tests/playbooks/test_skillmd.py
from core.playbooks.skillmd import parse_skillmd, Playbook, PlaybookStep

SAMPLE = """---
name: svg-enrich-publish
description: Enrich a batch of SVGs and publish to Etsy
tags: [svg, etsy, batch]
allowed-tools: [svg-enrich, care-card, etsy-export]
status: verified
---

## Steps

1. svg-enrich  in: {raw: raw}      out: EnrichedSvg
2. care-card   in: {doc: s1/out}   out: CareCards
3. etsy-export in: {cards: s2/out} out: Listing
"""

def test_parses_frontmatter_and_steps():
    pb = parse_skillmd(SAMPLE, slug="svg-enrich-publish")
    assert isinstance(pb, Playbook)
    assert pb.slug == "svg-enrich-publish"
    assert pb.description.startswith("Enrich a batch")
    assert pb.tags == ("svg", "etsy", "batch")
    assert pb.allowed_tools == ("svg-enrich", "care-card", "etsy-export")
    assert pb.status == "verified"
    assert len(pb.steps) == 3
    assert pb.steps[0] == PlaybookStep(id="s1", cli="svg-enrich", inputs={"raw": "raw"}, out_type="EnrichedSvg")
    assert pb.steps[1].inputs == {"doc": "s1/out"}

def test_missing_frontmatter_raises():
    import pytest
    with pytest.raises(ValueError, match="frontmatter"):
        parse_skillmd("no frontmatter here", slug="x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_skillmd.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.playbooks.skillmd'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/playbooks/skillmd.py
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlaybookStep:
    id: str
    cli: str
    inputs: dict
    out_type: str


@dataclass(frozen=True)
class Playbook:
    slug: str
    description: str
    tags: tuple = ()
    allowed_tools: tuple = ()
    steps: tuple = ()
    status: str = "draft"


_FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
# matches: "1. svg-enrich  in: {raw: raw}   out: EnrichedSvg"
_STEP_RE = re.compile(
    r"^\s*\d+\.\s+(?P<cli>[\w-]+)\s+in:\s*\{(?P<inputs>[^}]*)\}\s+out:\s*(?P<out>\w+)\s*$"
)


def _parse_inline_list(value: str) -> tuple:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    items = [v.strip() for v in value.split(",") if v.strip()]
    return tuple(items)


def _parse_inputs(raw: str) -> dict:
    out = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        k, _, v = pair.partition(":")
        out[k.strip()] = v.strip()
    return out


def parse_skillmd(text: str, slug: str) -> Playbook:
    m = _FM_RE.match(text)
    if not m:
        raise ValueError(f"SKILL.md for {slug!r} has no YAML frontmatter")
    fm_block, body = m.group(1), m.group(2)

    fm = {}
    for line in fm_block.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip()

    steps = []
    for i, line in enumerate(body.splitlines(), start=0):
        sm = _STEP_RE.match(line)
        if not sm:
            continue
        steps.append(
            PlaybookStep(
                id=f"s{len(steps) + 1}",
                cli=sm.group("cli"),
                inputs=_parse_inputs(sm.group("inputs")),
                out_type=sm.group("out"),
            )
        )

    return Playbook(
        slug=slug,
        description=fm.get("description", ""),
        tags=_parse_inline_list(fm.get("tags", "")),
        allowed_tools=_parse_inline_list(fm.get("allowed-tools", "")),
        steps=tuple(steps),
        status=fm.get("status", "draft"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_skillmd.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add core/playbooks/__init__.py core/playbooks/skillmd.py tests/playbooks/__init__.py tests/playbooks/test_skillmd.py
git commit -m "feat(playbooks): SKILL.md parser -> Playbook dataclass

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Loader — discover and parse all playbooks

**Files:**
- Create: `core/playbooks/loader.py`
- Create: `playbooks/svg-enrich-publish/SKILL.md` (seed)
- Test: `tests/playbooks/test_loader.py`

**Interfaces:**
- Consumes: `parse_skillmd`, `Playbook` (Task 1).
- Produces: `load_playbooks(root: str = "playbooks") -> list[Playbook]` (sorted by slug; skips dirs without a SKILL.md).

- [ ] **Step 1: Write the failing test**

```python
# tests/playbooks/test_loader.py
from pathlib import Path
from core.playbooks.loader import load_playbooks

def _write(root: Path, slug: str, body: str):
    d = root / slug
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body)

def test_loads_all_skillmd_sorted(tmp_path):
    _write(tmp_path, "b-pb", "---\ndescription: B\ntags: [x]\nallowed-tools: [foo]\n---\n1. foo in: {a: raw} out: T\n")
    _write(tmp_path, "a-pb", "---\ndescription: A\ntags: [y]\nallowed-tools: [bar]\n---\n1. bar in: {a: raw} out: T\n")
    (tmp_path / "not-a-playbook").mkdir()   # no SKILL.md -> skipped
    pbs = load_playbooks(str(tmp_path))
    assert [p.slug for p in pbs] == ["a-pb", "b-pb"]
    assert pbs[0].description == "A"

def test_empty_root_returns_empty(tmp_path):
    assert load_playbooks(str(tmp_path)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.playbooks.loader'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/playbooks/loader.py
from pathlib import Path
from core.playbooks.skillmd import parse_skillmd, Playbook


def load_playbooks(root: str = "playbooks") -> list[Playbook]:
    base = Path(root)
    if not base.is_dir():
        return []
    out: list[Playbook] = []
    for child in sorted(base.iterdir()):
        skill = child / "SKILL.md"
        if not skill.is_file():
            continue
        out.append(parse_skillmd(skill.read_text(), slug=child.name))
    out.sort(key=lambda p: p.slug)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_loader.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Create the seed playbook**

```bash
mkdir -p playbooks/svg-enrich-publish
```

```markdown
<!-- playbooks/svg-enrich-publish/SKILL.md -->
---
name: svg-enrich-publish
description: Enrich a batch of SVGs and publish to Etsy
tags: [svg, etsy, batch, enrich, publish]
allowed-tools: [svg-enrich, care-card, etsy-export]
status: draft
---

## Steps

1. svg-enrich  in: {raw: raw}      out: EnrichedSvg
2. care-card   in: {doc: s1/out}   out: CareCards
3. etsy-export in: {cards: s2/out} out: Listing
```

(Note: `status: draft` because the referenced CLI slugs are illustrative; flip to `verified` only after Task 5's drift check passes against real registry slugs.)

- [ ] **Step 6: Commit**

```bash
git add core/playbooks/loader.py tests/playbooks/test_loader.py playbooks/svg-enrich-publish/SKILL.md
git commit -m "feat(playbooks): loader discovers SKILL.md files + seed playbook

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Drift signature — detect when a referenced CLI's interface changed

**Files:**
- Create: `core/playbooks/signature.py`
- Test: `tests/playbooks/test_signature.py`

**Interfaces:**
- Consumes: `Playbook`, `PlaybookStep` (Task 1); the `Cli` and `Capability` SQLModel tables (`core/playbooks` reads them via the session).
- Produces:
  - `cli_signature(session, slug: str) -> str | None` — `sha256` hex of a CLI's sorted input/output types, or `None` if the CLI is absent.
  - `playbook_drift(session, pb: Playbook) -> dict` — `{"status": "ok"|"stale"|"broken", "stale_clis": [...], "missing_clis": [...]}`. `broken` = a referenced CLI is absent; `stale` = present but signature changed vs. a provided baseline; `ok` = all present (baseline comparison handled by index in Task 4).

> NOTE: In this task `playbook_drift` reports `broken`/`missing` only (no baseline yet). Baseline (cached signature) comparison is wired in Task 4 where the index stores it. This keeps Task 3 testable against a live DB without the index.

- [ ] **Step 1: Write the failing test**

```python
# tests/playbooks/test_signature.py
import hashlib
from core.store.db import init_db, get_session
from core.store.models import Cli, Capability
from core.playbooks.skillmd import Playbook, PlaybookStep
from core.playbooks.signature import cli_signature, playbook_drift

def _seed(session, slug, in_types, out_types):
    session.add(Cli(slug=slug, lang="python"))
    session.add(Capability(cli_slug=slug, input_types=in_types, output_types=out_types))
    session.commit()

def _pb(*clis):
    steps = tuple(PlaybookStep(id=f"s{i+1}", cli=c, inputs={}, out_type="T") for i, c in enumerate(clis))
    return Playbook(slug="pb", description="d", allowed_tools=tuple(clis), steps=steps)

def test_signature_is_order_independent(tmp_path):
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed(s, "foo", "b,a", "y,x")
        sig = cli_signature(s, "foo")
        expected = hashlib.sha256(b"a,b|x,y").hexdigest()
        assert sig == expected

def test_signature_none_for_missing(tmp_path):
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        assert cli_signature(s, "nope") is None

def test_drift_reports_missing_cli(tmp_path):
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed(s, "foo", "a", "x")
        d = playbook_drift(s, _pb("foo", "ghost"))
        assert d["status"] == "broken"
        assert d["missing_clis"] == ["ghost"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_signature.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.playbooks.signature'`

> If the import path `core.store.models` is wrong, first run `grep -rn "class Cli(SQLModel" core/` to find the real module path and fix the import in BOTH the test and `signature.py`. The models live where `Cli`/`Capability` are defined (per plan research: `core/models.py` or `core/store/models.py`).

- [ ] **Step 3: Write minimal implementation**

```python
# core/playbooks/signature.py
import hashlib
from sqlmodel import select
from core.store.models import Cli, Capability
from core.playbooks.skillmd import Playbook


def cli_signature(session, slug: str) -> "str | None":
    cli = session.get(Cli, slug)
    if cli is None:
        return None
    cap = session.exec(
        select(Capability).where(Capability.cli_slug == slug)
    ).first()
    in_types = cap.input_types if cap else ""
    out_types = cap.output_types if cap else ""
    norm_in = ",".join(sorted(t for t in in_types.split(",") if t))
    norm_out = ",".join(sorted(t for t in out_types.split(",") if t))
    payload = f"{norm_in}|{norm_out}".encode()
    return hashlib.sha256(payload).hexdigest()


def playbook_drift(session, pb: Playbook) -> dict:
    missing = []
    for slug in pb.allowed_tools:
        if cli_signature(session, slug) is None:
            missing.append(slug)
    status = "broken" if missing else "ok"
    return {"status": status, "stale_clis": [], "missing_clis": missing}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_signature.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add core/playbooks/signature.py tests/playbooks/test_signature.py
git commit -m "feat(playbooks): CLI interface signature + drift (broken/missing)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: FTS5 keyword index — build + retrieve candidates with cached signatures

**Files:**
- Create: `core/playbooks/index.py`
- Test: `tests/playbooks/test_index.py`

**Interfaces:**
- Consumes: `Playbook` (Task 1), `cli_signature` (Task 3), a raw DB connection from the session.
- Produces:
  - `rebuild_index(session, playbooks: list[Playbook]) -> int` — drops/recreates an FTS5 table `playbook_fts(slug, description, tags)` and a side table `playbook_sig(slug, cli, sig)` caching each referenced CLI's signature at index time. Returns count indexed.
  - `retrieve(session, query: str, limit: int = 5) -> list[str]` — BM25-ranked slugs for `query` (empty query → all slugs, slug-sorted).
  - `stale_against_index(session, pb: Playbook) -> list[str]` — slugs of referenced CLIs whose *current* signature differs from the cached one (the baseline comparison deferred from Task 3).

- [ ] **Step 1: Write the failing test**

```python
# tests/playbooks/test_index.py
from core.store.db import init_db, get_session
from core.store.models import Cli, Capability
from core.playbooks.skillmd import Playbook, PlaybookStep
from core.playbooks.index import rebuild_index, retrieve, stale_against_index

def _seed_cli(session, slug, in_t="a", out_t="x"):
    session.add(Cli(slug=slug, lang="python"))
    session.add(Capability(cli_slug=slug, input_types=in_t, output_types=out_t))
    session.commit()

def _pb(slug, desc, tags, clis):
    steps = tuple(PlaybookStep(id=f"s{i+1}", cli=c, inputs={}, out_type="T") for i, c in enumerate(clis))
    return Playbook(slug=slug, description=desc, tags=tuple(tags), allowed_tools=tuple(clis), steps=steps)

def test_rebuild_then_retrieve_by_keyword(tmp_path):
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed_cli(s, "svg-enrich")
        _seed_cli(s, "ledger")
        pbs = [
            _pb("svg-pub", "Enrich SVGs and publish to Etsy", ["svg", "etsy"], ["svg-enrich"]),
            _pb("acct", "Reconcile the ledger", ["finance"], ["ledger"]),
        ]
        assert rebuild_index(s, pbs) == 2
        assert retrieve(s, "etsy", limit=5) == ["svg-pub"]
        assert set(retrieve(s, "", limit=5)) == {"acct", "svg-pub"}

def test_stale_against_index_detects_signature_change(tmp_path):
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed_cli(s, "svg-enrich", in_t="a", out_t="x")
        pb = _pb("svg-pub", "Enrich", ["svg"], ["svg-enrich"])
        rebuild_index(s, [pb])
        assert stale_against_index(s, pb) == []
        # mutate the CLI's output type -> signature drifts
        from sqlmodel import select
        cap = s.exec(select(Capability).where(Capability.cli_slug == "svg-enrich")).first()
        cap.output_types = "x,y"
        s.add(cap); s.commit()
        assert stale_against_index(s, pb) == ["svg-enrich"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.playbooks.index'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/playbooks/index.py
from sqlalchemy import text
from core.playbooks.skillmd import Playbook
from core.playbooks.signature import cli_signature


def _conn(session):
    return session.connection()


def rebuild_index(session, playbooks: list) -> int:
    c = _conn(session)
    c.execute(text("DROP TABLE IF EXISTS playbook_fts"))
    c.execute(text("DROP TABLE IF EXISTS playbook_sig"))
    c.execute(text(
        "CREATE VIRTUAL TABLE playbook_fts USING fts5(slug, description, tags)"
    ))
    c.execute(text(
        "CREATE TABLE playbook_sig (slug TEXT, cli TEXT, sig TEXT)"
    ))
    for pb in playbooks:
        c.execute(
            text("INSERT INTO playbook_fts(slug, description, tags) VALUES (:s, :d, :t)"),
            {"s": pb.slug, "d": pb.description, "t": " ".join(pb.tags)},
        )
        for slug in pb.allowed_tools:
            c.execute(
                text("INSERT INTO playbook_sig(slug, cli, sig) VALUES (:s, :c, :g)"),
                {"s": pb.slug, "c": slug, "g": cli_signature(session, slug) or ""},
            )
    session.commit()
    return len(playbooks)


def retrieve(session, query: str, limit: int = 5) -> list:
    c = _conn(session)
    if not query.strip():
        rows = c.execute(text("SELECT slug FROM playbook_fts ORDER BY slug")).fetchall()
        return [r[0] for r in rows]
    rows = c.execute(
        text(
            "SELECT slug FROM playbook_fts WHERE playbook_fts MATCH :q "
            "ORDER BY bm25(playbook_fts) LIMIT :lim"
        ),
        {"q": query, "lim": limit},
    ).fetchall()
    return [r[0] for r in rows]


def stale_against_index(session, pb: Playbook) -> list:
    c = _conn(session)
    out = []
    for slug in pb.allowed_tools:
        row = c.execute(
            text("SELECT sig FROM playbook_sig WHERE slug = :s AND cli = :c"),
            {"s": pb.slug, "c": slug},
        ).fetchone()
        cached = row[0] if row else None
        current = cli_signature(session, slug) or ""
        if cached is not None and cached != current:
            out.append(slug)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_index.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add core/playbooks/index.py tests/playbooks/test_index.py
git commit -m "feat(playbooks): FTS5 index + BM25 retrieve + signature baseline

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Op handlers — list_playbooks and suggest_playbook

**Files:**
- Create: `core/playbooks/queries.py`
- Test: `tests/playbooks/test_queries.py`

**Interfaces:**
- Consumes: `load_playbooks` (Task 2), `retrieve`/`rebuild_index`/`stale_against_index` (Task 4), `playbook_drift` (Task 3).
- Produces (these exact signatures are wired into `OPS` in Task 6):
  - `list_playbooks(session, query: str = "") -> dict` → `{"playbooks": [{"slug","description","tags","status","drift"}]}`.
  - `suggest_playbook(session, goal: str, limit: int = 3) -> dict` → `{"goal": goal, "candidates": [{"slug","description","steps":[...],"drift",...}]}`, ranked by `retrieve`. Returns `{"candidates": []}` on no match (caller decides whether to fall back to `plan_cli_chain`).
  - `get_playbook(session, slug: str) -> dict | None` → the full candidate shape (with `steps`) for one slug, or `None` if absent. Used by the HTTP detail route (Task 7).
- All three call `rebuild_index` lazily if the FTS table is empty/absent (so the ops work against a fresh DB without an explicit reindex command).

- [ ] **Step 1: Write the failing test**

```python
# tests/playbooks/test_queries.py
from pathlib import Path
from core.store.db import init_db, get_session
from core.store.models import Cli, Capability
from core.playbooks import queries as q

def _seed_cli(s, slug):
    s.add(Cli(slug=slug, lang="python"))
    s.add(Capability(cli_slug=slug, input_types="a", output_types="x"))
    s.commit()

def _seed_pb(root: Path):
    d = root / "svg-pub"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\ndescription: Enrich SVGs and publish to Etsy\n"
        "tags: [svg, etsy]\nallowed-tools: [svg-enrich]\nstatus: verified\n---\n"
        "1. svg-enrich in: {raw: raw} out: EnrichedSvg\n"
    )

def test_suggest_ranks_matching_playbook(tmp_path, monkeypatch):
    _seed_pb(tmp_path)
    monkeypatch.setattr(q, "PLAYBOOKS_ROOT", str(tmp_path))
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed_cli(s, "svg-enrich")
        res = q.suggest_playbook(s, goal="publish svgs to etsy", limit=3)
        assert [c["slug"] for c in res["candidates"]] == ["svg-pub"]
        assert res["candidates"][0]["drift"]["status"] == "ok"
        assert len(res["candidates"][0]["steps"]) == 1

def test_list_returns_all_with_drift(tmp_path, monkeypatch):
    _seed_pb(tmp_path)
    monkeypatch.setattr(q, "PLAYBOOKS_ROOT", str(tmp_path))
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        # NOTE: svg-enrich NOT seeded -> drift should be "broken"
        res = q.list_playbooks(s)
        assert res["playbooks"][0]["slug"] == "svg-pub"
        assert res["playbooks"][0]["drift"]["status"] == "broken"

def test_get_playbook_includes_steps(tmp_path, monkeypatch):
    _seed_pb(tmp_path)
    monkeypatch.setattr(q, "PLAYBOOKS_ROOT", str(tmp_path))
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed_cli(s, "svg-enrich")
        pb = q.get_playbook(s, "svg-pub")
        assert pb["slug"] == "svg-pub"
        assert len(pb["steps"]) == 1
        assert pb["steps"][0]["cli"] == "svg-enrich"
        assert q.get_playbook(s, "ghost") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_queries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.playbooks.queries'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/playbooks/queries.py
from core.playbooks.loader import load_playbooks
from core.playbooks.index import rebuild_index, retrieve, stale_against_index
from core.playbooks.signature import playbook_drift

PLAYBOOKS_ROOT = "playbooks"


def _drift(session, pb) -> dict:
    d = playbook_drift(session, pb)            # broken/missing
    if d["status"] == "ok":
        stale = stale_against_index(session, pb)
        if stale:
            return {"status": "stale", "stale_clis": stale, "missing_clis": []}
    return d


def _ensure_index(session, playbooks):
    rebuild_index(session, playbooks)          # cheap; idempotent for a small set


def _step_dicts(pb):
    return [
        {"id": st.id, "cli": st.cli, "inputs": st.inputs, "out_type": st.out_type}
        for st in pb.steps
    ]


def list_playbooks(session, query: str = "") -> dict:
    pbs = load_playbooks(PLAYBOOKS_ROOT)
    _ensure_index(session, pbs)
    if query.strip():
        keep = set(retrieve(session, query, limit=len(pbs)))
        pbs = [p for p in pbs if p.slug in keep]
    return {
        "playbooks": [
            {
                "slug": p.slug,
                "description": p.description,
                "tags": list(p.tags),
                "status": p.status,
                "drift": _drift(session, p),
            }
            for p in pbs
        ]
    }


def _candidate_dict(session, p) -> dict:
    return {
        "slug": p.slug,
        "description": p.description,
        "tags": list(p.tags),
        "status": p.status,
        "steps": _step_dicts(p),
        "drift": _drift(session, p),
    }


def suggest_playbook(session, goal: str, limit: int = 3) -> dict:
    pbs = load_playbooks(PLAYBOOKS_ROOT)
    _ensure_index(session, pbs)
    by_slug = {p.slug: p for p in pbs}
    ranked = retrieve(session, goal, limit=limit)
    candidates = [_candidate_dict(session, by_slug[s]) for s in ranked if s in by_slug]
    return {"goal": goal, "candidates": candidates}


def get_playbook(session, slug: str) -> "dict | None":
    pbs = load_playbooks(PLAYBOOKS_ROOT)
    _ensure_index(session, pbs)
    for p in pbs:
        if p.slug == slug:
            return _candidate_dict(session, p)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_queries.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add core/playbooks/queries.py tests/playbooks/test_queries.py
git commit -m "feat(playbooks): list_playbooks + suggest_playbook op handlers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Register ops in OPS dispatch table

**Files:**
- Modify: `core/ops_registry.py` (the `OPS` list and imports)
- Test: `tests/playbooks/test_ops_registration.py`

**Interfaces:**
- Consumes: `list_playbooks`, `suggest_playbook` (Task 5).
- Produces: two new `Op` entries with `a2a_skill` `list-playbooks` and `suggest-playbook`, reachable via `op_by_a2a_skill` and `op_by_mcp_tool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/playbooks/test_ops_registration.py
from core.ops_registry import op_by_a2a_skill, op_by_mcp_tool, validate_input

def test_suggest_playbook_op_registered():
    op = op_by_a2a_skill("suggest-playbook")
    assert op.mcp_tool == "suggest_playbook"
    # required "goal" enforced by shared validator
    assert validate_input(op, {}) == "missing required input keys: ['goal']"
    assert validate_input(op, {"goal": "x"}) is None

def test_list_playbooks_op_registered():
    op = op_by_mcp_tool("list_playbooks")
    assert op.a2a_skill == "list-playbooks"
    assert validate_input(op, {"query": "etsy"}) is None
    assert validate_input(op, {"bogus": 1}) == "unknown input keys: ['bogus']"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_ops_registration.py -v`
Expected: FAIL — `KeyError: 'suggest-playbook'`

- [ ] **Step 3: Add the imports and ops**

In `core/ops_registry.py`, add to the imports near the top (after `from core.catalog import queries`):

```python
from core.playbooks import queries as playbook_queries
```

Append these two entries to the `OPS` list (after `plan_cli_chain`):

```python
    Op("list_playbooks", playbook_queries.list_playbooks,
       {"type": "object", "properties": {"query": {"type": "string"}}}),
    Op("suggest_playbook", playbook_queries.suggest_playbook,
       {"type": "object",
        "properties": {"goal": {"type": "string"},
                       "limit": {"type": "integer"}},
        "required": ["goal"]}),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_ops_registration.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest -m "not slow" -q`
Expected: all pass (existing ops untouched; dispatcher unchanged).

- [ ] **Step 6: Commit**

```bash
git add core/ops_registry.py tests/playbooks/test_ops_registration.py
git commit -m "feat(playbooks): register list_playbooks + suggest_playbook in OPS

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: HTTP catalog routes for the native clients

**Files:**
- Modify: `core/server/app.py` (add two routes near the existing `/clis` routes, ~line 88–98)
- Test: `tests/playbooks/test_http_routes.py`

**Interfaces:**
- Consumes: `list_playbooks` (Task 5) via the request session; the existing `_require_token` dependency and `_request_session` dependency already defined in `app.py`.
- Produces: `GET /playbooks?query=` → `list_playbooks` output (summary shape, no steps); `GET /playbooks/{slug}` → single playbook dict **including `steps`** (the full candidate shape, so the client detail view does not have to round-trip through suggest) or HTTP 404.

- [ ] **Step 1: Write the failing test**

```python
# tests/playbooks/test_http_routes.py
# Mirror the existing app test setup: find how other route tests build the app + token.
# Run first: grep -rn "TestClient\|_require_token\|create_app\|build_app" tests/ | head
# Use that exact harness here. Skeleton:
from fastapi.testclient import TestClient

def test_playbooks_route_lists(app_client):   # app_client fixture from existing conftest
    r = app_client.get("/playbooks", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
    assert "playbooks" in r.json()

def test_playbook_detail_404(app_client):
    r = app_client.get("/playbooks/does-not-exist", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 404
```

> Before writing this test, run `grep -rn "TestClient\|conftest\|_require_token\|Authorization" tests/ | head` to find the project's existing app-test fixture and auth header convention, and adapt the skeleton to match it exactly (fixture name, token value, header format). Do not invent a new harness.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_http_routes.py -v`
Expected: FAIL — 404 on `/playbooks` (route not yet defined) or fixture error to resolve first.

- [ ] **Step 3: Add the routes**

In `core/server/app.py`, after the existing `/clis/{slug}` route (~line 94), add:

```python
    @app.get("/playbooks", dependencies=[Depends(_require_token)])
    def playbooks(query: str = "", session=Depends(_request_session)):
        from core.playbooks.queries import list_playbooks
        return list_playbooks(session, query=query)

    @app.get("/playbooks/{slug}", dependencies=[Depends(_require_token)])
    def playbook_detail(slug: str, session=Depends(_request_session)):
        from core.playbooks.queries import get_playbook
        from fastapi import HTTPException
        pb = get_playbook(session, slug)
        if pb is None:
            raise HTTPException(status_code=404, detail="playbook not found")
        return pb            # full candidate shape, includes steps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_http_routes.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run full suite + manual curl smoke**

```bash
cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest -m "not slow" -q
```
Expected: all pass.

Then a manual smoke (find the serve command + port/token first):
```bash
grep -rn "def serve\|uvicorn.run\|--port\|--token\|REGISTRY_TOKEN\|cli-registry-token" core/cli/main.py | head
# start the server per that command, then:
# curl -s -H "Authorization: Bearer $(cat ~/.hermes/cli-registry-token.txt)" http://localhost:<PORT>/playbooks | python -m json.tool
```
Expected: JSON with the seed playbook and its drift status.

- [ ] **Step 6: Commit**

```bash
git add core/server/app.py tests/playbooks/test_http_routes.py
git commit -m "feat(playbooks): GET /playbooks + /playbooks/{slug} HTTP catalog

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: resolve_playbook — compile a playbook into a runnable launch plan (data only)

**Files:**
- Create: `core/playbooks/resolve.py`
- Modify: `core/ops_registry.py` (append one `Op`)
- Test: `tests/playbooks/test_resolve.py`

**Why this is separate from "run":** The registry **resolves** (turns a playbook
into a concrete, validated, ordered list of launch specs + bound args) but
**never executes** — same invariant as every other op (`a2a.py`: "data only;
never executes a CLI"). Execution belongs to the Hermes adapter (:9109), which
already owns the cli-slice subprocess path. `resolve_playbook` is the safe,
free-to-call half; the client uses it for both the **dry-run preview** and as the
payload it hands to the adapter to actually run.

**Interfaces:**
- Consumes: `load_playbooks` (Task 2), `playbook_drift`/`stale_against_index`
  via `_drift` (Task 5), the `Cli.launch_spec` column (`core/models.py:11`,
  JSON `{kind, entrypoint, args_schema}`).
- Produces: `resolve_playbook(session, slug: str) -> dict`:
  ```
  {
    "slug": str,
    "runnable": bool,                 # false if drift status is "broken"
    "drift": Drift,                   # same shape as elsewhere
    "plan": [                         # ordered, one entry per step
      { "step_id": "s1",
        "cli": "svg-enrich",
        "launch_spec": {...},         # parsed from Cli.launch_spec JSON
        "inputs": {"raw": "raw"},     # CWL-style bindings, unchanged
        "out_type": "EnrichedSvg" },
      ...
    ],
    "side_effects": ["writes-fs","network"]   # union of referenced CLIs' side_effect, deduped, "none"/"unknown" filtered
  }
  ```
  Returns `{"runnable": false, ...}` (still with whatever plan could be built) if
  any CLI is missing — the client greys out Run. Raises nothing for a missing
  *playbook*; returns `None` for an unknown slug (mirrors `get_playbook`).

- [ ] **Step 1: Write the failing test**

```python
# tests/playbooks/test_resolve.py
import json
from pathlib import Path
from core.store.db import init_db, get_session
from core.store.models import Cli, Capability
from core.playbooks import resolve as r

def _seed_cli(s, slug, side="writes-fs", launch=None):
    s.add(Cli(slug=slug, lang="python",
              launch_spec=json.dumps(launch or {"kind": "python_module", "entrypoint": slug})))
    s.add(Capability(cli_slug=slug, input_types="a", output_types="x", side_effect=side))
    s.commit()

def _seed_pb(root: Path):
    d = root / "svg-pub"; d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\ndescription: Enrich SVGs and publish\ntags: [svg]\n"
        "allowed-tools: [svg-enrich]\nstatus: verified\n---\n"
        "1. svg-enrich in: {raw: raw} out: EnrichedSvg\n"
    )

def test_resolve_builds_runnable_plan(tmp_path, monkeypatch):
    _seed_pb(tmp_path)
    monkeypatch.setattr(r, "PLAYBOOKS_ROOT", str(tmp_path))
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        _seed_cli(s, "svg-enrich", side="writes-fs")
        out = r.resolve_playbook(s, "svg-pub")
        assert out["runnable"] is True
        assert out["plan"][0]["cli"] == "svg-enrich"
        assert out["plan"][0]["launch_spec"]["kind"] == "python_module"
        assert out["plan"][0]["inputs"] == {"raw": "raw"}
        assert out["side_effects"] == ["writes-fs"]

def test_resolve_not_runnable_when_cli_missing(tmp_path, monkeypatch):
    _seed_pb(tmp_path)
    monkeypatch.setattr(r, "PLAYBOOKS_ROOT", str(tmp_path))
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        # svg-enrich NOT seeded
        out = r.resolve_playbook(s, "svg-pub")
        assert out["runnable"] is False
        assert out["drift"]["status"] == "broken"

def test_resolve_unknown_slug_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "PLAYBOOKS_ROOT", str(tmp_path))
    eng = init_db(str(tmp_path / "r.db"))
    with get_session(eng) as s:
        assert r.resolve_playbook(s, "ghost") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.playbooks.resolve'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/playbooks/resolve.py
import json
from sqlmodel import select
from core.store.models import Cli, Capability
from core.playbooks.loader import load_playbooks
from core.playbooks.index import rebuild_index
from core.playbooks.queries import _drift  # reuse the broken/stale/ok logic

PLAYBOOKS_ROOT = "playbooks"

_HIDDEN_SIDE_EFFECTS = {"none", "unknown", ""}


def _launch_spec(session, slug: str) -> dict:
    cli = session.get(Cli, slug)
    if cli is None or not cli.launch_spec:
        return {}
    try:
        return json.loads(cli.launch_spec)
    except (json.JSONDecodeError, TypeError):
        return {}


def _side_effect(session, slug: str) -> str:
    cap = session.exec(
        select(Capability).where(Capability.cli_slug == slug)
    ).first()
    return cap.side_effect if cap else "unknown"


def resolve_playbook(session, slug: str) -> "dict | None":
    pbs = load_playbooks(PLAYBOOKS_ROOT)
    rebuild_index(session, pbs)
    pb = next((p for p in pbs if p.slug == slug), None)
    if pb is None:
        return None

    drift = _drift(session, pb)
    plan = [
        {
            "step_id": st.id,
            "cli": st.cli,
            "launch_spec": _launch_spec(session, st.cli),
            "inputs": st.inputs,
            "out_type": st.out_type,
        }
        for st in pb.steps
    ]
    effects = []
    for slug_ in pb.allowed_tools:
        eff = _side_effect(session, slug_)
        if eff not in _HIDDEN_SIDE_EFFECTS and eff not in effects:
            effects.append(eff)

    return {
        "slug": pb.slug,
        "runnable": drift["status"] != "broken",
        "drift": drift,
        "plan": plan,
        "side_effects": effects,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest tests/playbooks/test_resolve.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Register the op**

In `core/ops_registry.py`, add to the playbook import line:

```python
from core.playbooks import queries as playbook_queries
from core.playbooks import resolve as playbook_resolve
```

Append to `OPS`:

```python
    Op("resolve_playbook", playbook_resolve.resolve_playbook,
       {"type": "object",
        "properties": {"slug": {"type": "string"}},
        "required": ["slug"]}),
```

- [ ] **Step 6: Run full suite**

Run: `cd /Users/jc-folder/projects/a2a-cli-registry && python -m pytest -m "not slow" -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add core/playbooks/resolve.py core/ops_registry.py tests/playbooks/test_resolve.py
git commit -m "feat(playbooks): resolve_playbook compiles runnable plan (data only)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## RUN execution — adapter-side, OUT OF SCOPE for this (registry) plan

The registry never spawns a CLI. Execution is the Hermes adapter's job (:9109,
which already owns the cli-slice subprocess path). The run flow:

1. Client calls `resolve_playbook(slug)` on the registry → gets the validated `plan`.
2. Client shows a **dry-run preview** (the `plan` + `side_effects`) and requires an
   explicit user Run tap (do-no-harm: side-effecting CLIs are never auto-run).
3. On Run, the client POSTs the resolved `plan` to the **adapter's** run endpoint
   (to be specified in `2026-XX-playbook-adapter-run.md`), which executes each
   step's `launch_spec` in order, piping `out_type` → next step's bound input.
4. Adapter streams per-step status back to the client.

The contract for that adapter run endpoint is drafted in the client system-prompt
(below, "Endpoint 5 — Run") as a FORWARD contract — flagged `NOT YET IMPLEMENTED`
so the client builds the button + status UI against it without blocking on the
adapter work.

---

## Phase 4 (DEFERRED — separate plan, needs package approval)

Hybrid retrieval upgrade: add `sqlite-vec` + `sentence-transformers` (`all-MiniLM-L6-v2`, local, ~80MB) and Reciprocal Rank Fusion (`1/(k+fts_rank) + 1/(k+vec_rank)`, k=60) merging the Task 4 BM25 ranks with vector ranks, plus a tag-match boost. **Do not build until Task 1–7 ship and you measure BM25-only recall on real queries.** Requires explicit dependency approval (CLAUDE.md). Tracked as its own plan: `2026-XX-playbook-hybrid-retrieval.md`.

## Follow-on client plans (separate, depend on this backend)

- `2026-XX-playbook-hermes-tab.md` — Flutter `PlaybookPlugin` in `hermes_android/lib/plugins/playbook/`, added to the `PluginRegistry([...])` list in `lib/app.dart:61`. Reuses `NavPin`/`NavPinsStore` for favourites, `padQuickButton` strip for quick-launch, and a `DeepLinkRunPlaybook` case in `DeepLinkService`. Consumes `GET /playbooks` + `suggest_playbook` via the existing adapter on `:9109`.
- `2026-XX-playbook-swift-appbar.md` — macOS `NSStatusItem` menu-bar popover. Favourites in `UserDefaults`, "open full catalog" deep-links to Hermes/overview. Consumes the same endpoints.

---

## Self-Review

**Spec coverage:**
- Curate & store recipes → SKILL.md format (Task 1–2) ✓
- Recipes reference registry CLIs by typed ports → `PlaybookStep.inputs` CWL-style bindings (Task 1), validated against `Capability` (Task 3) ✓
- Drift detection (Dagster-style, not mtime) → `cli_signature` + `stale_against_index` (Task 3–4) ✓
- Retrieve-then-rank, token-frugal → FTS5 BM25 retrieve narrows before any LLM (Task 4–5); LLM ranking is a *client* concern over ≤N candidates, not in the backend ✓
- Two consumers, one funnel → `list_playbooks`/`suggest_playbook` ops serve A2A, MCP, and HTTP from one code path (Task 5–7) ✓
- Chat-with-registry suggest → `suggest_playbook(goal)` (Task 5) ✓
- Favourites/quick-launch → explicitly client-side, out of backend scope (stated in Global Constraints) ✓
- "Registry returns data, never executes" → no process spawn anywhere; run is a client/bot concern ✓

**Placeholder scan:** Tasks 3, 7 contain explicit `grep` verification steps (real actions, not placeholders) because the exact models module path and the existing app-test fixture must be confirmed against the live repo — these are instructions to verify-then-match, with fallback guidance, not "figure it out yourself" hand-waves.

**Type consistency:** `Playbook`/`PlaybookStep` field names (`slug`, `description`, `tags`, `allowed_tools`, `steps`, `status`, `out_type`, `inputs`) are identical across Tasks 1–7. `cli_signature`/`playbook_drift`/`stale_against_index`/`retrieve`/`rebuild_index`/`list_playbooks`/`suggest_playbook` signatures match between their producing task and every consuming task. Drift status vocabulary (`ok`/`stale`/`broken`) is consistent (Task 3 emits broken/ok; Task 5's `_drift` upgrades ok→stale via the index).

**Known verification points the implementer MUST resolve (not gaps, but live-repo facts):**
1. Models import path — `core.store.models` vs `core/models.py`. Grep in Task 3 Step 2.
2. App-test fixture + token header convention. Grep in Task 7 Step 1.
3. Serve command port/token for the curl smoke. Grep in Task 7 Step 5.
