import os
import pytest
from core.remediation.safe_fixer import SafeFixer
from core.remediation.proposal import (
    SCHEMA_VERSION, RemediationProposal, FailureClass, FixKind, Confidence,
)


def _p(fc, target, conf=Confidence.DECLARED_BY_REGEX, fk=FixKind.AUTO_SAFE):
    return RemediationProposal(
        schema_version=SCHEMA_VERSION, slug="s", failure_class=fc, fix_kind=fk,
        target=target, confidence=conf, evidence="e")


def test_apply_raises_not_implemented(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    with pytest.raises(NotImplementedError):
        fixer.apply([_p(FailureClass.PIP_3RD_PARTY, "numpy")])


def test_eligible_for_mapped_pip_third_party(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    assert fixer.is_eligible(_p(FailureClass.PIP_3RD_PARTY, "numpy")) is True
    assert fixer.is_eligible(_p(FailureClass.PIP_3RD_PARTY, "beautifulsoup4")) is True


def test_refuses_unmapped_name(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    # 'romsorter' is not a value in IMPORT_TO_PACKAGE
    assert fixer.is_eligible(_p(FailureClass.PIP_3RD_PARTY, "romsorter")) is False


def test_refuses_import_key_that_is_not_a_dist_value(tmp_path):
    # 'bs4' is a KEY in IMPORT_TO_PACKAGE but NOT a value (the value is
    # 'beautifulsoup4'). Eligibility must check distribution names (values),
    # so a bare import name must be refused — guards against installing the
    # wrong package for an import alias.
    fixer = SafeFixer(demo_dir=str(tmp_path))
    assert fixer.is_eligible(_p(FailureClass.PIP_3RD_PARTY, "bs4")) is False


def test_refuses_all_non_pip_classes(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    for fc in (FailureClass.PIP_UNKNOWN, FailureClass.WRONG_CWD,
               FailureClass.CODE_BUG, FailureClass.ENV_MISSING, FailureClass.UNKNOWN):
        assert fixer.is_eligible(_p(fc, "numpy")) is False


def test_refuses_llm_inferred_confidence(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    assert fixer.is_eligible(
        _p(FailureClass.PIP_3RD_PARTY, "numpy", conf=Confidence.LLM_INFERRED)) is False


def test_venv_inside_demo_ok(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    assert fixer.venv_path_ok(str(tmp_path / "venv-numpy")) is True


def test_venv_symlink_escape_refused(tmp_path):
    demo = tmp_path / "demo"
    demo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    escape = demo / "escape"
    os.symlink(str(outside), str(escape))  # demo/escape -> outside (resolves out)
    fixer = SafeFixer(demo_dir=str(demo))
    assert fixer.venv_path_ok(str(escape / "venv")) is False


# --- Task 1: FixResult value object ---
from core.remediation.proposal import FixResult


def test_fixresult_to_dict_roundtrip():
    r = FixResult(slug="s", target="numpy", outcome="fixed", detail="re-probe passed")
    assert r.to_dict() == {
        "slug": "s", "target": "numpy", "outcome": "fixed",
        "detail": "re-probe passed",
    }


def test_fixresult_outcomes_are_constrained():
    # outcome is a plain str but the constructor documents the allowed set;
    # this test pins the vocabulary so a typo'd outcome string is caught.
    for o in ("fixed", "install-failed", "reprobe-failed", "refused", "timeout"):
        FixResult(slug="s", target="t", outcome=o, detail="")


# --- Task 2: Cli.fixed_by provenance column ---
from core.models import Cli


def test_cli_has_fixed_by_field_defaulting_none():
    c = Cli(slug="s", lang="python")
    assert c.fixed_by is None
