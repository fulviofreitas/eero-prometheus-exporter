"""Structural validation for the provisioned Grafana dashboard.

Runs in CI so a malformed or breaking edit to ``grafana/eero-dashboard.json``
fails loudly here instead of silently breaking the dashboard in Grafana.

Decision D16 (4.0.0): every metric in the registry must be charted, no metric
removed in 4.0.0 may be referenced, and every panel must follow the repo's
Grafana rules (templated datasource, ``network_id`` scoping, a unit, valid
colour schemes) -- see ``claude/rules/grafana-dashboard.md``.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from eero_exporter.metrics import REMOVED_IN_4_0_0, describe_metrics

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = REPO_ROOT / "grafana" / "eero-dashboard.json"
GENERATOR = REPO_ROOT / "scripts" / "gen_dashboard.py"

NETWORK_SCOPE = 'network_id=~"$network_id"'

#: The only ``fieldConfig.color.mode`` values Grafana accepts. Anything else
#: (``spectrum``, ``gradient``...) crashes the dashboard on load.
VALID_COLOR_SCHEMES = {
    "fixed",
    "shades",
    "thresholds",
    "palette-classic",
    "palette-classic-by-name",
    "continuous-GrYlRd",
    "continuous-RdYlGr",
    "continuous-BlYlRd",
    "continuous-YlRd",
    "continuous-BlPu",
    "continuous-YlBl",
    "continuous-blues",
    "continuous-reds",
    "continuous-greens",
    "continuous-purples",
}

#: Registry metrics that are intentionally not charted. Empty by design: every
#: 4.0.0 metric, including the exporter-internal ones, has a panel.
UNCHARTED_ALLOWLIST: frozenset[str] = frozenset()


def _dashboard() -> dict[str, Any]:
    return json.loads(DASHBOARD.read_text())


def _all_panels(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten top-level panels and any panels nested inside row panels."""
    panels: list[dict[str, Any]] = []
    for panel in dashboard.get("panels", []):
        panels.append(panel)
        panels.extend(panel.get("panels", []))
    return panels


def _data_panels(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    """Panels that render data (everything except rows)."""
    return [p for p in _all_panels(dashboard) if p.get("type") != "row"]


def _exprs(dashboard: dict[str, Any]) -> list[str]:
    return [t.get("expr", "") for p in _all_panels(dashboard) for t in p.get("targets", [])]


def _exposed_name(metric: Any) -> str:
    """The series name Prometheus renders for a registry entry.

    prometheus_client appends ``_info`` to ``Info`` metrics (so a declared
    ``eero_eero_role_info`` is exposed as ``eero_eero_role_info_info``);
    counters already carry ``_total`` in the registry.
    """
    return f"{metric.name}_info" if metric.type == "info" else metric.name


def _mentions(name: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text) is not None


def _overlaps(panels: list[dict[str, Any]]) -> list[tuple[int, int]]:
    overlaps = []
    for i, a in enumerate(panels):
        for b in panels[i + 1 :]:
            ga, gb = a["gridPos"], b["gridPos"]
            x_hit = ga["x"] < gb["x"] + gb["w"] and gb["x"] < ga["x"] + ga["w"]
            y_hit = ga["y"] < gb["y"] + gb["h"] and gb["y"] < ga["y"] + ga["h"]
            if x_hit and y_hit:
                overlaps.append((a["id"], b["id"]))
    return overlaps


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def test_generator_reproduces_the_committed_dashboard() -> None:
    """The committed JSON must be exactly what ``scripts/gen_dashboard.py`` emits.

    The dashboard is generated, not hand-edited: this fails when someone edits
    the JSON directly, or adds a metric without regenerating.
    """
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        "grafana/eero-dashboard.json is out of date -- run "
        f"`uv run python scripts/gen_dashboard.py`\n{result.stdout}{result.stderr}"
    )


def test_dashboard_is_valid_json() -> None:
    assert isinstance(_dashboard(), dict)


def test_uid_is_stable() -> None:
    """The UID is the dashboard's stable identity and must never change."""
    assert _dashboard()["uid"] == "eero-mesh-network"


def test_schema_version_is_int() -> None:
    assert isinstance(_dashboard()["schemaVersion"], int)


def test_version_bumped_for_4_0_0() -> None:
    """Grafana uses ``version`` to detect provisioning changes; 4.0.0 is >= 45."""
    assert _dashboard()["version"] >= 45


def test_panel_ids_are_unique() -> None:
    ids = [p["id"] for p in _all_panels(_dashboard())]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate panel ids: {dupes}"


def test_template_variables_present() -> None:
    names = {v["name"] for v in _dashboard()["templating"]["list"]}
    assert {"datasource", "network_id", "eero_id", "period"} <= names


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def test_no_panel_overlaps() -> None:
    """No two panels may occupy the same grid cell.

    Grafana silently reflows overlapping panels on load, which corrupts the
    intended layout, so the dashboard JSON itself must stay overlap-free.
    Checked for the top-level grid and, separately, inside each collapsed row.
    """
    dashboard = _dashboard()
    assert not _overlaps(dashboard["panels"]), _overlaps(dashboard["panels"])
    for row in dashboard["panels"]:
        if row.get("type") == "row" and row.get("panels"):
            bad = _overlaps(row["panels"])
            assert not bad, f"overlapping panels inside row {row['title']!r}: {bad}"


def test_grid_positions_fit_the_24_column_grid() -> None:
    bad = [
        p["id"]
        for p in _all_panels(_dashboard())
        if p["gridPos"]["x"] < 0 or p["gridPos"]["x"] + p["gridPos"]["w"] > 24
    ]
    assert not bad, f"panels outside the 24-column grid: {bad}"


def test_collapsed_rows_name_their_include_flag() -> None:
    """Optional tiers are collapsed rows whose title names the enabling flag."""
    rows = [p for p in _dashboard()["panels"] if p.get("type") == "row"]
    collapsed = [r for r in rows if r.get("collapsed")]
    assert collapsed, "expected at least one collapsed optional-tier row"
    bad = [r["title"] for r in collapsed if "--include-" not in r["title"]]
    assert not bad, f"collapsed rows without an --include- flag in the title: {bad}"
    for r in collapsed:
        assert r.get("panels"), f"collapsed row {r['title']!r} has no panels"


def test_every_default_off_tier_has_a_collapsed_row() -> None:
    flags = {
        f"--include-{t.replace('_', '-')}"
        for t in ("per_profile", "per_device", "per_eero", "unverified")
    }
    titles = " ".join(
        p["title"] for p in _dashboard()["panels"] if p.get("type") == "row" and p.get("collapsed")
    )
    missing = sorted(f for f in flags if f not in titles)
    assert not missing, f"no collapsed row for: {missing}"


# ---------------------------------------------------------------------------
# Per-panel rules (claude/rules/grafana-dashboard.md)
# ---------------------------------------------------------------------------


def test_panels_use_templated_datasource() -> None:
    """Every non-row panel must reference the ${datasource} template variable."""
    bad = [
        p["id"]
        for p in _data_panels(_dashboard())
        if not (
            isinstance(p.get("datasource"), dict) and p["datasource"].get("uid") == "${datasource}"
        )
    ]
    assert not bad, f"panels not using the templated datasource: {bad}"


def test_every_panel_has_a_unit() -> None:
    bad = [
        (p["id"], p.get("title"))
        for p in _data_panels(_dashboard())
        if not p.get("fieldConfig", {}).get("defaults", {}).get("unit")
    ]
    assert not bad, f"panels without a unit: {bad}"


def test_color_schemes_are_valid() -> None:
    bad = []
    for p in _data_panels(_dashboard()):
        field_config = p.get("fieldConfig", {})
        mode = field_config.get("defaults", {}).get("color", {}).get("mode")
        if mode is not None and mode not in VALID_COLOR_SCHEMES:
            bad.append((p["id"], mode))
        for override in field_config.get("overrides", []):
            for prop in override.get("properties", []):
                if prop.get("id") == "color":
                    override_mode = prop.get("value", {}).get("mode")
                    if override_mode not in VALID_COLOR_SCHEMES:
                        bad.append((p["id"], override_mode))
    assert not bad, f"invalid colour schemes: {bad}"


def test_network_scoped_queries_filter_on_network_id() -> None:
    """Any expression touching a metric that carries ``network_id`` must scope it."""
    scoped = {_exposed_name(m) for m in describe_metrics() if "network_id" in m.labels}
    bad = []
    for p in _data_panels(_dashboard()):
        for t in p.get("targets", []):
            expr = t.get("expr", "")
            if any(_mentions(name, expr) for name in scoped) and NETWORK_SCOPE not in expr:
                bad.append((p["id"], p.get("title"), expr))
    assert not bad, f"network-scoped queries missing {NETWORK_SCOPE}: {bad}"


def test_every_query_has_an_expr() -> None:
    bad = [
        p["id"]
        for p in _data_panels(_dashboard())
        for t in p.get("targets", [])
        if not t.get("expr")
    ]
    assert not bad, f"targets with an empty expr: {bad}"


# ---------------------------------------------------------------------------
# Metric coverage (D16)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("metric", describe_metrics(), ids=lambda m: m.name)
def test_every_registry_metric_is_charted(metric: Any) -> None:
    if metric.name in UNCHARTED_ALLOWLIST:
        pytest.skip("explicitly allowlisted as uncharted")
    exprs = "\n".join(_exprs(_dashboard()))
    assert _mentions(_exposed_name(metric), exprs), (
        f"{metric.name} ({metric.tier}/{metric.family}) is not charted on the dashboard"
    )


def test_uncharted_allowlist_only_names_registry_metrics() -> None:
    names = {m.name for m in describe_metrics()}
    assert UNCHARTED_ALLOWLIST <= names, UNCHARTED_ALLOWLIST - names


def test_no_removed_metric_is_referenced() -> None:
    """Names removed in 4.0.0 must not appear anywhere in the dashboard JSON."""
    text = DASHBOARD.read_text()
    present = sorted(name for name in REMOVED_IN_4_0_0 if _mentions(name, text))
    assert not present, f"removed 4.0.0 metrics still referenced: {present}"


def test_data_usage_metrics_are_charted() -> None:
    """The Data Usage row must wire up all three data_usage families and $period."""
    exprs = " ".join(_exprs(_dashboard()))
    for metric in (
        "eero_network_data_usage_bytes",
        "eero_device_data_usage_bytes",
        "eero_eero_data_usage_bytes",
    ):
        assert metric in exprs, f"{metric} is not charted on the dashboard"
    assert 'period="$period"' in exprs


def test_api_status_legend_covers_the_closed_enum() -> None:
    """The exporter row explains every ``status`` value of api_requests_total."""
    from eero_exporter.metrics import API_STATUS_VALUES

    legends = [
        p["options"]["content"]
        for p in _data_panels(_dashboard())
        if p.get("type") == "text" and "status" in p.get("title", "").lower()
    ]
    assert legends, "no API status legend text panel found"
    missing = sorted(s for s in API_STATUS_VALUES if f"`{s}`" not in legends[0])
    assert not missing, f"API status legend is missing: {missing}"
