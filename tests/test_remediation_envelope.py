from core.remediation.proposal import (
    SCHEMA_VERSION, FailureClass, FixKind, Confidence,
    RemediationProposal, FailureRecord, build_envelope,
)


def _proposal(**kw):
    base = dict(
        schema_version=SCHEMA_VERSION,
        slug="generate-pdf",
        failure_class=FailureClass.PIP_3RD_PARTY,
        fix_kind=FixKind.AUTO_SAFE,
        target="beautifulsoup4",
        confidence=Confidence.DECLARED_BY_REGEX,
        evidence="ModuleNotFoundError: No module named 'bs4' | mapped bs4->beautifulsoup4",
    )
    base.update(kw)
    return RemediationProposal(**base)


def test_proposal_to_dict_serializes_enums_as_values():
    d = _proposal().to_dict()
    assert d["failure_class"] == "pip-3rd-party"
    assert d["fix_kind"] == "auto-safe"
    assert d["confidence"] == "declared-by-regex"
    assert d["schema_version"] == 1
    assert d["slug"] == "generate-pdf"
    assert d["target"] == "beautifulsoup4"


def test_failure_record_to_dict():
    fr = FailureRecord(slug="app", reason="timeout", attempt_at="2026-06-25T20:00:00Z")
    assert fr.to_dict() == {
        "slug": "app", "reason": "timeout", "attempt_at": "2026-06-25T20:00:00Z",
    }


def test_build_envelope_shape():
    env = build_envelope(
        [_proposal()],
        [FailureRecord(slug="app", reason="refused", attempt_at="2026-06-25T20:00:00Z")],
        map_version=1,
        generated_at="2026-06-25T20:00:00Z",
        session_id="11111111-1111-1111-1111-111111111111",
    )
    assert env["schema_version"] == 1
    assert env["map_version"] == 1
    assert env["generated_at"] == "2026-06-25T20:00:00Z"
    assert env["session_id"] == "11111111-1111-1111-1111-111111111111"
    assert isinstance(env["proposals"], list) and env["proposals"][0]["failure_class"] == "pip-3rd-party"
    assert env["failure_records"][0]["reason"] == "refused"
