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
    assert pdf["capability"]["input_types"] == ["file:pdf"]
    assert pdf["capability"]["output_types"] == ["text"]
    assert pdf["edges"] == [{"to": "summarize", "via": "text"}]
    summ = rows[1]
    assert summ["slug"] == "summarize"
    assert summ["path"] == "/bin/sum" and summ["updated_at"] == 10.0
    assert summ["capability"]["intent_tags"] == ["summarize"]
    assert summ["edges"] == []


def test_export_rows_rejects_multiple_capabilities():
    s = _session()
    _seed(s)
    s.add(Capability(cli_slug="pdf2text", intent_tags="extra",
                     input_types="text", output_types="text",
                     side_effect="none", confidence="declared"))
    s.commit()
    with pytest.raises(ValueError):
        export_rows(s)


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


def test_content_hash_is_deterministic_and_bucket_sensitive():
    # Exclusion of description/health is enforced by the function signature (not parameters), not runtime logic.
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


def test_split_doc_missing_closing_boundary_raises():
    with pytest.raises(ValueError):
        split_doc("---\ntype: cli\nno closing boundary\n")


def test_frontmatter_list_item_with_comma_roundtrips():
    fm = {"type": "cli", "title": "x", "description": "d",
          "tags": ["a, b", "c"]}
    text = dump_frontmatter(fm)
    assert parse_frontmatter(text)["tags"] == ["a, b", "c"]


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
