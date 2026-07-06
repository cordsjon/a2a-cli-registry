"""Judge-guided repair for one sanity-failed (description, capability) pair.
Runs at most once per row, between the first sanity pass and the final
report: the sanity judge's rejection reason is fed back to the local router
so the row can be corrected instead of discarded. Never writes to the DB --
the caller re-checks the repaired row and only adopts it if it passes.
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
    "You repair a command-line tool's catalog entry. Given its current "
    "description, capability fields, a reviewer's rejection reason, and "
    "source context, return corrected fields that stay faithful to the "
    "source and resolve the reviewer's objection. Return ONLY a compact "
    "JSON object with keys: description (1-2 sentences, concretely naming "
    "what the inputs and outputs are), input_types (list of: "
    "path/int/float/str/json; empty list if the tool takes no arguments), "
    "output_types (list of: path/json/text; use 'path' for any file the "
    "tool writes, including binary formats like PDF or PPTX), intent_tags "
    "(list of verb strings), side_effect (one of: "
    f"{', '.join(_SIDE_EFFECTS)}). side_effect rules: 'writes-fs' if it "
    "writes to a database, modifies files in place, or writes files beyond "
    "an explicitly requested output path (seeders, migrators, and DB "
    "inserts are always 'writes-fs'); 'network' if it calls remote APIs or "
    "serves; 'destructive' if it deletes or drops data; 'none' for "
    "read-only tools and pure converters that only write the output file "
    "the caller asked for. Do not invent functionality not evidenced by "
    "the context."
)


def _call_router(prompt: str, slug: str, timeout: int = 30) -> dict | None:
    payload = {
        "model": ROUTER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
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
    s = content.find("{")
    e = content.rfind("}")
    if s == -1 or e == -1 or e < s:
        return None
    try:
        return json.loads(content[s : e + 1])
    except json.JSONDecodeError:
        return None


def repair_row(
    slug: str,
    description: str,
    capability: dict | None,
    reason: str,
    source: str,
) -> dict | None:
    """Returns a proposal-shaped dict {slug, description, capability} with
    corrected fields, or None if the router gave nothing usable. A None
    input capability (non-Python row) stays None -- only the description
    is repaired."""
    context = _extract_context(source) if source else ""
    prompt = (
        f"Tool slug: {slug}\n"
        f"Current description: {description}\n"
        f"Current capability fields: {json.dumps(capability or {})}\n"
        f"Reviewer's rejection reason: {reason}\n"
        f"Source context:\n{context}"
    )
    result = _call_router(prompt, slug)
    if not result:
        return None

    new_description = result.get("description")
    if not isinstance(new_description, str) or not new_description.strip():
        new_description = description

    if capability is None:
        return {"slug": slug, "description": new_description.strip(), "capability": None}

    se = result.get("side_effect", capability.get("side_effect", "unknown"))
    if se not in _SIDE_EFFECTS:
        se = "unknown"
    repaired = {
        "input_types": [str(t) for t in result.get("input_types", capability.get("input_types", [])) if t],
        "output_types": [str(t) for t in result.get("output_types", capability.get("output_types", [])) if t],
        "intent_tags": [str(t) for t in result.get("intent_tags", capability.get("intent_tags", [])) if t],
        "side_effect": se,
        "confidence": "inferred",
        "provenance": "llm",
    }
    return {"slug": slug, "description": new_description.strip(), "capability": repaired}
