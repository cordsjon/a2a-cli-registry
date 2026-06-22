from typing import Optional
from core.discovery.base import CliRecord
from core.capability.model import CapabilityRecord


class StubAdapter:
    """Non-Python languages: declared-capabilities-required, NEVER infers."""

    def detect(self, rec: CliRecord) -> bool:
        return rec.lang in {"go", "node", "shell"}

    def launch_spec(self, rec: CliRecord) -> dict:
        return {"kind": "executable", "entrypoint": rec.path, "args_schema": {}}

    def health_cmd(self, rec: CliRecord) -> str:
        return f"{rec.path} --help"

    def infer_capability(self, rec: CliRecord) -> Optional[CapabilityRecord]:
        return None  # declared-required
