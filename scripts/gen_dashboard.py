"""Generate grafana/eero-dashboard.json for eero-prometheus-exporter.

Design system (dataviz skill) -- one visual language, graph first:

* **Form follows the data's job.** Anything that changes over time is a
  ``timeseries``; booleans/enums that change are a ``state-timeline``; top-N
  comparisons are horizontal gradient ``bargauge``; a proportion is one donut.
  ``stat`` is reserved for the Overview KPI header (with area sparklines) and
  for text tiles that surface Info-metric labels. ``table`` only where rows
  ARE the point: eero, Ethernet-port and device inventories, port forwards,
  and one table for static configuration flags.
* **One grid.** Six panel sizes only: KPI 4x4, third 8x8, half 12x8, full
  24x8, half table 12x10, full table 24x10. Every line fills 24 columns.
* **One mark spec.** 2px smooth lines, 18% opacity-gradient fill, no points;
  bars for per-window counts; step lines for discrete values (channel, bars).
  Legends are tables (last / max) on the right of half- and full-width
  charts and compact lists under third-width charts; tooltips are
  multi-series, sorted descending.
* **Colour by job.** ``palette-classic`` for multi-series identity, ``fixed``
  blue for single series, ``thresholds`` only where the scale means something
  (signal dBm, utilisation %, API success, collection age). Status colours
  (green/orange/red) are reserved for health; neutral "off" states use the
  muted ink #898781.
* **Correct totals.** Per-device gauges can carry stale label sets (mutable
  ``band``/``source_eero``/``name`` labels), so headline counts come from
  network/eero-level gauges, and every per-device expression first collapses
  to one series per ``device_id``. Names are borrowed with a join that is
  guaranteed one-to-one (``topk by (key) (1, group by (key, label) (...))``).
* **Story order.** Overview, Network & WAN and Eero mesh health are open;
  secondary rows and the four opt-in tier rows (titled with their
  ``--include-*`` flag) start collapsed.

Regenerating after a metrics change::

    uv run python scripts/gen_dashboard.py           # rewrite the dashboard
    uv run python scripts/gen_dashboard.py --check   # exit 1 if it would change

``tests/test_dashboard.py`` runs the ``--check`` mode, so CI fails when the
registry and the committed dashboard drift apart.
``scripts/render_dashboard_preview.py`` renders it against synthetic data.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
from eero_exporter.metrics import (  # noqa: E402
    API_STATUS_VALUES,
    REMOVED_IN_4_0_0,
    describe_metrics,
)

DS = {"type": "prometheus", "uid": "${datasource}"}
N = 'network_id=~"$network_id"'
NE = 'network_id=~"$network_id", eero_id=~"$eero_id"'
NEUTRAL = "#898781"
ACCENT = "blue"
OUT = REPO_ROOT / "grafana" / "eero-dashboard.json"

# The six panel sizes (w, h). Grid.add refuses anything else.
KPI = (4, 4)
THIRD = (8, 8)
HALF = (12, 8)
FULL = (24, 8)
HALF_TABLE = (12, 10)
FULL_TABLE = (24, 10)
SIZES = {KPI, THIRD, HALF, FULL, HALF_TABLE, FULL_TABLE}

Panel = dict[str, Any]
Placed = tuple[Panel, tuple[int, int]]

_next_id = 0


def nid() -> int:
    global _next_id
    _next_id += 1
    return _next_id


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


class Grid:
    """Stacks full-width lines of panels; every line fills exactly 24 columns."""

    def __init__(self, y: int = 0) -> None:
        self.y = y
        self.panels: list[Panel] = []

    def line(self, *items: Placed) -> None:
        """Add one line of panels of equal height whose widths sum to 24."""
        titles = [p["title"] for p, _ in items]
        assert sum(s[0] for _, s in items) == 24, f"line does not fill 24 columns: {titles}"
        assert len({s[1] for _, s in items}) == 1, f"ragged line heights: {titles}"
        x = 0
        for panel, size in items:
            assert size in SIZES, f"{panel['title']!r}: {size} is not in the grid vocabulary"
            w, h = size
            panel["gridPos"] = {"h": h, "w": w, "x": x, "y": self.y}
            _place_legend(panel, w)
            self.panels.append(panel)
            x += w
        self.y += items[0][1][1]


def _place_legend(panel: Panel, w: int) -> None:
    """Table legend (last/max) right of wide charts, a plain list under narrow ones."""
    legend = panel.get("options", {}).get("legend")
    if panel["type"] != "timeseries" or legend is None or not legend["showLegend"]:
        return
    if w >= 12:
        legend.update(displayMode="table", placement="right", calcs=["lastNotNull", "max"])
    else:
        legend.update(displayMode="list", placement="bottom", calcs=[])


# ---------------------------------------------------------------------------
# PromQL helpers
# ---------------------------------------------------------------------------


def borrow(expr: str, key: str, label: str, source: str) -> str:
    """Attach ``label`` from ``source`` to ``expr``, joined on (network_id, key).

    ``group by`` makes the borrowed side's value 1 (an offline eero or an
    unpaused profile must not zero the result) and ``topk by (key) (1, ...)``
    keeps exactly one series per key, so a label that changed value (several
    stale series) can never cause a many-to-many matching error.
    """
    return (
        f"({expr}) * on (network_id, {key}) group_left({label}) "
        f"topk by (network_id, {key}) (1, group by (network_id, {key}, {label}) "
        f"({source}{{{N}}}))"
    )


def with_location(expr: str) -> str:
    """Attach the eero's ``location`` to an eero_id-only series."""
    return borrow(expr, "eero_id", "location", "eero_eero_status")


def with_device_name(expr: str) -> str:
    """Attach the device ``name``, joined one-to-one on ``device_id``.

    ``name`` lives on the device gauges (``eero_device_info`` carries only
    ``mac``), so we borrow it from ``eero_device_connected``. The ``borrow``
    helper's ``topk by (network_id, device_id) (1, ...)`` keeps exactly one
    ``name`` series per device even when a renamed device left a stale one
    behind -- the many-to-many match that made the old ``group_left(name)``
    join error (live-validation bug 1) can no longer happen.
    """
    return borrow(expr, "device_id", "name", "eero_device_connected")


def with_profile_name(expr: str) -> str:
    """Attach the profile ``name``."""
    return borrow(expr, "profile_id", "name", "eero_profile_paused")


def per_device(metric: str, extra: str = "") -> str:
    """One series per device (collapses stale label sets)."""
    return f"max by (network_id, device_id) ({metric}{{{N}{extra}}})"


CONNECTED = f"(max by (network_id, device_id) (eero_device_connected{{{N}}}) == 1)"


def connected_device(metric: str) -> str:
    """Per-device series restricted to connected devices, labelled with the device name."""
    return with_device_name(f"{per_device(metric)} and on (network_id, device_id) {CONNECTED}")


def device_count(metric: str) -> str:
    """Number of distinct devices whose flag is 1 (0 when none)."""
    return f"count({per_device(metric)} == 1) or on () vector(0)"


# ---------------------------------------------------------------------------
# Panel builders
# ---------------------------------------------------------------------------


def target(
    expr: str, ref: str = "A", legend: str = "", table: bool = False, instant: bool = False
) -> dict[str, Any]:
    t: dict[str, Any] = {"expr": expr, "refId": ref, "legendFormat": legend or "__auto"}
    if table:
        t["format"] = "table"
        t["instant"] = True
    elif instant:
        t["instant"] = True
        t["range"] = False
    return t


def targets_of(items: list[tuple[str, str]], instant: bool = False) -> list[dict[str, Any]]:
    return [target(e, chr(65 + i), lg, instant=instant) for i, (e, lg) in enumerate(items)]


def base(title: str, ptype: str, unit: str, description: str = "") -> Panel:
    p: Panel = {
        "id": nid(),
        "type": ptype,
        "title": title,
        "datasource": DS,
        "fieldConfig": {"defaults": {"unit": unit, "mappings": []}, "overrides": []},
        "options": {},
        "targets": [],
    }
    if description:
        p["description"] = description
    return p


Thresholds = list[tuple[str, float | None]]


def steps(thresholds: Thresholds) -> dict[str, Any]:
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in thresholds]}


def value_map(values: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
    opts = {k: {"index": i, "text": t, "color": c} for i, (k, (t, c)) in enumerate(values.items())}
    return [{"type": "value", "options": opts}]


BOOL_COLORS = {
    "health": ("green", "red"),  # 1 good / 0 bad
    "toggle": (ACCENT, NEUTRAL),  # 1 on / 0 off
    "warn": ("orange", NEUTRAL),  # 1 needs attention / 0 fine
}


def bool_map(on: str, off: str, kind: str = "toggle") -> list[dict[str, Any]]:
    c_on, c_off = BOOL_COLORS[kind]
    return value_map({"1": (on, c_on), "0": (off, c_off)})


def override(name: str, **props: Any) -> dict[str, Any]:
    return {
        "matcher": {"id": "byName", "options": name},
        "properties": [{"id": k, "value": v} for k, v in props.items()],
    }


def timeseries(
    title: str,
    items: list[tuple[str, str]],
    unit: str = "short",
    *,
    stack: bool = False,
    bars: bool = False,
    step: bool = False,
    min_: float | None = None,
    max_: float | None = None,
    decimals: int | None = None,
    thresholds: Thresholds | None = None,
    overrides: list[dict[str, Any]] | None = None,
    description: str = "",
) -> Panel:
    p = base(title, "timeseries", unit, description)
    d = p["fieldConfig"]["defaults"]
    single = len(items) == 1 and "{{" not in items[0][1]
    d["color"] = {"mode": "fixed", "fixedColor": ACCENT} if single else {"mode": "palette-classic"}
    custom: dict[str, Any] = {
        "drawStyle": "bars" if bars else "line",
        "lineInterpolation": "stepAfter" if step else "smooth",
        "lineWidth": 1 if bars else 2,
        "fillOpacity": 60 if bars else (18 if stack or not step else 0),
        "gradientMode": "opacity",
        "barAlignment": 0,
        "showPoints": "never",
        "pointSize": 4,
        "spanNulls": 600000,
        "axisPlacement": "auto",
        "axisBorderShow": False,
        "axisCenteredZero": False,
        "stacking": {"mode": "normal" if stack else "none", "group": "A"},
        "thresholdsStyle": {"mode": "line" if thresholds else "off"},
    }
    if min_ is None and unit != "dBm":
        custom["axisSoftMin"] = 0
    d["custom"] = custom
    if min_ is not None:
        d["min"] = min_
    if max_ is not None:
        d["max"] = max_
    if decimals is not None:
        d["decimals"] = decimals
    d["thresholds"] = steps(thresholds or [(ACCENT, None)])
    p["fieldConfig"]["overrides"] = overrides or []
    p["options"] = {
        "legend": {
            "calcs": [],
            "displayMode": "list",
            "placement": "bottom",
            "showLegend": not single,
        },
        "tooltip": {"mode": "multi", "sort": "desc"},
    }
    p["targets"] = targets_of(items)
    return p


def state_timeline(
    title: str,
    items: list[tuple[str, str]],
    mappings: list[dict[str, Any]],
    *,
    overrides: list[dict[str, Any]] | None = None,
    description: str = "",
) -> Panel:
    """Booleans / enums over time: one lane per series, colour from value mappings."""
    p = base(title, "state-timeline", "none", description)
    d = p["fieldConfig"]["defaults"]
    # Colour mode must not be "thresholds": Grafana then paints every state with
    # the threshold colour and ignores the value-mapping colours.
    d["color"] = {"mode": "fixed", "fixedColor": NEUTRAL}
    d["thresholds"] = steps([(NEUTRAL, None)])
    d["mappings"] = mappings
    d["custom"] = {"fillOpacity": 75, "lineWidth": 0, "hideFrom": {"legend": False}}
    p["fieldConfig"]["overrides"] = overrides or []
    p["options"] = {
        "mergeValues": True,
        "showValue": "never",
        "alignValue": "center",
        "rowHeight": 0.8,
        "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
        "tooltip": {"mode": "single", "sort": "none"},
    }
    p["targets"] = targets_of(items)
    return p


def kpi(
    title: str,
    expr: str,
    unit: str,
    *,
    thresholds: Thresholds | None = None,
    decimals: int | None = None,
    description: str = "",
) -> Panel:
    """Overview KPI tile: current value plus an area sparkline of the selected range."""
    p = base(title, "stat", unit, description)
    d = p["fieldConfig"]["defaults"]
    if thresholds:
        d["color"] = {"mode": "thresholds"}
        d["thresholds"] = steps(thresholds)
    else:
        d["color"] = {"mode": "fixed", "fixedColor": ACCENT}
        d["thresholds"] = steps([(ACCENT, None)])
    if decimals is not None:
        d["decimals"] = decimals
    p["options"] = {
        "colorMode": "value" if thresholds else "none",
        "graphMode": "area",
        "justifyMode": "auto",
        "orientation": "auto",
        "textMode": "value",
        "wideLayout": True,
        "showPercentChange": False,
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
    }
    p["targets"] = [target(expr)]
    return p


def stat_list(
    title: str, items: list[tuple[str, str]], unit: str, *, description: str = ""
) -> Panel:
    """One "name ........ value" row per series (dates, versions): a compact key/value list."""
    p = base(title, "stat", unit, description)
    d = p["fieldConfig"]["defaults"]
    d["color"] = {"mode": "fixed", "fixedColor": "text"}
    d["thresholds"] = steps([("text", None)])
    p["options"] = {
        "colorMode": "none",
        "graphMode": "none",
        "justifyMode": "auto",
        "orientation": "horizontal",
        "textMode": "value_and_name",
        "wideLayout": True,
        "showPercentChange": False,
        "text": {"titleSize": 14, "valueSize": 18},
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
    }
    p["targets"] = targets_of(items, instant=True)
    return p


Relabel = tuple[str, str, str]
"""(replacement, source label, anchored regex) for a PromQL ``label_replace``."""


def relabel(expr: str, dst: str, rules: list[Relabel]) -> str:
    """Apply ``label_replace`` rules in order; a rule whose regex does not match is a no-op."""
    for replacement, src, regex in rules:
        expr = f'label_replace({expr}, "{dst}", "{replacement}", "{src}", "{regex}")'
    return expr


def setting(order: int, name: str | list[Relabel], expr: str, value: str) -> str:
    """One key/value row: Info label ``value`` shown under the setting ``name``.

    ``name`` is either a fixed string or relabel rules deriving it from a label (one
    row per label value, e.g. per band); the hidden ``order`` label keeps rows stable.
    """
    rules = [(name, "", "")] if isinstance(name, str) else name
    order_rules = [(f"{order:02d}", "", "")]
    if not isinstance(name, str):
        order_rules = [(f"{order:02d}$1", name[0][1], "(.*)")]
    e = relabel(expr, "value", [("$1", value, "(.*)")])
    e = relabel(relabel(e, "setting", rules), "order", order_rules)
    return f"group by (network_id, setting, value, order) ({e})"


def settings_table(title: str, rows: list[str], *, description: str = "") -> Panel:
    """Two-column Setting | Value list built from Info labels, in declaration order."""
    p = base(title, "table", "none", description)
    d = p["fieldConfig"]["defaults"]
    d["custom"] = {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False}
    d["color"] = {"mode": "fixed", "fixedColor": "text"}
    d["thresholds"] = steps([("text", None)])
    muted = {
        "custom.width": 170,
        "color": {"mode": "fixed", "fixedColor": NEUTRAL},
        "custom.cellOptions": {"type": "color-text"},
    }
    p["fieldConfig"]["overrides"] = [override("Setting", **muted)]
    p["options"] = {
        "cellHeight": "sm",
        "showHeader": False,
        "footer": {"show": False, "reducer": ["sum"], "countRows": False, "fields": ""},
        "sortBy": [],
    }
    p["targets"] = [target(" or ".join(rows), table=True)]
    p["transformations"] = [
        {"id": "sortBy", "options": {"fields": {}, "sort": [{"field": "order"}]}},
        {
            "id": "organize",
            "options": {
                "excludeByName": {
                    "Time": True,
                    "Value": True,
                    "order": True,
                    "network_id": True,
                },
                "indexByName": {"setting": 0, "value": 1},
                "renameByName": {"setting": "Setting", "value": "Value"},
            },
        },
    ]
    return p


def bargauge(
    title: str,
    items: list[tuple[str, str]],
    unit: str = "short",
    *,
    min_: float | None = 0,
    max_: float | None = None,
    thresholds: Thresholds | None = None,
    description: str = "",
) -> Panel:
    """Horizontal gradient bars for top-N / per-item comparisons (current value)."""
    p = base(title, "bargauge", unit, description)
    d = p["fieldConfig"]["defaults"]
    if thresholds:
        d["color"] = {"mode": "thresholds"}
        d["thresholds"] = steps(thresholds)
    else:
        d["color"] = {"mode": "fixed", "fixedColor": ACCENT}
        d["thresholds"] = steps([(ACCENT, None)])
    if min_ is not None:
        d["min"] = min_
    if max_ is not None:
        d["max"] = max_
    p["options"] = {
        "displayMode": "gradient",
        "orientation": "horizontal",
        "namePlacement": "left",
        "showUnfilled": True,
        "sizing": "auto",
        "valueMode": "text",
        "minVizHeight": 14,
        "minVizWidth": 8,
        "maxVizHeight": 22,
        "text": {"titleSize": 12, "valueSize": 14},
        "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": False},
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
    }
    p["targets"] = targets_of(items, instant=True)
    return p


def donut(title: str, items: list[tuple[str, str]], unit: str = "short") -> Panel:
    """Part-to-whole at a glance (<= 6 segments)."""
    p = base(title, "piechart", unit)
    p["fieldConfig"]["defaults"]["color"] = {"mode": "palette-classic"}
    p["options"] = {
        "pieType": "donut",
        "displayLabels": ["percent"],
        "legend": {
            "displayMode": "table",
            "placement": "right",
            "showLegend": True,
            "values": ["value", "percent"],
        },
        "tooltip": {"mode": "single", "sort": "none"},
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
    }
    p["targets"] = targets_of(items, instant=True)
    return p


def histogram(title: str, expr: str, unit: str, bucket: float, description: str = "") -> Panel:
    """Distribution of the current per-item values."""
    p = base(title, "histogram", unit, description)
    d = p["fieldConfig"]["defaults"]
    d["color"] = {"mode": "fixed", "fixedColor": ACCENT}
    d["custom"] = {"fillOpacity": 60, "gradientMode": "opacity", "lineWidth": 1}
    p["options"] = {
        "bucketSize": bucket,
        "combine": True,
        "legend": {"displayMode": "list", "placement": "bottom", "showLegend": False},
        "tooltip": {"mode": "single", "sort": "none"},
    }
    p["targets"] = [target(expr, instant=True)]
    return p


Column = tuple[str, str, str, dict[str, Any] | None]
"""(refId, expr, display name, override properties or None)."""


def col_bool(on: str = "yes", off: str = "no", kind: str = "toggle") -> dict[str, Any]:
    return {"mappings": bool_map(on, off, kind), "custom.cellOptions": {"type": "color-text"}}


def col_unit(unit: str) -> dict[str, Any]:
    return {"unit": unit}


def col_hidden() -> dict[str, Any]:
    return {"custom.hidden": True}


def table(
    title: str,
    columns: list[Column],
    label_columns: dict[str, str],
    *,
    sort_by: str | None = None,
    description: str = "",
    hide_ids: tuple[str, ...] = ("eero_id", "device_id", "profile_id", "network_id", "forward_id"),
) -> Panel:
    """Table from several instant queries merged on their shared label columns.

    Each query projects only its key labels (``max by (...)``) so the Grafana
    ``merge`` transformation lines rows up without duplicate columns.
    """
    p = base(title, "table", "none", description)
    d = p["fieldConfig"]["defaults"]
    d["custom"] = {
        "align": "auto",
        "cellOptions": {"type": "auto"},
        "filterable": True,
        "inspect": False,
    }
    d["color"] = {"mode": "thresholds"}
    d["thresholds"] = steps([(ACCENT, None)])
    rename = {f"Value #{ref}": name for ref, _, name, _ in columns}
    rename.update(label_columns)
    # "mac" never reaches the screen (privacy); the rest is scrape plumbing.
    exclude = {"Time": True, "__name__": True, "instance": True, "job": True, "mac": True}
    for hid in hide_ids:
        if hid not in label_columns:
            exclude[hid] = True
    p["fieldConfig"]["overrides"] = [
        override(name, **props) for _ref, _, name, props in columns if props
    ]
    p["options"] = {
        "cellHeight": "sm",
        "showHeader": True,
        "footer": {"show": False, "reducer": ["sum"], "countRows": False, "fields": ""},
        "sortBy": [{"desc": False, "displayName": sort_by}] if sort_by else [],
    }
    p["targets"] = [target(expr, ref, table=True) for ref, expr, _, _ in columns]
    p["transformations"] = [
        {"id": "merge", "options": {}},
        {"id": "organize", "options": {"excludeByName": exclude, "renameByName": rename}},
    ]
    return p


def text_panel(title: str, markdown: str) -> Panel:
    p = base(title, "text", "none")
    p["options"] = {"mode": "markdown", "content": markdown}
    return p


def row(title: str, y: int, collapsed: bool, children: list[Panel]) -> Panel:
    return {
        "id": nid(),
        "type": "row",
        "title": title,
        "collapsed": collapsed,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "panels": children if collapsed else [],
    }


# Shared threshold scales (only where the scale carries meaning).
UTIL_TH: Thresholds = [("green", None), ("orange", 50), ("red", 80)]
SIGNAL_TH: Thresholds = [("red", None), ("orange", -75), ("green", -65)]

# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

panels: list[Panel] = []
y = 0


def section(title: str, build: Callable[[Grid], None], collapsed: bool = False) -> None:
    global y
    g = Grid(y + 1)
    build(g)
    if collapsed:
        panels.append(row(title, y, True, g.panels))
        y += 1
    else:
        panels.append(row(title, y, False, []))
        panels.extend(g.panels)
        y = g.y


# --- Overview ---------------------------------------------------------------


def overview(g: Grid) -> None:
    g.line(
        (
            kpi(
                "Connected clients",
                f"sum(eero_network_clients_count{{{N}}})",
                "short",
                description="Network-level client count reported by eero.",
            ),
            KPI,
        ),
        (kpi("Eeros online", f"sum(eero_eero_status{{{N}}})", "short"), KPI),
        (kpi("Download (speed test)", f"sum(eero_speed_download_mbps{{{N}}})", "Mbits"), KPI),
        (kpi("Upload (speed test)", f"sum(eero_speed_upload_mbps{{{N}}})", "Mbits"), KPI),
        (
            kpi(
                "Data used — $period",
                f'sum(eero_network_data_usage_bytes{{{N}, period="$period"}})',
                "bytes",
            ),
            KPI,
        ),
        (
            kpi(
                "API health (15m)",
                'sum(rate(eero_exporter_api_requests_total{status=~"success|not_found|'
                'premium_required|feature_unavailable"}[15m])) '
                "/ sum(rate(eero_exporter_api_requests_total[15m]))",
                "percentunit",
                thresholds=[("red", None), ("orange", 0.9), ("green", 0.99)],
                decimals=1,
                description="Share of API requests that succeeded or returned an expected state.",
            ),
            KPI,
        ),
    )
    health = [
        (f"max(eero_network_status{{{N}}})", "Network"),
        (f'max(eero_health_status{{{N}, source="internet"}})', "Internet"),
        (f'max(eero_health_status{{{N}, source="eero_network"}})', "Mesh"),
        (f"max(eero_network_isp_up{{{N}}})", "ISP link"),
        ("max(eero_up)", "Exporter"),
        (f"max(eero_network_double_nat_detected{{{N}}})", "Double NAT"),
        (f"max(eero_network_update_available{{{N}}})", "Firmware update"),
    ]
    g.line(
        (
            state_timeline(
                "Health",
                health,
                bool_map("OK", "DOWN", "health"),
                overrides=[
                    override("Double NAT", mappings=bool_map("DETECTED", "no", "warn")),
                    override("Firmware update", mappings=bool_map("AVAILABLE", "current", "warn")),
                ],
            ),
            FULL,
        )
    )
    g.line(
        (
            timeseries(
                "Clients — wireless vs wired",
                [
                    (f"sum(eero_eero_connected_wireless_clients_count{{{N}}})", "Wireless"),
                    (f"sum(eero_eero_connected_wired_clients_count{{{N}}})", "Wired"),
                ],
                stack=True,
                description="Eero-level client counts (stay correct when per-device series go stale).",
            ),
            HALF,
        ),
        (
            timeseries(
                "Speed test",
                [
                    (f"sum(eero_speed_download_mbps{{{N}}})", "Download"),
                    (f"sum(eero_speed_upload_mbps{{{N}}})", "Upload"),
                ],
                "Mbits",
                step=True,
            ),
            HALF,
        ),
    )


# --- Network & WAN ----------------------------------------------------------


def network_wan(g: Grid) -> None:
    wpa_band = f'label_replace(eero_network_wpa3_band_mode{{{N}}} == 1, "mode", "$1/$2", "mode", "(WPA2)_(WPA3)")'
    wpa_name = [
        ("Security · $1", "band", "(.*)"),
        ("Security · $1 GHz", "band", "([0-9]+)_ghz"),
        ("Security · $1.$2 GHz", "band", "([0-9]+)_([0-9]+)_ghz"),
    ]
    dns_name = [("DNS · IPv4", "family", "ipv4"), ("DNS · IPv6", "family", "ipv6")]
    settings_h = HALF_TABLE
    g.line(
        (
            settings_table(
                "Internet & LAN",
                [
                    setting(1, "ISP", f"eero_network_info{{{N}}}", "isp"),
                    setting(2, "WAN", f"eero_network_wan_type_info{{{N}}}", "type"),
                    setting(3, "Connection", f"eero_network_connection_mode_info{{{N}}}", "mode"),
                    setting(4, "DHCP", f"eero_network_dhcp_mode_info{{{N}}}", "mode"),
                    setting(5, dns_name, f"eero_network_dns_mode_info{{{N}}}", "mode"),
                    setting(6, "DNS config", f"eero_dns_config_info{{{N}}}", "mode"),
                    setting(7, "Timezone", f"eero_network_timezone_info{{{N}}}", "timezone"),
                    setting(8, "Account role", f"eero_network_role_info{{{N}}}", "role"),
                ],
            ),
            settings_h,
        ),
        (
            settings_table(
                "Wi-Fi & firmware",
                [
                    setting(1, "Wireless mode", f"eero_network_wireless_mode_info{{{N}}}", "mode"),
                    setting(2, "MLO", f"eero_network_mlo_mode_info{{{N}}}", "mode"),
                    setting(3, wpa_name, wpa_band, "mode"),
                    setting(4, "Guest network", f"eero_guest_network_info{{{N}}}", "name"),
                    setting(
                        5, "Target firmware", f"eero_network_update_target_info{{{N}}}", "version"
                    ),
                ],
            ),
            settings_h,
        ),
    )
    key_dates = (
        stat_list(
            "Key dates",
            [
                (f"eero_speed_test_timestamp_seconds{{{N}}} * 1000", "Last speed test"),
                (
                    f"eero_network_last_reboot_timestamp_seconds{{{N}}} * 1000",
                    "Network rebooted",
                ),
                (
                    f"eero_account_premium_next_renewal_timestamp_seconds{{{N}}} * 1000",
                    "Eero Plus renews",
                ),
                (
                    f"eero_account_entitlement_created_timestamp_seconds{{{N}}} * 1000",
                    "Entitlement since",
                ),
            ],
            "dateTimeFromNow",
        ),
        THIRD,
    )
    security = [
        ("WPA3", "eero_network_wpa3_enabled"),
        ("Fast transition", "eero_network_fast_transition_enabled"),
        ("Eero Plus", "eero_network_premium_enabled"),
        ("Ad blocking", "eero_network_ad_block_enabled"),
        ("Malware blocking", "eero_network_malware_block_enabled"),
        ("Custom DNS", "eero_network_custom_dns_enabled"),
        ("DNS caching", "eero_network_dns_caching_enabled"),
        ("UPnP", "eero_network_upnp_enabled"),
    ]
    connectivity = [
        ("IPv6", "eero_network_ipv6_enabled"),
        ("SQM", "eero_network_sqm_enabled"),
        ("Band steering", "eero_network_band_steering_enabled"),
        ("Thread", "eero_network_thread_enabled"),
        ("Guest network", "eero_network_guest_enabled"),
        ("Dynamic DNS", "eero_network_ddns_enabled"),
        ("Power saving", "eero_network_power_saving_enabled"),
        ("Backup internet", "eero_network_backup_internet_enabled"),
    ]
    on_off = bool_map("ON", "OFF")
    g.line(
        key_dates,
        (
            state_timeline(
                "Security & filtering features",
                [(f"max({m}{{{N}}})", t) for t, m in security],
                on_off,
            ),
            THIRD,
        ),
        (
            state_timeline(
                "Connectivity features",
                [(f"max({m}{{{N}}})", t) for t, m in connectivity],
                on_off,
            ),
            THIRD,
        ),
    )
    counts = [
        ("Eeros", f"sum(eero_network_eeros_count{{{N}}})"),
        ("Eeros pending update", f"sum(eero_network_updates_available{{{N}}})"),
        ("DNS servers", f"sum(eero_network_dns_server_count{{{N}}})"),
        ("Parent DNS servers", f"sum(eero_network_dns_parent_server_count{{{N}}})"),
        ("DHCP reservations", f"sum(eero_network_dhcp_reservations_count{{{N}}})"),
        ("Port forwards", f"sum(eero_network_port_forwards_count{{{N}}})"),
        ("Blacklisted devices", f"sum(eero_network_blacklisted_devices_count{{{N}}})"),
        ("DNS allow-list domains", f"sum(eero_dns_policy_allowed_domains_count{{{N}}})"),
        ("DNS block-list domains", f"sum(eero_dns_policy_blocked_domains_count{{{N}}})"),
        ("Entitled features", f"count(eero_network_feature_entitled{{{N}}} == 1)"),
        ("Networks in account", "sum(eero_account_networks_count)"),
    ]
    g.line(
        (
            bargauge(
                "Configuration counts",
                [(e, t) for t, e in counts],
                description="'Networks in account' is account-wide (not scoped by the selector).",
            ),
            HALF_TABLE,
        ),
        (
            table(
                "Port forwards",
                [
                    (
                        "A",
                        "max by (forward_id, description, protocol, client_port, gateway_port) "
                        f"(eero_port_forward_info{{{N}}})",
                        "Rule",
                        col_hidden(),
                    ),
                    (
                        "B",
                        f"max by (forward_id) (eero_port_forward_enabled{{{N}}})",
                        "Enabled",
                        col_bool(),
                    ),
                ],
                {
                    "description": "Description",
                    "protocol": "Protocol",
                    "client_port": "Client port",
                    "gateway_port": "Gateway port",
                },
                description="Empty when no port forwards are configured.",
            ),
            HALF_TABLE,
        ),
    )


# --- Eero mesh health -------------------------------------------------------


def _eero_inventory() -> Panel:
    ts = "dateTimeFromNow"

    def by(metric: str, extra: str = "") -> str:
        return f"max by (eero_id{extra}) ({metric}{{{NE}}})"

    return table(
        "Eero inventory",
        [
            (
                "A",
                by("eero_eero_info", ", location, model, os_version, ip_address"),
                "Info",
                col_hidden(),
            ),
            ("B", by("eero_eero_status"), "Status", col_bool("online", "offline", "health")),
            ("C", by("eero_eero_role_info_info", ", role"), "RL", col_hidden()),
            ("D", by("eero_eero_connection_type_info", ", connection_type"), "CT", col_hidden()),
            ("E", by("eero_eero_power_source_info", ", source"), "PS", col_hidden()),
            ("F", by("eero_eero_os_version_info", ", version"), "OSV", col_hidden()),
            ("G", by("eero_eero_is_gateway"), "Gateway", col_bool()),
            ("H", by("eero_eero_is_primary"), "Primary", col_bool()),
            ("I", by("eero_eero_using_wan"), "Using WAN", col_bool()),
            ("J", by("eero_eero_wired"), "Wired", col_bool()),
            ("K", by("eero_eero_wired_internet"), "Wired internet", col_bool()),
            ("L", by("eero_eero_provides_wifi"), "Wi-Fi", col_bool()),
            ("M", by("eero_eero_radio_count"), "Radios", None),
            ("N", f"count by (eero_id) (eero_eero_band_supported{{{NE}}} == 1)", "Bands", None),
            (
                "O",
                by("eero_eero_update_available"),
                "Update",
                col_bool("available", "current", "warn"),
            ),
            ("P", by("eero_eero_led_on"), "LED", col_bool("on", "off")),
            ("Q", by("eero_eero_nightlight_enabled"), "Nightlight", col_bool("on", "off")),
            (
                "R",
                by("eero_eero_nightlight_schedule_enabled"),
                "Nightlight schedule",
                col_bool("on", "off"),
            ),
            ("S", by("eero_eero_power_saving_active"), "Power saving", col_bool("active", "off")),
            (
                "T",
                f"{by('eero_eero_last_reboot_timestamp_seconds')} * 1000",
                "Last reboot",
                col_unit(ts),
            ),
            ("U", f"{by('eero_eero_joined_timestamp_seconds')} * 1000", "Joined", col_unit(ts)),
        ],
        {
            "location": "Eero",
            "model": "Model",
            "os_version": "OS",
            "ip_address": "IP",
            "role": "Role",
            "connection_type": "Backhaul",
            "source": "Power",
            "version": "Firmware",
        },
        sort_by="Eero",
        description="Role comes from the RF tier; nightlight fields populate on Beacons only.",
    )


def _ethernet_table() -> Panel:
    pk = "eero_id, port_number"
    return table(
        "Ethernet ports & LLDP neighbours",
        [
            (
                "A",
                f"max by ({pk}, location, port_name) (eero_ethernet_port_carrier{{{NE}}})",
                "Link",
                col_bool("up", "down", "health"),
            ),
            (
                "B",
                f"max by ({pk}) (eero_ethernet_port_speed_mbps{{{NE}}})",
                "Speed",
                col_unit("Mbits"),
            ),
            ("C", f"max by ({pk}) (eero_ethernet_port_is_wan{{{NE}}})", "WAN", col_bool()),
            ("D", f"max by ({pk}) (eero_ethernet_port_is_lte{{{NE}}})", "LTE", col_bool()),
            ("E", f"max by ({pk}) (eero_ethernet_port_info{{{NE}}})", "PI", col_hidden()),
            (
                "F",
                f"max by ({pk}, neighbor_type, neighbor_port) "
                f"(eero_ethernet_port_neighbor_info{{{NE}}})",
                "NB",
                col_hidden(),
            ),
        ],
        {
            "location": "Eero",
            "port_number": "Port",
            "port_name": "Name",
            "neighbor_type": "LLDP neighbour",
            "neighbor_port": "Neighbour port",
        },
        sort_by="Eero",
        description="Mesh wiring topology: link state per port plus LLDP neighbour reports.",
    )


def eero_mesh(g: Grid) -> None:
    def per_eero(metric: str) -> str:
        return f"max by (location) ({metric}{{{NE}}})"

    g.line(
        (
            state_timeline(
                "Eero status",
                [(per_eero("eero_eero_status"), "{{location}}")],
                bool_map("online", "offline", "health"),
            ),
            HALF,
        ),
        (
            state_timeline(
                "Heartbeat",
                [(per_eero("eero_eero_heartbeat_ok"), "{{location}}")],
                bool_map("ok", "failing", "health"),
            ),
            HALF,
        ),
    )
    g.line(
        *(
            (
                timeseries(
                    title,
                    [(f"sum by (location) ({metric}{{{NE}}})", "{{location}}")],
                    stack=True,
                ),
                THIRD,
            )
            for title, metric in (
                ("Clients per eero", "eero_eero_connected_clients_count"),
                ("Wireless clients per eero", "eero_eero_connected_wireless_clients_count"),
                ("Wired clients per eero", "eero_eero_connected_wired_clients_count"),
            )
        )
    )
    g.line(
        (
            timeseries(
                "Uptime since last reboot",
                [(per_eero("eero_eero_uptime_seconds"), "{{location}}")],
                "s",
            ),
            HALF,
        ),
        (
            timeseries(
                "Mesh quality",
                [(per_eero("eero_eero_mesh_quality_bars"), "{{location}}")],
                step=True,
                min_=0,
                max_=5,
                decimals=0,
                description="Backhaul quality in bars (0-5).",
            ),
            HALF,
        ),
    )
    g.line(
        (
            timeseries(
                "Time since last heartbeat",
                [
                    (
                        f"time() - {per_eero('eero_eero_last_heartbeat_timestamp_seconds')}",
                        "{{location}}",
                    )
                ],
                "s",
            ),
            HALF,
        ),
        (
            timeseries(
                "LED & nightlight brightness",
                [
                    (per_eero("eero_eero_led_brightness"), "{{location}} LED"),
                    (per_eero("eero_eero_nightlight_brightness"), "{{location}} nightlight"),
                ],
                "percent",
                step=True,
                min_=0,
                max_=100,
                description="Nightlight series exist on Beacon nodes only.",
            ),
            HALF,
        ),
    )
    port = "{{location}} port {{port_number}}"
    g.line(
        (
            timeseries(
                "Ethernet link speed",
                [
                    (
                        f"max by (location, port_number) (eero_ethernet_port_speed_mbps{{{NE}}})",
                        port,
                    )
                ],
                "Mbits",
                step=True,
            ),
            HALF,
        ),
        (
            state_timeline(
                "Ethernet link state",
                [(f"max by (location, port_number) (eero_ethernet_port_carrier{{{NE}}})", port)],
                bool_map("up", "down", "health"),
            ),
            HALF,
        ),
    )
    g.line((_eero_inventory(), FULL_TABLE))
    g.line((_ethernet_table(), FULL_TABLE))


# --- RF & radios ------------------------------------------------------------

LB = "{{location}} {{band}}"


def rf(g: Grid) -> None:
    def radio(metric: str) -> str:
        return f"max by (location, band) ({metric}{{{NE}}})"

    def rfq(metric: str) -> str:
        return f"max by (location, band) ({with_location(f'{metric}{{{NE}}}')})"

    g.line(
        (
            timeseries(
                "Radio channel utilisation",
                [(radio("eero_eero_radio_channel_utilization_percent"), LB)],
                "percent",
                min_=0,
                max_=100,
                thresholds=UTIL_TH,
            ),
            HALF,
        ),
        (
            timeseries(
                "Wireless clients per radio",
                [(f"sum by (location, band) (eero_eero_radio_client_count{{{NE}}})", LB)],
                stack=True,
            ),
            HALF,
        ),
    )
    g.line(
        (timeseries("Channel", [(radio("eero_eero_radio_channel"), LB)], "none", step=True), THIRD),
        (
            timeseries(
                "Channel width",
                [(radio("eero_eero_radio_channel_width_mhz"), LB)],
                "MHz",
                step=True,
            ),
            THIRD,
        ),
        (
            timeseries("Tx power", [(radio("eero_eero_radio_tx_power_dbm"), LB)], "dBm", step=True),
            THIRD,
        ),
    )
    g.line(
        (
            timeseries(
                "Average channel utilisation (window)",
                [(rfq("eero_channel_utilization_avg_percent"), LB)],
                "percent",
                min_=0,
                max_=100,
                thresholds=UTIL_TH,
            ),
            HALF,
        ),
        (
            timeseries(
                "p99 channel utilisation (window)",
                [(rfq("eero_channel_utilization_p99_percent"), LB)],
                "percent",
                min_=0,
                max_=100,
                thresholds=UTIL_TH,
            ),
            HALF,
        ),
    )
    g.line(
        (
            timeseries(
                "Busy airtime (latest sample)", [(rfq("eero_channel_busy_last"), LB)], "percent"
            ),
            THIRD,
        ),
        (
            timeseries(
                "Own vs other-BSS airtime",
                [
                    (rfq("eero_channel_rx_tx_last"), "{{location}} {{band}} own"),
                    (rfq("eero_channel_rx_other_last"), "{{location}} {{band}} other"),
                ],
                "percent",
                description="Latest 'rx_tx' (own traffic) and 'rx_other' (neighbour BSS) samples.",
            ),
            THIRD,
        ),
        (
            timeseries(
                "Noise floor (latest sample)", [(rfq("eero_channel_noise_last"), LB)], "dBm"
            ),
            THIRD,
        ),
    )
    g.line(
        (
            timeseries(
                "Minutes over busy threshold",
                [(rfq("eero_channel_busy_minutes"), LB)],
                "m",
                bars=True,
                stack=True,
            ),
            THIRD,
        ),
        (
            timeseries(
                "ACS channel changes (window)",
                [(rfq("eero_channel_acs_events_total"), LB)],
                bars=True,
                stack=True,
            ),
            THIRD,
        ),
        (
            bargauge(
                "Peak utilisation (window)",
                [(rfq("eero_channel_utilization_max_percent"), LB)],
                "percent",
                max_=100,
                thresholds=UTIL_TH,
            ),
            THIRD,
        ),
    )
    g.line((_channel_plan(), FULL))


# (band regex, column label, header). The API reports e.g. band_2_4GHz / band_5GHz_low;
# the regexes also accept the short 2.4GHz / 5GHz spellings.
CHANNEL_PLAN_BANDS = [
    (".*2[._]4_?GHz", "b24", "2.4 GHz"),
    ("(band_)?5_?GHz(_full)?", "b5", "5 GHz"),
    (".*5_?GHz_low", "b5l", "5 GHz low"),
    (".*5_?GHz_high", "b5h", "5 GHz high"),
    (".*6_?GHz", "b6", "6 GHz"),
]


def _channel_plan() -> Panel:
    """Eero x band matrix; each cell reads "ch 36 · 80 MHz"."""

    def cell(band: str, col: str) -> str:
        radios = (
            "max by (network_id, eero_id, channel, channel_bandwidth) "
            f'(eero_channel_info_info{{{NE}, band=~"{band}"}})'
        )
        joined = f'label_join({radios}, "{col}", " · ", "channel", "channel_bandwidth")'
        labelled = relabel(joined, col, [("ch $1", col, "(.*)")])
        return with_location(f"group by (network_id, eero_id, {col}) ({labelled})")

    return table(
        "Channel plan",
        [
            # The eero roster goes first: merge keeps the first frame's column order.
            (
                "E",
                f"group by (network_id, eero_id, location) (eero_eero_status{{{NE}}})",
                "roster",
                col_hidden(),
            ),
            *(
                (f"C{i}", cell(band, col), f"v{i}", col_hidden())
                for i, (band, col, _) in enumerate(CHANNEL_PLAN_BANDS)
            ),
        ],
        {"location": "Eero", **{col: name for _, col, name in CHANNEL_PLAN_BANDS}},
        sort_by="Eero",
        description="Current channel and bandwidth per radio (RF tier). Eeros split 5 GHz "
        "into low/high radios or use a single full-band radio, depending on the model.",
    )


# --- Devices ----------------------------------------------------------------


def _device_inventory() -> Panel:
    def dev(metric: str) -> str:
        return f"max by (device_id) ({metric}{{{N}}})"

    return table(
        "Device inventory",
        [
            (
                "A",
                "topk by (device_id) (1, max by (device_id, name, manufacturer, device_type, "
                f"connection_type, source_eero) (eero_device_connected{{{N}}}))",
                "Info",
                col_hidden(),
            ),
            (
                "A2",
                f"topk by (device_id) (1, max by (device_id, mac) (eero_device_info{{{N}}}))",
                "MacInfo",
                col_hidden(),
            ),
            (
                "B",
                dev("eero_device_connected"),
                "Connected",
                col_bool("yes", "no", "health"),
            ),
            (
                "C",
                dev("eero_device_signal_strength_dbm"),
                "Signal",
                {
                    "unit": "dBm",
                    "color": {"mode": "thresholds"},
                    "thresholds": steps(SIGNAL_TH),
                    "custom.cellOptions": {"type": "color-text"},
                },
            ),
            ("D", dev("eero_device_connection_score"), "Score", col_unit("percentunit")),
            ("E", dev("eero_device_connection_score_bars"), "Bars", None),
            ("F", dev("eero_device_frequency_mhz"), "Frequency", col_unit("MHz")),
            ("G", dev("eero_device_channel"), "Channel", None),
            ("H", dev("eero_device_rx_bitrate_mbps"), "Rx", col_unit("Mbits")),
            ("I", dev("eero_device_tx_bitrate_mbps"), "Tx", col_unit("Mbits")),
            ("J", dev("eero_device_wifi_generation"), "Wi-Fi", None),
            (
                "K",
                "topk by (device_id) (1, max by (device_id, subnet_kind) "
                f"(eero_device_subnet_kind_info{{{N}}}))",
                "SK",
                col_hidden(),
            ),
            (
                "L",
                f"{dev('eero_device_last_active_timestamp_seconds')} * 1000",
                "Last active",
                col_unit("dateTimeFromNow"),
            ),
            (
                "M",
                f"{dev('eero_device_first_seen_timestamp_seconds')} * 1000",
                "First seen",
                col_unit("dateTimeFromNow"),
            ),
            ("N", dev("eero_device_packet_stats_rx_packets"), "Rx packets", col_unit("short")),
            ("O", dev("eero_device_packet_stats_tx_packets"), "Tx packets", col_unit("short")),
            ("P", dev("eero_device_packet_stats_rx_drops"), "Rx drops", col_unit("short")),
            ("Q", dev("eero_device_packet_stats_tx_retries"), "Tx retries", col_unit("short")),
        ],
        {
            "name": "Device",
            "mac": "MAC",
            "manufacturer": "Manufacturer",
            "device_type": "Type",
            "connection_type": "Connection",
            "source_eero": "Via eero",
            "subnet_kind": "Subnet",
        },
        sort_by="Device",
        description="One row per device_id (stale label sets collapsed).",
    )


def devices(g: Grid) -> None:
    freq = f"({per_device('eero_device_frequency_mhz')} and on (network_id, device_id) {CONNECTED})"
    wired = (
        f"({per_device('eero_device_wireless')} == 0) and on (network_id, device_id) {CONNECTED}"
    )
    links = [
        (f"count({wired}) or on () vector(0)", "Wired"),
        (f"count(({freq} > 0) < 3000) or on () vector(0)", "2.4 GHz"),
        (f"count(({freq} >= 3000) < 5925) or on () vector(0)", "5 GHz"),
        (f"count({freq} >= 5925) or on () vector(0)", "6 GHz"),
    ]
    manufacturers = (
        "topk(10, count by (manufacturer) "
        f"(topk by (network_id, device_id) (1, eero_device_connected{{{N}}}) == 1))"
    )
    g.line(
        (
            donut(
                "Wireless clients by band",
                [(f"sum by (band) (eero_eero_radio_client_count{{{N}}})", "{{band}}")],
            ),
            THIRD,
        ),
        (donut("Connected devices by link", links), THIRD),
        (bargauge("Top manufacturers (connected)", [(manufacturers, "{{manufacturer}}")]), THIRD),
    )
    g.line(
        (
            timeseries(
                "Device flags",
                [
                    (device_count("eero_device_wireless"), "Wireless"),
                    (device_count("eero_device_connected_to_gateway"), "On gateway"),
                    (device_count("eero_device_is_guest"), "Guest"),
                    (device_count("eero_device_private"), "Private MAC"),
                    (device_count("eero_device_paused"), "Paused"),
                    (device_count("eero_device_blocked"), "Blocked"),
                ],
                step=True,
                description="Distinct known devices per flag (deduplicated by device_id).",
            ),
            HALF,
        ),
        (
            histogram(
                "Signal distribution (connected)",
                f"{per_device('eero_device_signal_strength_dbm')} "
                f"and on (network_id, device_id) {CONNECTED}",
                "dBm",
                5,
                description="Current signal of each connected wireless device, 5 dB buckets.",
            ),
            HALF,
        ),
    )
    g.line(
        (
            timeseries(
                "Weakest signals (bottom 10)",
                [
                    (
                        f"bottomk(10, {connected_device('eero_device_signal_strength_dbm')})",
                        "{{name}}",
                    )
                ],
                "dBm",
                thresholds=SIGNAL_TH,
            ),
            HALF,
        ),
        (
            timeseries(
                "Lowest connection scores (bottom 10)",
                [(f"bottomk(10, {connected_device('eero_device_connection_score')})", "{{name}}")],
                "percentunit",
                min_=0,
                max_=1,
            ),
            HALF,
        ),
    )
    g.line(
        *(
            (
                timeseries(
                    f"{title} bitrate (top 10)",
                    [(f"topk(10, {connected_device(metric)})", "{{name}}")],
                    "Mbits",
                ),
                HALF,
            )
            for title, metric in (
                ("Receive", "eero_device_rx_bitrate_mbps"),
                ("Transmit", "eero_device_tx_bitrate_mbps"),
            )
        )
    )
    packets = with_device_name(per_device("eero_device_packet_stats_total_packets"))
    g.line(
        (
            timeseries(
                "MCS index (top 5 rx / tx)",
                [
                    (f"topk(5, {connected_device('eero_device_rx_mcs')})", "{{name}} rx"),
                    (f"topk(5, {connected_device('eero_device_tx_mcs')})", "{{name}} tx"),
                ],
                step=True,
            ),
            THIRD,
        ),
        (
            timeseries(
                "Spatial streams (top 5 rx / tx)",
                [
                    (f"topk(5, {connected_device('eero_device_rx_nss')})", "{{name}} rx"),
                    (f"topk(5, {connected_device('eero_device_tx_nss')})", "{{name}} tx"),
                ],
                step=True,
            ),
            THIRD,
        ),
        (
            timeseries(
                "Lifetime packets (top 10)",
                [(f"topk(10, {packets})", "{{name}}")],
                description="Lifetime counters reported by the API as gauges.",
            ),
            THIRD,
        ),
    )
    g.line(
        *(
            (
                timeseries(
                    f"{title} (top 10)",
                    [(f"topk(10, {with_device_name(per_device(metric))})", "{{name}}")],
                    "ppm",
                ),
                THIRD,
            )
            for title, metric in (
                ("Tx retransmit rate", "eero_device_packet_stats_tx_retransmit_ppm"),
                ("Tx failure rate", "eero_device_packet_stats_tx_fail_ppm"),
                ("Rx drop rate", "eero_device_packet_stats_rx_drop_ppm"),
            )
        )
    )
    g.line((_device_inventory(), FULL_TABLE))


# --- Data usage -------------------------------------------------------------

# Breakdown metrics (per eero / device / profile / unprofiled) are only
# published for the API's current window (period="current"); only the
# network-level series carries day/week/month.
CUR = f'{N}, period="current"'


def data_usage(g: Grid) -> None:
    per = f'{N}, period="$period"'
    top_devices = with_device_name(
        "sum by (network_id, device_id) (max by (network_id, device_id, direction) "
        f"(eero_device_data_usage_bytes{{{CUR}}}))"
    )
    g.line(
        (
            timeseries(
                "Network usage — $period",
                [(f"sum by (direction) (eero_network_data_usage_bytes{{{per}}})", "{{direction}}")],
                "bytes",
                description="Running total for the selected calendar period.",
            ),
            HALF,
        ),
        (
            timeseries(
                "Network usage — trailing window",
                [
                    (f"sum(eero_data_usage_download_bytes{{{N}}})", "download"),
                    (f"sum(eero_data_usage_upload_bytes{{{N}}})", "upload"),
                ],
                "bytes",
            ),
            HALF,
        ),
    )
    g.line(
        (
            timeseries(
                "Download by calendar period",
                [
                    (
                        "sum by (period) "
                        f'(eero_network_data_usage_bytes{{{N}, direction="download"}})',
                        "{{period}}",
                    )
                ],
                "bytes",
            ),
            HALF,
        ),
        (
            timeseries(
                "Unprofiled devices — current window",
                [
                    (
                        f"sum by (direction) (eero_unprofiled_data_usage_bytes{{{CUR}}})",
                        "{{direction}}",
                    )
                ],
                "bytes",
                description="Breakdown metrics are only published for the current window.",
            ),
            HALF,
        ),
    )
    g.line(
        (
            bargauge(
                "Top 10 devices — current window",
                [(f"topk(10, {top_devices})", "{{name}}")],
                "bytes",
            ),
            THIRD,
        ),
        (
            bargauge(
                "Per eero — current window",
                [(f"sum by (location) (eero_eero_data_usage_bytes{{{CUR}}})", "{{location}}")],
                "bytes",
            ),
            THIRD,
        ),
        (
            bargauge(
                "Per profile — current window",
                [
                    (
                        "sum by (name) ("
                        + with_profile_name(f"eero_profile_data_usage_bytes{{{CUR}}}")
                        + ")",
                        "{{name}}",
                    )
                ],
                "bytes",
            ),
            THIRD,
        ),
    )
    g.line(
        *(
            (
                bargauge(
                    f"Top 10 devices {d} — trailing window",
                    [(f"topk(10, {with_device_name(per_device(m))})", "{{name}}")],
                    "bytes",
                ),
                HALF,
            )
            for d, m in (
                ("download", "eero_device_data_usage_download_bytes"),
                ("upload", "eero_device_data_usage_upload_bytes"),
            )
        )
    )


# --- Profiles & insights ----------------------------------------------------


def profiles_insights(g: Grid) -> None:
    def by_profile(metric: str) -> str:
        return f"max by (name) ({metric}{{{N}}})"

    g.line(
        (
            state_timeline(
                "Profile paused",
                [(by_profile("eero_profile_paused"), "{{name}}")],
                bool_map("paused", "active", "warn"),
            ),
            HALF,
        ),
        (
            timeseries(
                "Connected devices per profile",
                [(by_profile("eero_profile_connected_devices_count"), "{{name}}")],
                stack=True,
            ),
            HALF,
        ),
    )
    g.line(
        (
            bargauge(
                "Devices per profile", [(by_profile("eero_profile_devices_count"), "{{name}}")]
            ),
            THIRD,
        ),
        (
            bargauge(
                "Blocked apps & schedules",
                [
                    (by_profile("eero_profile_blocked_applications_count"), "{{name}} apps"),
                    (by_profile("eero_profile_schedules_count"), "{{name}} schedules"),
                ],
            ),
            THIRD,
        ),
        (
            state_timeline(
                "Content filters",
                [(by_profile("eero_profile_content_filters_set"), "{{name}}")],
                bool_map("set", "none"),
            ),
            THIRD,
        ),
    )
    g.line(
        (
            timeseries(
                "Insight events (window)",
                [
                    (f"sum(eero_insights_inspected_total{{{N}}})", "inspected"),
                    (f"sum(eero_insights_blocked_total{{{N}}})", "threats blocked"),
                    (f"sum(eero_insights_adblock_total{{{N}}})", "ads blocked"),
                ],
            ),
            FULL,
        )
    )
    g.line(
        *(
            (bargauge(title, [(f"sum by (category) ({m}{{{N}}})", "{{category}}")]), THIRD)
            for title, m in (
                ("Threats blocked by category", "eero_insights_blocked_total"),
                ("Ads blocked by category", "eero_insights_adblock_total"),
                ("Inspected by category", "eero_insights_inspected_total"),
            )
        )
    )
    g.line(
        (
            timeseries(
                "Profile insight events (top 10)",
                [
                    (
                        f"topk(10, {with_profile_name(f'eero_profile_insights_total{{{N}}}')})",
                        "{{name}} {{type}}",
                    )
                ],
            ),
            HALF,
        ),
        (
            bargauge(
                "Devices with insights per profile",
                [
                    (
                        "sum by (name, type) ("
                        + with_profile_name(f"eero_profile_insights_devices{{{N}}}")
                        + ")",
                        "{{name}} {{type}}",
                    )
                ],
            ),
            HALF,
        ),
    )


# --- Security & account -----------------------------------------------------


def flag_rows(metric: str, kind: str, item_label: str) -> str:
    """Relabel a boolean-per-item metric to (kind, item) so unlike flags share one table."""
    return (
        f"label_replace(label_replace(max by (network_id, {item_label}) ({metric}{{{N}}}), "
        f'"item", "$1", "{item_label}", "(.*)"), "kind", "{kind}", "", "")'
    )


def security_account(g: Grid) -> None:
    subnet_flags = [
        ("enabled", "eero_subnet_enabled"),
        ("WAN access", "eero_subnet_wan_access"),
        ("LAN access", "eero_subnet_lan_access"),
        ("open network", "eero_subnet_open_network"),
        ("NAT port randomisation", "eero_subnet_nat_port_randomization"),
        ("IGMP snooping", "eero_subnet_igmp_snooping_enabled"),
    ]
    per_eero_permission = (
        "label_replace(label_join(max by (network_id, eero_id, verb) "
        f'(eero_network_per_eero_permission{{{N}}}), "item", " eero ", "verb", "eero_id"), '
        '"kind", "Per-eero permission", "", "")'
    )
    union = " or ".join(
        [
            flag_rows("eero_network_capability", "Capability", "capability"),
            flag_rows("eero_network_feature_entitled", "Entitlement", "feature"),
            flag_rows("eero_network_permission", "Read permission", "capability"),
            flag_rows("eero_network_notification_enabled", "Notification", "event"),
            per_eero_permission,
        ]
        + [flag_rows(m, f"Subnet {t}", "subnet_kind") for t, m in subnet_flags]
    )
    g.line(
        (
            state_timeline(
                "Subscription & alerts",
                [
                    (f"max(eero_network_premium_enabled{{{N}}})", "Eero Plus"),
                    (f"eero_account_entitlement_state{{{N}}}", "Entitlement {{state}}"),
                    (f"eero_account_entitlement_product_info{{{N}}}", "Product {{type}}"),
                    (f"max(eero_network_notifications_unread{{{N}}})", "Unread notifications"),
                ],
                bool_map("yes", "no"),
                overrides=[
                    override("Unread notifications", mappings=bool_map("UNREAD", "none", "warn"))
                ],
            ),
            HALF_TABLE,
        ),
        (
            table(
                "Capabilities, entitlements, permissions & subnets",
                [("A", f"sum by (kind, item) ({union})", "Value", col_bool("yes", "no"))],
                {"kind": "Kind", "item": "Item"},
                sort_by="Kind",
                description="Static configuration flags, one row per item.",
            ),
            HALF_TABLE,
        ),
    )
    g.line(
        (
            timeseries(
                "Members & networks",
                [
                    (f"sum(eero_network_members_count{{{N}}})", "Members"),
                    ("sum(eero_account_networks_count)", "Networks in account"),
                ],
                step=True,
            ),
            THIRD,
        ),
        (
            timeseries(
                "Guest network clients",
                [(f"sum(eero_guest_network_connected_clients{{{N}}})", "Guest clients")],
                step=True,
            ),
            THIRD,
        ),
        (
            state_timeline(
                "Open (unencrypted) subnets",
                [(f"max by (subnet_kind) (eero_subnet_open_network{{{N}}})", "{{subnet_kind}}")],
                bool_map("OPEN", "encrypted", "warn"),
            ),
            THIRD,
        ),
    )


# --- Exporter health --------------------------------------------------------

API_STATUS_MEANING = {
    "success": ("green", "request completed"),
    "error": ("red", "unclassified API error"),
    "auth": ("red", "session invalid or expired; re-run `eero-exporter login`"),
    "transport": ("orange", "network / timeout failure reaching the API"),
    "rate_limited": ("orange", "API rate limit hit; collection backs off"),
    "validation": ("orange", "request rejected as invalid (SDK or API 400)"),
    "access_denied": ("purple", "account lacks permission for this resource"),
    "not_found": ("blue", "resource absent (expected for unprovisioned features)"),
    "premium_required": ("blue", "needs an Eero Plus subscription (expected state)"),
    "feature_unavailable": ("blue", "feature not available on this network (expected state)"),
}
assert set(API_STATUS_MEANING) == set(API_STATUS_VALUES)


def exporter(g: Grid) -> None:
    status_overrides = [
        override(s, color={"mode": "fixed", "fixedColor": c})
        for s, (c, _) in API_STATUS_MEANING.items()
    ]
    legend = "| status | meaning |\n|---|---|\n" + "\n".join(
        f"| `{s}` | {m} |" for s, (_, m) in API_STATUS_MEANING.items()
    )
    g.line(
        (
            timeseries(
                "API requests by status",
                [("sum by (status) (rate(eero_exporter_api_requests_total[5m]))", "{{status}}")],
                "reqps",
                stack=True,
                overrides=status_overrides,
            ),
            HALF,
        ),
        (
            text_panel(
                "API status legend",
                "Closed `status` enum of `eero_exporter_api_requests_total`. "
                'Sum failures with `status!="success"`.\n\n' + legend,
            ),
            HALF,
        ),
    )
    g.line(
        (
            timeseries(
                "Collection duration vs interval",
                [
                    ("eero_exporter_scrape_duration_seconds", "duration"),
                    ("eero_exporter_collection_interval_seconds", "interval"),
                ],
                "s",
            ),
            THIRD,
        ),
        (
            timeseries(
                "Time since last collection",
                [("time() - eero_exporter_last_collection_timestamp_seconds", "age")],
                "s",
                thresholds=[("green", None), ("orange", 300), ("red", 900)],
            ),
            THIRD,
        ),
        (
            timeseries(
                "API requests per cycle",
                [("eero_exporter_api_requests_last_cycle", "requests")],
                step=True,
            ),
            THIRD,
        ),
    )
    g.line(
        (
            timeseries(
                "Scrape errors by type",
                [
                    (
                        "sum by (error_type) (increase(eero_exporter_scrape_errors_total[5m]))",
                        "{{error_type}}",
                    )
                ],
                bars=True,
                stack=True,
                description="Empty while the exporter has never failed a collection.",
            ),
            HALF,
        ),
        (
            timeseries(
                "API requests by endpoint (top 10)",
                [
                    (
                        "topk(10, sum by (endpoint) (label_replace("
                        "rate(eero_exporter_api_requests_total[5m]), "
                        '"endpoint", "$1", "exported_endpoint", "(.+)")))',
                        "{{endpoint}}",
                    )
                ],
                "reqps",
                description=(
                    "Under the Prometheus Operator the exporter's `endpoint` label is renamed "
                    "`exported_endpoint` (it collides with the target label); both are handled."
                ),
            ),
            HALF,
        ),
    )


# --- Optional tiers (collapsed) --------------------------------------------


def opt_per_profile(g: Grid) -> None:
    q = f"max by (name) ({with_profile_name(f'eero_profile_dns_policy_applications_count{{{N}}}')})"
    g.line(
        (bargauge("DNS-policy applications per profile", [(q, "{{name}}")]), HALF),
        (timeseries("DNS-policy applications over time", [(q, "{{name}}")], step=True), HALF),
    )


def opt_per_device(g: Grid) -> None:
    q = with_device_name(
        f"sum by (network_id, device_id, type) (eero_device_insights_total{{{N}}})"
    )
    g.line(
        (bargauge("Top 10 device insights", [(f"topk(10, {q})", "{{name}} {{type}}")]), HALF),
        (
            timeseries(
                "Device insights by type",
                [(f"sum by (type) (eero_device_insights_total{{{N}}})", "{{type}}")],
            ),
            HALF,
        ),
    )


def opt_per_eero(g: Grid) -> None:
    def loc(metric: str) -> str:
        return f"max by (location) ({with_location(f'{metric}{{{NE}}}')})"

    g.line(
        (
            timeseries(
                "Wireless connections per eero",
                [(loc("eero_eero_connections_count"), "{{location}}")],
                stack=True,
            ),
            HALF,
        ),
        (
            state_timeline(
                "OUI check",
                [
                    (loc("eero_eero_ouicheck_can_add"), "{{location}} can add"),
                    (loc("eero_eero_ouicheck_must_update"), "{{location}} must update"),
                ],
                bool_map("yes", "no"),
            ),
            HALF,
        ),
    )


def opt_unverified(g: Grid) -> None:
    g.line(
        (
            timeseries(
                "Routing table sizes",
                [
                    (f"sum({m}{{{N}}})", t)
                    for t, m in (
                        ("devices", "eero_network_routing_devices_count"),
                        ("reservations", "eero_network_routing_reservations_count"),
                        ("forwards", "eero_network_routing_forwards_count"),
                        ("pinholes", "eero_network_routing_pinholes_count"),
                    )
                ],
                step=True,
            ),
            HALF,
        ),
        (
            timeseries(
                "Backup, cellular & schedules",
                [
                    (f"sum({m}{{{N}}})", t)
                    for t, m in (
                        ("backup access points", "eero_backup_access_points_count"),
                        ("cellular usage items", "eero_cellular_backup_usage_items_count"),
                        ("cellular outages", "eero_cellular_backup_outages_count"),
                        ("speed tests in window", "eero_speed_tests_total"),
                        ("power-saving schedules", "eero_network_power_saving_schedules_count"),
                    )
                ],
                step=True,
            ),
            HALF,
        ),
    )
    g.line(
        (
            state_timeline(
                "Unverified flags",
                [
                    (f"max(eero_network_scan_conflicting_ssid{{{N}}})", "Conflicting SSID nearby"),
                    (f"max(eero_network_multistaticip_enabled{{{N}}})", "Multi-static IP"),
                    (f"max(eero_network_ac_compat{{{N}}})", "AC compatibility"),
                ],
                bool_map("yes", "no"),
                overrides=[
                    override("Conflicting SSID nearby", mappings=bool_map("DETECTED", "no", "warn"))
                ],
            ),
            HALF,
        ),
        (
            state_timeline(
                "Backup access points",
                [
                    (
                        f"max by (index) (eero_backup_access_point_enabled{{{N}}})",
                        "AP {{index}} enabled",
                    ),
                    (
                        "max by (index, status) "
                        f"(eero_backup_access_point_connectivity_info_info{{{N}}})",
                        "AP {{index}} {{status}}",
                    ),
                ],
                bool_map("yes", "no"),
            ),
            HALF,
        ),
    )


section("Overview", overview)
section("Network & WAN", network_wan)
section("Eero mesh health", eero_mesh)
section("RF & radios", rf, collapsed=True)
section("Devices", devices, collapsed=True)
section("Data usage", data_usage, collapsed=True)
section("Profiles & insights", profiles_insights, collapsed=True)
section("Security & account", security_account, collapsed=True)
section("Exporter health", exporter, collapsed=True)
section("Per-profile (--include-per-profile)", opt_per_profile, collapsed=True)
section("Per-device (--include-per-device)", opt_per_device, collapsed=True)
section("Per-eero (--include-per-eero)", opt_per_eero, collapsed=True)
section("Unverified shapes (--include-unverified)", opt_unverified, collapsed=True)


# ---------------------------------------------------------------------------
# Dashboard envelope
# ---------------------------------------------------------------------------

PANEL_TYPES = {
    "bargauge": "Bar gauge",
    "histogram": "Histogram",
    "piechart": "Pie chart",
    "stat": "Stat",
    "state-timeline": "State timeline",
    "table": "Table",
    "text": "Text",
    "timeseries": "Time series",
}

dashboard = {
    "__inputs": [],
    "__elements": {},
    "__requires": [
        {"type": "grafana", "id": "grafana", "name": "Grafana", "version": "11.5.0"},
        {"type": "datasource", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"},
    ]
    + [{"type": "panel", "id": k, "name": v, "version": ""} for k, v in PANEL_TYPES.items()],
    "annotations": {
        "list": [
            {
                "builtIn": 1,
                "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                "enable": True,
                "hide": True,
                "iconColor": "rgba(0, 211, 255, 1)",
                "name": "Annotations & Alerts",
                "type": "dashboard",
            }
        ]
    },
    "description": (
        "Eero mesh network monitoring via eero-prometheus-exporter 4.x. Graph-first: every "
        "exported metric family has a panel; secondary rows start collapsed and optional "
        "tiers live in collapsed rows named after the flag that enables them."
    ),
    "editable": True,
    "fiscalYearStartMonth": 0,
    "graphTooltip": 1,
    "id": None,
    "links": [],
    "liveNow": False,
    "panels": panels,
    "preload": False,
    "refresh": "1m",
    "schemaVersion": 42,
    "tags": ["eero", "mesh", "wifi", "network", "prometheus"],
    "templating": {
        "list": [
            {
                "current": {},
                "includeAll": False,
                "label": "Data source",
                "name": "datasource",
                "options": [],
                "query": "prometheus",
                "refresh": 1,
                "regex": "",
                "type": "datasource",
            },
            {
                "allValue": ".*",
                "current": {"text": "All", "value": "$__all"},
                "datasource": DS,
                "definition": "label_values(eero_network_status, network_id)",
                "includeAll": True,
                "label": "Network",
                "multi": True,
                "name": "network_id",
                "options": [],
                "query": {
                    "query": "label_values(eero_network_status, network_id)",
                    "refId": "StandardVariableQuery",
                },
                "refresh": 2,
                "regex": "",
                "sort": 1,
                "type": "query",
            },
            {
                "allValue": ".*",
                "current": {"text": "All", "value": "$__all"},
                "datasource": DS,
                "definition": 'label_values(eero_eero_status{network_id=~"$network_id"}, eero_id)',
                "includeAll": True,
                "label": "Eero",
                "multi": True,
                "name": "eero_id",
                "options": [],
                "query": {
                    "query": 'label_values(eero_eero_status{network_id=~"$network_id"}, eero_id)',
                    "refId": "StandardVariableQuery",
                },
                "refresh": 2,
                "regex": "",
                "sort": 1,
                "type": "query",
            },
            {
                "current": {"text": "day", "value": "day"},
                "includeAll": False,
                "label": "Usage period",
                "name": "period",
                "options": [
                    {"selected": True, "text": "day", "value": "day"},
                    {"selected": False, "text": "week", "value": "week"},
                    {"selected": False, "text": "month", "value": "month"},
                ],
                "query": "day,week,month",
                "type": "custom",
            },
        ]
    },
    "time": {"from": "now-6h", "to": "now"},
    "timepicker": {},
    "timezone": "",
    "title": "Eero Mesh Network",
    "uid": "eero-mesh-network",
    "version": 46,
    "weekStart": "",
}

# ---------------------------------------------------------------------------
# Coverage check
# ---------------------------------------------------------------------------


def all_panels(ps: list[Panel]) -> Iterator[Panel]:
    for p in ps:
        yield p
        yield from all_panels(p.get("panels", []))


used_types = {p["type"] for p in all_panels(panels)} - {"row"}
assert used_types <= set(PANEL_TYPES), used_types - set(PANEL_TYPES)
exprs = " ".join(t["expr"] for p in all_panels(panels) for t in p.get("targets", []))
missing = []
for m in describe_metrics():
    exposed = f"{m.name}_info" if m.type == "info" else m.name
    if not re.search(rf"\b{re.escape(exposed)}\b", exprs):
        missing.append(m.name)
removed_hits = [n for n in REMOVED_IN_4_0_0 if re.search(rf"\b{n}\b", json.dumps(dashboard))]
print(f"metrics referenced: {len(describe_metrics()) - len(missing)}/{len(describe_metrics())}")
print("missing:", missing)
print("removed names present:", removed_hits)
print("rows:", sum(1 for p in panels if p["type"] == "row"))
print("panels (non-row):", sum(1 for p in all_panels(panels) if p["type"] != "row"))

rendered = json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n"

if "--check" in sys.argv:
    committed = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    if committed != rendered:
        print(f"{OUT} is out of date -- run: uv run python scripts/gen_dashboard.py")
        sys.exit(1)
    print(f"{OUT} is up to date")
else:
    OUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUT}")
