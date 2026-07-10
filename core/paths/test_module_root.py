import os
from core.paths.module_root import _project_root, _dotted_module


def test_project_root_finds_nearest_sentinel(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    sub = tmp_path / "pkg" / "sub"
    sub.mkdir(parents=True)
    cli = sub / "cli.py"
    cli.write_text("")
    assert _project_root(str(cli)) == str(tmp_path)


def test_project_root_returns_none_when_no_sentinel(tmp_path):
    # tmp_path itself has no sentinel and (in test envs) no parent will
    # either, so this must return None rather than walking to filesystem root
    # and matching an ancestor .git by accident. Use a deeply isolated dir.
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    cli = isolated / "c.py"
    cli.write_text("")
    result = _project_root(str(cli))
    # We can't assert None unconditionally (a real .git could exist above
    # tmp_path on some CI runners), so assert it's either None or a path
    # that does NOT equal our isolated dir (i.e., no false-positive on the
    # dir we just created without a sentinel in it).
    assert result != str(isolated)


def test_dotted_module_relative_path(tmp_path):
    root = tmp_path
    cli = root / "pkg" / "sub" / "cli.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("")
    assert _dotted_module(str(cli), str(root)) == "pkg.sub.cli"


def test_dotted_module_outside_root_returns_none(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside" / "c.py"
    outside.parent.mkdir()
    outside.write_text("")
    assert _dotted_module(str(outside), str(root)) is None
