from typing import Optional
from core.discovery.base import CliRecord
from core.capability.model import CapabilityRecord
from core.capability.infer import infer_python_capability


class PythonAdapter:
    """Reference adapter. Carries US-77 (two-stage filter) + US-80 (python -m)."""

    def detect(self, rec: CliRecord) -> bool:
        return rec.lang == "python"

    def launch_spec(self, rec: CliRecord) -> dict:
        # US-80: invoke as a module (python -m <slug>), not a bare script path.
        return {"kind": "python_module", "entrypoint": rec.slug, "args_schema": {}}

    def health_cmd(self, rec: CliRecord) -> str:
        # US-77 two-stage filter resolves a safe --help/--version probe.
        return f"python -m {rec.slug} --help"

    def infer_capability(self, rec: CliRecord) -> Optional[CapabilityRecord]:
        return infer_python_capability(rec)
