"""Precision/recall evaluation for the Python capability inferer (spec §9).

A prediction is a "hit" if the inferred intent_tags overlap the expected set AND
the inferred side_effect matches the expected (or expected is 'unknown').
"""


def _is_hit(pred, expected) -> bool:
    if pred is None:
        return False
    pred_tags = set(pred.intent_tags)
    exp_tags = set(expected["intent_tags"])
    tags_ok = bool(pred_tags & exp_tags)
    se_ok = (expected["side_effect"] == "unknown"
             or pred.side_effect == expected["side_effect"])
    return tags_ok and se_ok


def evaluate_inference(infer_fn, ground_truth) -> dict:
    """infer_fn(example) -> CapabilityRecord | None. Returns precision/recall/n."""
    predictions = 0
    correct = 0
    positives = 0   # examples that have a non-trivial expected capability
    for ex in ground_truth:
        expected = ex["expected"]
        if expected.get("intent_tags"):
            positives += 1
        pred = infer_fn(ex)
        # A CapabilityRecord with empty intent_tags is treated as an abstention:
        # the inferer found no signal, equivalent to returning None.
        if pred is not None and pred.intent_tags:
            predictions += 1
            if _is_hit(pred, expected):
                correct += 1
    precision = (correct / predictions) if predictions else 0.0
    recall = (correct / positives) if positives else 0.0
    return {"precision": precision, "recall": recall, "n": len(ground_truth)}
