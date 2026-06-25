# OKF Producer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `okf-produce` exporter and a descriptions-only `okf-ingest` importer that round-trip the CLI catalog through an Open Knowledge Format (OKF) Markdown+YAML bundle, with SQLite remaining the source of truth.

**Architecture:** A new `core/okf/` module is the only place that knows the OKF serialization. `okf-produce` reads a new ordered `export_rows()` query and writes a deterministic (byte-stable) bundle. `okf-ingest` reads the bundle and writes back **only** `Cli.description`. A2A/MCP/serve are untouched. YAML is hand-emitted (no new dependency).

**Tech Stack:** Python 3.11+, SQLModel/SQLite, argparse CLI (single-positional `choices`), pytest. venv is uv-managed.

**Spec:** `docs/superpowers/specs/2026-06-25-okf-producer-design.md`

## Global Constraints

- venv is uv-managed. Run tests with `.venv/bin/python -m pytest`. **No pip.**
- **No new runtime dependency.** YAML is hand-emitted/parsed in `core/okf/frontmatter.py` (spec D1). Do NOT add PyYAML.
- Commit by explicit path: `git commit -m "<msg>" -- <paths>`. **Never whole-index.**
- This repo has no committed git identity: pass `-c user.name="Jonas Cords" -c user.email="jonas.cords@gmail.com"` on every commit.
- Trailer on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Branch: work continues on `feat/web-overview` (current HEAD `b1d7e76`). Do not branch off master.
- Baseline before changes: **183 tests passing.** No regression permitted.
- No bare `except Exception` that swallows. No bare `.json()` after fetch (n/a here).
- Atomic writes: tempfile + `os.replace` for every bundle file.
- `core/okf/` is the ONLY module that imports/owns OKF serialization. It depends on `core/store` (a session) and `core/catalog/queries`; never the reverse. It must not import `core/server`, `core/mcp`, or `core/tui`.
- `launch_spec` is NEVER emitted into a bundle.
- Version bump to `1.3.0` (spec D2) happens in the final task.
- Commands are `okf-produce` / `okf-ingest` (hyphenated, spec D3).

---

## File Structure

| File | Responsibility |
|---|---|
| `core/okf/__init__.py` | Package marker; re-export `produce_bundle`, `ingest_bundle`. |
| `core/okf/frontmatter.py` | Hand-emit + parse the constrained YAML frontmatter subset; `ConceptDoc` (frontmatter dict + body); `"---"` boundary read/write; `content_hash`. |
| `core/okf/serialize.py` | `produce_bundle(session, out_dir, force=False)` — rows → bundle files. |
| `core/okf/parse.py` | `ingest_bundle(session, bundle_dir)` — bundle → `Cli.description` writes; returns a summary. |
| `core/catalog/queries.py` | Add `export_rows(session)` — full ordered rows for export. |
| `core/cli/main.py` | Add `okf-produce` / `okf-ingest` to `choices`; `--out`/`--bundle` flags; two command branches. |
| `pyproject.toml` | Version → `1.3.0`. |
| `README.md`, `CHANGELOG.md` | Document the two commands + OKF interchange. |
| `tests/test_okf.py` | All behavioral tests from spec §8. |

---

### Task 1: `export_rows()` ordered query

**Files:**
- Modify: `core/catalog/queries.py` (add function after `overview_rows`)
- Test: `tests/test_okf.py` (create)

**Interfaces:**
- Consumes: `Cli`, `Capability`, `CliEdge` from `core.models`; `select` from `sqlmodel`.
- Produces: `export_rows(session) -> list[dict]`. Each dict:
  `{"slug","lang","project","path","updated_at","description","health_status",
    "capability": {"intent_tags":[...sorted], "input_types":[...sorted],
    "output_types":[...sorted], "side_effect":str, "confidence":str} | None,
    "edges": [{"to":str,"via":str}, ...sorted by (to,via)]}`.
  CLIs sorted by `(project or "", slug)`. Raises `ValueError` if any CLI has >1 capability row.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_okf.py
import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool
from core.models import Cli, Capability, CliEdge
from core.catalog.queries import export_rows


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _seed(s):
    s.add(Cli(slug="summarize", lang="python", project="text", path="/bin/sum",
              updated_at=10.0, description="d2", health_status="healthy"))
    s.add(Cli(slug="pdf2text", lang="python", project="docs", path="/bin/p2t",
              updated_at=20.0, description="d1", health_status="healthy"))
    s.add(Capability(cli_slug="pdf2text", intent_tags="document,convert",
                     input_types="file:pdf", output_types="text",
                     side_effect="none", confidence="declared"))
    s.add(Capability(cli_slug="summarize", intent_tags="summarize",
                     input_types="text", output_types="text",
                     side_effect="none", confidence="declared"))
    s.add(CliEdge(from_slug="pdf2text", to_slug="summarize", via_type="text"))
    s.commit()


def test_export_rows_sorted_and_shaped():
    s = _session()
    _seed(s)
    rows = export_rows(s)
    assert [r["slug"] for r in rows] == ["pdf2text", "summarize"]  # by (project, slug): docs<text
    pdf = rows[0]
    assert pdf["path"] == "/bin/p2t" and pdf["updated_at"] == 20.0
    assert pdf["capability"]["intent_tags"] == ["convert", "document"]  # sorted
    assert pdf["edges"] == [{"to": "summarize", "via": "text"}]


def test_export_rows_rejects_multiple_capabilities():
    s = _session()
    _seed(s)
    s.add(Capability(cli_slug="pdf2text", intent_tags="extra",
                     input_types="text", output_types="text",
                     side_effect="none", confidence="declared"))
    s.commit()
    with pytest.raises(ValueError):
        export_rows(s)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_okf.py -v -k export_rows`
Expected: FAIL — `ImportError: cannot import name 'export_rows'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/catalog/queries.py  (append; reuse existing `select`, models already imported)
def export_rows(session):
    """Full, deterministically-ordered rows for OKF export.

    Unlike overview_rows/describe_cli this carries `path` and `updated_at`
    (needed for OKF `resource`/`timestamp`) and a fully sorted shape so the
    producer can emit byte-stable bundles. Fails loudly if a CLI has >1
    capability row (OKF v1 exports the one-capability-per-CLI invariant).
    """
    clis = session.exec(select(Cli)).all()
    caps_by_slug = {}
    for cap in session.exec(select(Capability)).all():
        caps_by_slug.setdefault(cap.cli_slug, []).append(cap)
    edges_by_slug = {}
    for e in session.exec(select(CliEdge)).all():
        edges_by_slug.setdefault(e.from_slug, []).append(e)

    out = []
    for c in sorted(clis, key=lambda x: ((x.project or ""), x.slug)):
        caps = caps_by_slug.get(c.slug, [])
        if len(caps) > 1:
            raise ValueError(
                f"OKF export: CLI {c.slug!r} has {len(caps)} capability rows; "
                "v1 exports one capability per CLI")
        cap = caps[0] if caps else None
        capability = None
        if cap is not None:
            capability = {
                "intent_tags": sorted(t for t in cap.intent_tags.split(",") if t),
                "input_types": sorted(t for t in cap.input_types.split(",") if t),
                "output_types": sorted(t for t in cap.output_types.split(",") if t),
                "side_effect": cap.side_effect,
                "confidence": cap.confidence,
            }
        edges = sorted(
            ({"to": e.to_slug, "via": e.via_type} for e in edges_by_slug.get(c.slug, [])),
            key=lambda d: (d["to"], d["via"]),
        )
        out.append({
            "slug": c.slug, "lang": c.lang, "project": c.project, "path": c.path,
            "updated_at": c.updated_at, "description": c.description or "",
            "health_status": _norm_health(c.health_status),
            "capability": capability, "edges": edges,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_okf.py -v -k export_rows`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add core/catalog/queries.py tests/test_okf.py
git -c user.name="Jonas Cords" -c user.email="jonas.cords@gmail.com" commit \
  -m "feat(okf): export_rows ordered query with path/updated_at + one-cap invariant

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" \
  -- core/catalog/queries.py tests/test_okf.py
```

---

### Task 2: Frontmatter emit/parse + content_hash

**Files:**
- Create: `core/okf/__init__.py`, `core/okf/frontmatter.py`
- Test: `tests/test_okf.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks (pure functions).
- Produces:
  - `dump_frontmatter(fm: dict) -> str` — deterministic YAML for the constrained subset (scalars; flat string lists; `ports` = `{"in":[...], "out":[...]}`; `edges` = `[{"to","via"}]`). Top-level keys emitted in a FIXED order; lists emitted in given order (caller pre-sorts).
  - `parse_frontmatter(text: str) -> dict` — parse the same subset back. Only needs to recover scalars + lists reliably; ingest uses `description`.
  - `split_doc(content: str) -> tuple[dict, str]` — split a `---`-delimited file into (frontmatter dict, body). Raises `ValueError` if boundaries missing.
  - `join_doc(fm: dict, body: str) -> str` — inverse: `---\n<yaml>---\n<body>`.
  - `content_hash(concept_id, slug, lang, project, resource, intent_tags, input_types, output_types, side_effect, confidence, edges) -> str` — returns `"sha256:<hex>"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_okf.py (append)
from core.okf.frontmatter import (
    dump_frontmatter, parse_frontmatter, split_doc, join_doc, content_hash)


def test_frontmatter_roundtrip_is_stable():
    fm = {
        "type": "cli", "title": "pdf2text", "description": "Convert PDF",
        "resource": "file:///bin/p2t", "tags": ["convert", "document"],
        "timestamp": "2026-06-25T00:00:20Z", "content_hash": "sha256:abc",
        "ports": {"in": ["file:pdf"], "out": ["text"]},
        "side_effect": "none", "confidence": "declared", "health": "healthy",
        "edges": [{"to": "summarize", "via": "text"}],
    }
    text = dump_frontmatter(fm)
    assert dump_frontmatter(parse_frontmatter(text)) == text  # byte-stable roundtrip
    assert parse_frontmatter(text)["description"] == "Convert PDF"
    assert parse_frontmatter(text)["tags"] == ["convert", "document"]


def test_split_and_join_doc():
    body = "## Capabilities\nReads pdf.\n"
    fm = {"type": "cli", "title": "x", "description": "d"}
    doc = join_doc(fm, body)
    assert doc.startswith("---\n") and "\n---\n" in doc
    got_fm, got_body = split_doc(doc)
    assert got_fm["title"] == "x" and got_body == body


def test_split_doc_missing_boundaries_raises():
    with pytest.raises(ValueError):
        split_doc("no frontmatter here")


def test_content_hash_excludes_description_and_health():
    args = dict(concept_id="clis/docs/pdf2text", slug="pdf2text", lang="python",
                project="docs", resource="file:///bin/p2t",
                intent_tags=["convert"], input_types=["file:pdf"],
                output_types=["text"], side_effect="none", confidence="declared",
                edges=[{"to": "summarize", "via": "text"}])
    h1 = content_hash(**args)
    # description/health are not even parameters -> identical inputs, identical hash
    assert content_hash(**args) == h1
    args2 = dict(args); args2["project"] = "elsewhere"; args2["concept_id"] = "clis/elsewhere/pdf2text"
    assert content_hash(**args2) != h1  # rebucket changes hash
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_okf.py -v -k "frontmatter or doc or content_hash"`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.okf'`.

- [ ] **Step 3: Write minimal implementation**

In Task 2, create `core/okf/__init__.py` as an **empty file** (the
`produce_bundle`/`ingest_bundle` re-exports are added in Task 5, once those
modules exist — re-exporting them now would fail at import time):

```python
# core/okf/__init__.py  (Task 2: empty placeholder)
```

```python
# core/okf/frontmatter.py
"""Hand-emitted, deterministic YAML frontmatter for OKF concept docs.

We control the full shape (scalars, flat string lists, a 2-key `ports` map,
an `edges` list of {to,via} maps), so we emit a constrained subset by hand
rather than depend on PyYAML. This guarantees byte-stable output (spec §6, D1).
"""
import hashlib

# Fixed top-level emission order (standard OKF fields first, then extensions).
_KEY_ORDER = [
    "type", "title", "description", "resource", "tags", "timestamp",
    "content_hash", "enriched_against", "okf_version",
    "ports", "side_effect", "confidence", "health", "edges",
]


def _scalar(v) -> str:
    s = "" if v is None else str(v)
    # Quote when needed to stay parseable; always safe to quote.
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _emit_list(items) -> str:
    return "[" + ", ".join(_scalar(i) for i in items) + "]"


def dump_frontmatter(fm: dict) -> str:
    lines = []
    for key in _KEY_ORDER:
        if key not in fm or fm[key] is None:
            continue
        val = fm[key]
        if key == "ports":
            lines.append("ports:")
            lines.append("  in: " + _emit_list(val.get("in", [])))
            lines.append("  out: " + _emit_list(val.get("out", [])))
        elif key == "edges":
            lines.append("edges:")
            for e in val:
                lines.append("  - to: " + _scalar(e["to"]))
                lines.append("    via: " + _scalar(e["via"]))
        elif key == "tags":
            lines.append("tags: " + _emit_list(val))
        else:
            lines.append(f"{key}: " + _scalar(val))
    return "\n".join(lines) + "\n"


def _unquote(s: str):
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return s


def parse_frontmatter(text: str) -> dict:
    fm: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line == "ports:":
            ports = {}
            i += 1
            while i < len(lines) and lines[i].startswith("  "):
                k, _, rest = lines[i].strip().partition(": ")
                ports[k] = _parse_inline_list(rest)
                i += 1
            fm["ports"] = ports
            continue
        if line == "edges:":
            edges = []
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith("- to:"):
                to = _unquote(lines[i].split("to:", 1)[1])
                via = _unquote(lines[i + 1].split("via:", 1)[1])
                edges.append({"to": to, "via": via})
                i += 2
            fm["edges"] = edges
            continue
        key, _, rest = line.partition(": ")
        key = key.strip()
        if rest.strip().startswith("["):
            fm[key] = _parse_inline_list(rest)
        else:
            fm[key] = _unquote(rest)
        i += 1
    return fm


def _parse_inline_list(rest: str):
    rest = rest.strip()
    if not (rest.startswith("[") and rest.endswith("]")):
        return []
    inner = rest[1:-1].strip()
    if not inner:
        return []
    return [_unquote(p) for p in inner.split(", ")]


def split_doc(content: str):
    if not content.startswith("---\n"):
        raise ValueError("OKF concept: missing opening '---' frontmatter boundary")
    rest = content[4:]
    end = rest.find("\n---\n")
    if end == -1:
        raise ValueError("OKF concept: missing closing '---' frontmatter boundary")
    return parse_frontmatter(rest[:end]), rest[end + 5:]


def join_doc(fm: dict, body: str) -> str:
    return "---\n" + dump_frontmatter(fm) + "---\n" + body


def content_hash(*, concept_id, slug, lang, project, resource,
                 intent_tags, input_types, output_types,
                 side_effect, confidence, edges) -> str:
    """sha256 over the canonical structural tuple (spec §6).

    Excludes description, health_status, timestamp by construction (not params).
    """
    parts = [
        concept_id, slug, lang, project or "", resource or "",
        ",".join(sorted(intent_tags)),
        ",".join(sorted(input_types)),
        ",".join(sorted(output_types)),
        side_effect, confidence,
        ";".join(f"{e['to']}>{e['via']}" for e in sorted(edges, key=lambda d: (d["to"], d["via"]))),
    ]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return "sha256:" + digest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_okf.py -v -k "frontmatter or doc or content_hash"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/okf/__init__.py core/okf/frontmatter.py tests/test_okf.py
git -c user.name="Jonas Cords" -c user.email="jonas.cords@gmail.com" commit \
  -m "feat(okf): hand-emitted deterministic frontmatter + content_hash

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" \
  -- core/okf/__init__.py core/okf/frontmatter.py tests/test_okf.py
```

---

### Task 3: `produce_bundle()` — the exporter

**Files:**
- Create: `core/okf/serialize.py`
- Test: `tests/test_okf.py` (append)

**Interfaces:**
- Consumes: `export_rows` (Task 1); `dump_frontmatter`/`join_doc`/`content_hash` (Task 2).
- Produces: `produce_bundle(session, out_dir, force=False) -> dict` returning
  `{"concepts": int}`. Writes `out_dir/index.md`, `out_dir/log.md`, and
  `out_dir/clis/<project|_unbucketed>/<slug>.md`. Refuses a non-empty,
  non-bundle `out_dir` unless `force=True` (raises `FileExistsError`).
  Preserves `description` + `enriched_against` from a pre-existing concept file.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_okf.py (append)
from pathlib import Path
from core.okf.serialize import produce_bundle


def test_produce_is_byte_identical_on_rerun(tmp_path):
    s = _session(); _seed(s)
    out = tmp_path / "bundle"
    produce_bundle(s, str(out))
    snap1 = {p.relative_to(out).as_posix(): p.read_bytes()
             for p in out.rglob("*.md")}
    produce_bundle(s, str(out), force=True)
    snap2 = {p.relative_to(out).as_posix(): p.read_bytes()
             for p in out.rglob("*.md")}
    assert snap1 == snap2  # determinism


def test_produce_emits_edges_both_ways_and_no_launch_spec(tmp_path):
    s = _session(); _seed(s)
    # add a launch_spec that must NOT leak
    s.get(__import__("core.models", fromlist=["Cli"]).Cli, "pdf2text").launch_spec = '{"secret":1}'
    s.commit()
    out = tmp_path / "bundle"
    produce_bundle(s, str(out))
    pdf = (out / "clis" / "docs" / "pdf2text.md").read_text()
    assert "secret" not in pdf and "launch_spec" not in pdf
    assert "edges:" in pdf                       # frontmatter edges
    assert "(../text/summarize.md" in pdf        # body link to summarize
    assert 'via text' in pdf                     # via_type in link title


def test_produce_refuses_nonempty_non_bundle_dir(tmp_path):
    s = _session(); _seed(s)
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "junk.txt").write_text("not a bundle")
    with pytest.raises(FileExistsError):
        produce_bundle(s, str(out))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_okf.py -v -k produce`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.okf.serialize'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/okf/serialize.py
"""okf-produce: render the catalog as a deterministic OKF bundle."""
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.catalog.queries import export_rows
from core.okf.frontmatter import join_doc, split_doc, content_hash

OKF_VERSION = "0.1"


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _iso(updated_at):
    if updated_at is None:
        return None
    return datetime.fromtimestamp(float(updated_at), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _bucket(project):
    return project if project else "_unbucketed"


def _concept_id(row):
    return f"clis/{_bucket(row['project'])}/{row['slug']}"


def _resource(path):
    return f"file://{path}" if path else None


def _is_bundle_dir(out: Path) -> bool:
    idx = out / "index.md"
    return idx.exists() and "okf_version" in idx.read_text(encoding="utf-8")


def _existing_enrichment(path: Path):
    """Return (description, enriched_against) preserved from a prior concept file."""
    if not path.exists():
        return None, None
    try:
        fm, _ = split_doc(path.read_text(encoding="utf-8"))
    except ValueError:
        return None, None
    return fm.get("description"), fm.get("enriched_against")


def produce_bundle(session, out_dir, force=False) -> dict:
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()) and not _is_bundle_dir(out) and not force:
        raise FileExistsError(
            f"{out_dir} is non-empty and not an OKF bundle; pass force=True to overwrite")

    rows = export_rows(session)
    max_updated = max((r["updated_at"] or 0.0) for r in rows) if rows else 0.0

    # concept files
    for row in rows:
        cid = _concept_id(row)
        cap = row["capability"] or {"intent_tags": [], "input_types": [],
                                    "output_types": [], "side_effect": "unknown",
                                    "confidence": "declared"}
        resource = _resource(row["path"])
        chash = content_hash(
            concept_id=cid, slug=row["slug"], lang=row["lang"],
            project=row["project"], resource=resource,
            intent_tags=cap["intent_tags"], input_types=cap["input_types"],
            output_types=cap["output_types"], side_effect=cap["side_effect"],
            confidence=cap["confidence"], edges=row["edges"])

        path = out / (cid + ".md")
        prior_desc, prior_enriched = _existing_enrichment(path)
        description = prior_desc if prior_desc else row["description"]

        fm = {"type": "cli", "title": row["slug"], "description": description}
        if resource:
            fm["resource"] = resource
        fm["tags"] = cap["intent_tags"]
        ts = _iso(row["updated_at"])
        if ts:
            fm["timestamp"] = ts
        fm["content_hash"] = chash
        if prior_enriched:
            fm["enriched_against"] = prior_enriched
        fm["ports"] = {"in": cap["input_types"], "out": cap["output_types"]}
        fm["side_effect"] = cap["side_effect"]
        fm["confidence"] = cap["confidence"]
        fm["health"] = row["health_status"]
        fm["edges"] = row["edges"]

        body = _render_body(row, cap, rows)
        _atomic_write(path, join_doc(fm, body))

    # reserved files (deterministic; no wall-clock)
    _atomic_write(out / "index.md", _render_index(rows))
    _atomic_write(out / "log.md", _render_log(max_updated))
    return {"concepts": len(rows)}


def _rel_link(from_row, to_slug, rows):
    to_row = next((r for r in rows if r["slug"] == to_slug), None)
    if to_row is None:
        return f"{to_slug}.md"
    from_dir = f"clis/{_bucket(from_row['project'])}"
    to_path = f"clis/{_bucket(to_row['project'])}/{to_slug}.md"
    return os.path.relpath(to_path, from_dir)


def _render_body(row, cap, rows) -> str:
    lines = ["## Capabilities", ""]
    ins = ", ".join(f"`{t}`" for t in cap["input_types"]) or "(none)"
    outs = ", ".join(f"`{t}`" for t in cap["output_types"]) or "(none)"
    lines.append(f"Reads {ins}, produces {outs}. "
                 f"Side effect: {cap['side_effect']}. ({cap['confidence']})")
    if row["edges"]:
        lines += ["", "## Chains into", ""]
        for e in row["edges"]:
            link = _rel_link(row, e["to"], rows)
            lines.append(f'- [{e["to"]}]({link} "via {e["via"]}")')
    return "\n".join(lines) + "\n"


def _render_index(rows) -> str:
    lines = [f"okf_version: {OKF_VERSION}", "", "# Bundle Index", ""]
    for r in rows:
        lines.append(f"- {_concept_id(r)}")
    return "\n".join(lines) + "\n"


def _render_log(max_updated) -> str:
    stamp = _iso(max_updated) if max_updated else "(empty)"
    return f"# Log\n\nLast structural change: {stamp}\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_okf.py -v -k produce`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/okf/serialize.py tests/test_okf.py
git -c user.name="Jonas Cords" -c user.email="jonas.cords@gmail.com" commit \
  -m "feat(okf): produce_bundle deterministic exporter (edges both ways, no launch_spec)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" \
  -- core/okf/serialize.py tests/test_okf.py
```

---

### Task 4: `ingest_bundle()` — descriptions-only importer

**Files:**
- Create: `core/okf/parse.py`
- Test: `tests/test_okf.py` (append)

**Interfaces:**
- Consumes: `split_doc` (Task 2); `produce_bundle` (Task 3, for round-trip test); `Cli` from `core.models`.
- Produces: `ingest_bundle(session, bundle_dir) -> dict` returning
  `{"updated": int, "skipped": int, "failed": int}`. Writes ONLY `Cli.description`.
  Unknown slug → skipped + warning. Malformed concept → failed (counted), continue.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_okf.py (append)
from core.models import Cli as _Cli
from core.okf.parse import ingest_bundle


def test_roundtrip_ingest_restores_descriptions(tmp_path):
    s = _session(); _seed(s)
    out = tmp_path / "bundle"
    produce_bundle(s, str(out))
    # edit the description in the bundle (simulating enrichment)
    p = out / "clis" / "docs" / "pdf2text.md"
    p.write_text(p.read_text().replace("d1", "ENRICHED pdf desc"))
    res = ingest_bundle(s, str(out))
    assert res["updated"] >= 1
    assert s.get(_Cli, "pdf2text").description == "ENRICHED pdf desc"


def test_ingest_never_mutates_structure(tmp_path):
    s = _session(); _seed(s)
    out = tmp_path / "bundle"
    produce_bundle(s, str(out))
    p = out / "clis" / "docs" / "pdf2text.md"
    p.write_text(p.read_text().replace("side_effect: \"none\"",
                                       "side_effect: \"destructive\""))
    ingest_bundle(s, str(out))
    from core.models import Capability
    from sqlmodel import select
    cap = s.exec(select(Capability).where(Capability.cli_slug == "pdf2text")).one()
    assert cap.side_effect == "none"  # untouched


def test_ingest_unknown_slug_skipped(tmp_path):
    s = _session(); _seed(s)
    out = tmp_path / "bundle"
    produce_bundle(s, str(out))
    ghost = out / "clis" / "docs" / "ghost.md"
    ghost.write_text((out / "clis" / "docs" / "pdf2text.md").read_text()
                     .replace("pdf2text", "ghost"))
    res = ingest_bundle(s, str(out))
    assert res["skipped"] >= 1


def test_ingest_malformed_counts_failed(tmp_path):
    s = _session(); _seed(s)
    out = tmp_path / "bundle"
    produce_bundle(s, str(out))
    (out / "clis" / "docs" / "broken.md").write_text("no frontmatter at all")
    res = ingest_bundle(s, str(out))
    assert res["failed"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_okf.py -v -k ingest`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.okf.parse'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/okf/parse.py
"""okf-ingest: read enriched descriptions back into the catalog.

Writes ONLY Cli.description. All structural frontmatter is read-and-discarded;
structure stays connector-owned (spec §5).
"""
import sys
from pathlib import Path

from core.models import Cli
from core.okf.frontmatter import split_doc

_RESERVED = {"index.md", "log.md"}


def _slug_from_path(path: Path, bundle: Path) -> str:
    # concept id = clis/<bucket>/<slug>; slug is the filename stem
    return path.stem


def ingest_bundle(session, bundle_dir) -> dict:
    bundle = Path(bundle_dir)
    updated = skipped = failed = 0
    for path in sorted(bundle.rglob("*.md")):
        if path.name in _RESERVED:
            continue
        try:
            fm, body = split_doc(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"okf-ingest: malformed concept {path}: {exc}", file=sys.stderr)
            failed += 1
            continue
        slug = _slug_from_path(path, bundle)
        cli = session.get(Cli, slug)
        if cli is None:
            print(f"okf-ingest: unknown slug {slug!r} ({path}); skipped",
                  file=sys.stderr)
            skipped += 1
            continue
        new_desc = fm.get("description", "")
        if new_desc != (cli.description or ""):
            cli.description = new_desc          # the ONLY field written
            session.add(cli)
            updated += 1
    session.commit()
    return {"updated": updated, "skipped": skipped, "failed": failed}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_okf.py -v -k ingest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/okf/parse.py tests/test_okf.py
git -c user.name="Jonas Cords" -c user.email="jonas.cords@gmail.com" commit \
  -m "feat(okf): ingest_bundle descriptions-only importer (structure read-only)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" \
  -- core/okf/parse.py tests/test_okf.py
```

---

### Task 5: CLI wiring (`okf-produce` / `okf-ingest`)

**Files:**
- Modify: `core/okf/__init__.py` (add re-exports), `core/cli/main.py`
- Test: `tests/test_cli.py` (append) or `tests/test_okf.py`

**Interfaces:**
- Consumes: `produce_bundle` (Task 3), `ingest_bundle` (Task 4), `with_file_lock`, `_db_lock_path`, `init_db`, `get_session` (existing in main.py).
- Produces: two new command branches; `--out` (default `./bundle`), `--bundle` (default `./bundle`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_okf.py (append)
def test_cli_okf_produce_then_ingest(tmp_path):
    from core.cli.main import main
    db = tmp_path / "registry.db"
    # seed via a real engine at that db path
    from core.store.db import init_db, get_session
    eng = init_db(str(db))
    with get_session(eng) as s:
        _seed(s)
    out = tmp_path / "bundle"
    rc = main(["okf-produce", "--db", str(db), "--out", str(out)])
    assert rc == 0 and (out / "index.md").exists()
    rc = main(["okf-ingest", "--db", str(db), "--bundle", str(out)])
    assert rc == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_okf.py -v -k cli_okf`
Expected: FAIL — argparse rejects `okf-produce` (`invalid choice`).

- [ ] **Step 3: Write minimal implementation**

In `core/okf/__init__.py` replace the empty file with:

```python
from core.okf.serialize import produce_bundle
from core.okf.parse import ingest_bundle

__all__ = ["produce_bundle", "ingest_bundle"]
```

In `core/cli/main.py`, add to the `choices` list (line ~95):

```python
        choices=["audit", "discover", "populate", "lifecycle", "serve",
                 "graph", "probe", "overview", "okf-produce", "okf-ingest"],
```

Add the two flags after the existing `add_argument` calls (near line ~102):

```python
    parser.add_argument("--out", default="./bundle")
    parser.add_argument("--bundle", default="./bundle")
```

Add command branches after `engine = init_db(args.db)` (after line ~127), before `serve`:

```python
    if args.command == "okf-produce":
        from core.okf import produce_bundle
        with get_session(engine) as session:
            result = produce_bundle(session, args.out)
        print(f"okf-produce: wrote {result['concepts']} concept(s) to {args.out}",
              file=sys.stderr)
        return 0

    if args.command == "okf-ingest":
        from core.okf import ingest_bundle
        with with_file_lock(_db_lock_path(args.db)):
            with get_session(engine) as session:
                result = ingest_bundle(session, args.bundle)
        print(f"okf-ingest: updated {result['updated']}, skipped {result['skipped']}, "
              f"failed {result['failed']}", file=sys.stderr)
        return 1 if result["failed"] else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_okf.py -v -k cli_okf`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/okf/__init__.py core/cli/main.py tests/test_okf.py
git -c user.name="Jonas Cords" -c user.email="jonas.cords@gmail.com" commit \
  -m "feat(okf): wire okf-produce / okf-ingest CLI commands

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" \
  -- core/okf/__init__.py core/cli/main.py tests/test_okf.py
```

---

### Task 6: Full suite green + docs + version bump (finalize)

**Files:**
- Modify: `pyproject.toml`, `README.md`, `CHANGELOG.md`

**Interfaces:** none (release task).

- [ ] **Step 1: Run the FULL suite (no regression)**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (≥183 baseline + new `tests/test_okf.py`). If any pre-existing test fails, STOP and fix root cause before continuing.

- [ ] **Step 2: Bump version**

In `pyproject.toml`: `version = "1.2.0"` → `version = "1.3.0"`.

- [ ] **Step 3: Document the commands**

In `README.md` Quickstart, add after the `overview` line:

```bash
a2a-cli-registry okf-produce --out ./bundle    # export catalog as an OKF bundle (Markdown+YAML)
a2a-cli-registry okf-ingest  --bundle ./bundle # round-trip enriched descriptions back (descriptions only)
```

In `CHANGELOG.md` under `## [Unreleased]` → `### Added`, add:

```
- `okf-produce` exports the catalog as an Open Knowledge Format (OKF) bundle
  (Markdown + YAML), consumable by okf-viz / okf-mcp / OKFy and any OKF-aware
  agent. Deterministic (byte-stable re-produce). Typed ports + side-effects ride
  as OKF producer extensions; the call-graph survives as an explicit `edges:`
  frontmatter list AND agreeing body Markdown links. `launch_spec` is never emitted.
- `okf-ingest` round-trips LLM/human-enriched descriptions from an OKF bundle
  back into the catalog (descriptions only; structure stays connector-owned).
```

- [ ] **Step 4: Re-run full suite (docs/version change is inert but verify)**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md CHANGELOG.md
git -c user.name="Jonas Cords" -c user.email="jonas.cords@gmail.com" commit \
  -m "release(okf): v1.3.0 — OKF producer/ingest commands + docs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" \
  -- pyproject.toml README.md CHANGELOG.md
```

---

## Post-plan finalize (outside task loop)

After all 6 tasks pass and the full suite is green:
1. Merge `feat/web-overview` → `master`.
2. Tag `v1.3.0`.
3. Push `master` + tag + `feat/web-overview`.

(These are the "finalize" actions from the session goal; do them once tasks 1-6 are committed and reviewed.)
