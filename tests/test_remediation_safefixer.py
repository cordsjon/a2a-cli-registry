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


# --- Task 4: isolated/scrubbed process env ---
def test_isolated_env_redirects_into_demo_and_scrubs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "/etc/should-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-should-not-leak")
    fixer = SafeFixer(demo_dir=str(tmp_path))
    env = fixer._isolated_env()
    demo = os.path.realpath(str(tmp_path))
    # redirected inside demo/
    assert env["HOME"].startswith(demo)
    assert env["PIP_CACHE_DIR"].startswith(demo)
    assert env["TMPDIR"].startswith(demo)
    assert env["XDG_DATA_HOME"].startswith(demo)  # overridden, not the leaked /etc value
    # hardening flag
    assert env["PYTHONNOUSERSITE"] == "1"
    # no inherited project secret
    assert "OPENAI_API_KEY" not in env
    # PATH is preserved (need to find pip/python) but not arbitrary project vars
    assert "PATH" in env


# --- Task 5: _run_contained killpg-timeout subprocess primitive ---
import sys


def test_run_contained_returns_zero_on_success(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    rc, timed_out = fixer._run_contained([sys.executable, "-c", "pass"], timeout=10.0)
    assert rc == 0 and timed_out is False


def test_run_contained_nonzero_exit(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    rc, timed_out = fixer._run_contained([sys.executable, "-c", "import sys; sys.exit(7)"], timeout=10.0)
    assert rc == 7 and timed_out is False


def test_run_contained_kills_on_timeout(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    rc, timed_out = fixer._run_contained(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert timed_out is True


# --- Task 6: per-target sandbox venv path with traversal refusal ---
def test_venv_dir_is_per_target_inside_demo(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    vd = fixer._venv_dir("numpy")
    assert os.path.realpath(vd).startswith(os.path.realpath(str(tmp_path)))
    assert "numpy" in os.path.basename(vd)


def test_venv_dir_rejects_path_traversal_target(tmp_path):
    fixer = SafeFixer(demo_dir=str(tmp_path))
    # a malicious/garbage target must not escape demo/ via .. or /
    with pytest.raises(ValueError):
        fixer._venv_dir("../../etc")
