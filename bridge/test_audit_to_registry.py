"""Spike verification: adapter output must round-trip through the REAL
registry loader (core.discovery.cli_audit_source.CliAuditSource).

If this passes, the mechanical mapping (component #3) is proven against the
genuine ingest code path — not a mock.
"""
from __future__ import annotations

import json

from bridge.audit_to_registry import build_feed, audit_record_to_cli
from core.discovery.cli_audit_source import CliAuditSource

# Two realistic cli-audit per-file records (design doc §6 shape): one usable
# (PASS), one broken (BUG) that must be excluded from a chainable registry.
AUDIT_RECORDS = [
    {
        "bucket": "consigliere",
        "project": "20_CONSIGLIERE",
        "file": "/Users/jc-folder/projects/20_CONSIGLIERE/consigliere/__main__.py",
        "invocation": "python -m consigliere --help",
        "exit_code": 0,
        "final_class": "PASS",
        "backlog_title": "",
    },
    {
        "bucket": "svg-paint",
        "project": "30_SVG-PAINT",
        "file": "/Users/jc-folder/projects/30_SVG-PAINT/app/cli/main.py",
        "invocation": "python app/cli/main.py --help",
        "exit_code": 1,
        "final_class": "BUG",  # crashes -> must be excluded
        "backlog_title": "[cli-audit] svg-paint/app/cli/main.py — ImportError",
    },
]


def test_broken_clis_excluded():
    feed = build_feed(AUDIT_RECORDS, run_id="t")
    slugs = [c["slug"] for c in feed["clis"]]
    assert len(feed["clis"]) == 1, "BUG-class CLI should be excluded"
    # __main__ is generic -> qualified with parent dir 'consigliere'
    assert slugs == ["consigliere-__main__"]


def test_generic_entrypoint_slug_qualified():
    rec = {
        "file": "/x/30_SVG-PAINT/app/cli/main.py",
        "project": "30_SVG-PAINT",
        "final_class": "PASS",
    }
    entry = audit_record_to_cli(rec)
    assert entry["slug"] == "cli-main"  # parent 'cli' + stem 'main'
    assert entry["lang"] == "python"


def test_roundtrip_through_real_loader(tmp_path):
    """The critical spike assertion: adapter JSON -> real CliAuditSource."""
    feed = build_feed(AUDIT_RECORDS, run_id="spike-run")
    feed_path = tmp_path / "latest.json"
    feed_path.write_text(json.dumps(feed), encoding="utf-8")

    records = CliAuditSource(str(feed_path)).discover()

    assert len(records) == 1
    r = records[0]
    assert r.slug == "consigliere-__main__"
    assert r.lang == "python"
    assert r.path.endswith("consigliere/__main__.py")
    assert r.source_class == "cli_audit"
    assert r.source_run_id == "spike-run"


def test_lang_inference():
    assert audit_record_to_cli({"file": "/x/foo.go", "final_class": "PASS"})["lang"] == "go"
    assert audit_record_to_cli({"file": "/x/bar.sh", "final_class": "PASS"})["lang"] == "shell"


def test_not_standalone_flag_round_trips(tmp_path):
    """A feed entry tagged not_standalone survives the real CliAuditSource load."""
    feed = {
        "schema_version": 1,
        "run_id": "t",
        "clis": [
            {"slug": "memory_commands", "lang": "python",
             "path": "/x/consigliere/cli/memory_commands.py",
             "not_standalone": True},
        ],
    }
    p = tmp_path / "feed.json"
    p.write_text(json.dumps(feed), encoding="utf-8")
    records = CliAuditSource(str(p)).discover()
    assert records[0].not_standalone is True


def test_subapp_record_flagged_not_standalone(tmp_path):
    """audit_record_to_cli stamps not_standalone:true for a real sub-app file."""
    import textwrap

    f = tmp_path / "sub_commands.py"
    f.write_text(textwrap.dedent("""
        import typer
        app = typer.Typer(name="sub")
        @app.command()
        def go(): ...
    """), encoding="utf-8")

    rec = {"final_class": "PASS", "file": str(f), "project": "p"}
    entry = audit_record_to_cli(rec)
    assert entry is not None
    assert entry.get("not_standalone") is True


def test_real_cli_not_flagged(tmp_path):
    """A standalone argparse CLI is NOT flagged."""
    import textwrap

    f = tmp_path / "real.py"
    f.write_text(textwrap.dedent("""
        import argparse
        def main():
            argparse.ArgumentParser().parse_args()
        if __name__ == "__main__":
            main()
    """), encoding="utf-8")

    rec = {"final_class": "PASS", "file": str(f), "project": "p"}
    entry = audit_record_to_cli(rec)
    assert "not_standalone" not in entry or entry["not_standalone"] is False
