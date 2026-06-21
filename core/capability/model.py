from dataclasses import dataclass, field, replace


@dataclass
class CapabilityRecord:
    intent_tags: list[str] = field(default_factory=list)
    input_types: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    side_effect: str = "unknown"
    confidence: str = "declared"


def _pick(declared_val, inferred_val):
    """Declared wins. Inferred only fills a falsy (null/empty) declared field.

    Guard: relies on Python truthiness; safe for list[str] and str. Do NOT add
    int/bool fields to CapabilityRecord without updating this guard (0/False
    would be wrongly treated as empty).
    """
    return declared_val if declared_val else inferred_val


def merge_capabilities(declared, inferred):
    """Declared ALWAYS wins. Inference only fills null/empty fields.
    Result confidence is 'declared' if any declared field survived into the
    merged result; otherwise uses inferred.confidence."""
    if declared is None:
        return inferred
    if inferred is None:
        return declared
    merged_tags    = _pick(declared.intent_tags,  inferred.intent_tags)
    merged_inputs  = _pick(declared.input_types,  inferred.input_types)
    merged_outputs = _pick(declared.output_types, inferred.output_types)
    merged_effect  = _pick(declared.side_effect,  inferred.side_effect)
    any_declared   = (merged_tags    is declared.intent_tags  or
                      merged_inputs  is declared.input_types  or
                      merged_outputs is declared.output_types or
                      merged_effect  is declared.side_effect)
    return CapabilityRecord(
        intent_tags=merged_tags,
        input_types=merged_inputs,
        output_types=merged_outputs,
        side_effect=merged_effect,
        confidence="declared" if any_declared else inferred.confidence,
    )


def admit_ports(rec, vocab):
    """Run every port through vocabulary admission; unregistered → unverified:."""
    return replace(
        rec,
        input_types=[vocab.admit(p)[0] for p in rec.input_types],
        output_types=[vocab.admit(p)[0] for p in rec.output_types],
    )
