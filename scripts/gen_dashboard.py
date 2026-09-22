"""Generate grafana/eero-dashboard.json for eero-prometheus-exporter 4.0.0.

Design system (dataviz skill): one visual language. Stat tiles for booleans /
enums with value mappings; timeseries (2px lines, no fill) for rates and
utilisation; bargauge (basic, single hue) for top-N; tables for per-item
detail. Status colours (green/red/orange) are reserved for meaning; neutral
"off" states use the mode-invariant muted ink #898781; nominal series use
Grafana's palette-classic (valid scheme) and single series use fixed blue.

Regenerating after a metrics change::

    uv run python scripts/gen_dashboard.py           # rewrite the dashboard
    uv run python scripts/gen_dashboard.py --check   # exit 1 if it would change

``tests/test_dashboard.py`` runs the ``--check`` mode, so CI fails when the
registry and the committed dashboard drift apart.
"""

from __future__ import annotations

import json
import re
import sys
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
OUT = REPO_ROOT / "grafana" / "eero-dashboard.json"

_next_id = 0


def nid() -> int:
    global _next_id
    _next_id += 1
    return _next_id


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


class Grid:
    """Packs panels left-to-right in 24 columns, wrapping to new lines."""

    def __init__(self, y: int = 0) -> None:
        self.y = y
        self.x = 0
        self.line_h = 0
        self.panels: list[dict[str, Any]] = []

    def newline(self) -> None:
        if self.x:
            self.y += self.line_h
        self.x = 0
        self.line_h = 0

    def add(self, panel: dict[str, Any], w: int, h: int) -> None:
        if self.x + w > 24:
            self.newline()
        panel["gridPos"] = {"h": h, "w": w, "x": self.x, "y": self.y}
        self.panels.append(panel)
        self.x += w
        self.line_h = max(self.line_h, h)
        if self.x == 24:
            self.newline()

    def end(self) -> int:
        self.newline()
        return self.y


# ---------------------------------------------------------------------------
# Panel builders
# ---------------------------------------------------------------------------


def target(expr: str, ref: str = "A", legend: str = "", table: bool = False) -> dict[str, Any]:
    t: dict[str, Any] = {"expr": expr, "refId": ref, "legendFormat": legend or "__auto"}
    if table:
        t["format"] = "table"
        t["instant"] = True
    return t


def base(title: str, ptype: str, unit: str, description: str = "") -> dict[str, Any]:
    p: dict[str, Any] = {
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


def _mapping(values: dict[str, tuple[str, str | None]]) -> dict[str, Any]:
    opts = {}
    for i, (k, (text, color)) in enumerate(values.items()):
        o: dict[str, Any] = {"index": i, "text": text}
        if color:
            o["color"] = color
        opts[k] = o
    return {"type": "value", "options": opts}


def bool_mapping(on: str, off: str, kind: str) -> list[dict[str, Any]]:
    """kind: health (1 good / 0 bad), toggle (1 accent / 0 neutral), warn (1 bad / 0 neutral)."""
    colors = {
        "health": ("green", "red"),
        "toggle": ("blue", NEUTRAL),
        "warn": ("orange", NEUTRAL),
        "warn_good": ("orange", "green"),
    }[kind]
    return [_mapping({"1": (on, colors[0]), "0": (off, colors[1])})]


def stat(
    title: str,
    expr: str,
    unit: str = "short",
    *,
    mappings: list[dict[str, Any]] | None = None,
    color_mode: str = "none",
    thresholds: list[tuple[str, float | None]] | None = None,
    decimals: int | None = None,
    description: str = "",
) -> dict[str, Any]:
    p = base(title, "stat", unit, description)
    d = p["fieldConfig"]["defaults"]
    d["color"] = {"mode": "thresholds"}
    steps = thresholds or [("blue", None)]
    d["thresholds"] = {
        "mode": "absolute",
        "steps": [{"color": c, "value": v} for c, v in steps],
    }
    if mappings:
        d["mappings"] = mappings
    if decimals is not None:
        d["decimals"] = decimals
    p["options"] = {
        "colorMode": color_mode,
        "graphMode": "none",
        "justifyMode": "center",
        "orientation": "auto",
        "textMode": "value",
        "wideLayout": True,
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
    }
    p["targets"] = [target(expr)]
    return p


def bool_stat(title: str, expr: str, on: str, off: str, kind: str = "toggle") -> dict[str, Any]:
    return stat(title, expr, "none", mappings=bool_mapping(on, off, kind), color_mode="value")


def ts_stat(title: str, expr: str) -> dict[str, Any]:
    return stat(title, f"({expr}) * 1000", "dateTimeAsIso")


def info_stat(title: str, expr: str, field: str, description: str = "") -> dict[str, Any]:
    """Show a label value (from an Info metric) as the stat text."""
    p = base(title, "stat", "none", description)
    p["fieldConfig"]["defaults"]["color"] = {"mode": "fixed", "fixedColor": "blue"}
    p["options"] = {
        "colorMode": "none",
        "graphMode": "none",
        "justifyMode": "center",
        "orientation": "auto",
        "textMode": "value",
        "wideLayout": True,
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": f"/^{field}$/", "values": False},
    }
    p["targets"] = [target(expr, table=True)]
    return p


def timeseries(
    title: str,
    targets: list[tuple[str, str]],
    unit: str = "short",
    *,
    stacked: bool = False,
    min_: float | None = None,
    max_: float | None = None,
    overrides: list[dict[str, Any]] | None = None,
    description: str = "",
) -> dict[str, Any]:
    p = base(title, "timeseries", unit, description)
    d = p["fieldConfig"]["defaults"]
    single = len(targets) == 1 and "{{" not in targets[0][1]
    d["color"] = {"mode": "fixed", "fixedColor": "blue"} if single else {"mode": "palette-classic"}
    d["custom"] = {
        "drawStyle": "line",
        "lineInterpolation": "linear",
        "lineWidth": 2,
        "fillOpacity": 20 if stacked else 0,
        "gradientMode": "none",
        "showPoints": "never",
        "pointSize": 4,
        "spanNulls": False,
        "axisPlacement": "auto",
        "axisBorderShow": False,
        "axisCenteredZero": False,
        "stacking": {"mode": "normal" if stacked else "none", "group": "A"},
        "thresholdsStyle": {"mode": "off"},
    }
    if min_ is not None:
        d["min"] = min_
    if max_ is not None:
        d["max"] = max_
    d["thresholds"] = {"mode": "absolute", "steps": [{"color": "blue", "value": None}]}
    p["fieldConfig"]["overrides"] = overrides or []
    p["options"] = {
        "legend": {
            "calcs": ["lastNotNull"],
            "displayMode": "list",
            "placement": "bottom",
            "showLegend": True,
        },
        "tooltip": {"mode": "multi", "sort": "desc"},
    }
    p["targets"] = [target(e, chr(65 + i), lg) for i, (e, lg) in enumerate(targets)]
    return p


def bargauge(
    title: str,
    targets: list[tuple[str, str]],
    unit: str = "short",
    *,
    min_: float | None = 0,
    max_: float | None = None,
    thresholds: list[tuple[str, float | None]] | None = None,
    description: str = "",
) -> dict[str, Any]:
    p = base(title, "bargauge", unit, description)
    d = p["fieldConfig"]["defaults"]
    if thresholds:
        d["color"] = {"mode": "thresholds"}
        d["thresholds"] = {
            "mode": "absolute",
            "steps": [{"color": c, "value": v} for c, v in thresholds],
        }
    else:
        d["color"] = {"mode": "fixed", "fixedColor": "blue"}
        d["thresholds"] = {"mode": "absolute", "steps": [{"color": "blue", "value": None}]}
    if min_ is not None:
        d["min"] = min_
    if max_ is not None:
        d["max"] = max_
    p["options"] = {
        "displayMode": "basic",
        "orientation": "horizontal",
        "namePlacement": "left",
        "showUnfilled": True,
        "sizing": "auto",
        "valueMode": "color",
        "minVizHeight": 12,
        "minVizWidth": 8,
        "maxVizHeight": 24,
        "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": False},
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
    }
    p["targets"] = [target(e, chr(65 + i), lg) for i, (e, lg) in enumerate(targets)]
    return p


def gauge(
    title: str, expr: str, unit: str, max_: float, thresholds: list[tuple[str, float | None]]
):
    p = base(title, "gauge", unit)
    d = p["fieldConfig"]["defaults"]
    d["color"] = {"mode": "thresholds"}
    d["min"] = 0
    d["max"] = max_
    d["thresholds"] = {
        "mode": "absolute",
        "steps": [{"color": c, "value": v} for c, v in thresholds],
    }
    p["options"] = {
        "orientation": "auto",
        "showThresholdLabels": False,
        "showThresholdMarkers": True,
        "sizing": "auto",
        "minVizHeight": 75,
        "minVizWidth": 75,
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
    }
    p["targets"] = [target(expr)]
    return p


Column = tuple[str, str, str, dict[str, Any] | None]
"""(refId, expr, display name, override properties or None)."""


def col_bool(on: str = "yes", off: str = "no", kind: str = "toggle") -> dict[str, Any]:
    return {
        "mappings": bool_mapping(on, off, kind),
        "custom.cellOptions": {"type": "color-text"},
    }


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
) -> dict[str, Any]:
    """Table from several instant queries merged on their shared label columns.

    Each query should project only its key labels (``sum by (...)``) so the
    Grafana ``merge`` transformation lines rows up without duplicate columns.
    """
    p = base(title, "table", "none", description)
    p["fieldConfig"]["defaults"]["custom"] = {
        "align": "auto",
        "cellOptions": {"type": "auto"},
        "filterable": True,
        "inspect": False,
    }
    p["fieldConfig"]["defaults"]["color"] = {"mode": "thresholds"}
    p["fieldConfig"]["defaults"]["thresholds"] = {
        "mode": "absolute",
        "steps": [{"color": "blue", "value": None}],
    }
    rename = {f"Value #{ref}": name for ref, _, name, _ in columns}
    rename.update(label_columns)
    exclude = {"Time": True, "__name__": True, "instance": True, "job": True}
    for hid in hide_ids:
        if hid not in label_columns:
            exclude[hid] = True
    overrides = []
    for _ref, _, name, props in columns:
        if props:
            overrides.append(
                {
                    "matcher": {"id": "byName", "options": name},
                    "properties": [{"id": k, "value": v} for k, v in props.items()],
                }
            )
    p["fieldConfig"]["overrides"] = overrides
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


def text_panel(title: str, markdown: str) -> dict[str, Any]:
    p = base(title, "text", "none")
    p["options"] = {"mode": "markdown", "content": markdown}
    return p


def row(title: str, y: int, collapsed: bool = False, panels: list[dict[str, Any]] | None = None):
    return {
        "id": nid(),
        "type": "row",
        "title": title,
        "collapsed": collapsed,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "panels": panels or [],
    }


def with_location(expr: str) -> str:
    """Attach the eero's `location` label to an eero_id-only series."""
    return (
        f"{expr} * on (network_id, eero_id) group_left(location) "
        f"sum by (network_id, eero_id, location) (eero_eero_status{{{N}}})"
    )


def with_device_name(expr: str) -> str:
    return (
        f"{expr} * on (network_id, device_id) group_left(name) "
        f"sum by (network_id, device_id, name) (eero_device_paused{{{N}}})"
    )


def with_profile_name(expr: str) -> str:
    return (
        f"{expr} * on (network_id, profile_id) group_left(name) "
        f"sum by (network_id, profile_id, name) (eero_profile_paused{{{N}}})"
    )


BY_EERO = "sum by (eero_id, location)"
BY_EERO_BAND = "sum by (eero_id, location, band)"

# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

panels: list[dict[str, Any]] = []
y = 0


def section(title: str, build, collapsed: bool = False, flag: str | None = None) -> None:
    global y
    full_title = f"{title} ({flag})" if flag else title
    if collapsed:
        g = Grid(y + 1)
        build(g)
        g.end()
        panels.append(row(full_title, y, True, g.panels))
        y += 1
    else:
        panels.append(row(full_title, y))
        g = Grid(y + 1)
        build(g)
        y = g.end()
        panels.extend(g.panels)


# --- Overview ---------------------------------------------------------------


def overview(g: Grid) -> None:
    g.add(bool_stat("Network", f"eero_network_status{{{N}}}", "ONLINE", "OFFLINE", "health"), 3, 4)
    g.add(
        bool_stat(
            "Internet", f'eero_health_status{{{N}, source="internet"}}', "HEALTHY", "DOWN", "health"
        ),
        3,
        4,
    )
    g.add(
        bool_stat(
            "Mesh",
            f'eero_health_status{{{N}, source="eero_network"}}',
            "HEALTHY",
            "DEGRADED",
            "health",
        ),
        3,
        4,
    )
    g.add(bool_stat("ISP link", f"eero_network_isp_up{{{N}}}", "UP", "DOWN", "health"), 3, 4)
    g.add(stat("Clients", f"sum(eero_network_clients_count{{{N}}})"), 3, 4)
    g.add(stat("Eeros", f"sum(eero_network_eeros_count{{{N}}})"), 3, 4)
    speed_th = [("red", None), ("orange", 50), ("green", 200)]
    g.add(gauge("Download", f"eero_speed_download_mbps{{{N}}}", "Mbits", 1000, speed_th), 3, 4)
    g.add(gauge("Upload", f"eero_speed_upload_mbps{{{N}}}", "Mbits", 1000, speed_th), 3, 4)

    g.add(ts_stat("Last speed test", f"eero_speed_test_timestamp_seconds{{{N}}}"), 4, 4)
    g.add(
        bool_stat(
            "Double NAT", f"eero_network_double_nat_detected{{{N}}}", "DETECTED", "NO", "warn"
        ),
        3,
        4,
    )
    g.add(
        ts_stat("Network last reboot", f"eero_network_last_reboot_timestamp_seconds{{{N}}}"), 4, 4
    )
    g.add(
        bool_stat(
            "Firmware update",
            f"eero_network_update_available{{{N}}}",
            "AVAILABLE",
            "UP TO DATE",
            "warn",
        ),
        3,
        4,
    )
    g.add(stat("Eeros pending update", f"sum(eero_network_updates_available{{{N}}})"), 3, 4)
    g.add(info_stat("Target firmware", f"eero_network_update_target_info{{{N}}}", "version"), 3, 4)
    g.add(
        stat(
            "Networks in account",
            "eero_account_networks_count",
            description="Account-wide; not scoped by the network selector.",
        ),
        4,
        4,
    )

    g.add(
        table(
            "Network",
            [
                (
                    "A",
                    f"sum by (network_id, name, status, isp, wan_type, gateway_ip) "
                    f"(eero_network_info{{{N}}})",
                    "Info",
                    col_hidden(),
                ),
                (
                    "B",
                    f"sum by (network_id, timezone) (eero_network_timezone_info{{{N}}})",
                    "TZ",
                    col_hidden(),
                ),
                (
                    "C",
                    f"sum by (network_id, mode) (eero_network_wireless_mode_info{{{N}}})",
                    "WM",
                    col_hidden(),
                ),
            ],
            {
                "network_id": "Network ID",
                "name": "Name",
                "status": "Status",
                "isp": "ISP",
                "wan_type": "WAN type",
                "gateway_ip": "Gateway IP",
                "timezone": "Timezone",
                "mode": "Wireless mode",
            },
            hide_ids=(),
        ),
        24,
        5,
    )


section("Overview", overview)


# --- Network features -------------------------------------------------------


def network_features(g: Grid) -> None:
    toggles = [
        ("WPA3", "eero_network_wpa3_enabled"),
        ("Band steering", "eero_network_band_steering_enabled"),
        ("SQM", "eero_network_sqm_enabled"),
        ("UPnP", "eero_network_upnp_enabled"),
        ("IPv6", "eero_network_ipv6_enabled"),
        ("Thread", "eero_network_thread_enabled"),
        ("Guest network", "eero_network_guest_enabled"),
        ("Eero Plus", "eero_network_premium_enabled"),
        ("Ad blocking", "eero_network_ad_block_enabled"),
        ("Malware blocking", "eero_network_malware_block_enabled"),
        ("DNS caching", "eero_network_dns_caching_enabled"),
        ("Custom DNS", "eero_network_custom_dns_enabled"),
        ("Dynamic DNS", "eero_network_ddns_enabled"),
        ("Power saving", "eero_network_power_saving_enabled"),
        ("Backup internet", "eero_network_backup_internet_enabled"),
        ("Fast transition (802.11r)", "eero_network_fast_transition_enabled"),
    ]
    for title, metric in toggles:
        g.add(bool_stat(title, f"{metric}{{{N}}}", "ON", "OFF"), 3, 4)

    infos = [
        ("Connection mode", "eero_network_connection_mode_info", "mode"),
        ("WAN type", "eero_network_wan_type_info", "type"),
        ("MLO mode", "eero_network_mlo_mode_info", "mode"),
        ("Wireless mode", "eero_network_wireless_mode_info", "mode"),
        ("DHCP mode", "eero_network_dhcp_mode_info", "mode"),
        ("DNS mode (IPv4)", 'eero_network_dns_mode_info{family="ipv4"', "mode"),
        ("DNS config", "eero_dns_config_info", "mode"),
        ("Timezone", "eero_network_timezone_info", "timezone"),
    ]
    for title, metric, field in infos:
        expr = f"{metric}, {N}}}" if metric.endswith('"') else f"{metric}{{{N}}}"
        g.add(info_stat(title, expr, field), 3, 4)

    counts = [
        ("DNS servers", "eero_network_dns_server_count"),
        ("Parent DNS servers", "eero_network_dns_parent_server_count"),
        ("DHCP reservations", "eero_network_dhcp_reservations_count"),
        ("Port forwards", "eero_network_port_forwards_count"),
        ("Blacklisted devices", "eero_network_blacklisted_devices_count"),
        ("DNS allow-list domains", "eero_dns_policy_allowed_domains_count"),
        ("DNS block-list domains", "eero_dns_policy_blocked_domains_count"),
    ]
    for title, metric in counts:
        g.add(stat(title, f"sum({metric}{{{N}}})"), 3, 4)
    g.add(stat("Entitled features", f"count(eero_network_feature_entitled{{{N}}} == 1)"), 3, 4)

    g.add(
        table(
            "WPA3 mode per band",
            [
                (
                    "A",
                    f"sum by (band, mode) (eero_network_wpa3_band_mode{{{N}}} == 1)",
                    "Set",
                    col_hidden(),
                )
            ],
            {"band": "Band", "mode": "WPA3 mode"},
            sort_by="Band",
        ),
        6,
        8,
    )
    g.add(
        table(
            "Capabilities",
            [
                (
                    "A",
                    f"sum by (capability) (eero_network_capability{{{N}}})",
                    "Capable",
                    col_bool("yes", "no"),
                )
            ],
            {"capability": "Capability"},
            sort_by="Capability",
        ),
        9,
        8,
    )
    g.add(
        table(
            "Port forwards",
            [
                (
                    "A",
                    f"sum by (forward_id, description, protocol, client_port, gateway_port) "
                    f"(eero_port_forward_info{{{N}}})",
                    "Rule",
                    col_hidden(),
                ),
                (
                    "B",
                    f"sum by (forward_id) (eero_port_forward_enabled{{{N}}})",
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
        ),
        9,
        8,
    )


section("Network features", network_features)


# --- Eero topology ----------------------------------------------------------


def eero_topology(g: Grid) -> None:
    g.add(
        table(
            "Eero inventory",
            [
                (
                    "A",
                    f"sum by (eero_id, location, model, os_version, ip_address) (eero_eero_info{{{N}}})",
                    "Info",
                    col_hidden(),
                ),
                (
                    "B",
                    f"sum by (eero_id) (eero_eero_status{{{N}}})",
                    "Status",
                    col_bool("online", "offline", "health"),
                ),
                ("C", f"sum by (eero_id) (eero_eero_is_gateway{{{N}}})", "Gateway", col_bool()),
                ("D", f"sum by (eero_id) (eero_eero_is_primary{{{N}}})", "Primary", col_bool()),
                ("E", f"sum by (eero_id) (eero_eero_using_wan{{{N}}})", "Using WAN", col_bool()),
                ("F", f"sum by (eero_id) (eero_eero_wired{{{N}}})", "Wired", col_bool()),
                (
                    "G",
                    f"sum by (eero_id) (eero_eero_wired_internet{{{N}}})",
                    "Wired internet",
                    col_bool(),
                ),
                (
                    "H",
                    f"sum by (eero_id) (eero_eero_provides_wifi{{{N}}})",
                    "Provides Wi-Fi",
                    col_bool(),
                ),
                (
                    "I",
                    f"sum by (eero_id, connection_type) (eero_eero_connection_type_info{{{N}}})",
                    "CT",
                    col_hidden(),
                ),
                (
                    "J",
                    f"sum by (eero_id, source) (eero_eero_power_source_info{{{N}}})",
                    "PS",
                    col_hidden(),
                ),
                (
                    "K",
                    f"sum by (eero_id, role) (eero_eero_role_info_info{{{N}}})",
                    "RL",
                    col_hidden(),
                ),
                ("L", f"sum by (eero_id) (eero_eero_radio_count{{{N}}})", "Radios", None),
                ("M", f"sum by (eero_id) (eero_eero_mesh_quality_bars{{{N}}})", "Mesh bars", None),
            ],
            {
                "location": "Location",
                "model": "Model",
                "os_version": "OS",
                "ip_address": "IP",
                "connection_type": "Connection",
                "source": "Power",
                "role": "Role (RF)",
            },
            sort_by="Location",
            description="Role comes from the RF tier (--include-rf).",
        ),
        24,
        9,
    )
    g.add(
        table(
            "Supported bands",
            [
                (
                    "A",
                    f"sum by (location, band) (eero_eero_band_supported{{{N}}} == 1)",
                    "Supported",
                    col_hidden(),
                )
            ],
            {"location": "Location", "band": "Band"},
            sort_by="Location",
        ),
        8,
        8,
    )
    g.add(
        table(
            "LLDP neighbours (Ethernet)",
            [
                (
                    "A",
                    with_location(
                        f"sum by (network_id, eero_id, port_number, neighbor_type, neighbor_port) "
                        f"(eero_ethernet_port_neighbor_info{{{N}}})"
                    ),
                    "Seen",
                    col_hidden(),
                ),
            ],
            {
                "location": "Eero",
                "port_number": "Port",
                "neighbor_type": "Neighbour type",
                "neighbor_port": "Neighbour port",
            },
            sort_by="Eero",
            description="Mesh wiring topology from LLDP neighbour reports on each Ethernet port.",
        ),
        16,
        8,
    )
    port_key = "sum by (eero_id, location, port_number, port_name)"
    g.add(
        table(
            "Ethernet ports",
            [
                (
                    "A",
                    f"sum by (eero_id, port_number, port_name) (eero_ethernet_port_info{{{N}}})",
                    "PortInfo",
                    col_hidden(),
                ),
                (
                    "B",
                    f"{port_key} (eero_ethernet_port_carrier{{{N}}})",
                    "Link",
                    col_bool("up", "down", "health"),
                ),
                (
                    "C",
                    f"{port_key} (eero_ethernet_port_speed_mbps{{{N}}})",
                    "Speed",
                    col_unit("Mbits"),
                ),
                ("D", f"{port_key} (eero_ethernet_port_is_wan{{{N}}})", "WAN", col_bool()),
                ("E", f"{port_key} (eero_ethernet_port_is_lte{{{N}}})", "LTE", col_bool()),
            ],
            {"location": "Eero", "port_number": "Port", "port_name": "Name"},
            sort_by="Eero",
        ),
        12,
        8,
    )
    g.add(
        table(
            "LED, nightlight and power saving",
            [
                ("A", f"{BY_EERO} (eero_eero_led_on{{{N}}})", "LED", col_bool("on", "off")),
                (
                    "B",
                    f"{BY_EERO} (eero_eero_led_brightness{{{N}}})",
                    "LED brightness",
                    col_unit("percent"),
                ),
                (
                    "C",
                    f"{BY_EERO} (eero_eero_nightlight_enabled{{{N}}})",
                    "Nightlight",
                    col_bool("on", "off"),
                ),
                (
                    "D",
                    f"{BY_EERO} (eero_eero_nightlight_brightness{{{N}}})",
                    "Nightlight brightness",
                    col_unit("percent"),
                ),
                (
                    "E",
                    f"{BY_EERO} (eero_eero_nightlight_schedule_enabled{{{N}}})",
                    "Nightlight schedule",
                    col_bool("on", "off"),
                ),
                (
                    "F",
                    f"{BY_EERO} (eero_eero_power_saving_active{{{N}}})",
                    "Power saving active",
                    col_bool("yes", "no"),
                ),
            ],
            {"location": "Eero"},
            sort_by="Eero",
            description="Nightlight fields populate on Beacon nodes only.",
        ),
        12,
        8,
    )


section("Eero topology", eero_topology)


# --- Eeros health -----------------------------------------------------------


def eeros_health(g: Grid) -> None:
    g.add(
        bargauge(
            "Uptime since last reboot",
            [(f"eero_eero_uptime_seconds{{{NE}}}", "{{location}}")],
            "dtdurations",
        ),
        8,
        8,
    )
    g.add(
        bargauge(
            "Mesh quality",
            [(f"eero_eero_mesh_quality_bars{{{NE}}}", "{{location}}")],
            "short",
            max_=5,
            thresholds=[("red", None), ("orange", 2), ("green", 4)],
        ),
        8,
        8,
    )
    g.add(
        table(
            "Heartbeat and firmware",
            [
                (
                    "A",
                    f"{BY_EERO} (eero_eero_heartbeat_ok{{{N}}})",
                    "Heartbeat",
                    col_bool("ok", "failing", "health"),
                ),
                (
                    "B",
                    f"{BY_EERO} (eero_eero_last_heartbeat_timestamp_seconds{{{N}}}) * 1000",
                    "Last heartbeat",
                    col_unit("dateTimeAsIso"),
                ),
                (
                    "C",
                    f"{BY_EERO} (eero_eero_last_reboot_timestamp_seconds{{{N}}}) * 1000",
                    "Last reboot",
                    col_unit("dateTimeAsIso"),
                ),
                (
                    "D",
                    f"{BY_EERO} (eero_eero_joined_timestamp_seconds{{{N}}}) * 1000",
                    "Joined mesh",
                    col_unit("dateTimeAsIso"),
                ),
                (
                    "E",
                    f"{BY_EERO} (eero_eero_update_available{{{N}}})",
                    "Update",
                    col_bool("available", "current", "warn"),
                ),
                (
                    "F",
                    f"sum by (eero_id, location, version) (eero_eero_os_version_info{{{N}}})",
                    "OSV",
                    col_hidden(),
                ),
            ],
            {"location": "Eero", "version": "Firmware"},
            sort_by="Eero",
        ),
        8,
        8,
    )
    g.add(
        timeseries(
            "Clients per eero",
            [(f"eero_eero_connected_clients_count{{{NE}}}", "{{location}}")],
            "short",
            stacked=True,
            min_=0,
        ),
        12,
        8,
    )
    g.add(
        timeseries(
            "Wired vs wireless clients per eero",
            [
                (f"eero_eero_connected_wired_clients_count{{{NE}}}", "{{location}} wired"),
                (f"eero_eero_connected_wireless_clients_count{{{NE}}}", "{{location}} wireless"),
            ],
            "short",
            min_=0,
        ),
        12,
        8,
    )
    g.add(
        timeseries(
            "Radio channel utilisation",
            [(f"eero_eero_radio_channel_utilization_percent{{{NE}}}", "{{location}} {{band}}")],
            "percent",
            min_=0,
            max_=100,
        ),
        12,
        8,
    )
    g.add(
        timeseries(
            "Radio clients by band",
            [(f"eero_eero_radio_client_count{{{NE}}}", "{{location}} {{band}}")],
            "short",
            stacked=True,
            min_=0,
        ),
        12,
        8,
    )
    g.add(
        table(
            "Radios",
            [
                ("A", f"{BY_EERO_BAND} (eero_eero_radio_channel{{{N}}})", "Channel", None),
                (
                    "B",
                    f"{BY_EERO_BAND} (eero_eero_radio_channel_width_mhz{{{N}}})",
                    "Width",
                    col_unit("MHz"),
                ),
                (
                    "C",
                    f"{BY_EERO_BAND} (eero_eero_radio_tx_power_dbm{{{N}}})",
                    "Tx power",
                    col_unit("dBm"),
                ),
                (
                    "D",
                    f"{BY_EERO_BAND} (eero_eero_radio_channel_utilization_percent{{{N}}})",
                    "Utilisation",
                    col_unit("percent"),
                ),
                ("E", f"{BY_EERO_BAND} (eero_eero_radio_client_count{{{N}}})", "Clients", None),
            ],
            {"location": "Eero", "band": "Band"},
            sort_by="Eero",
        ),
        24,
        7,
    )


section("Eeros health", eeros_health)


# --- RF ---------------------------------------------------------------------


def rf(g: Grid) -> None:
    util_th = [("green", None), ("orange", 50), ("red", 80)]
    g.add(
        timeseries(
            "Average channel utilisation",
            [
                (
                    with_location(f"eero_channel_utilization_avg_percent{{{NE}}}"),
                    "{{location}} {{band}}",
                )
            ],
            "percent",
            min_=0,
            max_=100,
        ),
        12,
        8,
    )
    g.add(
        bargauge(
            "p99 utilisation",
            [
                (
                    with_location(f"eero_channel_utilization_p99_percent{{{NE}}}"),
                    "{{location}} {{band}}",
                )
            ],
            "percent",
            max_=100,
            thresholds=util_th,
        ),
        6,
        8,
    )
    g.add(
        bargauge(
            "Minutes over busy threshold",
            [(with_location(f"eero_channel_busy_minutes{{{NE}}}"), "{{location}} {{band}}")],
            "m",
        ),
        6,
        8,
    )
    g.add(
        timeseries(
            "Busy (latest sample)",
            [(with_location(f"eero_channel_busy_last{{{NE}}}"), "{{location}} {{band}}")],
            "percent",
            min_=0,
            description="Latest 'busy' sample of the channel time series, as reported by the API.",
        ),
        8,
        8,
    )
    g.add(
        timeseries(
            "Rx/Tx vs other-BSS airtime (latest sample)",
            [
                (with_location(f"eero_channel_rx_tx_last{{{NE}}}"), "{{location}} {{band}} rx/tx"),
                (
                    with_location(f"eero_channel_rx_other_last{{{NE}}}"),
                    "{{location}} {{band}} other",
                ),
            ],
            "percent",
            min_=0,
            description="Latest 'rx_tx' and 'rx_other' samples, as reported by the API.",
        ),
        8,
        8,
    )
    g.add(
        timeseries(
            "Noise floor (latest sample)",
            [(with_location(f"eero_channel_noise_last{{{NE}}}"), "{{location}} {{band}}")],
            "dBm",
            description="Latest 'noise' sample, as reported by the API.",
        ),
        8,
        8,
    )
    g.add(
        table(
            "Channel configuration",
            [
                (
                    "A",
                    with_location(
                        f"sum by (network_id, eero_id, band, channel, center_channel, channel_bandwidth, frequency) "
                        f"(eero_channel_info_info{{{N}}})"
                    ),
                    "Cfg",
                    col_hidden(),
                ),
                (
                    "B",
                    with_location(
                        f"sum by (network_id, eero_id, band) (eero_channel_utilization_max_percent{{{N}}})"
                    ),
                    "Max util",
                    col_unit("percent"),
                ),
                (
                    "C",
                    with_location(
                        f"sum by (network_id, eero_id, band) (eero_channel_acs_events_total{{{N}}})"
                    ),
                    "ACS events",
                    None,
                ),
            ],
            {
                "location": "Eero",
                "band": "Band",
                "channel": "Channel",
                "center_channel": "Centre",
                "channel_bandwidth": "Bandwidth",
                "frequency": "Frequency",
            },
            sort_by="Eero",
        ),
        16,
        8,
    )
    g.add(stat("ACS events (window)", f"sum(eero_channel_acs_events_total{{{NE}}})"), 8, 4)
    g.add(
        stat(
            "Peak utilisation",
            f"max(eero_channel_utilization_max_percent{{{NE}}})",
            "percent",
            color_mode="value",
            thresholds=util_th,
        ),
        8,
        4,
    )


section("RF channel utilisation", rf, flag="--include-rf")


# --- Devices ----------------------------------------------------------------


def devices(g: Grid) -> None:
    g.add(stat("Connected", f"count(eero_device_connected{{{N}}} == 1)"), 3, 4)
    g.add(stat("Wireless", f"sum(eero_device_wireless{{{N}}})"), 3, 4)
    g.add(stat("On gateway", f"sum(eero_device_connected_to_gateway{{{N}}})"), 3, 4)
    g.add(stat("Guest", f"sum(eero_device_is_guest{{{N}}})"), 3, 4)
    g.add(stat("Blocked", f"sum(eero_device_blocked{{{N}}})"), 3, 4)
    g.add(stat("Paused", f"sum(eero_device_paused{{{N}}})"), 3, 4)
    g.add(stat("Private", f"sum(eero_device_private{{{N}}})"), 3, 4)
    g.add(stat("Wi-Fi 6+", f"count(eero_device_wifi_generation{{{N}}} >= 6)"), 3, 4)

    g.add(
        timeseries(
            "Connected devices by connection type",
            [
                (
                    f"count by (connection_type) (eero_device_connected{{{N}}} == 1)",
                    "{{connection_type}}",
                )
            ],
            "short",
            stacked=True,
            min_=0,
        ),
        12,
        8,
    )
    g.add(
        bargauge(
            "Devices by band", [(f"count by (band) (eero_device_frequency_mhz{{{N}}})", "{{band}}")]
        ),
        6,
        8,
    )
    g.add(
        bargauge(
            "Devices by Wi-Fi generation",
            [
                (f"count(eero_device_wifi_generation{{{N}}} == {gen})", f"Wi-Fi {gen}")
                for gen in (4, 5, 6, 7)
            ],
        ),
        6,
        8,
    )
    g.add(
        bargauge(
            "Top manufacturers",
            [
                (
                    f"topk(10, count by (manufacturer) (eero_device_connected{{{N}}} == 1))",
                    "{{manufacturer}}",
                )
            ],
        ),
        8,
        8,
    )
    g.add(
        bargauge(
            "Top 10 receive bitrate",
            [(f"topk(10, eero_device_rx_bitrate_mbps{{{N}}})", "{{name}}")],
            "Mbits",
        ),
        8,
        8,
    )
    g.add(
        bargauge(
            "Top 10 transmit bitrate",
            [(f"topk(10, eero_device_tx_bitrate_mbps{{{N}}})", "{{name}}")],
            "Mbits",
        ),
        8,
        8,
    )
    signal_th = [("red", None), ("orange", -75), ("green", -65)]
    g.add(
        timeseries(
            "Signal strength (top 10)",
            [(f"topk(10, eero_device_signal_strength_dbm{{{N}}})", "{{name}}")],
            "dBm",
        ),
        12,
        8,
    )
    g.add(
        bargauge(
            "Weakest 10 signals",
            [(f"bottomk(10, eero_device_signal_strength_dbm{{{N}}})", "{{name}}")],
            "dBm",
            min_=-95,
            max_=-30,
            thresholds=signal_th,
        ),
        6,
        8,
    )
    g.add(
        bargauge(
            "Lowest 10 connection scores",
            [(f"bottomk(10, eero_device_connection_score{{{N}}})", "{{name}}")],
            "short",
        ),
        6,
        8,
    )
    g.add(
        timeseries(
            "MCS index (top 5 rx / tx)",
            [
                (f"topk(5, eero_device_rx_mcs{{{N}}})", "{{name}} rx"),
                (f"topk(5, eero_device_tx_mcs{{{N}}})", "{{name}} tx"),
            ],
            "short",
            min_=0,
        ),
        8,
        8,
    )
    g.add(
        timeseries(
            "Spatial streams (top 5 rx / tx)",
            [
                (f"topk(5, eero_device_rx_nss{{{N}}})", "{{name}} rx"),
                (f"topk(5, eero_device_tx_nss{{{N}}})", "{{name}} tx"),
            ],
            "short",
            min_=0,
        ),
        8,
        8,
    )
    g.add(
        timeseries(
            "Transmit retransmit rate (top 10)",
            [
                (
                    f"topk(10, {with_device_name(f'eero_device_packet_stats_tx_retransmit_ppm{{{N}}}')})",
                    "{{name}}",
                )
            ],
            "ppm",
            min_=0,
        ),
        8,
        8,
    )
    dev = "sum by (device_id, name)"
    g.add(
        table(
            "Device details",
            [
                (
                    "A",
                    f"sum by (device_id, name, manufacturer, device_type, ip, hostname, connection_type, source_eero, profile) "
                    f"(eero_device_info{{{N}}})",
                    "Info",
                    col_hidden(),
                ),
                (
                    "B",
                    f"{dev} (eero_device_connected{{{N}}})",
                    "Connected",
                    col_bool("yes", "no", "health"),
                ),
                (
                    "C",
                    f"sum by (device_id, name, band) (eero_device_signal_strength_dbm{{{N}}})",
                    "Signal",
                    col_unit("dBm"),
                ),
                ("D", f"{dev} (eero_device_connection_score{{{N}}})", "Score", None),
                ("E", f"{dev} (eero_device_connection_score_bars{{{N}}})", "Bars", None),
                ("F", f"{dev} (eero_device_frequency_mhz{{{N}}})", "Frequency", col_unit("MHz")),
                ("G", f"{dev} (eero_device_channel{{{N}}})", "Channel", None),
                (
                    "H",
                    f"{dev} (eero_device_rx_bitrate_mbps{{{N}}})",
                    "Rx bitrate",
                    col_unit("Mbits"),
                ),
                (
                    "I",
                    f"{dev} (eero_device_tx_bitrate_mbps{{{N}}})",
                    "Tx bitrate",
                    col_unit("Mbits"),
                ),
                ("J", f"{dev} (eero_device_wifi_generation{{{N}}})", "Wi-Fi gen", None),
                (
                    "K",
                    f"{dev} (eero_device_last_active_timestamp_seconds{{{N}}}) * 1000",
                    "Last active",
                    col_unit("dateTimeAsIso"),
                ),
                (
                    "L",
                    f"{dev} (eero_device_first_seen_timestamp_seconds{{{N}}}) * 1000",
                    "First seen",
                    col_unit("dateTimeAsIso"),
                ),
                (
                    "M",
                    f"sum by (device_id, subnet_kind) (eero_device_subnet_kind_info{{{N}}})",
                    "SK",
                    col_hidden(),
                ),
            ],
            {
                "name": "Device",
                "manufacturer": "Manufacturer",
                "device_type": "Type",
                "ip": "IP",
                "hostname": "Hostname",
                "connection_type": "Connection",
                "source_eero": "Via eero",
                "profile": "Profile",
                "band": "Band",
                "subnet_kind": "Subnet",
            },
            sort_by="Device",
        ),
        24,
        10,
    )
    g.add(
        table(
            "Packet statistics",
            [
                (
                    "A",
                    f"{dev} ({with_device_name(f'eero_device_packet_stats_rx_packets{{{N}}}')})",
                    "Rx packets",
                    None,
                ),
                (
                    "B",
                    f"{dev} ({with_device_name(f'eero_device_packet_stats_tx_packets{{{N}}}')})",
                    "Tx packets",
                    None,
                ),
                (
                    "C",
                    f"{dev} ({with_device_name(f'eero_device_packet_stats_total_packets{{{N}}}')})",
                    "Total packets",
                    None,
                ),
                (
                    "D",
                    f"{dev} ({with_device_name(f'eero_device_packet_stats_rx_drops{{{N}}}')})",
                    "Rx drops",
                    None,
                ),
                (
                    "E",
                    f"{dev} ({with_device_name(f'eero_device_packet_stats_tx_retries{{{N}}}')})",
                    "Tx retries",
                    None,
                ),
                (
                    "F",
                    f"{dev} ({with_device_name(f'eero_device_packet_stats_tx_retransmit_ppm{{{N}}}')})",
                    "Tx retransmit",
                    col_unit("ppm"),
                ),
                (
                    "G",
                    f"{dev} ({with_device_name(f'eero_device_packet_stats_tx_fail_ppm{{{N}}}')})",
                    "Tx fail",
                    col_unit("ppm"),
                ),
                (
                    "H",
                    f"{dev} ({with_device_name(f'eero_device_packet_stats_rx_drop_ppm{{{N}}}')})",
                    "Rx drop",
                    col_unit("ppm"),
                ),
            ],
            {"name": "Device"},
            sort_by="Device",
            description="Lifetime counters reported by the API as gauges (no reset semantics).",
        ),
        24,
        8,
    )


section("Devices", devices)


# --- Profiles ---------------------------------------------------------------


def profiles(g: Grid) -> None:
    g.add(stat("Profiles", f"count(eero_profile_paused{{{N}}})"), 4, 4)
    g.add(stat("Paused", f"sum(eero_profile_paused{{{N}}})"), 4, 4)
    g.add(stat("Devices in profiles", f"sum(eero_profile_devices_count{{{N}}})"), 4, 4)
    g.add(stat("Connected in profiles", f"sum(eero_profile_connected_devices_count{{{N}}})"), 4, 4)
    g.add(stat("With content filters", f"sum(eero_profile_content_filters_set{{{N}}})"), 4, 4)
    g.add(
        stat("Blocked applications", f"sum(eero_profile_blocked_applications_count{{{N}}})"), 4, 4
    )
    g.add(
        bargauge("Devices per profile", [(f"eero_profile_devices_count{{{N}}}", "{{name}}")]), 8, 8
    )
    g.add(
        bargauge(
            "Connected devices per profile",
            [(f"eero_profile_connected_devices_count{{{N}}}", "{{name}}")],
        ),
        8,
        8,
    )
    prof = "sum by (profile_id, name)"
    g.add(
        table(
            "Profiles",
            [
                (
                    "A",
                    f"{prof} (eero_profile_paused{{{N}}})",
                    "Paused",
                    col_bool("paused", "active", "warn"),
                ),
                ("B", f"{prof} (eero_profile_devices_count{{{N}}})", "Devices", None),
                ("C", f"{prof} (eero_profile_connected_devices_count{{{N}}})", "Connected", None),
                ("D", f"{prof} (eero_profile_schedules_count{{{N}}})", "Schedules", None),
                (
                    "E",
                    f"{prof} (eero_profile_blocked_applications_count{{{N}}})",
                    "Blocked apps",
                    None,
                ),
                (
                    "F",
                    f"{prof} (eero_profile_content_filters_set{{{N}}})",
                    "Content filters",
                    col_bool("set", "none"),
                ),
            ],
            {"name": "Profile"},
            sort_by="Profile",
        ),
        8,
        8,
    )


section("Profiles", profiles)


# --- Data usage -------------------------------------------------------------


def data_usage(g: Grid) -> None:
    per = f'{N}, period="$period"'
    g.add(
        stat(
            "Download — $period",
            f'sum(eero_network_data_usage_bytes{{{per}, direction="download"}})',
            "bytes",
        ),
        4,
        4,
    )
    g.add(
        stat(
            "Upload — $period",
            f'sum(eero_network_data_usage_bytes{{{per}, direction="upload"}})',
            "bytes",
        ),
        4,
        4,
    )
    g.add(stat("Total — $period", f"sum(eero_network_data_usage_bytes{{{per}}})", "bytes"), 4, 4)
    g.add(
        stat("Download — trailing window", f"sum(eero_data_usage_download_bytes{{{N}}})", "bytes"),
        4,
        4,
    )
    g.add(
        stat("Upload — trailing window", f"sum(eero_data_usage_upload_bytes{{{N}}})", "bytes"), 4, 4
    )
    g.add(
        stat(
            "Total — trailing window",
            f"sum(eero_data_usage_download_bytes{{{N}}}) + sum(eero_data_usage_upload_bytes{{{N}}})",
            "bytes",
        ),
        4,
        4,
    )
    g.add(
        timeseries(
            "Network usage — $period",
            [(f"sum by (direction) (eero_network_data_usage_bytes{{{per}}})", "{{direction}}")],
            "bytes",
            min_=0,
        ),
        12,
        8,
    )
    g.add(
        timeseries(
            "Download by period",
            [
                (
                    f'sum by (period, cadence) (eero_network_data_usage_bytes{{{N}, direction="download"}})',
                    "{{period}} ({{cadence}})",
                )
            ],
            "bytes",
            min_=0,
        ),
        12,
        8,
    )
    g.add(
        bargauge(
            "Top 10 devices — $period",
            [(f"topk(10, sum by (name) (eero_device_data_usage_bytes{{{per}}}))", "{{name}}")],
            "bytes",
        ),
        8,
        8,
    )
    g.add(
        bargauge(
            "Usage per eero — $period",
            [
                (
                    f"sum by (location, direction) (eero_eero_data_usage_bytes{{{per}}})",
                    "{{location}} {{direction}}",
                )
            ],
            "bytes",
        ),
        8,
        8,
    )
    g.add(
        bargauge(
            "Usage per profile — $period",
            [
                (
                    f"sum by (profile_id, direction) ({with_profile_name(f'eero_profile_data_usage_bytes{{{per}}}')})",
                    "{{name}} {{direction}}",
                )
            ],
            "bytes",
        ),
        8,
        8,
    )
    g.add(
        timeseries(
            "Unprofiled device usage — $period",
            [
                (
                    f"sum by (direction) (eero_unprofiled_data_usage_bytes{{{per}}})",
                    "{{direction}}",
                )
            ],
            "bytes",
        ),
        8,
        8,
    )
    g.add(
        bargauge(
            "Top 10 devices download — trailing window",
            [(f"topk(10, eero_device_data_usage_download_bytes{{{N}}})", "{{name}}")],
            "bytes",
        ),
        4,
        8,
    )
    g.add(
        bargauge(
            "Top 10 devices upload — trailing window",
            [(f"topk(10, eero_device_data_usage_upload_bytes{{{N}}})", "{{name}}")],
            "bytes",
        ),
        4,
        8,
    )


section("Data usage", data_usage)


# --- Insights ---------------------------------------------------------------


def insights(g: Grid) -> None:
    g.add(
        timeseries(
            "Insight events in window",
            [
                (f"sum(eero_insights_adblock_total{{{N}}})", "ad-block"),
                (f"sum(eero_insights_blocked_total{{{N}}})", "blocked threats"),
                (f"sum(eero_insights_inspected_total{{{N}}})", "inspected"),
            ],
            "short",
            min_=0,
        ),
        12,
        8,
    )
    for title, metric in (
        ("Ad-block by category", "eero_insights_adblock_total"),
        ("Blocked by category", "eero_insights_blocked_total"),
        ("Inspected by category", "eero_insights_inspected_total"),
    ):
        g.add(bargauge(title, [(f"sum by (category) ({metric}{{{N}}})", "{{category}}")]), 4, 8)
    g.add(
        bargauge(
            "Profile insights (top 10)",
            [
                (
                    f"topk(10, {with_profile_name(f'eero_profile_insights_total{{{N}}}')})",
                    "{{name}} {{type}}",
                )
            ],
        ),
        12,
        8,
    )
    g.add(
        table(
            "Profile insights",
            [
                (
                    "A",
                    f"sum by (profile_id, name, type) ({with_profile_name(f'eero_profile_insights_total{{{N}}}')})",
                    "Events",
                    None,
                ),
                (
                    "B",
                    f"sum by (profile_id, name, type) ({with_profile_name(f'eero_profile_insights_devices{{{N}}}')})",
                    "Devices",
                    None,
                ),
            ],
            {"name": "Profile", "type": "Type"},
            sort_by="Profile",
        ),
        12,
        8,
    )


section("Insights", insights)


# --- Account & subscription -------------------------------------------------


def account(g: Grid) -> None:
    g.add(
        bool_stat("Eero Plus", f"eero_network_premium_enabled{{{N}}}", "ACTIVE", "INACTIVE"), 3, 4
    )
    g.add(
        ts_stat("Next renewal", f"eero_account_premium_next_renewal_timestamp_seconds{{{N}}}"), 4, 4
    )
    g.add(
        info_stat("Entitlement state", f"eero_account_entitlement_state{{{N}}} == 1", "state"), 3, 4
    )
    g.add(info_stat("Product", f"eero_account_entitlement_product_info{{{N}}} == 1", "type"), 3, 4)
    g.add(
        ts_stat(
            "Entitlement created", f"eero_account_entitlement_created_timestamp_seconds{{{N}}}"
        ),
        4,
        4,
    )
    g.add(stat("Members", f"sum(eero_network_members_count{{{N}}})"), 2, 4)
    g.add(
        bool_stat(
            "Unread notifications",
            f"eero_network_notifications_unread{{{N}}}",
            "UNREAD",
            "NONE",
            "warn",
        ),
        3,
        4,
    )
    g.add(info_stat("Role", f"eero_network_role_info{{{N}}}", "role"), 2, 4)
    g.add(
        table(
            "Feature entitlements",
            [
                (
                    "A",
                    f"sum by (feature) (eero_network_feature_entitled{{{N}}})",
                    "Entitled",
                    col_bool("yes", "no"),
                )
            ],
            {"feature": "Feature"},
            sort_by="Feature",
        ),
        8,
        8,
    )
    g.add(
        table(
            "Permissions (read)",
            [
                (
                    "A",
                    f"sum by (capability) (eero_network_permission{{{N}}})",
                    "Readable",
                    col_bool("yes", "no"),
                )
            ],
            {"capability": "Capability"},
            sort_by="Capability",
        ),
        8,
        8,
    )
    g.add(
        table(
            "Per-eero permissions",
            [
                (
                    "A",
                    f"sum by (eero_id, verb) (eero_network_per_eero_permission{{{N}}})",
                    "Allowed",
                    col_bool("yes", "no"),
                )
            ],
            {"eero_id": "Eero", "verb": "Verb"},
            sort_by="Eero",
        ),
        8,
        8,
    )
    g.add(
        table(
            "Notification settings",
            [
                (
                    "A",
                    f"sum by (event) (eero_network_notification_enabled{{{N}}})",
                    "Enabled",
                    col_bool("on", "off"),
                )
            ],
            {"event": "Event"},
            sort_by="Event",
        ),
        8,
        8,
    )


section("Account and subscription", account)


# --- Guest & subnets --------------------------------------------------------


def guest_subnets(g: Grid) -> None:
    g.add(bool_stat("Guest network", f"eero_network_guest_enabled{{{N}}}", "ON", "OFF"), 4, 4)
    g.add(stat("Guest clients", f"sum(eero_guest_network_connected_clients{{{N}}})"), 4, 4)
    g.add(info_stat("Guest SSID", f"eero_guest_network_info{{{N}}}", "name"), 4, 4)
    g.add(stat("Subnets enabled", f"sum(eero_subnet_enabled{{{N}}})"), 4, 4)
    g.add(
        stat(
            "Open (unencrypted) subnets",
            f"sum(eero_subnet_open_network{{{N}}})",
            color_mode="value",
            thresholds=[("green", None), ("orange", 1)],
        ),
        4,
        4,
    )
    g.add(
        bargauge(
            "Devices by subnet kind",
            [(f"count by (subnet_kind) (eero_device_subnet_kind_info{{{N}}})", "{{subnet_kind}}")],
        ),
        4,
        4,
    )
    sub = "sum by (subnet_kind, subnet_type)"
    g.add(
        table(
            "Subnets",
            [
                ("A", f"{sub} (eero_subnet_enabled{{{N}}})", "Enabled", col_bool()),
                ("B", f"{sub} (eero_subnet_wan_access{{{N}}})", "WAN access", col_bool()),
                ("C", f"{sub} (eero_subnet_lan_access{{{N}}})", "LAN access", col_bool()),
                (
                    "D",
                    f"{sub} (eero_subnet_open_network{{{N}}})",
                    "Open network",
                    col_bool("yes", "no", "warn"),
                ),
                (
                    "E",
                    f"{sub} (eero_subnet_nat_port_randomization{{{N}}})",
                    "NAT port randomisation",
                    col_bool(),
                ),
                (
                    "F",
                    f"{sub} (eero_subnet_igmp_snooping_enabled{{{N}}})",
                    "IGMP snooping",
                    col_bool(),
                ),
            ],
            {"subnet_kind": "Kind", "subnet_type": "Type"},
            sort_by="Kind",
        ),
        24,
        7,
    )


section("Guest and subnets", guest_subnets)


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
    g.add(bool_stat("Exporter", "eero_up", "UP", "DOWN", "health"), 3, 4)
    g.add(
        stat("Last collection duration", "eero_exporter_scrape_duration_seconds", "s", decimals=2),
        3,
        4,
    )
    g.add(stat("Collection interval", "eero_exporter_collection_interval_seconds", "s"), 3, 4)
    g.add(
        stat(
            "Since last collection",
            "time() - eero_exporter_last_collection_timestamp_seconds",
            "s",
            color_mode="value",
            thresholds=[("green", None), ("orange", 300), ("red", 900)],
        ),
        3,
        4,
    )
    g.add(stat("API requests last cycle", "eero_exporter_api_requests_last_cycle"), 3, 4)
    g.add(
        stat(
            "Scrape errors (range)",
            "sum(increase(eero_exporter_scrape_errors_total[$__range]))",
            color_mode="value",
            thresholds=[("green", None), ("red", 1)],
        ),
        3,
        4,
    )
    g.add(
        stat(
            "Failed API requests (range)",
            'sum(increase(eero_exporter_api_requests_total{status!="success"}[$__range]))',
            color_mode="value",
            thresholds=[("green", None), ("orange", 1)],
        ),
        3,
        4,
    )
    g.add(
        stat(
            "API success rate (range)",
            'sum(rate(eero_exporter_api_requests_total{status="success"}[$__range])) '
            "/ sum(rate(eero_exporter_api_requests_total[$__range]))",
            "percentunit",
            color_mode="value",
            thresholds=[("red", None), ("orange", 0.9), ("green", 0.99)],
        ),
        3,
        4,
    )
    status_overrides = [
        {
            "matcher": {"id": "byName", "options": s},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}],
        }
        for s, (c, _) in API_STATUS_MEANING.items()
    ]
    g.add(
        timeseries(
            "API requests by status",
            [("sum by (status) (rate(eero_exporter_api_requests_total[5m]))", "{{status}}")],
            "reqps",
            stacked=True,
            min_=0,
            overrides=status_overrides,
        ),
        10,
        8,
    )
    legend = "| status | meaning |\n|---|---|\n" + "\n".join(
        f"| `{s}` | {m} |" for s, (_, m) in API_STATUS_MEANING.items()
    )
    g.add(
        text_panel(
            "API status legend",
            "Closed `status` enum of `eero_exporter_api_requests_total`. "
            'Sum failures with `status!="success"`.\n\n' + legend,
        ),
        6,
        8,
    )
    g.add(
        timeseries(
            "Scrape errors by type",
            [
                (
                    "sum by (error_type) (rate(eero_exporter_scrape_errors_total[5m]))",
                    "{{error_type}}",
                )
            ],
            "short",
            min_=0,
        ),
        8,
        8,
    )
    g.add(
        timeseries(
            "Collection duration",
            [("eero_exporter_scrape_duration_seconds", "duration")],
            "s",
            min_=0,
        ),
        12,
        7,
    )
    g.add(
        timeseries(
            "API requests by endpoint (top 10)",
            [
                (
                    "topk(10, sum by (endpoint) (rate(eero_exporter_api_requests_total[5m])))",
                    "{{endpoint}}",
                )
            ],
            "reqps",
            min_=0,
        ),
        12,
        7,
    )


section("Exporter health", exporter)


# --- Optional tiers (collapsed) --------------------------------------------


def per_profile(g: Grid) -> None:
    g.add(
        table(
            "DNS-policy applications per profile",
            [
                (
                    "A",
                    f"sum by (profile_id, name) ({with_profile_name(f'eero_profile_dns_policy_applications_count{{{N}}}')})",
                    "Applications",
                    None,
                )
            ],
            {"name": "Profile"},
            sort_by="Profile",
        ),
        24,
        7,
    )


section("Per-profile", per_profile, collapsed=True, flag="--include-per-profile")


def per_device(g: Grid) -> None:
    g.add(
        bargauge(
            "Top 10 device insights",
            [
                (
                    f"topk(10, {with_device_name(f'eero_device_insights_total{{{N}}}')})",
                    "{{name}} {{type}}",
                )
            ],
        ),
        12,
        8,
    )
    g.add(
        timeseries(
            "Device insights by type",
            [(f"sum by (type) (eero_device_insights_total{{{N}}})", "{{type}}")],
            "short",
            min_=0,
        ),
        12,
        8,
    )


section("Per-device", per_device, collapsed=True, flag="--include-per-device")


def per_eero(g: Grid) -> None:
    e = "sum by (eero_id, location)"
    g.add(
        table(
            "Per-eero endpoints",
            [
                (
                    "A",
                    f"{e} ({with_location(f'eero_eero_connections_count{{{N}}}')})",
                    "Wireless connections",
                    None,
                ),
                (
                    "B",
                    f"{e} ({with_location(f'eero_eero_ouicheck_can_add{{{N}}}')})",
                    "OUI check: can add",
                    col_bool(),
                ),
                (
                    "C",
                    f"{e} ({with_location(f'eero_eero_ouicheck_must_update{{{N}}}')})",
                    "OUI check: must update",
                    col_bool("yes", "no", "warn"),
                ),
            ],
            {"location": "Eero"},
            sort_by="Eero",
        ),
        24,
        7,
    )


section("Per-eero", per_eero, collapsed=True, flag="--include-per-eero")


def unverified(g: Grid) -> None:
    for title, metric in (
        ("Routing: devices", "eero_network_routing_devices_count"),
        ("Routing: reservations", "eero_network_routing_reservations_count"),
        ("Routing: forwards", "eero_network_routing_forwards_count"),
        ("Routing: pinholes", "eero_network_routing_pinholes_count"),
        ("Backup access points", "eero_backup_access_points_count"),
        ("Cellular backup usage items", "eero_cellular_backup_usage_items_count"),
        ("Cellular backup outages", "eero_cellular_backup_outages_count"),
        ("Speed tests in window", "eero_speed_tests_total"),
    ):
        g.add(stat(title, f"sum({metric}{{{N}}})"), 3, 4)
    g.add(
        bool_stat(
            "Conflicting SSID nearby",
            f"eero_network_scan_conflicting_ssid{{{N}}}",
            "DETECTED",
            "NO",
            "warn",
        ),
        4,
        6,
    )
    g.add(
        bool_stat("Multi-static IP", f"eero_network_multistaticip_enabled{{{N}}}", "ON", "OFF"),
        4,
        6,
    )
    g.add(bool_stat("AC compatibility", f"eero_network_ac_compat{{{N}}}", "ON", "OFF"), 4, 6)
    g.add(
        stat("Power-saving schedules", f"sum(eero_network_power_saving_schedules_count{{{N}}})"),
        4,
        6,
    )
    g.add(
        table(
            "Backup access points",
            [
                (
                    "A",
                    f"sum by (index) (eero_backup_access_point_enabled{{{N}}})",
                    "Enabled",
                    col_bool(),
                ),
                (
                    "B",
                    f"sum by (index, status) (eero_backup_access_point_connectivity_info_info{{{N}}})",
                    "Conn",
                    col_hidden(),
                ),
            ],
            {"index": "#", "status": "Connectivity"},
            sort_by="#",
        ),
        8,
        6,
    )


section("Unverified shapes", unverified, collapsed=True, flag="--include-unverified")


# ---------------------------------------------------------------------------
# Dashboard envelope
# ---------------------------------------------------------------------------

dashboard = {
    "__inputs": [],
    "__elements": {},
    "__requires": [
        {"type": "grafana", "id": "grafana", "name": "Grafana", "version": "11.5.0"},
        {"type": "datasource", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"},
        {"type": "panel", "id": "bargauge", "name": "Bar gauge", "version": ""},
        {"type": "panel", "id": "gauge", "name": "Gauge", "version": ""},
        {"type": "panel", "id": "stat", "name": "Stat", "version": ""},
        {"type": "panel", "id": "table", "name": "Table", "version": ""},
        {"type": "panel", "id": "text", "name": "Text", "version": ""},
        {"type": "panel", "id": "timeseries", "name": "Time series", "version": ""},
    ],
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
        "Eero mesh network monitoring via eero-prometheus-exporter 4.0.0. Every exported "
        "metric family has a panel; optional tiers live in collapsed rows named after "
        "the flag that enables them."
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
    "version": 45,
    "weekStart": "",
}

# ---------------------------------------------------------------------------
# Coverage check
# ---------------------------------------------------------------------------


def all_panels(ps):
    for p in ps:
        yield p
        yield from all_panels(p.get("panels", []))


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
