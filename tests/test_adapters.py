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


def test_python_adapter_infers_none_without_signal():
    rec = _rec("python")
    rec.description = "a generic tool with no capability signal whatsoever"
    assert PythonAdapter().infer_capability(rec) is None


def test_python_adapter_infers_from_help_text_with_signal():
    # a help text containing a known signal ("format ... in place") now infers
    rec = _rec("python")
    rec.description = "The uncompromising code formatter; reformats files in place."
    cap = PythonAdapter().infer_capability(rec)
    assert cap is not None
    assert cap.confidence == "inferred"
    assert "format" in cap.intent_tags


def test_stub_adapter_requires_declared_never_infers():
    stub = StubAdapter()
    assert stub.infer_capability(_rec("shell")) is None   # non-Python never infers


def test_adapters_satisfy_protocol():
    assert isinstance(PythonAdapter(), LanguageAdapter)
    assert isinstance(StubAdapter(), LanguageAdapter)
