import pytest
from core.remediation.classify import (
    classify_failure, IMPORT_TO_PACKAGE, MAP_VERSION,
)
from core.remediation.proposal import FailureClass, FixKind, Confidence

MNFE = "ModuleNotFoundError: No module named '{}'"

from core.remediation.classify import _proven_module_mode


def test_mapped_identity_third_party():
    p = classify_failure("detect_freshness", MNFE.format("numpy"), "/x/detect_freshness.py")
    assert p.failure_class == FailureClass.PIP_3RD_PARTY
    assert p.fix_kind == FixKind.AUTO_SAFE
    assert p.target == "numpy"
    assert p.confidence == Confidence.DECLARED_BY_REGEX


@pytest.mark.parametrize("imp,dist", [
    ("bs4", "beautifulsoup4"),
    ("pptx", "python-pptx"),
    ("docx", "python-docx"),
    ("fitz", "PyMuPDF"),
    ("yaml", "pyyaml"),
    ("sklearn", "scikit-learn"),
    ("dotenv", "python-dotenv"),
    ("PIL", "pillow"),
    ("cv2", "opencv-python"),
])
def test_import_not_equal_distribution_alias(imp, dist):
    p = classify_failure("c", MNFE.format(imp), "/x/c.py")
    assert p.failure_class == FailureClass.PIP_3RD_PARTY
    assert p.target == dist, f"{imp} must map to distribution {dist}, not import name"


def test_unmapped_not_proven_local_is_pip_unknown_not_wrong_cwd():
    # The specific defect a review surfaced: a non-mapped third-party name must
    # NOT be mislabelled wrong-cwd. No local romsorter.py adjacent -> pip-unknown.
    p = classify_failure("rs", MNFE.format("romsorter"), "/nonexistent/dir/rs.py")
    assert p.failure_class == FailureClass.PIP_UNKNOWN
    assert p.fix_kind == FixKind.PROPOSE_ONLY
    assert p.target == "romsorter"
    assert p.failure_class != FailureClass.WRONG_CWD


def test_proven_local_module_is_wrong_cwd(tmp_path):
    (tmp_path / "syllabus_v2.py").write_text("# local module\n")
    cli = tmp_path / "seed_artefacts.py"
    cli.write_text("import syllabus_v2\n")
    p = classify_failure("seed_artefacts", MNFE.format("syllabus_v2"), str(cli))
    assert p.failure_class == FailureClass.WRONG_CWD
    assert p.fix_kind == FixKind.PROPOSE_ONLY
    assert p.target == "syllabus_v2"


def test_proven_local_package_dir_is_wrong_cwd(tmp_path):
    (tmp_path / "engine").mkdir()
    (tmp_path / "engine" / "__init__.py").write_text("")
    cli = tmp_path / "run.py"
    cli.write_text("import engine\n")
    p = classify_failure("run", MNFE.format("engine"), str(cli))
    assert p.failure_class == FailureClass.WRONG_CWD


def test_dotted_module_uses_top_segment(tmp_path):
    # google.cloud -> top segment 'google'; not mapped, not local -> pip-unknown
    p = classify_failure("c", MNFE.format("google.cloud"), str(tmp_path / "c.py"))
    assert p.target == "google"
    assert p.failure_class == FailureClass.PIP_UNKNOWN


def test_proven_module_mode_two_dirs_up(tmp_path):
    # syllabus_v2 lives at the project root, two directories above the
    # failing CLI's own file — _proven_local (adjacent-only) would miss
    # this; _proven_module_mode must find it via _project_root.
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "syllabus_v2").mkdir()
    (tmp_path / "syllabus_v2" / "__init__.py").write_text("")
    cli = tmp_path / "scripts" / "tools" / "categorize.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("import syllabus_v2\n")
    p = classify_failure("categorize", MNFE.format("syllabus_v2"), str(cli))
    assert p.failure_class == FailureClass.WRONG_CWD
    assert p.fix_kind == FixKind.PROPOSE_ONLY
    assert "python -m syllabus_v2" in p.evidence


def test_proven_module_mode_file_form(tmp_path):
    # A module as a single file (engine.py) at the project root, not a
    # package dir - both forms must be proven.
    (tmp_path / "setup.py").write_text("")
    (tmp_path / "engine.py").write_text("")
    cli = tmp_path / "sub" / "run.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("import engine\n")
    p = classify_failure("run", MNFE.format("engine"), str(cli))
    assert p.failure_class == FailureClass.WRONG_CWD
    assert "python -m engine" in p.evidence


def test_dotted_submodule_partial_proof_is_not_proof(tmp_path):
    # localpkg exists at the root, but the specific submodule 'missing' does
    # not. This must NOT be misclassified wrong-cwd - the missing submodule
    # is a real gap, not a wrong-cwd problem. (This is the case a partial
    # top-segment-only check would get wrong.)
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "localpkg").mkdir()
    (tmp_path / "localpkg" / "__init__.py").write_text("")
    cli = tmp_path / "sub" / "run.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("from localpkg import missing\n")
    p = classify_failure("run", MNFE.format("localpkg.missing"), str(cli))
    assert p.failure_class == FailureClass.PIP_UNKNOWN
    assert p.failure_class != FailureClass.WRONG_CWD


def test_proven_module_mode_empty_path_returns_none():
    assert _proven_module_mode("", "anything") is None


def test_proven_module_mode_no_root_found_returns_none(tmp_path):
    # No sentinel anywhere under tmp_path -> _project_root returns None ->
    # _proven_module_mode must return None, not raise.
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    cli = isolated / "c.py"
    cli.write_text("")
    assert _proven_module_mode(str(cli), "somepkg") is None


def test_adjacent_file_case_still_wins_over_module_mode(tmp_path):
    # Regression: the existing _proven_local (adjacent-file) path must still
    # be checked BEFORE _proven_module_mode, and still produce WRONG_CWD with
    # its own (non-python-m) evidence wording, per the current test
    # test_proven_local_module_is_wrong_cwd.
    (tmp_path / "syllabus_v2.py").write_text("# local module\n")
    cli = tmp_path / "seed_artefacts.py"
    cli.write_text("import syllabus_v2\n")
    p = classify_failure("seed_artefacts", MNFE.format("syllabus_v2"), str(cli))
    assert p.failure_class == FailureClass.WRONG_CWD
    assert "proven-local" in p.evidence


def test_syntax_error_is_code_bug():
    p = classify_failure("c", "SyntaxError: invalid syntax (foo.py, line 3)", "/x/c.py")
    assert p.failure_class == FailureClass.CODE_BUG
    assert p.fix_kind == FixKind.NEEDS_HUMAN
    assert p.target == ""


def test_indentation_error_is_code_bug():
    p = classify_failure("c", "IndentationError: unexpected indent", "/x/c.py")
    assert p.failure_class == FailureClass.CODE_BUG


def test_env_missing_extracts_var():
    p = classify_failure("c", "KeyError: 'OPENAI_API_KEY'", "/x/c.py")
    assert p.failure_class == FailureClass.ENV_MISSING
    assert p.fix_kind == FixKind.PROPOSE_ONLY
    assert p.target == "OPENAI_API_KEY"


def test_file_not_found_is_wrong_cwd():
    p = classify_failure("c", "FileNotFoundError: [Errno 2] No such file or directory: 'data.csv'", "/x/c.py")
    assert p.failure_class == FailureClass.WRONG_CWD
    assert p.fix_kind == FixKind.PROPOSE_ONLY


def test_path_only_description_is_unknown():
    # 114/217 fleet rows: description is just the file path, no error signal.
    p = classify_failure("inlay", "70_ASSET-ENGINE/backend/revisions/inlay.py", "/x/inlay.py")
    assert p.failure_class == FailureClass.UNKNOWN
    assert p.fix_kind == FixKind.NEEDS_HUMAN


def test_gibberish_is_unknown():
    p = classify_failure("c", "the cat sat on the mat", "/x/c.py")
    assert p.failure_class == FailureClass.UNKNOWN


def test_classifier_never_raises_on_empty():
    p = classify_failure("c", "", "")
    assert p.failure_class == FailureClass.UNKNOWN


def test_map_covers_required_aliases():
    for imp in ("bs4", "pptx", "docx", "fitz", "cv2", "PIL", "yaml", "sklearn", "dotenv"):
        assert imp in IMPORT_TO_PACKAGE
    assert MAP_VERSION == 1
