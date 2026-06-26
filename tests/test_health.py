"""Tests for the shared health-status vocabulary (core.health).

This module is the single source of truth for the canonical health states and
their normalization. It exists because the vocabulary was previously duplicated
in core/web/overview_view.py AND core/catalog/queries.py — a 5th badge added to
one but not the other rendered as dead code (the data layer collapsed it to
'unknown' before the render layer ever saw it). See KP on the distributed-enum
smell (US-CLIAUDIT-83).
"""
from __future__ import annotations

from core.health import CANON_HEALTH, norm_health


def test_canonical_set_has_five_states():
    assert CANON_HEALTH == {"healthy", "unhealthy", "stale", "unknown", "not_standalone"}


def test_norm_passes_canonical_values_through():
    for state in CANON_HEALTH:
        assert norm_health(state) == state


def test_norm_lowercases_legacy_uppercase():
    assert norm_health("UNKNOWN") == "unknown"
    assert norm_health("Healthy") == "healthy"


def test_norm_defaults_none_and_empty_to_unknown():
    assert norm_health(None) == "unknown"
    assert norm_health("") == "unknown"


def test_norm_unrecognized_value_becomes_unknown():
    assert norm_health("BROKEN") == "unknown"
    assert norm_health("garbage") == "unknown"


def test_not_standalone_is_preserved_not_collapsed():
    """The regression this whole module guards against."""
    assert norm_health("not_standalone") == "not_standalone"


def test_render_glyph_and_style_maps_cover_every_canonical_state():
    """Render-layer maps stay local but their KEYS must cover CANON_HEALTH —
    a missing key KeyErrors at render time. This guard catches drift the moment
    a 6th state is added to core.health without updating the render maps."""
    from core.web.overview_view import _HEALTH_GLYPHS
    from core.tui.overview import _HEALTH_STYLE

    assert set(_HEALTH_GLYPHS) >= CANON_HEALTH, set(_HEALTH_GLYPHS) ^ CANON_HEALTH
    assert set(_HEALTH_STYLE) >= CANON_HEALTH, set(_HEALTH_STYLE) ^ CANON_HEALTH
