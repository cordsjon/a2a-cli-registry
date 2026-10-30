import shlex
from pathlib import Path
from typing import Optional
from core.discovery.base import CliRecord
from core.capability.model import CapabilityRecord
from core.capability.infer import infer_python_capability


_VENV_DIRS = (".venv", "venv")
_VENV_PYTHONS = (("bin", "python"), ("Scripts", "python.exe"))


def project_interpreter(script_path: str, stop: Optional[Path] = None) -> Optional[str]:
    """Nearest project venv interpreter above `script_path`.

    Walks from the script's directory upward and returns the first
    `.venv`/`venv` python it meets, stopping BEFORE `stop` (default: $HOME)
    and at the filesystem root. None when the script has no project venv.

    Why: the fleet's CLIs import from their project venv. Probing them with
    the bare `python` on PATH fails on the first ModuleNotFoundError, which
    on 2026-10-31 mislabeled 138 of 281 existing-path Python rows unhealthy.
    """
    boundary = (stop or Path.home()).absolute()
    d = Path(script_path).absolute().parent
    while d != boundary and d != d.parent:
        for venv in _VENV_DIRS:
            for parts in _VENV_PYTHONS:
                py = d.joinpath(venv, *parts)
                if py.is_file():
                    return str(py)
        d = d.parent
    return None


class PythonAdapter:
    """Reference adapter. Carries US-77 (two-stage filter) + US-80 (python -m)."""

    def detect(self, rec: CliRecord) -> bool:
        return rec.lang == "python"

    def launch_spec(self, rec: CliRecord) -> dict:
        # US-80: invoke as a module (python -m <slug>), not a bare script path.
        # Carry the absolute script_path too: the fleet's CLIs are loose .py
        # files (not importable modules), so a downstream executor needs the
        # concrete path to run `python3 <path>` — the entrypoint slug alone is
        # not runnable. Consumers that can import the module ignore it.
        spec = {"kind": "python_module", "entrypoint": rec.slug, "args_schema": {}}
        path = (rec.path or "").strip()
        if path:
            spec["script_path"] = path
        return spec

    def health_cmd(self, rec: CliRecord, stop: Optional[Path] = None) -> str:
        # US-77 two-stage filter resolves a safe --help/--version probe.
        # A loose script FILE (the cli-audit fleet shape) only runs as
        # `<interpreter> <path> --help` — `python -m <slug>` assumes the slug
        # is an importable module and fails for path-based scripts. Prefer the
        # path invocation when rec.path points at a real .py file, run with
        # the script's own project venv when one exists (bare `python` only
        # as the fallback); fall back to the module form (US-80) for
        # module-style entries with no script path.
        path = (rec.path or "").strip()
        if path.endswith(".py"):
            interpreter = project_interpreter(path, stop) or "python"
            return f"{shlex.quote(interpreter)} {shlex.quote(path)} --help"
        return f"python -m {rec.slug} --help"

    def infer_capability(self, rec: CliRecord) -> Optional[CapabilityRecord]:
        return infer_python_capability(rec)
