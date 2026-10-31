import os
from typing import Optional
from core.adapters.python_adapter import (
    _SHELL_EXEC_PASSTHROUGH,
    _SHELL_HELP_BRANCH,
    _is_shell_script,
    _read_text,
)
from core.discovery.base import CliRecord
from core.capability.model import CapabilityRecord


class StubAdapter:
    """Non-Python languages: declared-capabilities-required, NEVER infers."""

    def detect(self, rec: CliRecord) -> bool:
        return rec.lang in {"go", "node", "shell"}

    def launch_spec(self, rec: CliRecord) -> dict:
        spec = {"kind": "executable", "entrypoint": rec.path, "args_schema": {}}
        spec.update(self.launch_fields(rec))
        return spec

    def launch_fields(self, rec: CliRecord) -> dict:
        """The `argv` a launcher runs; empty when the path cannot be executed."""
        path = (rec.path or "").strip()
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return {"argv": [path]}
        return {}

    def health_cmd(self, rec: CliRecord) -> str:
        path = (rec.path or "").strip()
        if path.endswith(".sh") or _is_shell_script(path):
            # "" = unknown, never run: same guard as PythonAdapter._invocation.
            text = _read_text(path)
            if not (_SHELL_HELP_BRANCH.search(text) or _SHELL_EXEC_PASSTHROUGH.search(text)):
                return ""
        return f"{rec.path} --help"

    def infer_capability(self, rec: CliRecord) -> Optional[CapabilityRecord]:
        return None  # declared-required
