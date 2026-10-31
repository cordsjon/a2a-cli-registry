import os
import shlex
import shutil
import subprocess

import pytest

from core.adapters.base import LanguageAdapter
from core.adapters.python_adapter import PythonAdapter
from core.adapters.stub_adapter import StubAdapter
from core.discovery.base import CliRecord


def _rec(lang, slug="x"):
    return CliRecord(slug=slug, lang=lang, path="/x", bucket=None, project=None,
                     description="", declared_capability=None, source_class=None, source_run_id=None)


def test_python_adapter_launch_spec_uses_module_invocation():
    spec = PythonAdapter().launch_spec(_rec("python", "pdf2text"))
    assert spec["kind"] == "python_module"        # US-80: python -m, not script path
    assert spec["entrypoint"] == "pdf2text"


def test_python_adapter_health_cmd_uses_path_for_script_file():
    """A loose .py script must be probed as `python <path> --help` — the only
    invocation that works for path-based CLIs (the cli-audit fleet shape)."""
    rec = _rec("python", "verify-potx")
    rec.path = "/Users/me/projects/scripts/verify_potx.py"
    cmd = PythonAdapter().health_cmd(rec)
    assert cmd == "python /Users/me/projects/scripts/verify_potx.py --help"


def test_python_adapter_health_cmd_falls_back_to_module_without_script_path():
    """No .py script path -> module invocation (US-80) is preserved."""
    rec = _rec("python", "black")
    rec.path = ""
    assert PythonAdapter().health_cmd(rec) == "python -m black --help"


def test_python_adapter_health_cmd_quotes_spaced_path():
    """Paths with spaces are shell-quoted so shlex.split reconstructs one arg."""
    rec = _rec("python", "x")
    rec.path = "/Users/me/My Projects/tool.py"
    cmd = PythonAdapter().health_cmd(rec)
    assert "'/Users/me/My Projects/tool.py'" in cmd


def test_python_adapter_health_cmd_prefers_nearest_project_venv(tmp_path):
    """A script inside a project that carries its own venv is probed with THAT
    interpreter. The bare `python` on PATH fails every CLI whose imports live
    in the project venv (138 of 281 unhealthy rows measured 2026-10-31)."""
    proj = tmp_path / "proj"
    venv_py = proj / ".venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("#!/bin/sh\n")
    venv_py.chmod(0o755)
    script = proj / "scripts" / "tool.py"
    script.parent.mkdir()
    script.write_text("print('hi')\n")
    rec = _rec("python", "tool")
    rec.path = str(script)
    cmd = PythonAdapter().health_cmd(rec, stop=tmp_path)
    assert cmd == f"{venv_py} {script} --help"


def test_python_adapter_health_cmd_stops_walking_at_boundary(tmp_path):
    """The venv walk never climbs past the boundary (default: $HOME). A venv
    sitting above it is not the script's project venv, so the bare `python`
    fallback stays."""
    above = tmp_path / ".venv" / "bin" / "python"
    above.parent.mkdir(parents=True)
    above.write_text("")
    above.chmod(0o755)
    script = tmp_path / "home" / "projects" / "p" / "tool.py"
    script.parent.mkdir(parents=True)
    script.write_text("")
    rec = _rec("python", "tool")
    rec.path = str(script)
    cmd = PythonAdapter().health_cmd(rec, stop=tmp_path / "home")
    assert cmd == f"python {script} --help"


def test_python_adapter_infers_none_without_signal():
    rec = _rec("python")
    rec.description = "a generic tool with no capability signal whatsoever"
    assert PythonAdapter().infer_capability(rec) is None


def test_python_adapter_infers_from_help_text_with_signal():
    # a help text containing a known signal ("format ... in place") now infers
    rec = _rec("python")
    rec.description = "The uncompromising code formatter; reformats files in place."
    cap = PythonAdapter().infer_capability(rec)
    assert cap is not None
    assert cap.confidence == "inferred"
    assert "format" in cap.intent_tags


def test_stub_adapter_requires_declared_never_infers():
    stub = StubAdapter()
    assert stub.infer_capability(_rec("shell")) is None   # non-Python never infers


def test_adapters_satisfy_protocol():
    assert isinstance(PythonAdapter(), LanguageAdapter)
    assert isinstance(StubAdapter(), LanguageAdapter)


def _executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path


def _path_rec(path):
    rec = _rec("python", "tool")
    rec.path = str(path)
    return rec


def test_health_cmd_never_runs_a_shell_script_without_a_help_branch(tmp_path):
    """`bash sync-global-hooks.sh --help` ignores the flag and syncs. All 8 .sh
    rows measured 2026-10-31 had no help branch. Unknown beats executed."""
    script = _executable(tmp_path / "sync.sh", "#!/usr/bin/env bash\nrm -f \"$1\"\n")
    assert PythonAdapter().health_cmd(_path_rec(script)) == ""


def test_health_cmd_does_not_count_a_function_call_as_a_passthrough(tmp_path):
    """log-truncate.sh uses "$@" inside a function and acts on its arguments."""
    script = _executable(tmp_path / "trunc.sh",
                         '#!/usr/bin/env bash\nf() { truncate "$@"; }\nf -s 0 "$1"\n')
    assert PythonAdapter().health_cmd(_path_rec(script)) == ""


def test_health_cmd_probes_a_shell_script_with_a_help_branch(tmp_path):
    script = _executable(tmp_path / "tool.sh",
                         '#!/bin/sh\ncase "$1" in --help) echo usage ;; esac\n')
    assert PythonAdapter().health_cmd(_path_rec(script)) == f"bash {script} --help"


def test_health_cmd_probes_an_exec_wrapper_directly(tmp_path):
    """bin/decisions is `exec python3 decisions_cli.py "$@"`: --help reaches the
    wrapped CLI's parser."""
    script = _executable(tmp_path / "decisions",
                         '#!/usr/bin/env bash\nexec python3 "$ROOT/cli.py" "$@"\n')
    assert PythonAdapter().health_cmd(_path_rec(script)) == f"{script} --help"


def test_health_cmd_probes_an_extensionless_python_entrypoint(tmp_path):
    script = _executable(tmp_path / "tool", "#!/usr/bin/env python3\nprint('hi')\n")
    assert PythonAdapter().health_cmd(_path_rec(script)) == f"{script} --help"


def test_health_cmd_skips_non_executable_extensionless_file(tmp_path):
    script = tmp_path / "tool"
    script.write_text("#!/usr/bin/env python3\n")
    assert PythonAdapter().health_cmd(_path_rec(script)) == ""


def test_health_cmd_skips_typescript_and_javascript(tmp_path):
    for name in ("legal.ts", "legal.js"):
        script = tmp_path / name
        script.write_text("")
        assert PythonAdapter().health_cmd(_path_rec(script)) == ""


def test_health_cmd_runs_dunder_main_as_a_module(tmp_path):
    """ytx/__main__.py run by path fails its relative import; `-m ytx` with the
    package's parent on PYTHONPATH is how it actually runs."""
    script = tmp_path / "scripts" / "ytx" / "__main__.py"
    script.parent.mkdir(parents=True)
    script.write_text("")
    adapter = PythonAdapter()
    rec = _path_rec(script)
    assert adapter.health_cmd(rec, stop=tmp_path) == "python -m ytx --help"
    assert str(tmp_path / "scripts") in adapter.health_env(rec)["PYTHONPATH"].split(os.pathsep)


def test_health_env_adds_project_root_and_keeps_existing_pythonpath(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/already/there")
    (tmp_path / "pyproject.toml").write_text("")
    script = tmp_path / "scripts" / "tool.py"
    script.parent.mkdir()
    script.write_text("")
    entries = PythonAdapter().health_env(_path_rec(script))["PYTHONPATH"].split(os.pathsep)
    assert entries == [str(tmp_path), "/already/there"]


def test_health_env_is_empty_without_a_project_root(tmp_path):
    rec = _rec("python", "black")
    rec.path = ""
    assert PythonAdapter().health_env(rec) == {}


def test_launch_spec_carries_project_interpreter_and_pythonpath(tmp_path):
    """US-CLIREG-LAUNCH-01 AC-01: the row records what the probe ran with."""
    (tmp_path / "pyproject.toml").write_text("")
    venv_py = _executable(tmp_path / ".venv" / "bin" / "python", "#!/bin/sh\n")
    script = tmp_path / "scripts" / "tool.py"
    script.parent.mkdir()
    script.write_text("")
    spec = PythonAdapter().launch_spec(_path_rec(script), stop=tmp_path.parent)
    assert spec["argv"] == [str(venv_py), str(script)]
    assert spec["env"] == {"PYTHONPATH": str(tmp_path)}


def test_launch_spec_does_not_persist_the_callers_pythonpath(tmp_path, monkeypatch):
    """health_env appends the prober's own PYTHONPATH for the child it spawns.
    Stored in the row, that would hand every launch the prober's environment."""
    monkeypatch.setenv("PYTHONPATH", "/only/in/the/prober")
    (tmp_path / "pyproject.toml").write_text("")
    script = tmp_path / "tool.py"
    script.write_text("")
    spec = PythonAdapter().launch_spec(_path_rec(script), stop=tmp_path)
    assert spec["env"] == {"PYTHONPATH": str(tmp_path)}


def test_launch_argv_is_the_probe_invocation_for_every_shape(tmp_path):
    """Green predicts a launch only if both run the same thing. `python <path>`
    is wrong for a package's __main__ and for a shell wrapper."""
    main = tmp_path / "ytx" / "__main__.py"
    main.parent.mkdir()
    main.write_text("")
    shapes = [
        main,
        _executable(tmp_path / "wrapper", '#!/usr/bin/env bash\nexec python3 cli.py "$@"\n'),
        _executable(tmp_path / "entry", "#!/usr/bin/env python3\nprint('hi')\n"),
        _executable(tmp_path / "branch.sh", '#!/bin/sh\ncase "$1" in --help) echo u ;; esac\n'),
    ]
    adapter = PythonAdapter()
    for path in shapes:
        rec = _path_rec(path)
        spec = adapter.launch_spec(rec, stop=tmp_path)
        assert shlex.join(spec["argv"]) + " --help" == adapter.health_cmd(rec, stop=tmp_path)


_PEP723_NO_DEPS = '# /// script\n# dependencies = []\n# ///\nimport sys\nsys.exit(0)\n'


def test_pep723_script_without_a_venv_runs_through_uv_offline(tmp_path):
    """AC-04: it declares its own deps. Offline, so a sweep never fetches unpinned
    packages: green means they are already cached."""
    script = tmp_path / "tool.py"
    script.write_text(_PEP723_NO_DEPS)
    argv = PythonAdapter().launch_spec(_path_rec(script), stop=tmp_path)["argv"]
    assert argv[1:] == ["run", "--offline", "--script", str(script)]
    assert os.path.basename(argv[0]) == "uv"


def test_project_venv_outranks_pep723(tmp_path):
    venv_py = _executable(tmp_path / ".venv" / "bin" / "python", "#!/bin/sh\n")
    script = tmp_path / "tool.py"
    script.write_text(_PEP723_NO_DEPS)
    argv = PythonAdapter().launch_spec(_path_rec(script), stop=tmp_path.parent)["argv"]
    assert argv == [str(venv_py), str(script)]


def test_plain_script_without_a_venv_gets_no_borrowed_interpreter(tmp_path):
    """Q22 stands: a foreign venv's green says nothing about this script."""
    script = tmp_path / "tool.py"
    script.write_text("import sys\n")
    argv = PythonAdapter().launch_spec(_path_rec(script), stop=tmp_path)["argv"]
    assert argv == ["python", str(script)]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_pep723_invocation_runs_under_real_uv(tmp_path):
    script = tmp_path / "tool.py"
    script.write_text(_PEP723_NO_DEPS)
    cmd = PythonAdapter().health_cmd(_path_rec(script), stop=tmp_path)
    assert subprocess.run(shlex.split(cmd), cwd=tmp_path, capture_output=True).returncode == 0


def test_launch_spec_has_no_argv_when_the_probe_has_no_safe_invocation(tmp_path):
    script = _executable(tmp_path / "sync.sh", "#!/usr/bin/env bash\nrm -f \"$1\"\n")
    spec = PythonAdapter().launch_spec(_path_rec(script), stop=tmp_path)
    assert "argv" not in spec and "env" not in spec
