import json
import textwrap
from pathlib import Path

from scripts.audit_md_to_json import (
    main as convert_main,
    normalize_status,
    parse_markdown,
)

WIKI = textwrap.dedent("""\
    ---
    title: "CLI Tools - All CLIs"
    ---

    ## Summary

    | Status | Count |
    |--------|-------|
    | 📦 DEP (missing package) | 49 |
    | **Total** | 2 |

    ## asset-engine

    | File | Invocation | Status | Notes |
    |------|-----------|--------|-------|
    | `70_ASSET-ENGINE/inlay_log.py` | `timeout 5 python3 .../inlay_log.py --help` | ✅ PASS | — |

    ## coaching

    | File | Invocation | Status | Notes |
    |------|-----------|--------|-------|
    | `75_Coaching/generate-pdf.py` | `timeout 5 python3 .../generate-pdf.py --help` | 📦 DEP | ModuleNotFoundError: No module named 'markdown' |
    | `75_Coaching/verify_potx.py` | `timeout 5 python3 .../verify_potx.py --help` | 🔧 TRIVIAL fixed | — |
""")


def test_summary_table_is_not_parsed_as_records():
    """The leading Summary table shares the pipe syntax but not the header."""
    records = parse_markdown(WIKI)
    assert [r["file"] for r in records] == [
        "70_ASSET-ENGINE/inlay_log.py",
        "75_Coaching/generate-pdf.py",
        "75_Coaching/verify_potx.py",
    ]


def test_section_header_becomes_project():
    records = parse_markdown(WIKI)
    assert records[0]["project"] == "asset-engine"
    assert records[1]["project"] == "coaching"


def test_status_normalizes_to_audit_class():
    assert normalize_status("✅ PASS") == "PASS"
    assert normalize_status("🔧 TRIVIAL fixed") == "TRIVIAL-FIXED"
    assert normalize_status("🔴 TRIVIAL-UNFIXED") == "TRIVIAL-UNFIXED"
    records = parse_markdown(WIKI)
    assert [r["final_class"] for r in records] == ["PASS", "DEP", "TRIVIAL-FIXED"]


def test_notes_go_to_stderr_never_to_description():
    records = parse_markdown(WIKI)
    assert records[0]["stderr"] == ""          # em-dash placeholder
    assert "ModuleNotFoundError" in records[1]["stderr"]
    assert "backlog_title" not in records[1]


def test_root_absolutizes_relative_paths():
    records = parse_markdown(WIKI, root="/tmp/projects")
    assert records[0]["file"] == "/tmp/projects/70_ASSET-ENGINE/inlay_log.py"


def test_unknown_status_fails_closed():
    bad = WIKI.replace("✅ PASS", "🚧 WIP")
    try:
        parse_markdown(bad)
    except ValueError as exc:
        assert "WIP" in str(exc)
    else:
        raise AssertionError("unknown status must raise")


def test_feed_mode_chains_into_the_bridge(tmp_path, capsys):
    src = tmp_path / "all-clis.md"
    src.write_text(WIKI, encoding="utf-8")
    out = tmp_path / "feed.json"
    rc = convert_main([str(src), "--feed", "--run-id", "t1", "-o", str(out)])
    assert rc == 0
    feed = json.loads(out.read_text(encoding="utf-8"))
    assert feed["schema_version"] == 1 and feed["run_id"] == "t1"
    # All three rows carry a usable final_class, so all three survive the bridge.
    assert {c["slug"] for c in feed["clis"]} == {
        "inlay_log", "generate-pdf", "verify_potx"}
    assert all({"slug", "lang", "path"} <= c.keys() for c in feed["clis"])


def test_missing_source_exits_2(tmp_path, capsys):
    assert convert_main([str(tmp_path / "nope.md")]) == 2


def test_records_mode_is_the_default_and_prints_json(tmp_path, capsys):
    src = tmp_path / "all-clis.md"
    src.write_text(WIKI, encoding="utf-8")
    assert convert_main([str(src)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list) and len(payload) == 3


def test_real_wiki_export_parses_if_present():
    """Smoke test against the live governance export when it exists locally."""
    wiki = Path.home() / "projects/00_Governance/wiki/export_md/cli-tools/all-clis.md"
    if not wiki.exists():
        return
    records = parse_markdown(wiki.read_text(encoding="utf-8"))
    assert len(records) > 400
    assert all(r["final_class"] for r in records)
