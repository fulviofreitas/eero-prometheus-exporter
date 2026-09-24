"""Render grafana/eero-dashboard.json against SYNTHETIC data and screenshot it.

No eero account, session or network is involved: every sample is invented
here from the metric registry (``describe_metrics()``) and a small fictional
mesh (4 eeros, ~24 devices, 4 profiles). Use it to review dashboard changes
visually, and to refresh ``docs/images/grafana-dashboard.png``.

Needs standalone Prometheus and Grafana OSS linux-amd64 builds unpacked
somewhere (no Docker), plus Playwright with a Chromium binary::

    SCRATCH=.scratch   # git-ignored via .git/info/exclude
    curl -sSL https://github.com/prometheus/prometheus/releases/download/v3.14.0/\
prometheus-3.14.0.linux-amd64.tar.gz | tar xz -C $SCRATCH
    curl -sSL https://dl.grafana.com/oss/release/grafana-13.2.2.linux-amd64.tar.gz \
| tar xz -C $SCRATCH

    uv run python scripts/render_dashboard_preview.py backfill --prometheus $SCRATCH/prometheus-*
    uv run python scripts/render_dashboard_preview.py serve \
        --prometheus $SCRATCH/prometheus-* --grafana $SCRATCH/grafana-*      # Ctrl-C to stop
    python3 scripts/render_dashboard_preview.py screenshot --out shot.png [--expand]

(``screenshot`` imports only Playwright, so any interpreter that has it works;
``backfill`` needs the project environment for the metric registry.)

``serve`` binds Prometheus and Grafana to 127.0.0.1 only, provisions the repo's
dashboard directory (re-read every 10 s, so regenerating the JSON is picked up
live) and enables anonymous viewer access so the screenshot needs no login.
"""

from __future__ import annotations

import argparse
import math
import random
import shutil
import signal

# Reviewed: subprocess is only called with list argv and no shell (see cmd_backfill/cmd_serve).
import subprocess  # nosec B404
import sys
import time
import zlib
from collections.abc import Callable, Iterator
from itertools import product
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

WORK = REPO_ROOT / ".scratch" / "preview"
PROM_PORT = 19390
GRAFANA_PORT = 19300
STEP_S = 120
HOURS = 24
LEAD_S = 3 * 3600  # samples extend past "now" so instant queries stay fresh

# ---------------------------------------------------------------------------
# A fictional mesh
# ---------------------------------------------------------------------------

NETWORK = {"network_id": "999001", "name": "Home"}
EEROS = [
    {"eero_id": "1001", "location": "Living Room", "model": "eero Pro 6E"},
    {"eero_id": "1002", "location": "Office", "model": "eero 6+"},
    {"eero_id": "1003", "location": "Bedroom", "model": "eero 6+"},
    {"eero_id": "1004", "location": "Garage", "model": "eero Outdoor 7"},
]
BANDS = ["2.4GHz", "5GHz", "6GHz"]
PROFILES = [
    {"profile_id": "1", "name": "Kids"},
    {"profile_id": "2", "name": "Adults"},
    {"profile_id": "3", "name": "Guests"},
    {"profile_id": "4", "name": "IoT"},
]
_MANUFACTURERS = ["Apple", "Samsung", "Google", "Sonos", "Espressif", "Intel", "Amazon", "LG"]
_TYPES = ["phone", "laptop", "tablet", "speaker", "tv", "iot", "console", "watch"]
DEVICES = [
    {
        "device_id": f"d{i:02d}",
        "mac": f"02:00:00:00:00:{i:02x}",
        "name": f"{_TYPES[i % 8].title()} {i}",
        "manufacturer": _MANUFACTURERS[(i * 3) % 8],
        "device_type": _TYPES[i % 8],
        "connection_type": "wired" if i % 7 == 0 else "wireless",
        "source_eero": EEROS[i % 4]["location"],
        "band": BANDS[i % 3] if i % 5 else "5GHz",
        "profile": PROFILES[i % 4]["name"],
    }
    for i in range(1, 25)
]
FORWARDS = [
    {"forward_id": "f1", "gateway_port": "443", "protocol": "tcp"},
    {"forward_id": "f2", "gateway_port": "51820", "protocol": "udp"},
]

LABEL_VALUES: dict[str, list[str]] = {
    "source": ["internet", "eero_network"],
    "direction": ["download", "upload"],
    "capability": [
        "sqm",
        "wpa3",
        "block_apps",
        "eero_network",
        "network",
        "eeros",
        "amazon_account",
    ],
    "feature": ["ad_blocking", "content_filter", "dynamic_dns", "internet_backup", "malwarebytes"],
    "event": ["device_new", "network_updated", "network_datausagereport", "permissions_updates"],
    "verb": ["create", "read", "update", "delete"],
    "category": ["ads", "malware", "adult", "trackers"],
    "type": ["blocked", "adblock", "inspected"],
    "state": ["Active"],
    "family": ["ipv4", "ipv6"],
    "subnet_kind": ["main", "guest", "iot"],
    "subnet_type": ["main"],
    "mode": ["WPA2_WPA3"],
    "index": ["0", "1"],
    "status": ["connected"],
    "endpoint": [
        "network",
        "eeros",
        "devices",
        "profiles",
        "data_usage",
        "insights_blocked",
        "channel_utilization",
        "premium",
    ],
    "error_type": ["network", "api", "rate_limit"],
    "port_number": ["1", "2"],
    "port_name": ["eth0", "eth1"],
    "band": BANDS,
}
API_STATUS_SAMPLE = ["success", "not_found", "premium_required", "transport"]
PERIODS = [("day", "hourly"), ("week", "daily"), ("month", "daily")]

INFO_EXTRA: dict[str, dict[str, str]] = {
    "eero_network": {
        "name": "Home",
        "status": "connected",
        "isp": "Example ISP",
        "wan_type": "dhcp",
        "gateway_ip": "192.0.2.1",
    },
    "eero_network_timezone": {"timezone": "Europe/Lisbon"},
    "eero_network_wireless_mode": {"mode": "WIFI6E"},
    "eero_network_connection_mode": {"mode": "AUTOMATIC"},
    "eero_network_wan_type": {"type": "dhcp"},
    "eero_network_mlo_mode": {"mode": "auto"},
    "eero_network_dhcp_mode": {"mode": "automatic"},
    "eero_network_dns_mode": {"mode": "automatic"},
    "eero_dns_config": {"mode": "automatic"},
    "eero_network_update_target": {"version": "7.4.1"},
    "eero_guest_network": {"name": "Home Guest", "enabled": "true"},
    "eero_network_role": {"role": "standard-admin"},
    "eero_channel_info": {"frequency": "5745"},
    "eero_eero_role_info": {"role": "leaf"},
    "eero_device_subnet_kind": {"subnet_kind": "main"},
    "eero_eero_connection_type": {"connection_type": "WIRELESS"},
    "eero_eero_power_source": {"source": "AC"},
    "eero_ethernet_port_neighbor": {"neighbor_type": "eero", "neighbor_port": "eth1"},
}

_DEVICE_BY_ID = {d["device_id"]: d for d in DEVICES}
_EERO_BY_ID = {e["eero_id"]: e for e in EEROS}


def _device_info(labels: dict[str, str]) -> dict[str, str]:
    d = _DEVICE_BY_ID[labels["device_id"]]
    n = int(d["device_id"][1:])
    keys = ("name", "manufacturer", "device_type", "connection_type", "source_eero", "profile")
    return {
        **{k: d[k] for k in keys},
        "ip": f"192.0.2.{10 + n}",
        "hostname": d["name"].lower().replace(" ", "-"),
    }


def _eero_info(labels: dict[str, str]) -> dict[str, str]:
    e = _EERO_BY_ID[labels["eero_id"]]
    n = int(e["eero_id"]) - 1000
    return {
        "location": e["location"],
        "model": e["model"],
        "os_version": "7.4.1",
        "ip_address": f"192.0.2.{n}",
    }


ENTITY_INFO: dict[str, Callable[[dict[str, str]], dict[str, str]]] = {
    "eero_device": _device_info,
    "eero_eero": _eero_info,
    # Reviewed: opengrep's return-not-in-function misreads lambda bodies as a bare
    # `return` (a real one would be a SyntaxError), so each lambda carries a nosemgrep.
    # nosemgrep: python.lang.maintainability.return.return-not-in-function
    "eero_eero_os_version": lambda lab: {"version": "7.4.1", "model": "eero 6+"},
    # nosemgrep: python.lang.maintainability.return.return-not-in-function
    "eero_port_forward": lambda lab: {
        "description": {"f1": "Web server", "f2": "WireGuard"}[lab["forward_id"]],
        "client_port": {"f1": "443", "f2": "51820"}[lab["forward_id"]],
    },
    # nosemgrep: python.lang.maintainability.return.return-not-in-function
    "eero_channel_info": lambda lab: {
        "channel": {"2.4GHz": "6", "5GHz": "149", "6GHz": "37"}[lab["band"]],
        "center_channel": {"2.4GHz": "6", "5GHz": "155", "6GHz": "47"}[lab["band"]],
        "channel_bandwidth": {"2.4GHz": "20MHz", "5GHz": "80MHz", "6GHz": "160MHz"}[lab["band"]],
    },
    # nosemgrep: python.lang.maintainability.return.return-not-in-function
    "eero_ethernet_port": lambda lab: {"port_name": f"eth{int(lab['port_number']) - 1}"},
}

# ---------------------------------------------------------------------------
# Label sets
# ---------------------------------------------------------------------------


def _entities(name: str, labels: tuple[str, ...]) -> Iterator[dict[str, str]]:
    """Yield consistent label dicts for a metric's label names."""
    base: list[dict[str, str]] = [{}]
    if "device_id" in labels:
        base = [dict(d) for d in DEVICES]
    elif "eero_id" in labels:
        base = [dict(e) for e in EEROS]
        if "band" in labels:
            base = [dict(e, band=b) for e in base for b in BANDS]
    elif "profile_id" in labels:
        base = [dict(p) for p in PROFILES]
    elif "forward_id" in labels:
        base = [dict(f) for f in FORWARDS]
    free = [
        lab
        for lab in labels
        if lab not in {"network_id", "name"}
        and not any(lab in b for b in base)
        and lab not in {"period", "cadence"}
    ]
    periods: list[tuple[str, str] | None] = [None]
    if "period" in labels:
        # Only the network-level series has calendar periods; breakdowns are "current".
        periods = PERIODS if name == "eero_network_data_usage_bytes" else [("current", "hourly")]
    values = {lab: LABEL_VALUES.get(lab, ["x"]) for lab in free}
    if "endpoint" in labels:
        values["status"] = API_STATUS_SAMPLE
    for b, per, combo in product(base, periods, product(*values.values())):
        row = {k: v for k, v in b.items() if k in labels}
        if "network_id" in labels:
            row["network_id"] = NETWORK["network_id"]
        if "name" in labels:
            row["name"] = b.get("name", NETWORK["name"])
        if "location" in labels and "location" in b:
            row["location"] = b["location"]
        if per:
            row["period"], row["cadence"] = per
        row.update(dict(zip(free, combo, strict=True)))
        if "port_name" in row and "port_number" in row:
            if row["port_name"] != f"eth{int(row['port_number']) - 1}":
                continue
        yield row


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

ValueFn = Callable[[float, float], float]
"""f(t_fraction_of_day, seed) -> value."""


def _wave(lo: float, hi: float) -> ValueFn:
    def f(t: float, s: float) -> float:
        diurnal = 0.5 + 0.5 * math.sin(2 * math.pi * (t - 0.3) + s)
        # Reviewed: jitter for synthetic preview data, not a security-sensitive value.
        # nosemgrep: python_random_rule-random
        noise = random.uniform(-0.02, 0.02)  # nosec B311
        return round(lo + (hi - lo) * min(1.0, max(0.0, diurnal + noise)), 2)

    return f


def _flag(p_on: float, flips: bool = False) -> ValueFn:
    def f(t: float, s: float) -> float:
        on = (s * 7.3) % 1 < p_on
        if flips and 0.86 < t < 0.87 + (s % 0.02):
            on = not on
        return 1.0 if on else 0.0

    return f


def _const(lo: float, hi: float) -> ValueFn:
    return lambda t, s: float(int(lo + (hi - lo) * ((s * 3.7) % 1)))


def _value_fn(name: str) -> ValueFn:  # noqa: C901 - a flat lookup table
    if name.endswith("_timestamp_seconds"):
        now = time.time()
        if "next_renewal" in name:
            return lambda t, s: now + 200 * 86400
        return lambda t, s: now - 3600 * (1 + (s * 97) % 300)
    rules: list[tuple[str, ValueFn]] = [
        ("uptime_seconds", lambda t, s: 86400 * (3 + (s * 13) % 20) + t * 86400),
        ("speed_download_mbps", _wave(620, 910)),
        ("speed_upload_mbps", _wave(38, 46)),
        (
            "signal_strength_dbm",
            lambda t, s: round(-45 - 35 * ((s * 5.1) % 1) + 4 * math.sin(t * 20 + s), 1),
        ),
        ("noise_last", _wave(-96, -89)),
        ("tx_power_dbm", _const(18, 30)),
        ("_percent", _wave(4, 72)),
        ("busy_last", _wave(5, 60)),
        ("rx_tx_last", _wave(2, 35)),
        ("rx_other_last", _wave(1, 20)),
        (
            "bitrate_mbps",
            lambda t, s: round(86 + 1100 * ((s * 2.9) % 1) * (0.8 + 0.2 * math.sin(t * 9)), 1),
        ),
        ("speed_mbps", lambda t, s: 1000.0 if s % 2 < 1.5 else 100.0),
        ("frequency_mhz", lambda t, s: [2437.0, 5745.0, 6115.0][int(s) % 3]),
        ("width_mhz", lambda t, s: [20.0, 80.0, 160.0][int(s) % 3]),
        (
            "radio_channel",
            lambda t, s: (
                [6.0, 149.0, 37.0][int(s) % 3] if t < 0.7 else [1.0, 36.0, 37.0][int(s) % 3]
            ),
        ),
        ("device_channel", lambda t, s: [6.0, 149.0, 37.0][int(s) % 3]),
        ("_mcs", _const(5, 11)),
        ("_nss", _const(1, 4)),
        ("wifi_generation", _const(4, 8)),
        ("connection_score_bars", _const(2, 6)),
        ("connection_score", lambda t, s: round(0.4 + 0.6 * ((s * 1.7) % 1), 2)),
        ("mesh_quality_bars", lambda t, s: float(3 + int((s * 2.3) % 3))),
        ("brightness", _const(20, 100)),
        ("_ppm", _wave(100, 9000)),
        ("_packets", lambda t, s: 1e6 * (1 + s % 5) + t * 4e5),
        ("_drops", lambda t, s: 1e3 * (1 + s % 5) + t * 800),
        ("_retries", lambda t, s: 2e4 * (1 + s % 5) + t * 9000),
        ("data_usage_bytes", lambda t, s: 1e8 * (1 + (s * 1.3) % 6) * (0.2 + t)),
        ("download_bytes", lambda t, s: 4e9 * (1 + (s * 1.3) % 4) * (0.5 + t / 2)),
        ("upload_bytes", lambda t, s: 6e8 * (1 + (s * 1.3) % 4) * (0.5 + t / 2)),
        ("wired_clients_count", _wave(0, 3)),
        ("wireless_clients_count", _wave(3, 9)),
        ("eero_connected_clients_count", _wave(4, 11)),
        ("clients_count", _wave(18, 32)),
        ("client_count", _wave(1, 9)),
        ("connected_clients", _wave(0, 4)),
        ("eeros_count", lambda t, s: 4.0),
        ("networks_count", lambda t, s: 1.0),
        ("insights_", _wave(5, 400)),
        ("busy_minutes", _wave(0, 45)),
        ("acs_events", _const(0, 4)),
        ("scrape_duration_seconds", _wave(2.5, 6.5)),
        ("collection_interval_seconds", lambda t, s: 60.0),
        ("api_requests_last_cycle", lambda t, s: 29.0),
        ("radio_count", lambda t, s: 3.0),
        ("_count", _const(0, 9)),
        ("speed_tests_total", _const(1, 6)),
        ("eero_status", _flag(1.0, flips=True)),
        ("heartbeat_ok", _flag(1.0, flips=True)),
        ("network_status", _flag(1.0)),
        ("health_status", _flag(1.0, flips=True)),
        ("isp_up", _flag(1.0, flips=True)),
        ("eero_up", _flag(1.0, flips=True)),
        ("carrier", _flag(0.8, flips=True)),
        ("device_connected", _flag(0.85)),
        ("double_nat", _flag(0.0)),
        ("update_available", _flag(0.3)),
        ("open_network", _flag(0.3)),
        ("must_update", _flag(0.1)),
        ("unread", _flag(0.5)),
        ("conflicting_ssid", _flag(0.3)),
    ]
    for key, fn in rules:
        if key in name:
            return fn
    return _flag(0.6)  # remaining gauges are 0/1 flags


def _openmetrics_lines(start: float, end: float) -> Iterator[str]:
    from eero_exporter.metrics import describe_metrics

    random.seed(4)
    for m in describe_metrics():
        exposed = f"{m.name}_info" if m.type == "info" else m.name
        family = exposed.removesuffix("_total") if m.type == "counter" else exposed
        mtype = "counter" if m.type == "counter" else "gauge"
        yield f"# TYPE {family} {mtype}\n"
        extra = INFO_EXTRA.get(m.name, {}) if m.type == "info" else {}
        entity_info = ENTITY_INFO.get(m.name) if m.type == "info" else None
        fn = _value_fn(m.name)
        for idx, labels in enumerate(_entities(m.name, m.labels)):
            labels = {**labels, **extra, **(entity_info(labels) if entity_info else {})}
            if "subnet_kind" in labels and "subnet_type" in labels:
                labels["subnet_type"] = labels["subnet_kind"]
            lab = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
            seed = idx + 1 + (zlib.crc32(m.name.encode()) % 97) / 97
            total = 0.0
            t = start
            while t <= end:
                frac = ((t % 86400) / 86400) % 1
                if m.type == "info":
                    v = 1.0
                elif m.type == "counter":
                    rate = 0.05 if ("error" in m.name or labels.get("status") != "success") else 0.4
                    if labels.get("status") == "success":
                        rate *= 1 + (seed % 3)
                    # Reviewed: jitter for synthetic preview data, not security-sensitive.
                    # nosemgrep: python_random_rule-random
                    total += rate * STEP_S * random.uniform(0.6, 1.4)  # nosec B311
                    v = round(total)
                else:
                    v = fn(frac, seed)
                yield f"{exposed}{{{lab}}} {v} {int(t)}\n"
                t += STEP_S
    yield "# EOF\n"


def cmd_backfill(args: argparse.Namespace) -> None:
    """Write synthetic OpenMetrics and turn it into TSDB blocks with promtool."""
    prom = Path(args.prometheus).resolve()
    WORK.mkdir(parents=True, exist_ok=True)
    om = WORK / "synthetic.om"
    tsdb = WORK / "tsdb"
    shutil.rmtree(tsdb, ignore_errors=True)
    end = time.time() + LEAD_S
    start = end - HOURS * 3600 - LEAD_S
    with om.open("w") as fh:
        for line in _openmetrics_lines(start, end):
            fh.write(line)
    # Reviewed: binary from the operator's local --prometheus path; list argv, no shell.
    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit  # noqa: E501
    subprocess.run(  # nosec B603
        [
            str(prom / "promtool"),
            "tsdb",
            "create-blocks-from",
            "openmetrics",
            "--max-block-duration=24h",
            str(om),
            str(tsdb),
        ],
        check=True,
    )
    om.unlink()
    print(f"backfilled {tsdb}")


# ---------------------------------------------------------------------------
# Serve
# ---------------------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def cmd_serve(args: argparse.Namespace) -> None:
    """Start Prometheus (on the backfilled TSDB) and Grafana on 127.0.0.1."""
    prom = Path(args.prometheus).resolve()
    graf = Path(args.grafana).resolve()
    prov = WORK / "provisioning"
    _write(WORK / "prometheus.yml", "global:\n  scrape_interval: 1h\nscrape_configs: []\n")
    _write(
        prov / "datasources" / "prometheus.yml",
        "apiVersion: 1\ndatasources:\n  - name: Prometheus\n    type: prometheus\n"
        f"    access: proxy\n    url: http://127.0.0.1:{PROM_PORT}\n    isDefault: true\n"
        '    jsonData:\n      timeInterval: "120s"\n',
    )
    _write(
        prov / "dashboards" / "dashboards.yml",
        "apiVersion: 1\nproviders:\n  - name: eero\n    type: file\n"
        "    updateIntervalSeconds: 10\n"
        f"    options:\n      path: {REPO_ROOT / 'grafana'}\n",
    )
    for sub in ("plugins", "alerting", "notifiers"):
        (prov / sub).mkdir(parents=True, exist_ok=True)
    procs = [
        # Reviewed: binary from the operator's local --prometheus path; list argv, no shell.
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit  # noqa: E501
        subprocess.Popen(  # nosec B603
            [
                str(prom / "prometheus"),
                f"--config.file={WORK / 'prometheus.yml'}",
                f"--storage.tsdb.path={WORK / 'tsdb'}",
                "--storage.tsdb.retention.time=30d",
                f"--web.listen-address=127.0.0.1:{PROM_PORT}",
            ],
            stdout=(WORK / "prometheus.log").open("w"),
            stderr=subprocess.STDOUT,
        ),
        # Reviewed: binary from the operator's local --grafana path; list argv, no shell.
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit  # noqa: E501
        subprocess.Popen(  # nosec B603
            [str(graf / "bin" / "grafana"), "server", f"--homepath={graf}"],
            env={
                "PATH": "/usr/bin:/bin",
                "GF_PATHS_DATA": str(Path(args.grafana_data or WORK / "grafana-data").resolve()),
                "GF_PATHS_LOGS": str(WORK / "grafana-logs"),
                "GF_PATHS_PROVISIONING": str(prov),
                "GF_SERVER_HTTP_ADDR": "127.0.0.1",
                "GF_SERVER_HTTP_PORT": str(GRAFANA_PORT),
                "GF_AUTH_ANONYMOUS_ENABLED": "true",
                "GF_AUTH_ANONYMOUS_ORG_ROLE": "Viewer",
                "GF_AUTH_DISABLE_LOGIN_FORM": "true",
                "GF_ANALYTICS_REPORTING_ENABLED": "false",
                "GF_ANALYTICS_CHECK_FOR_UPDATES": "false",
                "GF_NEWS_NEWS_FEED_ENABLED": "false",
            },
            stdout=(WORK / "grafana.log").open("w"),
            stderr=subprocess.STDOUT,
        ),
    ]
    print(f"Prometheus http://127.0.0.1:{PROM_PORT}  Grafana http://127.0.0.1:{GRAFANA_PORT}")

    def stop(*_: Any) -> None:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=30)
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while all(p.poll() is None for p in procs):
        time.sleep(1)
    stop()


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------


def cmd_screenshot(args: argparse.Namespace) -> None:
    """Screenshot the provisioned dashboard via Playwright/Chromium.

    Grafana draws charts on canvases that stay blank in a very tall headless
    viewport, so the page is captured one screen at a time while scrolling
    (which also triggers Grafana's lazy panel loading) and stitched together.
    """
    from PIL import Image
    from playwright.sync_api import sync_playwright

    url = (
        f"http://127.0.0.1:{GRAFANA_PORT}/d/eero-mesh-network/?orgId=1"
        f"&from=now-{args.hours}h&to=now&theme={args.theme}&kiosk"
    )
    screen = 1000
    out = Path(args.out)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": args.width, "height": screen})
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector("[data-testid^='data-testid dashboard-row-toggle-for-']")
        for _ in range(30 if args.expand else 0):
            rows = page.locator(
                "button[data-testid^='data-testid dashboard-row-toggle-for-']"
                "[aria-expanded='false']"
            )
            if rows.count() == 0:
                break
            rows.first.click()
            page.wait_for_timeout(600)
        page.wait_for_timeout(args.settle_ms)
        height = page.evaluate("document.documentElement.scrollHeight")
        if args.max_height:
            height = min(height, args.max_height)
        tiles: list[tuple[int, Path]] = []
        top = 0
        while top < height:
            # Grafana ignores window.scrollTo(); a real wheel event scrolls it.
            page.mouse.move(args.width / 2, screen / 2)
            page.mouse.wheel(0, top - page.evaluate("window.scrollY"))
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(args.settle_ms)
            actual = page.evaluate("window.scrollY")
            # Hide fixed/sticky chrome (footer always, the top bar after the first
            # screen) so it does not get stitched into the middle of the page.
            # The kiosk "Powered by Grafana" badge is not position:fixed -- it is
            # anchored inside the scroll container -- so it has to be matched by
            # its text; left visible it overlays the bottom of each tile and cuts
            # through whichever panel sits under the seam.
            page.evaluate(
                """(first) => { for (const e of document.querySelectorAll('body *')) {
                    const pos = getComputedStyle(e).position;
                    const bar = String(e.className).includes('dashboard-controls');
                    const r = e.getBoundingClientRect();
                    const badge = r.height < 80 && r.width < 400 &&
                        (e.textContent || '').trim().startsWith('Powered by');
                    if (((pos === 'fixed' || pos === 'sticky') && r.top > 100) ||
                        (bar && !first) || badge) {
                        e.style.visibility = 'hidden';
                    } } }""",
                not tiles,
            )
            tile = out.with_suffix(f".tile{len(tiles)}.png")
            page.screenshot(path=str(tile))
            tiles.append((actual, tile))
            if args.viewport_only or actual + screen >= height:
                break
            top += screen
        browser.close()
    canvas = Image.new("RGB", (args.width, min(height, tiles[-1][0] + screen)))
    for offset, tile in tiles:
        canvas.paste(Image.open(tile), (0, offset))
        tile.unlink()
    canvas.save(out, optimize=True)
    print(f"wrote {out} ({canvas.size[0]}x{canvas.size[1]})")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill", help="generate synthetic samples into a TSDB")
    b.add_argument("--prometheus", required=True, help="unpacked Prometheus directory")
    s = sub.add_parser("serve", help="run Prometheus + Grafana on 127.0.0.1 until Ctrl-C")
    s.add_argument("--prometheus", required=True)
    s.add_argument("--grafana", required=True, help="unpacked Grafana OSS directory")
    s.add_argument(
        "--grafana-data",
        help="Grafana state dir (SQLite); put it on local disk if the repo is on a network FS",
    )
    sh = sub.add_parser("screenshot", help="screenshot the running dashboard")
    sh.add_argument("--out", required=True)
    sh.add_argument("--hours", type=int, default=6)
    sh.add_argument("--width", type=int, default=1600)
    sh.add_argument("--theme", default="dark", choices=["dark", "light"])
    sh.add_argument("--expand", action="store_true", help="expand every collapsed row")
    sh.add_argument("--viewport-only", action="store_true", help="first screen only")
    sh.add_argument("--settle-ms", type=int, default=2500, help="wait per screen")
    sh.add_argument("--max-height", type=int, default=0, help="crop to this many pixels")
    sh.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    {"backfill": cmd_backfill, "serve": cmd_serve, "screenshot": cmd_screenshot}[args.cmd](args)


if __name__ == "__main__":
    main()
