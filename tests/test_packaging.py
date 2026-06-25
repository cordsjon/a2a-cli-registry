# tests/test_packaging.py
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def test_console_entry_point_points_to_main():
    cfg = tomllib.loads(_PYPROJECT.read_text())
    scripts = cfg["project"]["scripts"]
    assert scripts["a2a-cli-registry"] == "core.cli.main:main"


def test_entry_point_callable_resolves():
    from core.cli.main import main
    assert callable(main)


def test_version_is_1_3_0():
    cfg = tomllib.loads(_PYPROJECT.read_text())
    assert cfg["project"]["version"] == "1.3.0"


def test_rich_is_declared_runtime_dependency():
    cfg = tomllib.loads(_PYPROJECT.read_text())
    deps = cfg["project"]["dependencies"]
    assert any(d == "rich" or d.startswith("rich>") or d.startswith("rich=")
               or d.startswith("rich ") for d in deps)


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


def test_jinja2_is_declared_runtime_dependency():
    cfg = tomllib.loads(_PYPROJECT.read_text())
    deps = cfg["project"]["dependencies"]
    assert any(d == "jinja2" or d.startswith("jinja2>") or d.startswith("jinja2=")
               or d.startswith("jinja2 ") for d in deps)


def test_jinja2_imported_only_in_core_web():
    import pathlib
    root = pathlib.Path(__file__).parent.parent / "core"
    offenders = []
    for p in root.rglob("*.py"):
        if "web" in p.parts:
            continue
        text = p.read_text()
        if "import jinja2" in text or "from jinja2" in text:
            offenders.append(str(p))
    assert offenders == [], f"jinja2 imported outside core/web/: {offenders}"


def test_overview_template_declared_as_package_data():
    cfg = tomllib.loads(_PYPROJECT.read_text())
    wheel = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]
    included = wheel.get("include", [])
    assert "core/web/templates/*.html" in included


def test_metadata_complete_for_pypi():
    cfg = tomllib.loads(_PYPROJECT.read_text())["project"]
    assert cfg["description"]
    assert cfg["readme"]
    assert any("License" in c for c in cfg.get("classifiers", []))
    assert cfg.get("urls", {}).get("Homepage") or cfg.get("urls", {}).get("Repository")
