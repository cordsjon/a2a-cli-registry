"""LLM fallback for CLIs the static extractor could not fully resolve (empty
input_types OR output_types). Local router only -- token-frugal, local-first.
Capped by backfill_capabilities.py at ~30 CLIs; a larger fallback set signals
the static extractor needs tuning, not brute LLM force.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from tools.description_regenerator import _extract_context

ROUTER_URL = "http://localhost:9111/v1/chat/completions"
ROUTER_MODEL = "deepseek-v4-flash"
ROUTER_KEY = "router-local"

_SIDE_EFFECTS = ["none", "writes-fs", "network", "destructive", "unknown"]

_SYSTEM = (
    "You infer a command-line tool's capability shape from its description "
    "and source context. Return ONLY a compact JSON object with keys: "
    "input_types (list of strings: path/int/float/str/json), "
    "output_types (list of strings: path/json/text), "
    "intent_tags (list of verb strings), "
    f"side_effect (one of: {', '.join(_SIDE_EFFECTS)}). "
    "side_effect='writes-fs' ONLY if the tool modifies an input file in "
    "place (formatters); a tool producing a NEW output file is 'none'. "
    "If genuinely unsure about any field, return an empty list (or "
    "'unknown' for side_effect) rather than guessing."
)


def _call_router(prompt: str, slug: str, timeout: int = 30) -> dict | None:
    payload = {
        "model": ROUTER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Tool slug: {slug}\n\nContext:\n{prompt}"},
        ],
        "max_tokens": 200,
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


def infer_capability_llm(slug: str, description: str, source: str) -> dict:
    context = _extract_context(source) if source else description
    result = _call_router(context, slug) or {}
    return {
        "input_types": result.get("input_types") or [],
        "output_types": result.get("output_types") or [],
        "intent_tags": result.get("intent_tags") or [],
        "side_effect": result.get("side_effect") or "unknown",
        "confidence": "inferred",
        "provenance": "llm",
    }
