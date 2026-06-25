"""ONE real install+re-probe. Network + pip required; marked 'e2e' so the
default suite can deselect it (pytest -m 'not e2e'). Uses a tiny pure-Python
wheel that is a VALUE in IMPORT_TO_PACKAGE so eligibility passes."""
import os
import sys
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from core.models import Cli
from core.remediation.safe_fixer import SafeFixer
from core.remediation.proposal import (
    SCHEMA_VERSION, RemediationProposal, FailureClass, FixKind, Confidence)
from core.remediation.classify import IMPORT_TO_PACKAGE

# pick a small, pure-python, wheel-only-installable mapped dist
_TARGET = "portalocker"  # identity-mapped in the fleet; tiny; pure python


@pytest.mark.e2e
def test_real_install_and_reprobe_flips_health(tmp_path):
    assert _TARGET in set(IMPORT_TO_PACKAGE.values())
    demo = tmp_path / "demo"; demo.mkdir()
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        # health cmd is irrelevant to the assertion below — apply() re-probes via
        # health_cmd_for, which we point at the venv python so the import only
        # succeeds if the install really landed.
        s.add(Cli(slug="pl-cli", lang="python", health_status="unhealthy",
                  health_cmd="true")); s.commit()
        fixer = SafeFixer(demo_dir=str(demo))
        p = RemediationProposal(schema_version=SCHEMA_VERSION, slug="pl-cli",
            failure_class=FailureClass.PIP_3RD_PARTY, fix_kind=FixKind.AUTO_SAFE,
            target=_TARGET, confidence=Confidence.DECLARED_BY_REGEX, evidence="e")
        venv_python = os.path.join(
            str(demo), ".sandbox", f"venv-{_TARGET}", "bin", "python")
        results = fixer.apply([p], session=s,
            health_cmd_for=lambda slug: f'{venv_python} -c "import portalocker"')
        row = s.get(Cli, "pl-cli")
        assert results[0].outcome == "fixed", results[0].detail
        assert row.health_status == "healthy"
        assert row.fixed_by == "remediation"
