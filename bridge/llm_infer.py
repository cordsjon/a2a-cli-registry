"""SPIKE: LLM capability inference per CLI (component #2 of the bridge epic).

Goal the keyword inferer (core/capability/infer.py) cannot meet: produce the
typed input/output PORTS that `plan_cli_chain` needs to form edges. Keyword
inference yields intent_tags + side_effect only (input_types/output_types = []).

Design (locked from reading the registry):
  - Reads a CLI's --help text, asks a local LLM to emit a capability JSON.
  - Calls the LOCAL gbrain router (deepseek-v4-flash) — token-frugal, local-first.
    NOT a paid API.
  - Returns a core.capability.model.CapabilityRecord with confidence='inferred'.
  - Output is meant to be written into the feed as DECLARED capability at
    feed-build time (the enrich-at-feed-build decision), then merged by the
    registry's existing merge_capabilities() pipeline.
  - Ports are emitted raw; the registry's vocab.admit() marks unregistered ones
    'unverified:' (graceful) at populate time — we do NOT hard-validate here.

This is a SPIKE: proves the mechanism on a handful of CLIs and is scored on the
registry's own evaluate_inference() harness. Not the 474-CLI production pass.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request

from core.capability.model import CapabilityRecord

ROUTER_URL = "http://localhost:9111/v1/chat/completions"
ROUTER_MODEL = "deepseek-v4-flash"
ROUTER_KEY = "router-local"

# Controlled vocab the registry recognises (demo config). The prompt steers the
# LLM toward these so emitted ports are more likely to be 'registered' rather
# than 'unverified:'. This list is advisory in the prompt, not enforced here.
KNOWN_INTENTS = [
    "convert", "extract", "summarize", "lint", "format", "test", "build",
    "download", "publish", "install", "package", "query", "generate", "index",
]
KNOWN_PORTS = ["file:pdf", "text:doc", "text:summary", "text", "url", "json", "file:csv", "file:json"]
SIDE_EFFECTS = ["none", "writes-fs", "network", "destructive", "unknown"]

_SYSTEM = (
    "You classify a command-line tool from its --help text. "
    "Return ONLY a compact JSON object, no prose, with keys: "
    "intent_tags (list of verb tags), input_types (list of typed ports it consumes), "
    "output_types (list of typed ports it produces), side_effect (one of: "
    f"{', '.join(SIDE_EFFECTS)}). "
    f"Prefer these intent tags when they fit: {', '.join(KNOWN_INTENTS)}. "
    f"Prefer these port types when they fit: {', '.join(KNOWN_PORTS)}. "
    "A typed port is 'family:subtype' or a bare family (e.g. 'file:pdf', 'text', 'url'). "
    "If the tool reads no file/stdin, input_types is []. If it only prints to stdout, "
    "output_types is ['text']. "
    # side_effect = the tool's DEFINING effect, not every effect it can have.
    # Classify by what the tool is FOR, in this priority order:
    "Choose side_effect by the tool's PRIMARY purpose, in this priority: "
    "(1) 'network' if it fetches/sends over the network (downloaders, HTTP clients, scrapers) "
    "— network wins even though such tools also save files. "
    "(2) 'destructive' if it deletes or irreversibly overwrites the user's existing data. "
    "(3) 'writes-fs' ONLY for tools whose job is to MODIFY input files IN PLACE "
    "(formatters like black, import sorters) — NOT tools that merely produce a new output file. "
    "(4) 'none' otherwise — this is the DEFAULT, and it covers converters, extractors, "
    "and test runners EVEN IF they write an output file or report, because writing a new "
    "result file is not a side effect on existing data. "
    "When unsure between 'writes-fs' and 'none', choose 'none'. "
    # Fix 4: thin-help recovery. Many tools emit only a usage line; infer from the
    # tool's NAME plus that line rather than abstaining, but stay conservative.
    "If the help text is sparse (just a usage line or a few words), still infer "
    "intent_tags from the tool's slug and any verbs present (e.g. slug 'seed_sources' "
    "-> ['generate','index']; 'export_entities' -> ['extract']). Only return empty "
    "intent_tags when there is genuinely no signal in either the slug or the text."
)


# Markers that mean the captured output is a CRASH, not help. A CLI that
# ImportErrors on --help prints a traceback to stderr; capture_help used to
# return that as "help text" (it has length), and the LLM correctly abstained
# on garbage — but the abstention looked like "no signal in good help" when the
# real cause was "the CLI can't run". Reject these so the caller sees no-help.
_CRASH_MARKERS = (
    "Traceback (most recent call last)",
    "No module named",
    "ModuleNotFoundError",
    "ImportError",
)
# argparse/click emit these when a tool doesn't accept the flag we tried —
# that's "wrong probe", not a crash; the probe ladder moves to the next form.
_BAD_FLAG_MARKERS = (
    "unrecognized arguments",
    "no such option",
    "invalid choice",
    "unknown command",
    "does not exist",
)

# Project-root sentinels: the nearest ancestor containing one of these is the
# directory from which `python -m pkg.module` resolves package-relative imports.
_ROOT_SENTINELS = ("pyproject.toml", "setup.py", "setup.cfg", ".git", "requirements.txt")


def _is_crash(out: str) -> bool:
    return any(m in out for m in _CRASH_MARKERS)


def _is_bad_flag(out: str) -> bool:
    low = out.lower()
    return any(m in low for m in _BAD_FLAG_MARKERS)


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
    """Dotted module path of `path` relative to `root` (Fix 1: package mode).

    /root/pkg/sub/cli.py  under root  ->  pkg.sub.cli
    A trailing __main__ is kept (python -m pkg works via pkg/__main__.py only if
    we target the package, but file-stem __main__ is rare here)."""
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


def _venv_python(root: str | None) -> str:
    """Prefer a project-local venv interpreter so package imports resolve."""
    if root:
        for cand in (".venv/bin/python", "venv/bin/python", ".venv/bin/python3"):
            p = os.path.join(root, cand)
            if os.path.exists(p):
                return p
    return "python3"


# Probe forms tried in order. argv-suffix appended to the base invocation.
_PROBE_FLAGS = (["--help"], ["-h"], ["help"], [])  # Fix 3: subcommand ladder


def capture_help(path: str, python: str = "python3", timeout: int = 5) -> str:
    """Capture a CLI's help text, robust to package-mode CLIs and crashes.

    Strategy (in order, first CLEAN result wins):
      1. module mode: `<venv-python> -m pkg.module <flag>` run from the project
         root — fixes the dominant abstention cause (CLIs that ImportError when
         run as a loose file because they use package-relative imports). (Fix 1)
      2. file mode:   `<python> <file> <flag>` — for standalone scripts.
    Each mode walks a flag ladder (--help, -h, help, bare). (Fix 3)
    Any output that is a traceback / import crash is REJECTED as no-help. (Fix 2)
    Returns clean help text (<=4000 chars) or "" if nothing usable was found.
    """
    root = _project_root(path)
    mod = _dotted_module(path, root) if root else None
    vpy = _venv_python(root)

    invocations: list[tuple[list[str], str | None]] = []
    if mod:
        # module mode, run from project root so package imports resolve
        for flag in _PROBE_FLAGS:
            invocations.append(([vpy, "-m", mod, *flag], root))
    for flag in _PROBE_FLAGS:
        invocations.append(([python, path, *flag], None))

    for argv, cwd in invocations:
        try:
            p = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, cwd=cwd
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, OSError):
            continue
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        if not out:
            continue
        if _is_crash(out):
            continue                 # crash, not help — try the next form/mode
        if _is_bad_flag(out):
            continue                 # wrong flag — ladder moves on
        # Looks like real help. Guard against a bare run that just did the work
        # (no help, normal program output): require a help-ish shape OR a flag
        # form (--help/-h/help) that succeeded.
        is_flagged = argv[-1] in ("--help", "-h", "help")
        if is_flagged or _looks_like_help(out):
            return out[:4000]
    return ""


_HELP_SHAPE = re.compile(r"(?im)^\s*(usage:|options:|commands:|positional arguments|"
                         r"-h,\s*--help|--\w[\w-]+)")


def _looks_like_help(out: str) -> bool:
    """Heuristic: does this output resemble a help screen (not program output)?
    Used only to accept BARE invocations, where many tools print usage but some
    just run. Flagged invocations (--help/-h/help) skip this check."""
    return bool(_HELP_SHAPE.search(out))


def _call_router(help_text: str, slug: str, timeout: int = 30) -> dict | None:
    payload = {
        "model": ROUTER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Tool slug: {slug}\n\n--help output:\n{help_text}"},
        ],
        "max_tokens": 300,
        "temperature": 0,
    }
    req = urllib.request.Request(
        ROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {ROUTER_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    try:
        content = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return None
    return _extract_json(content)


def _extract_json(content: str) -> dict | None:
    """LLMs sometimes wrap JSON in ```json fences or add stray text. Extract the
    first {...} block and parse it."""
    s = content.find("{")
    e = content.rfind("}")
    if s == -1 or e == -1 or e < s:
        return None
    try:
        return json.loads(content[s : e + 1])
    except json.JSONDecodeError:
        return None


def infer_llm_capability(slug: str, help_text: str) -> CapabilityRecord | None:
    """Infer a capability record from --help via the local router. None on failure."""
    if not help_text.strip():
        return None
    data = _call_router(help_text, slug)
    if data is None:
        return None
    se = data.get("side_effect", "unknown")
    if se not in SIDE_EFFECTS:
        se = "unknown"
    return CapabilityRecord(
        intent_tags=[str(t) for t in data.get("intent_tags", []) if t],
        input_types=[str(t) for t in data.get("input_types", []) if t],
        output_types=[str(t) for t in data.get("output_types", []) if t],
        side_effect=se,
        confidence="inferred",
    )
