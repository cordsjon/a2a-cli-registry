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
    assert merged.side_effect == "writes-fs"        # filled from inferred


def test_admit_ports_quarantines_unregistered():
    vocab = VocabularyRegistry(registered={"file:pdf"}, aliases={})
    rec = CapabilityRecord(intent_tags=["c"], input_types=["file:pdf"],
                           output_types=["weird"], side_effect="none", confidence="inferred")
    out = admit_ports(rec, vocab)
    assert out.input_types == ["file:pdf"]
    assert out.output_types == ["unverified:weird"]
