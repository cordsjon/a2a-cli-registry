import json
from pathlib import Path

from scripts.golden_audit import default_triggers, find_leaks, main as audit_main

GOLDEN = Path(__file__).parent / "golden_caps" / "ground_truth.json"


def test_default_triggers_come_from_infer_table():
    triggers = default_triggers()
    assert "linter" in triggers
    assert "downloader" in triggers
    # longest-first so the report names the most specific phrase first
    assert len(triggers[0]) >= len(triggers[-1])


def test_clean_negative_is_not_flagged():
    data = [{"slug": "quiet", "help_text": "Print a number.",
             "expected": {"intent_tags": [], "side_effect": "unknown"}}]
    assert find_leaks(data, ["linter"]) == []


def test_leaking_negative_is_reported():
    data = [{"slug": "sneaky", "help_text": "A security LINTER for code.",
             "expected": {"intent_tags": [], "side_effect": "unknown"}}]
    leaks = find_leaks(data, ["linter"])
    assert leaks == [{"slug": "sneaky", "triggers": ["linter"]}]


def test_positive_examples_are_never_leaks():
    data = [{"slug": "black", "help_text": "The uncompromising code formatter.",
             "expected": {"intent_tags": ["format"], "side_effect": "writes-fs"}}]
    assert find_leaks(data, ["code formatter"]) == []


def test_shipped_golden_set_has_no_leaking_negatives():
    data = json.loads(GOLDEN.read_text())
    assert find_leaks(data, default_triggers()) == []


def test_cli_exit_codes(tmp_path):
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps([{"slug": "q", "help_text": "print a number",
                                  "expected": {"intent_tags": []}}]))
    leaky = tmp_path / "leaky.json"
    leaky.write_text(json.dumps([{"slug": "s", "help_text": "a linter",
                                  "expected": {"intent_tags": []}}]))
    assert audit_main([str(clean), "--triggers", "linter"]) == 0
    assert audit_main([str(leaky), "--triggers", "linter"]) == 1
    assert audit_main([str(tmp_path / "missing.json")]) == 2
