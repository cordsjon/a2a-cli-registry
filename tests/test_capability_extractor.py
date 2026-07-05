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


def test_side_effect_new_output_file_regardless_of_name_vocabulary():
    # Two declared arguments -- output flag name ("--result-path") happens to
    # contain an input-heuristic substring ("path") and no denylist word.
    # Must still be "none": declaration COUNT (2 args), not name content, is
    # what makes this a converter, not an in-place tool.
    source = '''
import argparse
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("--in", type=Path)
p.add_argument("--result-path", type=Path)
args = p.parse_args()
with open(args.result_path, "w") as f:
    f.write("converted")
'''
    assert infer_side_effect(source) == "none"


def test_side_effect_writes_fs_regardless_of_name_vocabulary():
    # Exactly ONE declared argument -- name ("--target-file") happens to contain
    # a word that would have been in the old deny-list ("target"). Must still be
    # "writes-fs": it's the CLI's only path, and it's opened for writing --
    # definitionally in-place, regardless of what the flag is called.
    source = '''
import argparse
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("--target-file", type=Path)
args = p.parse_args()
with open(args.target_file, "w") as f:
    f.write("formatted")
'''
    assert infer_side_effect(source) == "writes-fs"


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


def test_side_effect_writes_fs_scoped_per_subcommand_not_contaminated_by_siblings():
    # 'format' subcommand has exactly ONE argument, rewritten in place (writes-fs
    # for that subcommand). 'convert' subcommand has TWO arguments, a genuine
    # converter (none for that subcommand). The whole-CLI side_effect must not
    # let 'convert's argument count leak into 'format's classification --
    # 'format' alone is a genuine in-place tool and that must be detected.
    source = '''
import argparse
from pathlib import Path
p = argparse.ArgumentParser()
sub = p.add_subparsers()

format_p = sub.add_parser("format")
format_p.add_argument("--file", type=Path)

convert_p = sub.add_parser("convert")
convert_p.add_argument("--src", type=Path)
convert_p.add_argument("--dst", type=Path)

args = p.parse_args()
if args.command == "format":
    with open(args.file, "w") as f:
        f.write("formatted")
else:
    with open(args.dst, "w") as f:
        f.write("converted")
'''
    assert infer_side_effect(source) == "writes-fs"


def test_extract_capability_empty_source_all_empty():
    cap = extract_capability("myclitool", "", "")
    assert cap["input_types"] == []
    assert cap["output_types"] == []
    assert cap["intent_tags"] == []
    assert cap["side_effect"] == "none"


def test_click_option_path():
    source = '''
import click

@click.command()
@click.option("--out", type=click.Path())
def main(out):
    pass
'''
    assert "path" in extract_inputs(source)


def test_typer_command_path_param():
    source = '''
import typer
from pathlib import Path

app = typer.Typer()

@app.command()
def main(path: Path):
    pass
'''
    assert "path" in extract_inputs(source)


def test_typer_command_int_param():
    source = '''
import typer

app = typer.Typer()

@app.command()
def main(count: int):
    pass
'''
    assert "int" in extract_inputs(source)


def test_typer_option_default():
    source = '''
import typer

app = typer.Typer()

@app.command()
def main(name: str = typer.Option(...)):
    pass
'''
    assert "str" in extract_inputs(source)


def test_typer_only_no_argparse_click_signal_extractor_still_finds_parser():
    # Full Typer CLI with zero argparse/click markers -- this is the 72-CLI
    # Typer-only gap the spec calls out. Extractor must find inputs (not
    # empty), so backfill_capabilities does NOT route this to LLM fallback.
    source = '''
import typer
from pathlib import Path

app = typer.Typer()

@app.command()
def convert(input_file: Path, output_file: Path):
    """Convert input to output."""
    pass

if __name__ == "__main__":
    app()
'''
    inputs = extract_inputs(source)
    assert inputs, "Typer-only CLI must not extract to empty input_types"
    assert "path" in inputs


def test_click_option_int_attribute_form():
    source = '''
import click

@click.command()
@click.option("--n", type=click.INT)
def main(n):
    pass
'''
    assert "int" in extract_inputs(source)


def test_typer_annotated_path_param():
    source = '''
import typer
from pathlib import Path
from typing import Annotated

app = typer.Typer()

@app.command()
def main(path: Annotated[Path, typer.Argument()]):
    pass
'''
    assert "path" in extract_inputs(source)


def test_typer_annotated_int_param():
    source = '''
import typer
from typing import Annotated

app = typer.Typer()

@app.command()
def main(count: Annotated[int, typer.Option()]):
    pass
'''
    assert "int" in extract_inputs(source)


def test_side_effect_writes_fs_for_generic_db_execute_no_output_arg():
    source = '''
import argparse
import sqlite3

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--role", required=True)
    args = p.parse_args()
    conn = sqlite3.connect("syllabus.db")
    conn.execute("INSERT INTO topic_role (role) VALUES (?)", (args.role,))
    conn.commit()
'''
    assert infer_side_effect(source) == "writes-fs"


def test_side_effect_network_for_http_server_serve_forever():
    source = '''
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        pass

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    server = ThreadingHTTPServer(("", args.port), Handler)
    server.serve_forever()
'''
    assert infer_side_effect(source) == "network"


def test_side_effect_writes_fs_for_generic_file_write_non_input_path():
    source = '''
import argparse

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--role")
    p.add_argument("--topic")
    args = p.parse_args()
    with open("results.csv", "a") as f:
        f.write(f"{args.role},{args.topic}\\n")
'''
    assert infer_side_effect(source) == "writes-fs"


def test_side_effect_none_still_correct_for_genuinely_pure_function():
    source = '''
import argparse

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--value", type=int)
    args = p.parse_args()
    print(args.value * 2)
'''
    assert infer_side_effect(source) == "none"


def test_side_effect_existing_inplace_rewrite_rule_still_fires_first():
    """Regression: the existing narrow in-place-rewrite rule (Task 1, 3
    review rounds) must still take priority and still work exactly as
    before -- this fix must not break it."""
    source = '''
import argparse

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    args = p.parse_args()
    content = open(args.file).read()
    with open(args.file, "w") as f:
        f.write(content.strip())
'''
    assert infer_side_effect(source) == "writes-fs"


def test_side_effect_existing_network_import_rule_still_fires():
    """Regression: existing client-network-module import detection must
    still work exactly as before."""
    source = '''
import argparse
import requests

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    args = p.parse_args()
    requests.get(args.url)
'''
    assert infer_side_effect(source) == "network"


def test_intent_tags_corpus_verbs_seed_ingest_migrate():
    assert "seed" in extract_intent_tags("seed_db", "Seeds a database from an XLSX syllabus file.", "")
    assert "ingest" in extract_intent_tags("x", "Ingest the O*NET text database into backbone tables.", "")
    assert "migrate" in extract_intent_tags("x", "Runs a database migration for one table.", "")


def test_intent_tags_prefix_boundary_no_substring_false_positive():
    # 'scan' must not fire from 'landscape'; 'seed' must not fire from 'proceeds'
    tags = extract_intent_tags("x", "renders a landscape view of proceeds", "")
    assert "scan" not in tags
    assert "seed" not in tags


def test_extract_outputs_library_save_call_is_path():
    source = "def main(out):\n    prs.save(out)\n"
    assert extract_outputs(source) == ["path"]


def test_extract_outputs_savefig_is_path():
    source = "def main(out):\n    plt.savefig(out)\n"
    assert extract_outputs(source) == ["path"]
