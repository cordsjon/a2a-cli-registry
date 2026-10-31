import os
import re
import shlex
import shutil
from pathlib import Path
from typing import Optional
from core.discovery.base import CliRecord
from core.capability.model import CapabilityRecord
from core.capability.infer import infer_python_capability
from core.paths.module_root import _project_root


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


# A shell script is only safe to call with --help if it reads that flag, or hands
# its arguments to another program with `exec`. Anything else ignores --help and
# does its real work: sync-global-hooks.sh syncs, log-truncate.sh truncates.
_SHELL_HELP_BRANCH = re.compile(r"--help|getopts|^\s*-h\)", re.MULTILINE)
_SHELL_EXEC_PASSTHROUGH = re.compile(r'^\s*exec\s.*"\$@"', re.MULTILINE)
_SHELL_SHEBANG = re.compile(rb"^#!.*\b(ba|z|da|k)?sh\b")
_UNPROBEABLE_SUFFIXES = (".ts", ".js", ".mjs", ".cjs")
_PEP723_BLOCK = re.compile(r"^# /// script\s*$", re.MULTILINE)


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _is_shell_script(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return bool(_SHELL_SHEBANG.match(fh.readline(200)))
    except OSError:
        return False


class PythonAdapter:
    """Reference adapter. Carries US-77 (two-stage filter) + US-80 (python -m)."""

    def detect(self, rec: CliRecord) -> bool:
        return rec.lang == "python"

    def launch_spec(self, rec: CliRecord, stop: Optional[Path] = None) -> dict:
        # US-80: invoke as a module (python -m <slug>), not a bare script path.
        # Carry the absolute script_path too: the fleet's CLIs are loose .py
        # files (not importable modules), so a downstream executor needs the
        # concrete path to run `python3 <path>` — the entrypoint slug alone is
        # not runnable. Consumers that can import the module ignore it.
        spec = {"kind": "python_module", "entrypoint": rec.slug, "args_schema": {}}
        path = (rec.path or "").strip()
        if path:
            spec["script_path"] = path
        spec.update(self.launch_fields(rec, stop))
        return spec

    def launch_fields(self, rec: CliRecord, stop: Optional[Path] = None) -> dict:
        """What the probe runs, for a launcher to run the same thing: `argv`
        and `env`. Empty when there is no safe invocation."""
        invocation = self._invocation(rec, stop)
        if not invocation:
            return {}
        fields = {"argv": shlex.split(invocation)}
        # Never the caller's PYTHONPATH: this is stored on the row.
        entries = self._project_pythonpath(rec)
        if entries:
            fields["env"] = {"PYTHONPATH": os.pathsep.join(entries)}
        return fields

    def health_cmd(self, rec: CliRecord, stop: Optional[Path] = None) -> str:
        # US-77 two-stage filter resolves a safe --help/--version probe.
        invocation = self._invocation(rec, stop)
        return f"{invocation} --help" if invocation else ""

    def _invocation(self, rec: CliRecord, stop: Optional[Path] = None) -> str:
        # A loose script FILE (the cli-audit fleet shape) only runs as
        # `<interpreter> <path>` — `python -m <slug>` assumes the slug
        # is an importable module and fails for path-based scripts. Prefer the
        # path invocation when rec.path points at a real .py file, run with
        # the script's own project venv when one exists (bare `python` only
        # as the fallback); fall back to the module form (US-80) for
        # module-style entries with no script path.
        path = (rec.path or "").strip()
        if not path:
            return f"python -m {rec.slug}"
        if path.endswith(".py"):
            venv_python = project_interpreter(path, stop)
            interpreter = shlex.quote(venv_python or "python")
            if os.path.basename(path) == "__main__.py":
                # Run by path, a package's __main__ fails its relative imports.
                package = os.path.basename(os.path.dirname(path))
                return f"{interpreter} -m {shlex.quote(package)}"
            if venv_python is None and _PEP723_BLOCK.search(_read_text(path)):
                # Offline: a sweep must not fetch unpinned packages. Green means
                # the declared deps are already in uv's cache.
                uv = shlex.quote(shutil.which("uv") or "uv")
                return f"{uv} run --offline --script {shlex.quote(path)}"
            return f"{interpreter} {shlex.quote(path)}"
        # "" = unknown, never run. Registered under lang=python but not Python
        # (the feed infers lang loosely): .ts/.js, shell scripts, bare entrypoints.
        if path.endswith(_UNPROBEABLE_SUFFIXES):
            return ""
        if path.endswith(".sh") or _is_shell_script(path):
            text = _read_text(path)
            if _SHELL_EXEC_PASSTHROUGH.search(text) and os.access(path, os.X_OK):
                return shlex.quote(path)
            if _SHELL_HELP_BRANCH.search(text):
                return f"bash {shlex.quote(path)}"
            return ""
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return shlex.quote(path)
        return ""

    def health_env(self, rec: CliRecord) -> dict:
        """PYTHONPATH additions the probe needs on top of what it inherits."""
        entries = self._project_pythonpath(rec)
        if not entries:
            return {}
        inherited = os.environ.get("PYTHONPATH")
        if inherited:
            entries.append(inherited)
        return {"PYTHONPATH": os.pathsep.join(entries)}

    def _project_pythonpath(self, rec: CliRecord) -> list:
        """The script's project root, and a package's parent for `-m`. Scripts
        import their own project's code, which nothing on the default sys.path
        can resolve."""
        path = (rec.path or "").strip()
        if not path:
            return []
        entries = []
        if os.path.basename(path) == "__main__.py":
            entries.append(os.path.dirname(os.path.dirname(os.path.abspath(path))))
        root = _project_root(path)
        if root and root not in entries:
            entries.append(root)
        return entries

    def infer_capability(self, rec: CliRecord) -> Optional[CapabilityRecord]:
        return infer_python_capability(rec)
