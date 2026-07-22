# core/catalog/match.py
"""Shared term-match predicate — LEAF module (spec §2.2,
docs/superpowers/specs/2026-07-12-producer-relevance-design.md).

Imports nothing from catalog.queries or planner.search; BOTH import this file
(catalog.queries -> planner.search already exists, so the shared predicate must
sit below both to avoid a cycle; core/catalog/__init__.py is empty).

Two-haystack semantics, extracted verbatim from search_clis: a term matches a
CLI iff it is a case-insensitive substring of (slug + " " + description) OR of
the aggregated capability-vocab string (intent_tags, input_types, output_types
over ALL capability rows of the slug). A single five-field concatenation would
permit synthetic matches spanning the description/vocab boundary that
search_clis cannot produce."""


def ident_haystack(slug: str, description: str | None) -> str:
    return f"{slug} {description or ''}".lower()


def vocab_haystack(caps) -> str:
    return " ".join(
        f"{c.intent_tags} {c.input_types} {c.output_types}" for c in caps
    ).lower()


def clean_terms(terms) -> list[str]:
    """Drop non-string and blank/whitespace-only elements; strip+lowercase.
    The ops schema validates only the outer array type, so this is the
    authoritative hygiene filter (spec §2.1/§2.3): a blank term would
    substring-match every haystack and mark every chain relevant."""
    return [t.strip().lower() for t in (terms or [])
            if isinstance(t, str) and t.strip()]


def term_matches(term: str, ident: str, vocab: str) -> bool:
    q = term.strip().lower()
    return bool(q) and (q in ident or q in vocab)
