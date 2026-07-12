# tests/test_match.py
from core.catalog.match import clean_terms, ident_haystack, vocab_haystack, term_matches
from core.models import Capability


def _cap(**kw):
    base = dict(cli_slug="x", intent_tags="", input_types="", output_types="",
                side_effect="none", confidence="declared")
    base.update(kw)
    return Capability(**base)


def test_two_haystack_boundary_not_spanned():
    # spec §2.2: a term spanning the description-end/vocab-start boundary must
    # NOT match — a single five-field concatenation would accept it.
    ident = ident_haystack("mycli", "converts doc")
    vocab = vocab_haystack([_cap(intent_tags="convert", input_types="file:doc",
                                 output_types="text")])
    assert not term_matches("doc convert", ident, vocab)


def test_ident_and_vocab_hits():
    ident = ident_haystack("zzz_codename", "scripts/gen.py")
    vocab = vocab_haystack([_cap(intent_tags="generate", output_types="text")])
    assert term_matches("codename", ident, vocab)    # slug hit
    assert term_matches("gen.py", ident, vocab)      # description hit
    assert term_matches("generate", ident, vocab)    # vocab hit
    assert term_matches("CODENAME", ident, vocab)    # case-insensitive
    assert not term_matches("poster", ident, vocab)


def test_none_description_and_no_caps_are_safe():
    assert term_matches("mycli", ident_haystack("mycli", None), vocab_haystack([]))
    assert not term_matches("anything", ident_haystack("z", None), vocab_haystack([]))


def test_clean_terms_drops_junk():
    # spec §2.1: ops validator only checks the outer array type — this filter
    # is the real guard. Blank terms would substring-match EVERYTHING.
    assert clean_terms([42, "  ", None, " Codename ", ""]) == ["codename"]
    assert clean_terms(None) == []
    assert clean_terms([]) == []
