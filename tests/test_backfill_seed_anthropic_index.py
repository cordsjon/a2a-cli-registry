from core.models import Capability
from core.planner.search import _hop_excluded


def _seed_cap():
    # The target post-backfill shape for seed_anthropic_index (AC-03):
    # side_effect='writes-fs', input_types='path', output_types='', confidence='inferred'.
    return [Capability(cli_slug="seed_anthropic_index", intent_tags="",
                       input_types="path", output_types="",
                       side_effect="writes-fs", confidence="inferred")]


def test_writes_fs_excluded_by_default():
    # writes-fs carries real blast radius; with no allow-set it must be excluded.
    assert _hop_excluded(_seed_cap(), set()) is True


def test_writes_fs_allowed_when_opted_in():
    # An operator opting into writes-fs accepts that blast radius.
    assert _hop_excluded(_seed_cap(), {"writes-fs"}) is False
