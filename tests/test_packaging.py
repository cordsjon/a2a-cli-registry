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


def test_version_is_1_1_0():
    cfg = tomllib.loads(_PYPROJECT.read_text())
    assert cfg["project"]["version"] == "1.1.0"


def test_rich_is_declared_runtime_dependency():
    cfg = tomllib.loads(_PYPROJECT.read_text())
    deps = cfg["project"]["dependencies"]
    assert any(d == "rich" or d.startswith("rich>") or d.startswith("rich=")
               or d.startswith("rich ") for d in deps)


def test_metadata_complete_for_pypi():
    cfg = tomllib.loads(_PYPROJECT.read_text())["project"]
    assert cfg["description"]
    assert cfg["readme"]
    assert any("License" in c for c in cfg.get("classifiers", []))
    assert cfg.get("urls", {}).get("Homepage") or cfg.get("urls", {}).get("Repository")
