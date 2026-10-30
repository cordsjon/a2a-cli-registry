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
