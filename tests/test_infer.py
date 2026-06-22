import json
from pathlib import Path
from core.capability.infer_eval import evaluate_inference

_GT = Path(__file__).parent / "golden_caps" / "ground_truth.json"


def test_ground_truth_set_has_at_least_30_examples():
    gt = json.loads(_GT.read_text())
    assert len(gt) >= 30


def test_evaluator_computes_precision_recall():
    gt = json.loads(_GT.read_text())

    # a perfect oracle that reads the expected straight from the example
    def _oracle(example):
        exp = example["expected"]
        from core.capability.model import CapabilityRecord
        return CapabilityRecord(intent_tags=exp["intent_tags"],
                                side_effect=exp["side_effect"],
                                confidence="inferred")

    scores = evaluate_inference(_oracle, gt)
    assert scores["precision"] == 1.0
    assert scores["recall"] == 1.0
    assert scores["n"] == len(gt)
