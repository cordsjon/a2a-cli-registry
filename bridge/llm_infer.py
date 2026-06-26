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
    "output_types is ['text']. Be conservative on side_effect: 'none' unless it clearly "
    "writes files (writes-fs), hits the network (network), or deletes data (destructive)."
)


def capture_help(path: str, python: str = "python3", timeout: int = 5) -> str:
    """Capture a CLI's --help. Tries `<python> <file> --help` then `-m` form.
    Returns combined stdout+stderr (help often goes to stderr on error)."""
    for argv in ([python, path, "--help"], [python, "-m", _module_of(path), "--help"]):
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            out = (p.stdout or "") + (p.stderr or "")
            if out.strip():
                return out[:4000]
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            continue
    return ""


def _module_of(path: str) -> str:
    # best-effort: strip to a dotted module under projects — only used as fallback
    import os
    return os.path.splitext(os.path.basename(path))[0]


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
