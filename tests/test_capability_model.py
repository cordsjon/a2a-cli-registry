from core.capability.model import CapabilityRecord, merge_capabilities, admit_ports
from core.vocabulary import VocabularyRegistry


def test_declared_wins_over_inferred():
    declared = CapabilityRecord(intent_tags=["convert"], input_types=["file:pdf"],
                                output_types=["text"], side_effect="none", confidence="declared")
    inferred = CapabilityRecord(intent_tags=["extract"], input_types=[],
                                output_types=["text", "json"], side_effect="writes-fs", confidence="inferred")
    merged = merge_capabilities(declared, inferred)
    assert merged.intent_tags == ["convert"]      # declared wins, not overridden
    assert merged.input_types == ["file:pdf"]      # declared non-empty wins
    assert merged.side_effect == "none"            # declared wins
    assert merged.confidence == "declared"


def test_inferred_fills_null_fields_only():
    declared = CapabilityRecord(intent_tags=["convert"], input_types=[],
                                output_types=[], side_effect="", confidence="declared")
    inferred = CapabilityRecord(intent_tags=["x"], input_types=["file:pdf"],
                                output_types=["text"], side_effect="writes-fs", confidence="inferred")
    merged = merge_capabilities(declared, inferred)
    assert merged.intent_tags == ["convert"]       # declared had it
    assert merged.input_types == ["file:pdf"]       # filled from inferred (declared empty)
    assert merged.output_types == ["text"]          # filled from inferred (declared empty)
    assert merged.side_effect == "writes-fs"        # filled from inferred


def test_fully_inferred_merge_keeps_inferred_confidence():
    # Empty declared (all fields falsy) merged with full inferred must NOT
    # promote confidence to "declared" — the downstream fail-UNSAFE guard relies on this.
    declared = CapabilityRecord(intent_tags=[], input_types=[],
                                output_types=[], side_effect="", confidence="declared")
    inferred = CapabilityRecord(intent_tags=["extract"], input_types=["file:pdf"],
                                output_types=["text"], side_effect="writes-fs", confidence="inferred")
    merged = merge_capabilities(declared, inferred)
    assert merged.intent_tags == ["extract"]
    assert merged.input_types == ["file:pdf"]
    assert merged.output_types == ["text"]
    assert merged.side_effect == "writes-fs"
    assert merged.confidence == "inferred"   # must NOT be "declared"


def test_admit_ports_quarantines_unregistered():
    vocab = VocabularyRegistry(registered={"file:pdf"}, aliases={})
    rec = CapabilityRecord(intent_tags=["c"], input_types=["file:pdf"],
                           output_types=["weird"], side_effect="none", confidence="inferred")
    out = admit_ports(rec, vocab)
    assert out.input_types == ["file:pdf"]
    assert out.output_types == ["unverified:weird"]
