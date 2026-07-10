"""Pure filesystem path derivation for module-mode invocation.

Shared by bridge/llm_infer.py (probe ladder) and
core/remediation/classify.py (module-mode proof). Pure path math only —
no subprocess, no network. Moved here from bridge/llm_infer.py so both
consumers use one definition (abstract-on-third)."""
import os

# Project-root sentinels: the nearest ancestor containing one of these is the
# directory from which `python -m pkg.module` resolves package-relative imports.
_ROOT_SENTINELS = ("pyproject.toml", "setup.py", "setup.cfg", ".git", "requirements.txt")


def _project_root(path: str) -> str | None:
    """Walk up from the file to the nearest dir holding a root sentinel."""
    d = os.path.dirname(os.path.abspath(path))
    prev = None
    while d and d != prev:
        for s in _ROOT_SENTINELS:
            if os.path.exists(os.path.join(d, s)):
                return d
        prev, d = d, os.path.dirname(d)
    return None


def _dotted_module(path: str, root: str) -> str | None:
    """Dotted module path of `path` relative to `root`.

    /root/pkg/sub/cli.py  under root  ->  pkg.sub.cli
    """
    try:
        rel = os.path.relpath(os.path.abspath(path), root)
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    rel = os.path.splitext(rel)[0]
    parts = [p for p in rel.split(os.sep) if p]
    if not parts:
        return None
    return ".".join(parts)
