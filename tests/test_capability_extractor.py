import pytest
from tools.capability_extractor import (
    extract_inputs, extract_outputs, extract_intent_tags,
    infer_side_effect, extract_capability,
)


def test_argparse_type_path():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--in", type=Path)
'''
    assert "path" in extract_inputs(source)


def test_argparse_type_int():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--n", type=int)
'''
    assert "int" in extract_inputs(source)


def test_argparse_type_float():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--ratio", type=float)
'''
    assert "float" in extract_inputs(source)


def test_argparse_name_heuristic_untyped():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--input-file")
'''
    inputs = extract_inputs(source)
    assert "path" in inputs


def test_argparse_json_name_heuristic():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--json")
'''
    assert "json" in extract_inputs(source)


def test_argparse_untyped_no_heuristic_falls_back_to_str():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--verbose")
'''
    assert extract_inputs(source) == ["str"]


def test_argparse_import_alias():
    source = '''
import argparse as ap
p = ap.ArgumentParser()
p.add_argument("--in", type=Path)
'''
    assert "path" in extract_inputs(source)


def test_argparse_subparsers():
    source = '''
import argparse
p = argparse.ArgumentParser()
sub = p.add_subparsers()
build_p = sub.add_parser("build")
build_p.add_argument("--in", type=Path)
'''
    assert "path" in extract_inputs(source)


def test_output_file_write_text():
    source = '''
from pathlib import Path
Path("out.txt").write_text("hi")
'''
    assert "path" in extract_outputs(source)


def test_output_open_write_mode():
    source = '''
with open("out.csv", "w") as f:
    f.write("a,b")
'''
    assert "path" in extract_outputs(source)


def test_output_json_dump():
    source = '''
import json
with open("out.json", "w") as f:
    json.dump({"a": 1}, f)
'''
    outputs = extract_outputs(source)
    assert "path" in outputs
    assert "json" in outputs


def test_output_json_stdout():
    source = '''
import json
print(json.dumps({"a": 1}))
'''
    assert extract_outputs(source) == ["json"]


def test_output_bare_print_text():
    source = '''
print("hello world")
'''
    assert extract_outputs(source) == ["text"]


def test_output_empty_source():
    assert extract_outputs("") == []


def test_intent_tags_vocab_constrained():
    tags = extract_intent_tags("svg-export", "publish SVGs to Etsy", "")
    assert "export" in tags
    assert "publish" in tags
    # a word not in the controlled vocab must never appear
    assert "etsy" not in tags


def test_intent_tags_no_signal_returns_empty():
    assert extract_intent_tags("xz", "", "") == []


def test_side_effect_network_wins():
    source = '''
import httpx
def main():
    httpx.get("https://example.com")
    with open("cache.json", "w") as f:
        f.write("{}")
'''
    assert infer_side_effect(source) == "network"


def test_side_effect_writes_fs_in_place():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--file", type=Path)
args = p.parse_args()
with open(args.file, "w") as f:
    f.write("formatted")
'''
    assert infer_side_effect(source) == "writes-fs"


def test_side_effect_new_output_file_is_none():
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--in", type=Path)
p.add_argument("--out", type=Path)
args = p.parse_args()
with open(args.out, "w") as f:
    f.write("converted")
'''
    assert infer_side_effect(source) == "none"


def test_side_effect_output_file_flag_name_not_misclassified_as_writes_fs():
    """Realistic flag name containing 'file' (an input-heuristic substring) that is
    actually an OUTPUT -- must not be misclassified as writes-fs.
    Regression test for bug where --output-file was treated as input due to
    substring "file" matching input heuristics."""
    source = '''
import argparse
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("--in", type=Path)
p.add_argument("--output-file", type=Path)
args = p.parse_args()
with open(args.output_file, "w") as f:
    f.write("converted")
'''
    assert infer_side_effect(source) == "none"


def test_side_effect_none_when_neither():
    source = '''
def add(a, b):
    return a + b
'''
    assert infer_side_effect(source) == "none"


def test_extract_capability_partial_input_only_flags_incomplete():
    # input detected, output empty -> extract_capability itself still reports
    # empty output_types; routing to fallback is backfill_capabilities' job,
    # not the extractor's -- the extractor just reports honestly.
    source = '''
import argparse
p = argparse.ArgumentParser()
p.add_argument("--in", type=Path)
'''
    cap = extract_capability("myclitool", "reads a file", source)
    assert cap["input_types"] == ["path"]
    assert cap["output_types"] == []
    assert cap["confidence"] == "inferred"
    assert cap["provenance"] == "static"


def test_extract_capability_empty_source_all_empty():
    cap = extract_capability("myclitool", "", "")
    assert cap["input_types"] == []
    assert cap["output_types"] == []
    assert cap["intent_tags"] == []
    assert cap["side_effect"] == "none"
