import json
import sqlite3
import stat
import sys

from core.prober.smoke import run_smoke
from scripts.derive_smoke import main

_HELP = """
import sys
open({marker!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')
if '--help' in sys.argv:
    print({help_text!r})
    raise SystemExit({help_exit})
raise SystemExit(0)
"""


def _tool(tmp_path, name, help_text="usage: tool [--version]", help_exit=0):
    """A fake row. It records every argv it runs with, in <name>.ran."""
    path = tmp_path / name
    marker = tmp_path / f"{name}.ran"
    path.write_text(f"#!{sys.executable}\n"
                    + _HELP.format(marker=str(marker), help_text=help_text, help_exit=help_exit))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path), marker


def _db(tmp_path, rows):
    """rows: (slug, argv, overrides for the columns and launch_spec keys)."""
    db = tmp_path / "registry.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cli (slug TEXT, path TEXT, project TEXT, enabled INT, "
                "health_status TEXT, launch_spec TEXT)")
    for slug, argv, over in rows:
        spec = {"kind": over.get("kind", "python_module"), "argv": argv}
        if "smoke" in over:
            spec["smoke"] = over["smoke"]
        con.execute("INSERT INTO cli VALUES (?, ?, ?, ?, ?, ?)",
                    (slug, over.get("path", "/x/tool.py"), over.get("project"),
                     over.get("enabled", 1), over.get("health", "healthy"), json.dumps(spec)))
    con.commit()
    con.close()
    return db


def _derive(tmp_path, rows):
    out = tmp_path / "derived"
    code = main(["--tier", "version", "--db", str(_db(tmp_path, rows)), "--out", str(out)])
    assert code == 0
    return out


def _seeded(out):
    return sorted(p.stem for p in out.glob("*.json"))


def test_a_row_whose_help_lists_version_gets_a_seed_that_passes(tmp_path):
    tool, _ = _tool(tmp_path, "tool")
    out = _derive(tmp_path, [("tool", [tool], {})])
    seed = json.loads((out / "tool.json").read_text())
    assert seed["argv"] == [tool, "--version"]
    assert seed["tier"] == "version"
    assert run_smoke({"smoke": seed}, timeout=10) == "pass"


def test_no_seed_without_the_flag_or_when_help_fails(tmp_path):
    plain, _ = _tool(tmp_path, "plain", help_text="usage: plain [--verbose] see foo--version")
    broken, _ = _tool(tmp_path, "broken", help_exit=2)
    takes_value, _ = _tool(tmp_path, "takes-value",
                           help_text="usage: f [--version VERSION]\n  --version VERSION  a filter")
    out = _derive(tmp_path, [("plain", [plain], {}), ("broken", [broken], {}),
                             ("takes-value", [takes_value], {})])
    assert _seeded(out) == []


def test_each_form_of_a_real_version_flag_gets_a_seed(tmp_path):
    forms = {"usage-only": "usage: f [-h] [--version] [x]",
             "described": "options:\n  -V, --version  show the version",
             "line-end": "options:\n  --version\n      show the version"}
    rows = [(name, [_tool(tmp_path, name, help_text=text)[0]], {}) for name, text in forms.items()]
    assert _seeded(_derive(tmp_path, rows)) == sorted(forms)


def test_a_null_project_is_not_silently_skipped(tmp_path):
    tool, marker = _tool(tmp_path, "tool")
    out = _derive(tmp_path, [("tool", [tool], {"project": None})])
    assert _seeded(out) == ["tool"]
    assert marker.exists()


def test_rows_outside_the_tier_are_never_executed(tmp_path):
    rows, markers = [], []
    for name, over in [("held-path", {"path": "/x/20_CONSIGLIERE/tool"}),
                       ("held-project", {"project": "20_consigliere"}),
                       ("has-smoke", {"smoke": {"argv": ["/bin/true"]}}),
                       ("disabled", {"enabled": 0}),
                       ("stale", {"health": "stale"}),
                       ("shell", {"kind": "executable"})]:
        tool, marker = _tool(tmp_path, name)
        rows.append((name, [tool], over))
        markers.append(marker)
    out = _derive(tmp_path, rows)
    assert _seeded(out) == []
    assert [m.name for m in markers if m.exists()] == []
