#!/usr/bin/env python3
"""Render ``wiki/Metrics.md`` from the metrics registry.

Every table in the generated page comes from
:func:`eero_exporter.metrics.describe_metrics` (name, type, labels, tier,
family, source path, evidence level), so the wiki cannot drift from the code:
``tests/test_metrics_doc.py`` asserts the committed page equals this
script's output.

Usage::

    uv run python scripts/gen_metrics_doc.py            # rewrite wiki/Metrics.md
    uv run python scripts/gen_metrics_doc.py --stdout   # print instead
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eero_exporter import metrics as m
from eero_exporter.metrics import MetricProvenance

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "wiki" / "Metrics.md"

# ---------------------------------------------------------------------------
# Presentation metadata. Everything that is *data* (names, labels, tiers,
# sources) comes from the registry; this block only holds prose and ordering.
# The generator refuses to run if a family, tier or removed metric is missing
# from these maps, so adding one to metrics.py forces a docs update.
# ---------------------------------------------------------------------------

#: Display order and titles for the per-resource sections.
FAMILY_TITLES: dict[str, str] = {
    "exporter": "Exporter self-observability",
    "account": "Account",
    "network": "Network identity, health and speed test",
    "network_features": "Network settings and feature flags",
    "network_capabilities": "Network capabilities",
    "guest": "Guest network",
    "eeros": "Eero nodes",
    "radio": "Eero radios (per band)",
    "ethernet": "Ethernet ports",
    "devices": "Client devices",
    "profiles": "Profiles",
    "data_usage": "Data usage",
    "insights": "Insights (eero Secure)",
    "port_forwards": "Port forwards",
    "reservations": "DHCP reservations",
    "blacklist": "Blocked devices",
    "entitlements": "Entitlements and subscription",
    "security": "Wireless security",
    "permissions": "Account permissions",
    "members": "Network members",
    "notifications": "Notification settings",
    "dns_policy": "DNS policy (eero Secure)",
    "subnets": "Subnets",
    "profile_insights": "Profile insights",
    "rf": "RF channel utilisation",
    "per_profile": "Per-profile reads",
    "per_device": "Per-device reads",
    "device_insights": "Device insights",
    "per_eero": "Per-eero reads",
    "unverified": "Unverified-shape families",
}

#: Tier -> (enabling flag, default, cost note). Costs are GETs per network per
#: collection cycle as measured by ``tests/test_collector_readonly.py`` and
#: the ``EeroCollector.collect()`` docstring for the probed mesh
#: (4 eeros, 137 devices, 10 profiles).
TIER_TABLE: dict[str, tuple[str, str, str]] = {
    "core": (
        "per-family `--include-*` flags",
        "on",
        "about 16 GETs: account + networks (2), network envelope, eeros, devices, profiles, "
        "data usage (one per period + one breakdown), insights (3), port forwards, "
        "reservations, blacklist",
    ),
    "extended": (
        "`--include-extended`",
        "on",
        "+12 GETs, fixed cost: entitlements, WPA3 per band, fast transition, permissions, "
        "members, notification settings, unread flag, DNS content filter, subnets, "
        "profile insights (3)",
    ),
    "rf": (
        "`--include-rf`",
        "on",
        "+1 GET: a single unparameterised channel-utilisation call covering every eero and band",
    ),
    "per_profile": (
        "`--include-per-profile`",
        "off",
        "+1 GET per profile (DNS policy applications, needs eero Secure)",
    ),
    "per_device": (
        "`--include-per-device`",
        "off",
        "+3 GETs (list-level device insights, one per insight type); high series cardinality "
        "on large meshes",
    ),
    "per_eero": (
        "`--include-per-eero`",
        "off",
        "+3 GETs per eero: nightlight (Beacon only), connections, OUI check",
    ),
    "unverified": (
        "`--include-unverified`",
        "off",
        "+12 GETs: families whose payload was empty or absent on the probed mesh; parsers are "
        "defensive and log the observed keys at DEBUG",
    ),
}

#: ``eero_exporter_api_requests_total{status}`` -- the closed vocabulary from
#: :data:`eero_exporter.metrics.API_STATUS_VALUES` with its meaning.
STATUS_MEANINGS: dict[str, str] = {
    "success": "The request completed and its payload was parsed.",
    "error": "A generic API error not mapped to a more specific class (for example a blocked "
    "client version, or an unrecognised domain error).",
    "auth": "HTTP 401 that the SDK could not refresh. The network scrape is aborted, `eero_up` "
    "drops to 0 and the session file is deleted by the SDK; run `eero-exporter login` again.",
    "not_found": "HTTP 404 -- the resource or feature does not exist on this network. An "
    "expected state (for example `multistaticip` on most meshes), not an error.",
    "access_denied": "HTTP 403 -- the account role lacks the permission "
    "(see `eero_network_permission`).",
    "premium_required": "The endpoint needs an eero Plus/Secure subscription. An expected state.",
    "feature_unavailable": "The eero is offline or the feature does not exist on this hardware "
    "(for example nightlight on a non-Beacon node). An expected state.",
    "rate_limited": "HTTP 429 or `error.rate.limit`. Increase `--interval` or disable optional "
    "tiers.",
    "validation": "The SDK rejected an argument before sending, or the API returned a 400 "
    "form error. Usually a malformed identifier -- please report it.",
    "transport": "DNS failure, connection error or timeout. Transient; the bounded "
    "`--get-retries` applies.",
}

#: Removed metric -> (replacement or "", reason).
REMOVED_METRICS: dict[str, tuple[str, str]] = {
    "eero_eero_memory_usage_percent": ("", "No such field on the eero resource."),
    "eero_eero_temperature_celsius": ("", "No such field on the eero resource."),
    "eero_eero_backup_connection": ("", "No such field on the eero resource."),
    "eero_device_prioritized": ("", "The API has no `prioritized` field."),
    "eero_device_signal_strength_avg_dbm": (
        "",
        "`connectivity.signal_avg` is null on every device.",
    ),
    "eero_device_rx_bandwidth_mhz": ("", "No such field on the device resource."),
    "eero_device_tx_bandwidth_mhz": ("", "No such field on the device resource."),
    "eero_device_adblock_enabled": (
        "eero_network_ad_block_enabled",
        "Ad blocking is a network-level setting; no per-device field exists.",
    ),
    "eero_sqm_upload_bandwidth_mbps": (
        "eero_network_sqm_enabled",
        "SQM is a single boolean in the API.",
    ),
    "eero_sqm_download_bandwidth_mbps": (
        "eero_network_sqm_enabled",
        "SQM is a single boolean in the API.",
    ),
    "eero_guest_network_access_duration_enabled": (
        "",
        "The guest network object has only `enabled`, `name` and `password`.",
    ),
    "eero_network_auto_update_enabled": (
        "eero_network_update_available",
        "No `auto_update` field; the updates object carries `has_update`.",
    ),
    "eero_security_threats_blocked_total": (
        "eero_insights_blocked_total",
        "Never populated; insights cover blocked threats by category.",
    ),
    "eero_security_scans_blocked_total": (
        "eero_insights_blocked_total",
        "Never populated; insights cover blocked threats by category.",
    ),
    "eero_ethernet_port_power_saving": (
        "",
        "Never populated by the 3.x parser and dropped with the Ethernet family rewrite.",
    ),
    "eero_exporter_scrape_success": (
        "eero_up",
        "Deprecated since 3.x; `eero_up` and `eero_exporter_scrape_errors_total` cover it.",
    ),
    "eero_network_download_bytes_total": (
        "eero_network_data_usage_bytes",
        "Transfer statistics are inaccessible (403/404); use the data-usage family.",
    ),
    "eero_network_upload_bytes_total": (
        "eero_network_data_usage_bytes",
        "Transfer statistics are inaccessible (403/404); use the data-usage family.",
    ),
    "eero_device_download_bytes_total": (
        "eero_device_data_usage_bytes",
        "Transfer statistics are inaccessible (403/404); use the data-usage family.",
    ),
    "eero_device_upload_bytes_total": (
        "eero_device_data_usage_bytes",
        "Transfer statistics are inaccessible (403/404); use the data-usage family.",
    ),
    "eero_eero_rx_bytes_total": (
        "eero_eero_data_usage_bytes",
        "Transfer statistics are inaccessible (403/404); use the data-usage family.",
    ),
    "eero_eero_tx_bytes_total": (
        "eero_eero_data_usage_bytes",
        "Transfer statistics are inaccessible (403/404); use the data-usage family.",
    ),
    "eero_diagnostics_internet_latency_ms": (
        "",
        "`get_diagnostics` returns `{status}` only; results need a write-triggered run.",
    ),
    "eero_diagnostics_dns_latency_ms": (
        "",
        "`get_diagnostics` returns `{status}` only; results need a write-triggered run.",
    ),
    "eero_diagnostics_gateway_latency_ms": (
        "",
        "`get_diagnostics` returns `{status}` only; results need a write-triggered run.",
    ),
    "eero_diagnostics_last_run_timestamp_seconds": (
        "",
        "`get_diagnostics` returns `{status}` only; results need a write-triggered run.",
    ),
    "eero_thread_device_count": (
        "eero_network_thread_enabled",
        "`get_thread` carries no device count (mostly key material).",
    ),
    "eero_thread_border_router": (
        "eero_network_thread_enabled",
        "`get_thread` carries no border-router field.",
    ),
    "eero_eero_nightlight_ambient_enabled": (
        "",
        "`ambient_light_enabled` is a pre-v8 key that no longer exists.",
    ),
    "eero_backup_enabled": (
        "eero_network_backup_internet_enabled",
        "The backup endpoints were removed from the SDK and never returned data.",
    ),
    "eero_backup_active": (
        "",
        "The backup endpoints were removed from the SDK and never returned data.",
    ),
    "eero_backup_connected": (
        "eero_backup_access_point_connectivity_info (unverified tier)",
        "The backup endpoints were removed from the SDK and never returned data.",
    ),
    "eero_backup_data_used_bytes_total": (
        "eero_cellular_backup_usage_items_count (unverified tier)",
        "The backup endpoints were removed from the SDK and never returned data.",
    ),
    "eero_backup_signal_strength": (
        "",
        "The backup endpoints were removed from the SDK and never returned data.",
    ),
    "eero_account_premium_expiration_timestamp_seconds": (
        "eero_account_premium_next_renewal_timestamp_seconds",
        "Renamed: the field is the next billing/renewal date, not an expiry.",
    ),
    "eero_data_usage_active_clients": (
        "eero_network_clients_count",
        "`get_data_usage` has no `totals` object; the value never populated.",
    ),
}

PROMQL_EXAMPLES = """\
```promql
# Is the exporter collecting successfully?
eero_up == 1

# API calls that did not succeed, by endpoint and status (5m rate)
sum by (endpoint, status) (rate(eero_exporter_api_requests_total{status!="success"}[5m]))

# Expected non-success states you can ignore on most meshes
eero_exporter_api_requests_total{status=~"premium_required|feature_unavailable|not_found"}

# Requests issued per collection cycle (watch the ~100 req/min API limit)
eero_exporter_api_requests_last_cycle

# Eeros with a firmware update pending
eero_eero_update_available == 1

# Devices with a weak signal
eero_device_signal_strength_dbm < -70

# Busiest radios in the mesh (per eero and band)
topk(5, eero_eero_radio_channel_utilization_percent)

# Daily download per device, top 10
topk(10, eero_device_data_usage_bytes{period="day", direction="download"})

# Which eero Secure features is the network entitled to?
eero_network_feature_entitled == 1
```"""


def _tick(value: str) -> str:
    """Wrap a value in backticks, escaping pipes for Markdown tables."""
    return f"`{value.replace('|', '\\|')}`"


def _labels(labels: tuple[str, ...]) -> str:
    return ", ".join(_tick(label) for label in labels) if labels else "-"


def _validate(rows: list[MetricProvenance]) -> None:
    """Fail loudly when the registry has something this page does not describe."""
    families = {row.family for row in rows}
    missing_families = families - FAMILY_TITLES.keys()
    if missing_families:
        raise SystemExit(f"FAMILY_TITLES lacks: {sorted(missing_families)}")

    tiers = set(m.FAMILY_TIER.values())
    missing_tiers = tiers - TIER_TABLE.keys()
    if missing_tiers:
        raise SystemExit(f"TIER_TABLE lacks: {sorted(missing_tiers)}")

    missing_status = set(m.API_STATUS_VALUES) - STATUS_MEANINGS.keys()
    extra_status = STATUS_MEANINGS.keys() - set(m.API_STATUS_VALUES)
    if missing_status or extra_status:
        raise SystemExit(
            f"STATUS_MEANINGS out of sync: missing={sorted(missing_status)} "
            f"extra={sorted(extra_status)}"
        )

    missing_removed = set(m.REMOVED_IN_4_0_0) - REMOVED_METRICS.keys()
    extra_removed = REMOVED_METRICS.keys() - set(m.REMOVED_IN_4_0_0)
    if missing_removed or extra_removed:
        raise SystemExit(
            f"REMOVED_METRICS out of sync: missing={sorted(missing_removed)} "
            f"extra={sorted(extra_removed)}"
        )


def _family_order(rows: list[MetricProvenance]) -> list[str]:
    present = {row.family for row in rows}
    return [family for family in FAMILY_TITLES if family in present]


def _anchor(title: str) -> str:
    """GitHub-style heading anchor."""
    keep = "".join(ch for ch in title.lower() if ch.isalnum() or ch in " -")
    return keep.replace(" ", "-")


def render() -> str:
    """Build the whole Markdown page."""
    rows = m.describe_metrics()
    _validate(rows)

    by_family: dict[str, list[MetricProvenance]] = {}
    for row in rows:
        by_family.setdefault(row.family, []).append(row)

    tier_counts: dict[str, int] = {}
    for row in rows:
        tier_counts[row.tier] = tier_counts.get(row.tier, 0) + 1

    out: list[str] = []
    out.append("# Metrics Reference")
    out.append("")
    out.append(
        "<!-- GENERATED FILE: do not edit by hand. Regenerate with "
        "`uv run python scripts/gen_metrics_doc.py`; tests/test_metrics_doc.py "
        "fails when this page and src/eero_exporter/metrics.py drift. -->"
    )
    out.append("")
    out.append(
        f"The exporter declares **{len(rows)} metrics** in {len(by_family)} resource families. "
        "Every metric is read from the eero cloud API with GET requests only; the exporter "
        "never changes anything on your network."
    )
    out.append("")
    out.append(
        "Each table lists the metric name, its Prometheus type, labels, the collection tier "
        "that has to be enabled for it to be exposed, the evidence level for its source, and "
        "the API path it is read from. Metrics whose family is disabled do not appear on "
        "`/metrics` at all (no empty `# HELP` lines)."
    )
    out.append("")
    out.append("**Evidence levels**")
    out.append("")
    out.append("| Level | Meaning |")
    out.append("|---|---|")
    out.append(
        "| `verified` | The path was observed on a live mesh by the read-only probe and "
        "parses as declared. |"
    )
    out.append(
        "| `documented` | The path is named in the eero-api SDK or its wiki but was empty or "
        "absent on the probed mesh. |"
    )
    out.append(
        "| `inferred` | Kept from a pre-4.0.0 metric whose exact path was not re-verified by "
        "the probe; parsed defensively. |"
    )
    out.append("")

    # -- tiers ---------------------------------------------------------------
    out.append("## Collection tiers")
    out.append("")
    out.append(
        "Families are grouped into tiers. A tier is enabled with one `serve` flag "
        "(or its `EERO_EXPORTER_*` environment variable / YAML key -- see "
        "[Configuration](Configuration)). GET counts are per network per collection cycle "
        "on the reference mesh (4 eeros, 137 devices, 10 profiles): **29 with the defaults**, "
        "**66 with every tier on**. The eero API allows roughly 100 requests per minute."
    )
    out.append("")
    out.append("| Tier | Enable with | Default | Metrics | Cost per cycle |")
    out.append("|---|---|---|---:|---|")
    for tier, (flag, default, cost) in TIER_TABLE.items():
        out.append(f"| `{tier}` | {flag} | {default} | {tier_counts.get(tier, 0)} | {cost} |")
    out.append("")
    gated_present = sorted(
        (family, flag) for family, flag in m._FAMILY_INCLUDE_FLAG.items() if family in by_family
    )
    gated_absent = sorted(
        flag for family, flag in m._FAMILY_INCLUDE_FLAG.items() if family not in by_family
    )
    out.append(
        "Core families with their own flag: "
        + ", ".join(f"`{family}` (`--{flag.replace('_', '-')}`)" for family, flag in gated_present)
        + ". Every other core family is always on."
    )
    if gated_absent:
        out.append("")
        out.append(
            "Flags that gate reads inside other families rather than a family of their own: "
            + ", ".join(f"`--{flag.replace('_', '-')}`" for flag in gated_absent)
            + " (`--no-premium` skips the premium sub-collector and the eero Secure DNS "
            "content-filter read; `--include-thread` is accepted for compatibility but gates "
            "nothing in 4.0.0 -- the Thread read lives in the `unverified` tier)."
        )
    out.append("")

    # -- table of contents ---------------------------------------------------
    out.append("## Table of contents")
    out.append("")
    for family in _family_order(rows):
        title = FAMILY_TITLES[family]
        out.append(f"- [{title}](#{_anchor(title)}) ({len(by_family[family])})")
    out.append("- [`eero_exporter_api_requests_total{status}` values](#api-request-status-values)")
    out.append("- [PromQL examples](#promql-examples)")
    out.append("- [Removed in 4.0.0](#removed-in-400)")
    out.append("")

    # -- per-family tables ---------------------------------------------------
    for family in _family_order(rows):
        title = FAMILY_TITLES[family]
        tier = m.FAMILY_TIER[family]
        out.append(f"## {title}")
        out.append("")
        gate = m._FAMILY_INCLUDE_FLAG.get(family)
        if tier == "core" and gate:
            out.append(
                f"Family `{family}` -- tier `core`, toggled by `--{gate.replace('_', '-')}` "
                f"(default on)."
            )
        elif tier == "core":
            out.append(f"Family `{family}` -- tier `core`, always on.")
        else:
            flag, default, _ = TIER_TABLE[tier]
            out.append(
                f"Family `{family}` -- tier `{tier}`, enabled with {flag} (default {default})."
            )
        out.append("")
        out.append("| Metric | Type | Labels | Tier | Evidence | Source |")
        out.append("|---|---|---|---|---|---|")
        for row in sorted(by_family[family], key=lambda r: r.name):
            out.append(
                f"| {_tick(row.name)} | {row.type} | {_labels(row.labels)} | `{row.tier}` | "
                f"`{row.evidence}` | {_tick(row.source)} |"
            )
        out.append("")

    # -- status enum ---------------------------------------------------------
    out.append("## API request status values")
    out.append("")
    out.append(
        "`eero_exporter_api_requests_total{endpoint,status}` uses a closed `status` vocabulary "
        "derived from the exception class the adapter raised -- never from message text, and "
        'never the raw API `error_code`. Sum failures with `status!="success"`; the three '
        "expected states below are not failures."
    )
    out.append("")
    out.append("| `status` | Meaning |")
    out.append("|---|---|")
    for status in sorted(m.API_STATUS_VALUES):
        out.append(f"| `{status}` | {STATUS_MEANINGS[status]} |")
    out.append("")
    out.append(
        "`eero_exporter_scrape_errors_total{error_type}` counts whole-cycle failures with "
        "`error_type` in `auth`, `api`, `network`, `rate_limit` or `unknown`."
    )
    out.append("")

    # -- PromQL --------------------------------------------------------------
    out.append("## PromQL examples")
    out.append("")
    out.append(PROMQL_EXAMPLES)
    out.append("")

    # -- removed -------------------------------------------------------------
    out.append("## Removed in 4.0.0")
    out.append("")
    out.append(
        f"These {len(m.REMOVED_IN_4_0_0)} metric names no longer exist. Each had no source in "
        "the eero API (most never produced a sample) or was renamed. Update dashboards and "
        "alerts that reference them."
    )
    out.append("")
    out.append("| Removed metric | Replacement | Reason |")
    out.append("|---|---|---|")
    for name in sorted(m.REMOVED_IN_4_0_0):
        replacement, reason = REMOVED_METRICS[name]
        out.append(f"| {_tick(name)} | {_tick(replacement) if replacement else '-'} | {reason} |")
    out.append("")
    out.append(
        "Also removed: the `original_speed` and `derated_reason` fields of "
        "`eero_ethernet_port_info` (always null), the `endpoint` values `backup`, "
        "`backup_status`, `premium` and `sqm` on `eero_exporter_api_requests_total` "
        '(those reads were folded into the network envelope), and the `status="error"` '
        "catch-all semantics -- see the status table above."
    )
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout", action="store_true", help="print instead of writing")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    text = render()
    if args.stdout:
        sys.stdout.write(text)
        return 0
    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {args.output} ({len(m.describe_metrics())} metrics)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
