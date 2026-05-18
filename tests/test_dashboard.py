"""Structural validation for the provisioned Grafana dashboard.

Runs in CI so a malformed or breaking edit to ``grafana/eero-dashboard.json``
fails loudly here instead of silently breaking the dashboard in Grafana.
"""

import json
from pathlib import Path
from typing import Any

DASHBOARD = Path(__file__).resolve().parent.parent / "grafana" / "eero-dashboard.json"


def _dashboard() -> dict[str, Any]:
    return json.loads(DASHBOARD.read_text())


def _all_panels(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten top-level panels and any panels nested inside row panels."""
    panels: list[dict[str, Any]] = []
    for panel in dashboard.get("panels", []):
        panels.append(panel)
        panels.extend(panel.get("panels", []))
    return panels


def test_dashboard_is_valid_json() -> None:
    assert isinstance(_dashboard(), dict)


def test_uid_is_stable() -> None:
    """The UID is the dashboard's stable identity and must never change."""
    assert _dashboard()["uid"] == "eero-mesh-network"


def test_schema_version_is_int() -> None:
    assert isinstance(_dashboard()["schemaVersion"], int)


def test_panel_ids_are_unique() -> None:
    ids = [p["id"] for p in _all_panels(_dashboard())]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate panel ids: {dupes}"


def test_panels_use_templated_datasource() -> None:
    """Every non-row panel must reference the ${datasource} template variable."""
    bad = [
        p["id"]
        for p in _all_panels(_dashboard())
        if p.get("type") != "row"
        and not (
            isinstance(p.get("datasource"), dict) and p["datasource"].get("uid") == "${datasource}"
        )
    ]
    assert not bad, f"panels not using the templated datasource: {bad}"


def test_data_usage_metrics_are_charted() -> None:
    """The Data Usage row must wire up all three data_usage metrics."""
    exprs = " ".join(
        t.get("expr", "") for p in _all_panels(_dashboard()) for t in p.get("targets", [])
    )
    for metric in (
        "eero_network_data_usage_bytes",
        "eero_device_data_usage_bytes",
        "eero_eero_data_usage_bytes",
    ):
        assert metric in exprs, f"{metric} is not charted on the dashboard"


def test_period_variable_present() -> None:
    """The Data Usage panels depend on the $period template variable."""
    names = {v["name"] for v in _dashboard()["templating"]["list"]}
    assert "period" in names


def test_data_usage_panels_do_not_overlap() -> None:
    """The Data Usage row (panel ids >= 200) sits below the existing rows
    with no panels overlapping each other."""
    new = [p for p in _dashboard()["panels"] if p["id"] >= 200]
    assert new, "Data Usage panels are missing"
    assert all(p["gridPos"]["y"] >= 127 for p in new), "Data Usage row overlaps existing rows"
    for i, a in enumerate(new):
        for b in new[i + 1 :]:
            ga, gb = a["gridPos"], b["gridPos"]
            x_hit = ga["x"] < gb["x"] + gb["w"] and gb["x"] < ga["x"] + ga["w"]
            y_hit = ga["y"] < gb["y"] + gb["h"] and gb["y"] < ga["y"] + ga["h"]
            assert not (x_hit and y_hit), f"panels {a['id']} and {b['id']} overlap"
