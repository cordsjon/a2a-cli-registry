"""Read-only sanity check over a proposed (description, capability) pair.
Runs last in the backfill pipeline, before any DB write. Purely additive --
never edits rows, only flags them ok=True/False with a reason.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

ROUTER_URL = "http://localhost:9111/v1/chat/completions"
ROUTER_MODEL = "deepseek-v4-flash"
ROUTER_KEY = "router-local"

_PATH_LIKE = re.compile(r"^[\w./-]+\.py$")
_TRACEBACK_MARKERS = ("Error", "Traceback", "Errno", "Exception")

_SYSTEM = (
    "You are a strict reviewer. Given a CLI's description and its capability "
    "fields (input_types, output_types, intent_tags, side_effect), decide: can "
    "a reader tell what this CLI is for and how it fits into a pipeline? "
    "Return ONLY a compact JSON object with keys: ok (boolean), reason "
    "(short string). If ambiguous, return ok=false with a reason -- never "
    "guess true."
)


def _mechanical_prefilter(description: str) -> str | None:
    """Returns a rejection reason string if description is still corrupted
    (path-like or traceback-like), else None (passes, proceed to LLM)."""
    if _PATH_LIKE.match(description.strip()):
        return "description is path-like, not a purpose statement"
    if any(marker in description for marker in _TRACEBACK_MARKERS):
        return "description contains traceback/exception markers"
    return None


def _call_router(prompt: str, slug: str, timeout: int = 30) -> dict | None:
    payload = {
        "model": ROUTER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 150,
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
    s = content.find("{")
    e = content.rfind("}")
    if s == -1 or e == -1 or e < s:
        return None
    try:
        return json.loads(content[s : e + 1])
    except json.JSONDecodeError:
        return None


def check_row(slug: str, description: str, capability: dict) -> dict:
    rejection = _mechanical_prefilter(description)
    if rejection:
        return {"ok": False, "reason": rejection}

    prompt = (
        f"Tool slug: {slug}\n"
        f"Description: {description}\n"
        f"Capability fields: {json.dumps(capability)}"
    )
    result = _call_router(prompt, slug)
    if not result or "ok" not in result or not isinstance(result["ok"], bool):
        return {"ok": False, "reason": "ambiguous or malformed model output"}
    return {"ok": bool(result["ok"]), "reason": str(result.get("reason", ""))}


CALIBRATION_SET = [
    {
        "slug": "csv2json",
        "description": "Converts CSV files to JSON format.",
        "capability": {"input_types": ["path"], "output_types": ["json"], "intent_tags": ["convert"], "side_effect": "none"},
        "expected_ok": True,
    },
    {
        "slug": "svg-export",
        "description": "Exports SVG assets and publishes them to Etsy.",
        "capability": {"input_types": ["path"], "output_types": ["path"], "intent_tags": ["export", "publish"], "side_effect": "network"},
        "expected_ok": True,
    },
    {
        "slug": "auto-format",
        "description": "Formats Python source files in place.",
        "capability": {"input_types": ["path"], "output_types": ["path"], "intent_tags": ["build"], "side_effect": "writes-fs"},
        "expected_ok": True,
    },
    {
        "slug": "fetch-data",
        "description": "Downloads a dataset from a remote URL and saves it locally.",
        "capability": {"input_types": ["str"], "output_types": ["path"], "intent_tags": ["download"], "side_effect": "network"},
        "expected_ok": True,
    },
    {
        "slug": "broken1",
        "description": "30_SVG-PAINT/scripts/ppv-dashboard.py",
        "capability": {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "unknown"},
        "expected_ok": False,
    },
    {
        "slug": "broken2",
        "description": "ModuleNotFoundError: No module named 'portalocker'",
        "capability": {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "unknown"},
        "expected_ok": False,
    },
    {
        "slug": "mismatch1",
        "description": "Converts CSV files to JSON format.",
        "capability": {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "destructive"},
        "expected_ok": False,
    },
    {
        "slug": "vague1",
        "description": "does stuff",
        "capability": {"input_types": [], "output_types": [], "intent_tags": [], "side_effect": "unknown"},
        "expected_ok": False,
    },
]
