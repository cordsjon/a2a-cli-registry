"""Moved to core/prober/standalone.py so the prober can gate on it without core
importing bridge (only core ships in the wheel). Kept as the import path for
the feed builder and scripts/reeval_not_standalone.py."""
from core.prober.standalone import classify_standalone  # noqa: F401
