import json
import sqlite3
import stat
import sys

from scripts.verify_smoke_seed import main

# Prints its argument doubled, so a changed input changes the answer.
_TOOL = "import sys\nif '--help' in sys.argv: print('usage: tool N')\nelse: print('answer', int(sys.argv[1]) * 2)"


def _setup(tmp_path, **smoke):
    tool = tmp_path / "tool"
    tool.write_text(f"#!{sys.executable}\n{_TOOL}\n")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    db = tmp_path / "registry.db"
    con = sqlite3.connect(db)
    con.execute("DROP TABLE IF EXISTS cli")     # tests call this twice to compare two seeds
    con.execute("CREATE TABLE cli (slug TEXT, launch_spec TEXT)")
    con.execute("INSERT INTO cli VALUES ('tool', ?)", (json.dumps({"argv": [str(tool)]}),))
    con.commit()
    con.close()
    seeds = tmp_path / "seeds"
    seeds.mkdir(exist_ok=True)
    seed = {"argv": [str(tool), "21"], "expect_stdout_re": "answer 42", "side_effects": "none", "tier": "hand",
            "negative": {"argv": [str(tool), "22"]}, **smoke}
    (seeds / "tool.json").write_text(json.dumps({k: v for k, v in seed.items() if v is not None}))
    return ["--db", str(db), "--seed-dir", str(seeds)]


def _problems(capsys):
    return json.loads(capsys.readouterr().out)["bad"].get("tool", [])


def test_a_seed_that_can_fail_passes(tmp_path, capsys):
    assert main(_setup(tmp_path)) == 0
    assert _problems(capsys) == []


def test_refuses_a_seed_that_asserts_nothing_about_the_output(tmp_path, capsys):
    assert main(_setup(tmp_path, expect_stdout_re=None)) == 1
    assert "asserts no output" in _problems(capsys)[0]


def test_refuses_a_regex_the_help_text_or_empty_output_satisfies(tmp_path, capsys):
    assert main(_setup(tmp_path, expect_stdout_re="usage")) == 1
    assert any("--help" in p for p in _problems(capsys))
    assert main(_setup(tmp_path, expect_stdout_re="x*")) == 1
    assert any("empty output" in p for p in _problems(capsys))


def test_a_seed_that_does_not_pass_reports_the_exit_code_and_output(tmp_path, capsys):
    assert main(_setup(tmp_path, expect_stdout_re="answer 43")) == 1
    problem = _problems(capsys)[0]
    assert "exit 0" in problem and "answer 42" in problem


def test_refuses_a_negative_case_that_still_passes(tmp_path, capsys):
    tool_args = _setup(tmp_path, negative={"argv": [str(tmp_path / "tool"), "21"]})
    assert main(tool_args) == 1
    assert any("negative" in p for p in _problems(capsys))


def test_refuses_a_negative_case_that_only_crashes(tmp_path, capsys):
    """A crash fails any assertion, so it proves nothing about the regex."""
    assert main(_setup(tmp_path, negative={"argv": [str(tmp_path / "tool"), "notanumber"]})) == 1
    assert any("did not run cleanly" in p for p in _problems(capsys))


def test_a_missing_negative_needs_a_stated_reason(tmp_path, capsys):
    assert main(_setup(tmp_path, negative=None)) == 1
    assert any("negative" in p for p in _problems(capsys))
    assert main(_setup(tmp_path, negative=None, negative_why="reads one fixed public page")) == 0
