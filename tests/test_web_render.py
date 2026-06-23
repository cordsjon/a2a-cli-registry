from core.web.render import render_overview_html


def _model():
    return {
        "summary": {
            "total": 3,
            "healthy": 1,
            "unhealthy": 1,
            "stale": 1,
            "unknown": 0,
            "version": "1.2.0",
        },
        "buckets": [
            {
                "name": "alpha",
                "count": 2,
                "clis": [
                    {
                        "slug": "healthy-cli",
                        "lang": "python",
                        "health_status": "healthy",
                        "description": "good",
                        "capabilities": [{
                            "intent_tags": ["inspect"],
                            "input_types": ["file:json"],
                            "output_types": ["text:plain"],
                            "side_effect": "none",
                            "confidence": "declared",
                        }],
                        "edges": [],
                    },
                    {
                        "slug": "unhealthy-cli",
                        "lang": "shell",
                        "health_status": "unhealthy",
                        "description": "bad",
                        "capabilities": [],
                        "edges": [{"from": "healthy-cli", "to": "unhealthy-cli", "via_type": "text:plain"}],
                    },
                ],
            },
            {
                "name": "beta",
                "count": 1,
                "clis": [{
                    "slug": "stale-cli",
                    "lang": "go",
                    "health_status": "stale",
                    "description": "old",
                    "capabilities": [],
                    "edges": [],
                }],
            },
        ],
    }


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
