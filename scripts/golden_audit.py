"""False-positive trap check for the capability golden set.

The §9 precision/recall floor in tests/test_infer.py only measures the inferer.
It says nothing about whether the *golden set itself* still contains negatives
(examples whose expected.intent_tags is empty) that are honest traps. A negative
whose help text carries a positive trigger phrase is a leaking negative: either
the label is wrong, or the trigger table grew into it and the example silently
stopped being a trap.

Exit 0 = no leaking negatives; 1 = leaks found (printed); 2 = load/schema error.

Triggers default to the intent-signal phrases in core.capability.infer, so the
audit tracks the trigger table automatically instead of a hand-kept copy.
"""
import argparse
import json
import sys
from pathlib import Path

from core.capability.infer import _INTENT_SIGNALS, _NETWORK_SIGNALS, _WRITES_FS_SIGNALS


def default_triggers() -> list[str]:
    """Every phrase the inferer treats as a positive signal, longest first."""
    phrases = {phrase for phrase, _ in _INTENT_SIGNALS}
    phrases |= set(_WRITES_FS_SIGNALS)
    phrases |= set(_NETWORK_SIGNALS)
    return sorted(phrases, key=lambda p: (-len(p), p))


def find_leaks(ground_truth, triggers) -> list[dict]:
    """Negative examples whose help_text contains a positive trigger phrase."""
    lowered = [t.lower() for t in triggers if t]
    leaks = []
    for ex in ground_truth:
        if ex.get("expected", {}).get("intent_tags"):
            continue  # positive example — not a trap
        help_text = (ex.get("help_text") or "").lower()
        hits = [t for t in lowered if t in help_text]
        if hits:
            leaks.append({"slug": ex.get("slug", "<no-slug>"), "triggers": hits})
    return leaks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ground_truth", help="labeled golden JSON (list of examples)")
    ap.add_argument("--triggers", default=None,
                    help="comma-separated trigger phrases (default: infer.py signals)")
    args = ap.parse_args(argv)

    try:
        data = json.loads(Path(args.ground_truth).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot load {args.ground_truth}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(data, list):
        print("ERROR: ground truth must be a JSON list of examples", file=sys.stderr)
        return 2

    triggers = ([t.strip() for t in args.triggers.split(",") if t.strip()]
                if args.triggers else default_triggers())
    negatives = [e for e in data if not e.get("expected", {}).get("intent_tags")]
    leaks = find_leaks(data, triggers)

    print(f"examples={len(data)} negatives={len(negatives)} triggers={len(triggers)}")
    for leak in leaks:
        print(f"LEAK {leak['slug']}: {', '.join(leak['triggers'])}")
    if not leaks:
        print("OK: no negative example contains a positive trigger phrase")
        return 0
    print(f"FAIL: {len(leaks)} leaking negative(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
