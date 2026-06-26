from importlib.metadata import PackageNotFoundError

from core.web import overview_view


def _rows():
    return {
        "clis": [
            {"slug": "zulu", "lang": "python", "project": "beta",
             "description": "z", "health_status": "healthy"},
            {"slug": "alpha", "lang": "python", "project": "alpha",
             "description": "a", "health_status": "unhealthy"},
            {"slug": "missing", "lang": "shell",
             "description": "missing project", "health_status": "stale"},
            {"slug": "empty", "lang": "go", "project": "",
             "description": "empty project", "health_status": "unknown"},
            {"slug": "weird", "lang": "node", "project": "beta",
             "description": "bad state", "health_status": "BROKEN"},
        ],
        "caps_by_slug": {
            "alpha": [{
                "intent_tags": ["inspect"],
                "input_types": ["file:json"],
                "output_types": ["text:plain"],
                "side_effect": "none",
                "confidence": "declared",
            }],
            "empty": [],
        },
        "edges": [
            {"from": "alpha", "to": "zulu", "via_type": "text:plain"},
            {"from": "missing", "to": "alpha", "via_type": "file:json"},
            {"from": "other", "to": "empty", "via_type": "event"},
        ],
    }


def test_groups_by_project_with_ungrouped_pinned_last_and_clis_sorted(monkeypatch):
    monkeypatch.setattr(overview_view, "_package_version", lambda: "test-version")

    model = overview_view.build_overview_model(_rows())

    assert [bucket["name"] for bucket in model["buckets"]] == ["alpha", "beta", "(ungrouped)"]
    assert [cli["slug"] for cli in model["buckets"][1]["clis"]] == ["weird", "zulu"]
    ungrouped = model["buckets"][2]
    assert ungrouped["count"] == 2
    assert [cli["slug"] for cli in ungrouped["clis"]] == ["empty", "missing"]


def test_summary_counts_all_states_with_total_equal_to_parts(monkeypatch):
    monkeypatch.setattr(overview_view, "_package_version", lambda: "1.2.0")

    summary = overview_view.build_overview_model(_rows())["summary"]

    assert summary == {
        "total": 5,
        "healthy": 1,
        "unhealthy": 1,
        "stale": 1,
        "unknown": 2,
        "not_standalone": 0,
        "version": "1.2.0",
    }
    assert summary["total"] == (
        summary["healthy"] + summary["unhealthy"] + summary["stale"]
        + summary["unknown"] + summary["not_standalone"]
    )


def test_not_standalone_counted_and_badged(monkeypatch):
    """US-CLIAUDIT-83: a not_standalone row is a distinct 5th category — counted
    in the summary (not collapsed to unknown) and carries its own glyph."""
    monkeypatch.setattr(overview_view, "_package_version", lambda: "1.2.0")
    rows = {"clis": [
        {"slug": "a", "health_status": "healthy"},
        {"slug": "b", "health_status": "not_standalone"},
    ], "caps_by_slug": {}, "edges": []}
    model = overview_view.build_overview_model(rows)
    assert model["summary"]["not_standalone"] == 1
    assert model["summary"]["total"] == 2   # the internal assert must not trip
    card_b = next(c for bucket in model["buckets"]
                  for c in bucket["clis"] if c["slug"] == "b")
    assert card_b["health_status"] == "not_standalone"
    assert card_b["health_glyph"]   # a glyph exists for it


def test_incident_edges_match_from_and_to_separately(monkeypatch):
    monkeypatch.setattr(overview_view, "_package_version", lambda: "1.2.0")

    model = overview_view.build_overview_model(_rows())
    clis = {
        cli["slug"]: cli
        for bucket in model["buckets"]
        for cli in bucket["clis"]
    }

    assert clis["missing"]["edges"] == [
        {"from": "missing", "to": "alpha", "via_type": "file:json"}
    ]
    assert clis["empty"]["edges"] == [
        {"from": "other", "to": "empty", "via_type": "event"}
    ]


def test_empty_caps_become_empty_capabilities_list(monkeypatch):
    monkeypatch.setattr(overview_view, "_package_version", lambda: "1.2.0")

    model = overview_view.build_overview_model(_rows())
    clis = {
        cli["slug"]: cli
        for bucket in model["buckets"]
        for cli in bucket["clis"]
    }

    assert clis["zulu"]["capabilities"] == []
    assert clis["empty"]["capabilities"] == []


def test_empty_input_returns_zero_summary_and_no_buckets(monkeypatch):
    monkeypatch.setattr(overview_view, "_package_version", lambda: "1.2.0")

    model = overview_view.build_overview_model({"clis": [], "caps_by_slug": {}, "edges": []})

    assert model["summary"] == {
        "total": 0,
        "healthy": 0,
        "unhealthy": 0,
        "stale": 0,
        "unknown": 0,
        "not_standalone": 0,
        "version": "1.2.0",
    }
    assert model["buckets"] == []


def test_version_unknown_when_package_and_pyproject_are_unavailable(monkeypatch):
    def _missing(_name):
        raise PackageNotFoundError("a2a-cli-registry")

    monkeypatch.setattr(overview_view.importlib.metadata, "version", _missing)
    monkeypatch.setattr(overview_view, "_pyproject_version", lambda: None)

    model = overview_view.build_overview_model({"clis": [], "caps_by_slug": {}, "edges": []})

    assert model["summary"]["version"] == "unknown"
