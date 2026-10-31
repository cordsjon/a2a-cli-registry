import json
import sqlite3
import stat
import subprocess
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
    for name, over in [("has-smoke", {"smoke": {"argv": ["/bin/true"]}}),
                       ("disabled", {"enabled": 0}),
                       ("stale", {"health": "stale"}),
                       ("shell", {"kind": "executable"})]:
        tool, marker = _tool(tmp_path, name)
        rows.append((name, [tool], over))
        markers.append(marker)
    out = _derive(tmp_path, rows)
    assert _seeded(out) == []
    assert [m.name for m in markers if m.exists()] == []


def _repo(tmp_path, tests, name="repo", scripts=("scripts/tool.py",)):
    """A git repo with the scripts and {tests/<file>: source}, staged, not committed:
    git grep and ls-files read the index, and no commit means no hooks."""
    root = tmp_path / name
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for script in scripts:
        path = root / script
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 1\n")
    for test, source in tests.items():
        path = root / "tests" / test
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    return root


def _project_tests(tmp_path, root, script="scripts/tool.py", over=None):
    out = tmp_path / "derived"
    rows = [("tool", [sys.executable, str(root / script)], {"path": str(root / script), **(over or {})})]
    assert main(["--tier", "project-tests", "--db", str(_db(tmp_path, rows)), "--out", str(out)]) == 0
    return out


# Only a cwd in the checkout finds scripts.tool: pytest puts just tests/ on sys.path.
_IMPORTS = "from scripts.tool import VALUE\n\ndef test_it():\n    assert VALUE == {expected}\n"


def test_a_project_test_seed_is_gated_and_runs_in_its_checkout(tmp_path):
    root = _repo(tmp_path, {"test_tool.py": _IMPORTS.format(expected=1)})
    seed = json.loads((_project_tests(tmp_path, root) / "tool.json").read_text())
    assert seed["tier"] == seed["side_effects"] == "project-tests"
    assert seed["cwd"] == str(root.resolve())
    assert seed["argv"][0] == sys.executable and seed["argv"][-1] == "tests/test_tool.py"
    assert run_smoke({"smoke": seed}, timeout=60) == "unknown"
    assert run_smoke({"smoke": seed}, timeout=60, allow_network=True) == "pass"


def test_a_failing_project_test_is_a_fail(tmp_path):
    root = _repo(tmp_path, {"test_tool.py": _IMPORTS.format(expected=2)})
    seed = json.loads((_project_tests(tmp_path, root) / "tool.json").read_text())
    assert run_smoke({"smoke": seed}, timeout=60, allow_network=True) == "fail"


def test_a_test_that_only_mentions_the_stem_earns_no_seed(tmp_path):
    root = _repo(tmp_path, {"test_other.py": "# the tool is great\ndef test_it():\n    pass\n",
                            "tool_data.py": "from scripts.tool import VALUE\n"})
    assert _seeded(_project_tests(tmp_path, root)) == []


def test_a_shared_stem_needs_the_full_path_or_module(tmp_path):
    bare = "from cli import VALUE\n"
    root = _repo(tmp_path, {"test_cli.py": bare}, scripts=("a/cli.py", "b/cli.py"))
    assert _seeded(_project_tests(tmp_path, root, "a/cli.py")) == []
    qualified = _repo(tmp_path, {"test_cli.py": "from a.cli import VALUE\n"}, name="qualified",
                      scripts=("a/cli.py", "b/cli.py"))
    assert _seeded(_project_tests(tmp_path / "qualified", qualified, "a/cli.py")) == ["tool"]


def test_a_unique_stem_may_be_imported_bare_or_named_by_file(tmp_path):
    for name, source in [("bare", "import tool\n"), ("named", "SCRIPT = 'tool.py'\n")]:
        root = _repo(tmp_path, {"test_x.py": source}, name=name)
        assert _seeded(_project_tests(tmp_path / name, root)) == ["tool"], name


def test_the_frozen_repo_and_a_seeded_row_get_no_project_test_seed(tmp_path):
    frozen = _repo(tmp_path, {"test_tool.py": _IMPORTS.format(expected=1)}, name="15_belegfluss")
    assert _seeded(_project_tests(tmp_path / "15_belegfluss", frozen)) == []
    root = _repo(tmp_path, {"test_tool.py": _IMPORTS.format(expected=1)})
    out = _project_tests(tmp_path / "repo", root, over={"smoke": {"argv": ["/bin/true"]}})
    assert _seeded(out) == []


def test_a_script_outside_git_gets_no_seed(tmp_path):
    script = tmp_path / "loose.py"
    script.write_text("VALUE = 1\n")
    out = tmp_path / "derived"
    rows = [("loose", [sys.executable, str(script)], {"path": str(script)})]
    assert main(["--tier", "project-tests", "--db", str(_db(tmp_path, rows)), "--out", str(out)]) == 0
    assert _seeded(out) == []
