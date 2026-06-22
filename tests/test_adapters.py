import pytest
from core.adapters.base import LanguageAdapter
from core.adapters.python_adapter import PythonAdapter
from core.adapters.stub_adapter import StubAdapter
from core.discovery.base import CliRecord


def _rec(lang, slug="x"):
    return CliRecord(slug=slug, lang=lang, path="/x", bucket=None, project=None,
                     description="", declared_capability=None, source_class=None, source_run_id=None)


def test_python_adapter_launch_spec_uses_module_invocation():
    spec = PythonAdapter().launch_spec(_rec("python", "pdf2text"))
    assert spec["kind"] == "python_module"        # US-80: python -m, not script path
    assert spec["entrypoint"] == "pdf2text"


def test_python_adapter_infer_returns_none_in_v1():
    # v1: infer_python_capability is a deliberate no-op stub; it returns None.
    assert PythonAdapter().infer_capability(_rec("python")) is None


@pytest.mark.xfail(reason="v1 inferer is a no-op stub; real inference deferred — when added, inferred caps MUST carry confidence='inferred'", strict=False)
def test_python_adapter_inferred_capability_is_flagged():
    cap = PythonAdapter().infer_capability(_rec("python"))
    assert cap is not None and cap.confidence == "inferred"


def test_stub_adapter_requires_declared_never_infers():
    stub = StubAdapter()
    assert stub.infer_capability(_rec("shell")) is None   # non-Python never infers


def test_adapters_satisfy_protocol():
    assert isinstance(PythonAdapter(), LanguageAdapter)
    assert isinstance(StubAdapter(), LanguageAdapter)
