# core/okf/frontmatter.py
"""Hand-emitted, deterministic YAML frontmatter for OKF concept docs.

We control the full shape (scalars, flat string lists, a 2-key `ports` map,
an `edges` list of {to,via} maps), so we emit a constrained subset by hand
rather than depend on PyYAML. This guarantees byte-stable output (spec §6, D1).
"""
import hashlib

# Fixed top-level emission order (standard OKF fields first, then extensions).
_KEY_ORDER = [
    "type", "title", "description", "resource", "tags", "timestamp",
    "content_hash", "enriched_against", "okf_version",
    "ports", "side_effect", "confidence", "health", "edges",
]


def _scalar(v) -> str:
    s = "" if v is None else str(v)
    # Quote when needed to stay parseable; always safe to quote.
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _emit_list(items) -> str:
    return "[" + ", ".join(_scalar(i) for i in items) + "]"


def dump_frontmatter(fm: dict) -> str:
    lines = []
    for key in _KEY_ORDER:
        if key not in fm or fm[key] is None:
            continue
        val = fm[key]
        if key == "ports":
            lines.append("ports:")
            lines.append("  in: " + _emit_list(val.get("in", [])))
            lines.append("  out: " + _emit_list(val.get("out", [])))
        elif key == "edges":
            lines.append("edges:")
            for e in val:
                lines.append("  - to: " + _scalar(e["to"]))
                lines.append("    via: " + _scalar(e["via"]))
        elif key == "tags":
            lines.append("tags: " + _emit_list(val))
        else:
            lines.append(f"{key}: " + _scalar(val))
    return "\n".join(lines) + "\n"


def _unquote(s: str):
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return s


def parse_frontmatter(text: str) -> dict:
    fm: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line == "ports:":
            ports = {}
            i += 1
            while i < len(lines) and lines[i].startswith("  "):
                k, _, rest = lines[i].strip().partition(": ")
                ports[k] = _parse_inline_list(rest)
                i += 1
            fm["ports"] = ports
            continue
        if line == "edges:":
            edges = []
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith("- to:"):
                if i + 1 >= len(lines):
                    raise ValueError("OKF: edge entry missing 'via:' line")
                to = _unquote(lines[i].split("to:", 1)[1])
                via = _unquote(lines[i + 1].split("via:", 1)[1])
                edges.append({"to": to, "via": via})
                i += 2
            fm["edges"] = edges
            continue
        key, _, rest = line.partition(": ")
        key = key.strip()
        if rest.strip().startswith("["):
            fm[key] = _parse_inline_list(rest)
        else:
            fm[key] = _unquote(rest)
        i += 1
    return fm


def _parse_inline_list(rest: str):
    rest = rest.strip()
    if not (rest.startswith("[") and rest.endswith("]")):
        return []
    inner = rest[1:-1].strip()
    if not inner:
        return []
    items = []
    i = 0
    while i < len(inner):
        if inner[i] == '"':
            end = i + 1
            while end < len(inner):
                if inner[end] == '\\':
                    end += 2
                    continue
                if inner[end] == '"':
                    break
                end += 1
            items.append(_unquote(inner[i:end + 1]))
            i = end + 1
            if i < len(inner) and inner[i:i+2] == ", ":
                i += 2
        else:
            end = inner.find(", ", i)
            if end == -1:
                items.append(_unquote(inner[i:]))
                break
            items.append(_unquote(inner[i:end]))
            i = end + 2
    return items


def split_doc(content: str):
    if not content.startswith("---\n"):
        raise ValueError("OKF concept: missing opening '---' frontmatter boundary")
    rest = content[4:]
    end = rest.find("\n---\n")
    if end == -1:
        raise ValueError("OKF concept: missing closing '---' frontmatter boundary")
    return parse_frontmatter(rest[:end]), rest[end + 5:]


def join_doc(fm: dict, body: str) -> str:
    return "---\n" + dump_frontmatter(fm) + "---\n" + body


def content_hash(*, concept_id, slug, lang, project, resource,
                 intent_tags, input_types, output_types,
                 side_effect, confidence, edges) -> str:
    """sha256 over the canonical structural tuple (spec §6).

    Excludes description, health_status, timestamp by construction (not params).
    """
    parts = [
        concept_id, slug, lang, project or "", resource or "",
        ",".join(sorted(intent_tags)),
        ",".join(sorted(input_types)),
        ",".join(sorted(output_types)),
        side_effect, confidence,
        ";".join(f"{e['to']}>{e['via']}" for e in sorted(edges, key=lambda d: (d["to"], d["via"]))),
    ]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return "sha256:" + digest
