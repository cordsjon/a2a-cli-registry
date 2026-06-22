import json
from pathlib import Path
from core.capability.infer_eval import evaluate_inference
from core.capability.infer import infer_python_capability

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


def _example_to_record(ex):
    from core.discovery.base import CliRecord
    return CliRecord(slug=ex["slug"], lang="python", path="/x/" + ex["slug"],
                     bucket=None, project=None, description=ex["help_text"],
                     declared_capability=None, source_class=None, source_run_id=None)


def test_inference_meets_precision_recall_floor():
    gt = json.loads(_GT.read_text())

    def _infer(ex):
        return infer_python_capability(_example_to_record(ex))

    scores = evaluate_inference(_infer, gt)
    assert scores["precision"] >= 0.6, scores
    assert scores["recall"] >= 0.6, scores


def test_inferred_records_carry_inferred_confidence():
    gt = json.loads(_GT.read_text())
    any_pred = False
    for ex in gt:
        pred = infer_python_capability(_example_to_record(ex))
        if pred is not None:
            any_pred = True
            assert pred.confidence == "inferred"
    assert any_pred  # the inferer actually fires on the golden set
