from dataclasses import dataclass, field, replace


@dataclass
class CapabilityRecord:
    intent_tags: list[str] = field(default_factory=list)
    input_types: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    side_effect: str = "unknown"
    confidence: str = "declared"


def _pick(declared_val, inferred_val):
    """Declared wins. Inferred only fills a falsy (null/empty) declared field."""
    return declared_val if declared_val else inferred_val


def merge_capabilities(declared, inferred):
    """Declared ALWAYS wins. Inference only fills null/empty fields.
    Result confidence is 'declared' if any declared field survived."""
    if declared is None:
        return inferred
    if inferred is None:
        return declared
    return CapabilityRecord(
        intent_tags=_pick(declared.intent_tags, inferred.intent_tags),
        input_types=_pick(declared.input_types, inferred.input_types),
        output_types=_pick(declared.output_types, inferred.output_types),
        side_effect=_pick(declared.side_effect, inferred.side_effect),
        confidence="declared",
    )


def admit_ports(rec, vocab):
    """Run every port through vocabulary admission; unregistered → unverified:."""
    return replace(
        rec,
        input_types=[vocab.admit(p)[0] for p in rec.input_types],
        output_types=[vocab.admit(p)[0] for p in rec.output_types],
    )
