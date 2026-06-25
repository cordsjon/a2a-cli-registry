import json
import pytest
from core.remediation.hermes_adapter import HermesAdapter
from core.remediation.proposal import FailureClass, FixKind, Confidence


class Row:
    def __init__(self, slug, description="", path=""):
        self.slug = slug
        self.description = description
        self.path = path


def _fixed_now():
    return "2026-06-25T20:00:00Z"


def test_empty_input_makes_no_call():
    calls = []
    a = HermesAdapter(now=_fixed_now)
    a._post = lambda payload: calls.append(payload) or {}
    props, recs = a.diagnose([], max_calls=5)
    assert props == [] and recs == []
    assert calls == []


def test_success_refines_to_llm_inferred():
    a = HermesAdapter(now=_fixed_now)

    def fake_post(payload):
        return {"choices": [{"message": {"content": json.dumps([
            {"slug": "app", "failure_class": "wrong-cwd", "target": "app",
             "evidence": "local module app/ exists one level up"},
        ])}}]}
    a._post = fake_post
    props, recs = a.diagnose([Row("app")], max_calls=5)
    assert recs == []
    assert props[0].slug == "app"
    assert props[0].failure_class == FailureClass.WRONG_CWD
    assert props[0].confidence == Confidence.LLM_INFERRED
    assert props[0].fix_kind == FixKind.PROPOSE_ONLY


@pytest.mark.parametrize("exc_or_status,reason", [
    ("refused", "refused"),
    ("timeout", "timeout"),
    ("non200", "non200"),
    ("parse", "parse"),
])
def test_degrades_to_unknown_with_failure_record(exc_or_status, reason):
    a = HermesAdapter(now=_fixed_now)

    def fake_post(payload):
        if exc_or_status == "refused":
            raise ConnectionRefusedError("refused")
        if exc_or_status == "timeout":
            raise TimeoutError("slow")
        if exc_or_status == "non200":
            from core.remediation.hermes_adapter import HermesHTTPError
            raise HermesHTTPError(503, "non200")
        return {"choices": [{"message": {"content": "NOT JSON"}}]}  # parse failure
    a._post = fake_post
    props, recs = a.diagnose([Row("app"), Row("cli")], max_calls=5)
    assert all(p.failure_class == FailureClass.UNKNOWN for p in props)
    assert all(p.fix_kind == FixKind.NEEDS_HUMAN for p in props)
    assert {r.reason for r in recs} == {reason}
    assert {r.slug for r in recs} == {"app", "cli"}
    assert all(r.attempt_at == "2026-06-25T20:00:00Z" for r in recs)


def test_max_calls_caps_batches_and_leaves_rest_unknown():
    a = HermesAdapter(now=_fixed_now)
    seen = []

    def fake_post(payload):
        seen.append(payload)
        return {"choices": [{"message": {"content": json.dumps([])}}]}
    a._post = fake_post
    rows = [Row(f"c{i}") for i in range(25)]  # 25 CLIs -> 3 batches of <=10
    props, recs = a.diagnose(rows, max_calls=1)  # only 1 batch allowed
    assert len(seen) == 1  # exactly one HTTP call made
    # 15 CLIs beyond the cap stay unknown
    unknown = [p for p in props if p.failure_class == FailureClass.UNKNOWN]
    assert len(unknown) == 15


def test_batch_size_at_most_ten():
    a = HermesAdapter(now=_fixed_now)
    sizes = []

    def fake_post(payload):
        sizes.append(len(payload["_batch_slugs"]))
        return {"choices": [{"message": {"content": json.dumps([])}}]}
    a._post = fake_post
    a.diagnose([Row(f"c{i}") for i in range(23)], max_calls=10)
    assert max(sizes) <= 10
    assert sum(sizes) == 23
