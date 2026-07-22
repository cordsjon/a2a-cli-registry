"""Regenerate a 1-2 sentence purpose description for one CLI, via the local
router. Runs first in the backfill pipeline -- its output feeds
capability_extractor.extract_intent_tags, never the corrupted original
cli.description.
"""
from __future__ import annotations

import ast
import json
import urllib.error
import urllib.request

ROUTER_URL = "http://localhost:9111/v1/chat/completions"
ROUTER_MODEL = "deepseek-v4-flash"
ROUTER_KEY = "router-local"

_SYSTEM = (
    "You write a single 1-2 sentence description of what a command-line tool "
    "does, in plain language, based on its docstring, parser help text, and "
    "entrypoint signature. Return ONLY a compact JSON object with one key: "
    "description (string). Do not invent functionality not evidenced by the "
    "given context."
)


def _extract_context(source: str) -> str:
    """AST-extract module docstring + parser/command help strings + entrypoint
    function signature+docstring, plus the first ~20 lines as light context.
    NOT a fixed first-N-lines slice -- parser definitions land beyond line 60
    in ~50% of sampled files."""
    parts = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "\n".join(source.splitlines()[:20])

    module_doc = ast.get_docstring(tree)
    if module_doc:
        parts.append(module_doc)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("add_argument", "command", "ArgumentParser"):
                for kw in node.keywords:
                    if kw.arg in ("description", "help") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        parts.append(kw.value.value)
        if isinstance(node, ast.FunctionDef):
            fn_doc = ast.get_docstring(node)
            if fn_doc:
                parts.append(fn_doc)

    parts.append("\n".join(source.splitlines()[:20]))
    return "\n".join(parts)


def _call_router(prompt: str, slug: str, timeout: int = 30) -> dict | None:
    payload = {
        "model": ROUTER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Tool slug: {slug}\n\nContext:\n{prompt}"},
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


def regenerate_description(slug: str, source: str | None) -> str:
    if not source or not source.strip():
        return f"unknown purpose ({slug})"

    context = _extract_context(source)
    result = _call_router(context, slug)
    if not result or "description" not in result or not isinstance(result["description"], str):
        return f"unknown purpose ({slug})"
    return result["description"].strip()
