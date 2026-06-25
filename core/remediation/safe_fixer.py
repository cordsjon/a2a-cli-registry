"""The one mutating path — ARMED. apply() installs eligible packages into an
isolated per-target venv and re-probes before flipping health.

Honest threat model (spec §3.4): a venv isolates PACKAGES, not EXECUTION. pip can
run arbitrary build code. Containment is the SUM of the §3.4 constraints, opt-in
and allowlist-gated: wheel-only install (--only-binary=:all:, no setup.py run),
realpath-resolved venv inside demo/, scrubbed allowlist env, killpg wall-clock
timeout, and a re-probe whose only DB write is the single health_status/fixed_by
flip. Eligibility (class AND confidence AND mapped dist) gates every entry."""
import os
import subprocess

from core.prober.prober import _kill_tree, _POSIX
from core.remediation.proposal import FailureClass, Confidence
from core.remediation.classify import IMPORT_TO_PACKAGE

_MAPPED_DISTS = set(IMPORT_TO_PACKAGE.values())


class SafeFixer:
    def __init__(self, *, demo_dir: str):
        self.demo_dir = os.path.realpath(demo_dir)

    def is_eligible(self, proposal) -> bool:
        """All required (spec §3.4): pip-3rd-party class AND declared-by-regex
        confidence AND target is a MAPPED distribution name. Anything else refused."""
        return (
            proposal.failure_class == FailureClass.PIP_3RD_PARTY
            and proposal.confidence == Confidence.DECLARED_BY_REGEX
            and proposal.target in _MAPPED_DISTS
        )

    def venv_path_ok(self, candidate_path: str) -> bool:
        """The resolved (symlink-followed) venv path must stay inside demo_dir.
        Refuses a symlink that escapes the sandbox."""
        resolved = os.path.realpath(candidate_path)
        return resolved == self.demo_dir or resolved.startswith(self.demo_dir + os.sep)

    _ALLOWLIST_ENV = ("PATH",)  # minimum needed to locate python/pip; nothing project-specific

    def _isolated_env(self) -> dict:
        """Build a scrubbed process env for pip + re-probe (spec §3.4).

        Allowlist (not blocklist) so no project secret/config leaks in: start
        from an allowlisted few (PATH), then redirect HOME/caches/XDG inside
        demo/ and set PYTHONNOUSERSITE. A blocklist would silently pass any new
        env var the host adds; the allowlist fails closed."""
        sandbox = os.path.join(self.demo_dir, ".sandbox")
        env = {k: os.environ[k] for k in self._ALLOWLIST_ENV if k in os.environ}
        env["HOME"] = sandbox
        env["PIP_CACHE_DIR"] = os.path.join(sandbox, "pip-cache")
        env["TMPDIR"] = os.path.join(sandbox, "tmp")
        env["XDG_DATA_HOME"] = os.path.join(sandbox, "xdg-data")
        env["XDG_CACHE_HOME"] = os.path.join(sandbox, "xdg-cache")
        env["XDG_CONFIG_HOME"] = os.path.join(sandbox, "xdg-config")
        env["PYTHONNOUSERSITE"] = "1"
        return env

    def _venv_dir(self, target: str) -> str:
        """Per-package venv path inside demo/, with a defensive name check.

        target is already constrained to be a value in IMPORT_TO_PACKAGE by
        is_eligible(), but _venv_dir refuses any name containing path separators
        or '..' so a future caller can't smuggle traversal. The resulting path
        is also checked via venv_path_ok by the caller."""
        if os.sep in target or (os.altsep and os.altsep in target) or ".." in target:
            raise ValueError(f"unsafe venv target name: {target!r}")
        return os.path.join(self.demo_dir, ".sandbox", f"venv-{target}")

    def _run_contained(self, argv: list, *, timeout: float, env=None) -> tuple:
        """Run argv in the scrubbed env, own process group, wall-clock killpg.

        Returns (returncode, timed_out). Reuses the prober's _kill_tree so the
        whole process tree dies on timeout (a pip build subprocess can fork).
        Output is discarded — health is decided by exit code, same as the
        prober. cwd is demo_dir so any stray file write lands in the sandbox.
        env overrides the default scrubbed env (the re-probe prepends the
        venv bin to PATH); when None the standard _isolated_env() is used."""
        try:
            proc = subprocess.Popen(
                argv,
                cwd=self.demo_dir,
                env=env if env is not None else self._isolated_env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=_POSIX,
            )
        except (OSError, ValueError):
            return (1, False)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.wait()
            return (proc.returncode if proc.returncode is not None else -1, True)
        return (proc.returncode, False)

    def apply(self, proposals, *, session, health_cmd_for) -> list:
        """Install + re-probe each eligible proposal. Atomic per CLI: a failure
        records a FixResult and writes NOTHING for that CLI (spec §3.4).

        session: SQLModel session for the single health_status/fixed_by flip.
        health_cmd_for: callable slug -> health command string for the re-probe.
        """
        from core.remediation.proposal import FixResult
        from core.models import Cli
        results = []
        for p in proposals:
            if not self.is_eligible(p):
                results.append(FixResult(p.slug, p.target, "refused", "ineligible"))
                continue
            try:
                venv_dir = self._venv_dir(p.target)
            except ValueError as exc:
                results.append(FixResult(p.slug, p.target, "refused", str(exc)))
                continue
            if not self.venv_path_ok(venv_dir):
                results.append(FixResult(p.slug, p.target, "refused", "venv path escapes demo/"))
                continue

            rc, timed_out = self._install_one(p.target, venv_dir)
            if timed_out:
                results.append(FixResult(p.slug, p.target, "timeout", "install timed out"))
                continue
            if rc != 0:
                results.append(FixResult(p.slug, p.target, "install-failed", f"pip rc={rc}"))
                continue

            status = self._reprobe_one(p.slug, health_cmd_for(p.slug), venv_dir)
            if status != "healthy":
                results.append(FixResult(p.slug, p.target, "reprobe-failed", "still unhealthy"))
                continue

            # SUCCESS: the ONLY DB write — flip this one CLI. (spec §3.4)
            row = session.get(Cli, p.slug)
            if row is not None:
                row.health_status = "healthy"
                row.fixed_by = "remediation"
                session.add(row)
                session.commit()
            results.append(FixResult(p.slug, p.target, "fixed", "re-probe passed"))
        return results

    def _install_one(self, target, venv_dir) -> tuple:
        """Create the venv, wheel-only install `target`. Returns (rc, timed_out).
        --only-binary=:all: forbids source builds (no setup.py execution)."""
        import sys
        rc, t = self._run_contained([sys.executable, "-m", "venv", venv_dir], timeout=120.0)
        if rc != 0 or t:
            return (rc or 1, t)
        pip = os.path.join(venv_dir, "bin", "pip")
        return self._run_contained(
            [pip, "install", "--only-binary=:all:", "--no-input",
             "--timeout", "60", target],
            timeout=180.0)

    def _reprobe_one(self, slug, health_cmd, venv_dir) -> str:
        """Re-probe the CLI's health command in the isolated env. The venv's
        bin is prepended to PATH so the freshly-installed package is importable.
        Returns 'healthy' | 'unhealthy'."""
        import shlex
        env = self._isolated_env()
        env["PATH"] = os.path.join(venv_dir, "bin") + os.pathsep + env.get("PATH", "")
        rc, t = self._run_contained(shlex.split(health_cmd), timeout=10.0, env=env)
        return "healthy" if (rc == 0 and not t) else "unhealthy"
