from core.cli.main import load_config, main


def test_load_config_reads_planner_bounds_and_vocab():
    cfg = load_config("examples/jonas-fleet/config.toml")
    assert cfg["planner"]["max_chain_depth"] == 4
    assert "file:pdf" in cfg["vocabulary"]["registered"]
    assert cfg["vocabulary"]["aliases"]["pdf"] == "file:pdf"


def test_main_graph_command_returns_zero(tmp_path, capsys):
    # graph on an empty db should succeed (exit 0), printing an empty graph
    rc = main(["graph", "--db", str(tmp_path / "r.db")])
    assert rc == 0
