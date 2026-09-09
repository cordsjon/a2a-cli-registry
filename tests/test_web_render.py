from core.web.overview_view import build_overview_model
from core.web.render import render_overview_html


def _model():
    """Built by the REAL view-model builder, not hand-written.

    This fixture used to be a literal dict mirroring build_overview_model's
    output. When the template gained `cli.health_glyph` the production path
    (app.py: build_overview_model -> render_overview_html) kept working and
    only this copy fell behind — and because Jinja renders an undefined
    variable as an empty string rather than raising, the card silently lost its
    glyph instead of failing loudly. Going through the builder means a new
    required field cannot drift out of the fixture again.
    """
    return build_overview_model({
        "clis": [
            {
                "slug": "healthy-cli",
                "lang": "python",
                "project": "alpha",
                "health_status": "healthy",
                "description": "good",
            },
            {
                "slug": "unhealthy-cli",
                "lang": "shell",
                "project": "alpha",
                "health_status": "unhealthy",
                "description": "bad",
            },
            {
                "slug": "stale-cli",
                "lang": "go",
                "project": "beta",
                "health_status": "stale",
                "description": "old",
            },
        ],
        "caps_by_slug": {
            "healthy-cli": [{
                "intent_tags": ["inspect"],
                "input_types": ["file:json"],
                "output_types": ["text:plain"],
                "side_effect": "none",
                "confidence": "declared",
            }],
        },
        "edges": [
            {"from": "healthy-cli", "to": "unhealthy-cli", "via_type": "text:plain"},
        ],
    })


def _card(html, slug):
    marker = f'data-slug="{slug}"'
    start = html.index(marker)
    end = html.index("</details>", start) + len("</details>")
    return html[start:end]


def test_render_binds_each_card_to_its_own_health_and_bucket():
    html = render_overview_html(_model())

    healthy = _card(html, "healthy-cli")
    unhealthy = _card(html, "unhealthy-cli")
    stale = _card(html, "stale-cli")

    assert "alpha" in html
    assert "beta" in html
    assert "● healthy" in healthy
    assert "▲ unhealthy" not in healthy
    assert "▲ unhealthy" in unhealthy
    assert "● healthy" not in unhealthy
    assert "◆ stale" in stale


def test_empty_model_template_loads():
    html = render_overview_html({
        "summary": {
            "total": 0,
            "healthy": 0,
            "unhealthy": 0,
            "stale": 0,
            "unknown": 0,
            "version": "1.2.0",
        },
        "buckets": [],
    })

    assert "<html" in html


def _sanity_model(cap):
    return {
        "summary": {"total": 1, "healthy": 1, "unhealthy": 0, "stale": 0,
                    "unknown": 0, "version": "1.2.0"},
        "buckets": [{
            "name": "alpha", "count": 1,
            "clis": [{
                "slug": "sanity-cli", "lang": "python", "health_status": "healthy",
                "description": "does a thing", "capabilities": [cap], "edges": [],
            }],
        }],
    }


def test_render_shows_sanity_pass_verdict_with_as_of_date():
    html = render_overview_html(_sanity_model({
        "intent_tags": ["convert"], "input_types": ["path"], "output_types": ["json"],
        "side_effect": "none", "confidence": "inferred",
        "sanity_ok": True, "sanity_reason": "",
        "sanity_checked_at": 1700000000.0, "sanity_checked_at_display": "2023-11-14",
    }))
    card = _card(html, "sanity-cli")
    assert "sanity ok" in card
    assert "2023-11-14" in card


def test_render_shows_sanity_fail_reason():
    html = render_overview_html(_sanity_model({
        "intent_tags": ["convert"], "input_types": ["path"], "output_types": ["json"],
        "side_effect": "writes-fs", "confidence": "inferred",
        "sanity_ok": False, "sanity_reason": "side_effect contradicts description",
        "sanity_checked_at": 1700000000.0, "sanity_checked_at_display": "2023-11-14",
    }))
    card = _card(html, "sanity-cli")
    assert "side_effect contradicts description" in card
    assert "2023-11-14" in card


def test_render_shows_not_yet_checked_when_sanity_none():
    html = render_overview_html(_sanity_model({
        "intent_tags": ["convert"], "input_types": ["path"], "output_types": ["json"],
        "side_effect": "none", "confidence": "inferred",
        "sanity_ok": None, "sanity_reason": "",
        "sanity_checked_at": None, "sanity_checked_at_display": "",
    }))
    card = _card(html, "sanity-cli")
    assert "not yet checked" in card


def test_render_escapes_description_xss_sentinel():
    model = {
        "summary": {
            "total": 1,
            "healthy": 0,
            "unhealthy": 0,
            "stale": 0,
            "unknown": 1,
            "version": "1.2.0",
        },
        "buckets": [{
            "name": "unsafe",
            "count": 1,
            "clis": [{
                "slug": "unsafe-cli",
                "lang": "python",
                "health_status": "unknown",
                "description": "<script>__XSS__()</script>",
                "capabilities": [],
                "edges": [],
            }],
        }],
    }

    html = render_overview_html(model)

    assert "&lt;script&gt;__XSS__" in html
    assert "<script>__XSS__" not in html
