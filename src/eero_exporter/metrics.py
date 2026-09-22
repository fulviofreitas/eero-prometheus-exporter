"""Prometheus metrics definitions for Eero Exporter.

Reorganised (4.0.0, commit 4) by API resource and collection tier. Every
metric is declared through :func:`_gauge`/:func:`_counter`/:func:`_info`,
which records its family, tier, source path, and evidence level in
:data:`_METRIC_PROVENANCE` (read via :func:`describe_metrics`) and appends the
metric object to :data:`_FAMILY_METRICS` (consumed by :func:`register_metrics`
for tier gating).

Metrics are created **unregistered** (``registry=None``): the collector can
set them at any time regardless of whether they are currently exposed, and
:func:`register_metrics` decides -- based on :class:`~eero_exporter.config.
ExporterConfig` -- which families actually get registered into the
Prometheus registry that ``/metrics`` renders. This keeps disabled tiers/
families out of the exposition entirely (no empty ``# HELP`` lines) without
the collector needing any tier-awareness of its own.

See ``claude/tasks/probes/2026-09-21-shape-summary.md`` (the v8 probe shape
summary) for the source of truth on which metrics have a real API source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from prometheus_client import REGISTRY, Counter, Gauge, Info

# Metric prefix
PREFIX = "eero"

# =============================================================================
# Provenance / tier-gating machinery
# =============================================================================

#: The closed vocabulary of collection tiers a metric family can belong to.
#: "core" families are always registered (subject to their own per-family
#: ``include_*`` flag); every other tier is gated by the matching
#: ``ExporterConfig.include_<tier>`` flag.
TierName = str

#: family name -> tier name. Every family declared below must have an entry
#: here. In this commit every kept family is "core" -- no metric yet lives in
#: extended/rf/per_profile/per_device/per_eero/unverified; those tiers exist
#: in `ExporterConfig` ahead of the families that will populate them.
FAMILY_TIER: dict[str, TierName] = {}

#: metric name -> family name, for every declared metric.
METRIC_FAMILY: dict[str, str] = {}

#: The `ExporterConfig` boolean field gating each non-core tier.
_TIER_INCLUDE_FLAG: dict[str, str] = {
    "extended": "include_extended",
    "rf": "include_rf",
    "per_profile": "include_per_profile",
    "per_device": "include_per_device",
    "per_eero": "include_per_eero",
    "unverified": "include_unverified",
}

#: The `ExporterConfig` boolean field gating each core-tier family that has
#: its own dedicated toggle. Core families with no entry here are always on.
_FAMILY_INCLUDE_FLAG: dict[str, str] = {
    "devices": "include_devices",
    "profiles": "include_profiles",
    "data_usage": "include_data_usage",
    "premium": "include_premium",
    "ethernet": "include_ethernet",
    "thread": "include_thread",
    "port_forwards": "include_port_forwards",
    "reservations": "include_reservations",
    "blacklist": "include_blacklist",
    "insights": "include_insights",
}


@dataclass(frozen=True)
class MetricProvenance:
    """Where one declared metric's value comes from, for docs generation."""

    name: str
    type: str
    labels: tuple[str, ...]
    tier: TierName
    family: str
    source: str
    evidence: str


#: metric name -> its provenance record. Populated by `_gauge`/`_counter`/`_info`.
_METRIC_PROVENANCE: dict[str, MetricProvenance] = {}

#: family name -> the metric objects declared under it, in declaration order.
_FAMILY_METRICS: dict[str, list[Any]] = {}


def _register_family(family: str, tier: TierName) -> None:
    FAMILY_TIER.setdefault(family, tier)
    _FAMILY_METRICS.setdefault(family, [])


def _declare(
    cls: type,
    name: str,
    doc: str,
    labelnames: tuple[str, ...] = (),
    *,
    family: str,
    source: str,
    evidence: str = "verified",
    tier: TierName = "core",
) -> Any:
    """Create one Prometheus metric object and record its provenance.

    Args:
        cls: ``Gauge``, ``Counter``, or ``Info``.
        name: Full metric name, e.g. ``f"{PREFIX}_up"``.
        doc: Human-readable HELP text.
        labelnames: Label names, if any.
        family: The resource family this metric belongs to (organisational
            grouping, drives tier gating alongside ``tier``).
        source: The API path this metric's value is read from, e.g.
            ``"network.data.dns.caching"``.
        evidence: One of ``"verified"`` (path observed live and parseable),
            ``"documented"`` (SDK/API docs only), or ``"inferred"`` (kept from
            a pre-v8 metric whose exact source path was not directly
            re-verified by the v8 probe).
        tier: The collection tier this metric's family belongs to.

    Returns:
        The created (unregistered -- ``registry=None``) metric object.
    """
    _register_family(family, tier)
    metric = cls(name, doc, labelnames=list(labelnames), registry=None)
    _METRIC_PROVENANCE[name] = MetricProvenance(
        name=name,
        type=cls.__name__.lower(),
        labels=tuple(labelnames),
        tier=tier,
        family=family,
        source=source,
        evidence=evidence,
    )
    METRIC_FAMILY[name] = family
    _FAMILY_METRICS[family].append(metric)
    return metric


def _gauge(
    name: str,
    doc: str,
    labelnames: tuple[str, ...] = (),
    *,
    family: str,
    source: str,
    evidence: str = "verified",
    tier: TierName = "core",
) -> Gauge:
    return cast(
        Gauge,
        _declare(
            Gauge, name, doc, labelnames, family=family, source=source, evidence=evidence, tier=tier
        ),
    )


def _counter(
    name: str,
    doc: str,
    labelnames: tuple[str, ...] = (),
    *,
    family: str,
    source: str,
    evidence: str = "verified",
    tier: TierName = "core",
) -> Counter:
    return cast(
        Counter,
        _declare(
            Counter,
            name,
            doc,
            labelnames,
            family=family,
            source=source,
            evidence=evidence,
            tier=tier,
        ),
    )


def _info(
    name: str,
    doc: str,
    labelnames: tuple[str, ...] = (),
    *,
    family: str,
    source: str,
    evidence: str = "verified",
    tier: TierName = "core",
) -> Info:
    return cast(
        Info,
        _declare(
            Info, name, doc, labelnames, family=family, source=source, evidence=evidence, tier=tier
        ),
    )


# =============================================================================
# REMOVED IN 4.0.0 (BREAKING) -- families with no eero-api v8 source.
#
# See claude/tasks/probes/2026-09-21-shape-summary.md §11.11 and the v8
# migration plan §5.1 "Removed (BREAKING)" table. Every name here must NOT
# exist as a metric object below.
# =============================================================================

REMOVED_IN_4_0_0: frozenset[str] = frozenset(
    {
        f"{PREFIX}_eero_memory_usage_percent",
        f"{PREFIX}_eero_temperature_celsius",
        f"{PREFIX}_eero_backup_connection",
        f"{PREFIX}_device_prioritized",
        f"{PREFIX}_device_signal_strength_avg_dbm",
        f"{PREFIX}_device_rx_bandwidth_mhz",
        f"{PREFIX}_device_tx_bandwidth_mhz",
        f"{PREFIX}_device_adblock_enabled",
        f"{PREFIX}_sqm_upload_bandwidth_mbps",
        f"{PREFIX}_sqm_download_bandwidth_mbps",
        f"{PREFIX}_guest_network_access_duration_enabled",
        f"{PREFIX}_network_auto_update_enabled",
        f"{PREFIX}_security_threats_blocked_total",
        f"{PREFIX}_security_scans_blocked_total",
        f"{PREFIX}_ethernet_port_power_saving",
        f"{PREFIX}_exporter_scrape_success",
        f"{PREFIX}_network_download_bytes_total",
        f"{PREFIX}_network_upload_bytes_total",
        f"{PREFIX}_device_download_bytes_total",
        f"{PREFIX}_device_upload_bytes_total",
        f"{PREFIX}_eero_rx_bytes_total",
        f"{PREFIX}_eero_tx_bytes_total",
        f"{PREFIX}_diagnostics_internet_latency_ms",
        f"{PREFIX}_diagnostics_dns_latency_ms",
        f"{PREFIX}_diagnostics_gateway_latency_ms",
        f"{PREFIX}_diagnostics_last_run_timestamp_seconds",
        f"{PREFIX}_thread_device_count",
        f"{PREFIX}_thread_border_router",
        f"{PREFIX}_eero_nightlight_ambient_enabled",
        f"{PREFIX}_backup_enabled",
        f"{PREFIX}_backup_active",
        f"{PREFIX}_backup_connected",
        f"{PREFIX}_backup_data_used_bytes_total",
        f"{PREFIX}_backup_signal_strength",
        # Renamed in commit 6: the field is a renewal date, not an expiry
        # date -- see ACCOUNT_PREMIUM_NEXT_RENEWAL.
        f"{PREFIX}_account_premium_expiration_timestamp_seconds",
    }
)

# =============================================================================
# EXPORTER -- self-observability, no eero API source
# =============================================================================

EERO_UP = _gauge(
    f"{PREFIX}_up",
    "Whether the eero API is reachable and the last scrape was successful (1=up, 0=down)",
    family="exporter",
    source="derived: collect() outcome",
    evidence="verified",
)

EXPORTER_SCRAPE_DURATION = _gauge(
    f"{PREFIX}_exporter_scrape_duration_seconds",
    "Time taken to collect metrics from eero API",
    family="exporter",
    source="derived: collect() wall-clock duration",
    evidence="verified",
)

EXPORTER_LAST_COLLECTION_TIMESTAMP = _gauge(
    f"{PREFIX}_exporter_last_collection_timestamp_seconds",
    "Unix timestamp of the last successful metrics collection. "
    "Metrics are cached between collections per Prometheus guidelines for expensive APIs.",
    family="exporter",
    source="derived: collect() wall-clock time",
    evidence="verified",
)

EXPORTER_COLLECTION_INTERVAL = _gauge(
    f"{PREFIX}_exporter_collection_interval_seconds",
    "Configured collection interval in seconds. Prometheus scrapes may receive cached data.",
    family="exporter",
    source="derived: ExporterConfig.collection_interval",
    evidence="verified",
)

EXPORTER_SCRAPE_ERRORS = _counter(
    f"{PREFIX}_exporter_scrape_errors_total",
    "Total number of scrape errors",
    ("error_type",),
    family="exporter",
    source="derived: collect() exception classification",
    evidence="verified",
)

EXPORTER_API_REQUESTS = _counter(
    f"{PREFIX}_exporter_api_requests_total",
    "Total number of API requests made",
    ("endpoint", "status"),
    family="exporter",
    source="derived: _record_api_result()",
    evidence="verified",
)

# The complete, closed vocabulary for EXPORTER_API_REQUESTS's `status` label.
# `_record_api_result` in collector.py never emits anything outside this set
# -- see tests/test_collector_api_status.py.
API_STATUS_VALUES: frozenset[str] = frozenset(
    {
        "success",
        "error",
        "auth",
        "not_found",
        "access_denied",
        "premium_required",
        "feature_unavailable",
        "rate_limited",
        "validation",
        "transport",
    }
)

EXPORTER_API_REQUESTS_LAST_CYCLE = _gauge(
    f"{PREFIX}_exporter_api_requests_last_cycle",
    "Number of eero API requests issued during the most recently completed collection cycle.",
    family="exporter",
    source="derived: EeroCollector._api_requests_this_cycle",
    evidence="verified",
)

# =============================================================================
# ACCOUNT
# =============================================================================

ACCOUNT_NETWORKS_COUNT = _gauge(
    f"{PREFIX}_account_networks_count",
    "Total number of networks in account",
    family="account",
    source="account.data.networks.count",
    evidence="verified",
)

ACCOUNT_PREMIUM_NEXT_RENEWAL = _gauge(
    f"{PREFIX}_account_premium_next_renewal_timestamp_seconds",
    "Next premium subscription billing/renewal event (Unix epoch). "
    "Renamed from `_expiration_` in 4.0.0 -- this field is a renewal date, "
    "not an expiry date (v8 probe shape summary §6 Q3, §10 §5.3).",
    ("network_id",),
    family="account",
    source="network.data.premium_details.next_billing_event_date",
    evidence="verified",
)

# =============================================================================
# NETWORK -- identity, status, health, speed test
# =============================================================================

NETWORK_INFO = _info(
    f"{PREFIX}_network",
    "Information about the eero network.",
    ("network_id",),
    family="network",
    source="network.data (name, status, geo_ip.isp, ip_settings.public_ip, wan_type, gateway_ip)",
    evidence="verified",
)

NETWORK_STATUS = _gauge(
    f"{PREFIX}_network_status",
    "Network status (1=online, 0=offline)",
    ("network_id", "name"),
    family="network",
    source="network.data.status",
    evidence="verified",
)

NETWORK_CLIENTS_COUNT = _gauge(
    f"{PREFIX}_network_clients_count",
    "Total number of clients on the network",
    ("network_id", "name"),
    family="network",
    source="network.data.clients.count",
    evidence="verified",
)

NETWORK_EEROS_COUNT = _gauge(
    f"{PREFIX}_network_eeros_count",
    "Number of eero devices in the network",
    ("network_id", "name"),
    family="network",
    source="network.data.eeros.count",
    evidence="verified",
)

HEALTH_STATUS = _gauge(
    f"{PREFIX}_health_status",
    "Health status of network components (1=healthy, 0=unhealthy)",
    ("network_id", "source"),
    family="network",
    source="network.data.health.{internet,eero_network}.status",
    evidence="verified",
)

SPEED_UPLOAD_MBPS = _gauge(
    f"{PREFIX}_speed_upload_mbps",
    "Latest speed test upload result in megabits per second (Mbps). "
    "Note: Uses Mbps as industry-standard unit for network speeds.",
    ("network_id",),
    family="network",
    source="network.data.speed.up.value",
    evidence="verified",
)

SPEED_DOWNLOAD_MBPS = _gauge(
    f"{PREFIX}_speed_download_mbps",
    "Latest speed test download result in megabits per second (Mbps). "
    "Note: Uses Mbps as industry-standard unit for network speeds.",
    ("network_id",),
    family="network",
    source="network.data.speed.down.value",
    evidence="verified",
)

SPEED_TEST_TIMESTAMP = _gauge(
    f"{PREFIX}_speed_test_timestamp_seconds",
    "Timestamp of the last speed test (Unix epoch)",
    ("network_id",),
    family="network",
    source="network.data.speed.date",
    evidence="verified",
)

# =============================================================================
# NETWORK FEATURE FLAGS
# =============================================================================

NETWORK_WPA3_ENABLED = _gauge(
    f"{PREFIX}_network_wpa3_enabled",
    "Whether WPA3 is enabled (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.wpa3",
    evidence="verified",
)

NETWORK_BAND_STEERING_ENABLED = _gauge(
    f"{PREFIX}_network_band_steering_enabled",
    "Whether band steering is enabled (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.band_steering",
    evidence="verified",
)

NETWORK_SQM_ENABLED = _gauge(
    f"{PREFIX}_network_sqm_enabled",
    "Whether Smart Queue Management is enabled (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.sqm",
    evidence="verified",
)

NETWORK_UPNP_ENABLED = _gauge(
    f"{PREFIX}_network_upnp_enabled",
    "Whether UPnP is enabled (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.upnp",
    evidence="verified",
)

NETWORK_THREAD_ENABLED = _gauge(
    f"{PREFIX}_network_thread_enabled",
    "Whether Thread is enabled (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.thread",
    evidence="verified",
)

NETWORK_IPV6_ENABLED = _gauge(
    f"{PREFIX}_network_ipv6_enabled",
    "Whether IPv6 is enabled (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.ipv6_upstream",
    evidence="verified",
)

NETWORK_DNS_CACHING_ENABLED = _gauge(
    f"{PREFIX}_network_dns_caching_enabled",
    "Whether DNS caching is enabled (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.dns.caching",
    evidence="verified",
)

NETWORK_POWER_SAVING_ENABLED = _gauge(
    f"{PREFIX}_network_power_saving_enabled",
    "Whether power saving is enabled (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.power_saving",
    evidence="verified",
)

NETWORK_GUEST_ENABLED = _gauge(
    f"{PREFIX}_network_guest_enabled",
    "Whether guest network is enabled (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.guest_network.enabled",
    evidence="verified",
)

NETWORK_PREMIUM_ENABLED = _gauge(
    f"{PREFIX}_network_premium_enabled",
    "Whether Eero Plus/Secure subscription is active (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.{premium_status,premium_details}",
    evidence="verified",
)

NETWORK_BACKUP_INTERNET_ENABLED = _gauge(
    f"{PREFIX}_network_backup_internet_enabled",
    "Whether backup internet is enabled (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.backup_internet_enabled",
    evidence="verified",
)

NETWORK_UPDATES_AVAILABLE = _gauge(
    f"{PREFIX}_network_updates_available",
    "Number of eeros with firmware updates available",
    ("network_id", "name"),
    family="network_features",
    source="eeros.data[].update_available (count)",
    evidence="verified",
)

NETWORK_AD_BLOCK_ENABLED = _gauge(
    f"{PREFIX}_network_ad_block_enabled",
    "Whether ad blocking is enabled network-wide (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.premium_dns.dns_policies.ad_block",
    evidence="verified",
)

NETWORK_CUSTOM_DNS_ENABLED = _gauge(
    f"{PREFIX}_network_custom_dns_enabled",
    "Whether custom DNS is configured (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="derived: network.data.dns.mode == 'custom'",
    evidence="verified",
)

NETWORK_DNS_SERVER_COUNT = _gauge(
    f"{PREFIX}_network_dns_server_count",
    "Number of DNS servers configured",
    ("network_id", "name"),
    family="network_features",
    source="len(network.data.dns.custom.ips)",
    evidence="verified",
)

DNS_CONFIG_INFO = _info(
    f"{PREFIX}_dns_config",
    "DNS configuration information (mode only -- never the resolver IPs)",
    ("network_id",),
    family="network_features",
    source="network.data.dns.mode",
    evidence="verified",
)

# =============================================================================
# NETWORK -- commit 6 additions: free fields on the already-fetched network
# envelope (§5.2/§8/§11.1 of the v8 probe shape summary). Zero extra requests.
# =============================================================================

NETWORK_ISP_UP = _gauge(
    f"{PREFIX}_network_isp_up",
    "Whether the ISP/internet connection is reported up (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.health.internet.isp_up",
    evidence="verified",
)

NETWORK_DOUBLE_NAT_DETECTED = _gauge(
    f"{PREFIX}_network_double_nat_detected",
    "Whether double NAT was detected on the network (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.ip_settings.double_nat",
    evidence="verified",
)

NETWORK_LAST_REBOOT = _gauge(
    f"{PREFIX}_network_last_reboot_timestamp_seconds",
    "Timestamp of the network's (gateway eero's) last reboot (Unix epoch)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.last_reboot",
    evidence="verified",
)

NETWORK_CONNECTION_MODE_INFO = _info(
    f"{PREFIX}_network_connection_mode",
    "Network connection mode (e.g. NAT, bridge)",
    ("network_id",),
    family="network_features",
    source="network.data.connection.mode (upper-cased)",
    evidence="verified",
)

NETWORK_WAN_TYPE_INFO = _info(
    f"{PREFIX}_network_wan_type",
    "Network WAN type (e.g. DHCP, PPPoE, static)",
    ("network_id",),
    family="network_features",
    source="network.data.wan_type",
    evidence="verified",
)

NETWORK_MLO_MODE_INFO = _info(
    f"{PREFIX}_network_mlo_mode",
    "Network Multi-Link Operation (MLO) mode",
    ("network_id",),
    family="network_features",
    source="network.data.mlo_mode",
    evidence="verified",
)

NETWORK_WIRELESS_MODE_INFO = _info(
    f"{PREFIX}_network_wireless_mode",
    "Network wireless mode",
    ("network_id",),
    family="network_features",
    source="network.data.wireless_mode",
    evidence="verified",
)

NETWORK_DDNS_ENABLED = _gauge(
    f"{PREFIX}_network_ddns_enabled",
    "Whether Dynamic DNS is enabled (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.ddns.enabled",
    evidence="verified",
)

NETWORK_MALWARE_BLOCK_ENABLED = _gauge(
    f"{PREFIX}_network_malware_block_enabled",
    "Whether malware blocking is enabled network-wide (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.premium_dns.dns_policies.block_malware",
    evidence="verified",
)

NETWORK_UPDATE_AVAILABLE = _gauge(
    f"{PREFIX}_network_update_available",
    "Whether a firmware update is available for the network (1=yes, 0=no)",
    ("network_id", "name"),
    family="network_features",
    source="network.data.updates.has_update",
    evidence="verified",
)

NETWORK_UPDATE_TARGET_INFO = _info(
    f"{PREFIX}_network_update_target",
    "The firmware version the network would update to, if an update is available",
    ("network_id",),
    family="network_features",
    source="network.data.updates.target_firmware",
    evidence="verified",
)

NETWORK_DNS_MODE_INFO = _info(
    f"{PREFIX}_network_dns_mode",
    "Network DNS mode, by IP family",
    ("network_id", "family"),
    family="network_features",
    source="network.data.dns.mode (ipv4); network.data.ipv6.name_servers.mode (ipv6, if observed)",
    evidence="verified",
)

NETWORK_DNS_PARENT_SERVER_COUNT = _gauge(
    f"{PREFIX}_network_dns_parent_server_count",
    "Number of parent (upstream/ISP) DNS servers configured",
    ("network_id", "name"),
    family="network_features",
    source="len(network.data.dns.parent.ips)",
    evidence="verified",
)

NETWORK_DHCP_MODE_INFO = _info(
    f"{PREFIX}_network_dhcp_mode",
    "Network DHCP mode",
    ("network_id",),
    family="network_features",
    source="network.data.dhcp.mode",
    evidence="verified",
)

NETWORK_TIMEZONE_INFO = _info(
    f"{PREFIX}_network_timezone",
    "Network configured timezone",
    ("network_id",),
    family="network_features",
    source="network.data.timezone.value",
    evidence="verified",
)

# =============================================================================
# NETWORK CAPABILITIES -- the envelope's 119-entry `capabilities.<name>.capable`
# boolean dict (§8/§11.1). The `capability` label value is the API's own key
# name, sanitised (`[^a-z0-9_]` -> `_`); the vocabulary is bounded by the API,
# not user input.
# =============================================================================

NETWORK_CAPABILITY = _gauge(
    f"{PREFIX}_network_capability",
    "Whether a named network capability/feature is available (1=yes, 0=no). "
    "Capability names are the eero API's own feature keys.",
    ("network_id", "capability"),
    family="network_capabilities",
    source="network.data.capabilities.<name>.capable",
    evidence="verified",
)

# =============================================================================
# GUEST NETWORK
# =============================================================================

GUEST_NETWORK_CONNECTED_CLIENTS = _gauge(
    f"{PREFIX}_guest_network_connected_clients",
    "Number of clients connected to guest network",
    ("network_id", "name"),
    family="guest",
    source="derived: count(devices.data[] where connected and is_guest)",
    evidence="verified",
)

GUEST_NETWORK_INFO = _info(
    f"{PREFIX}_guest_network",
    "Guest network information",
    ("network_id",),
    family="guest",
    source="network.data.guest_network",
    evidence="verified",
)

# =============================================================================
# EEROS
# =============================================================================

EERO_INFO = _info(
    f"{PREFIX}_eero",
    "Information about an eero device.",
    ("network_id", "eero_id"),
    family="eeros",
    source=(
        "eeros.data[] (location, model, model_number, os_version, serial, mac_address, ip_address)"
    ),
    evidence="verified",
)

EERO_OS_VERSION_INFO = _info(
    f"{PREFIX}_eero_os_version",
    "Eero firmware version information",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].os_version",
    evidence="verified",
)

EERO_STATUS = _gauge(
    f"{PREFIX}_eero_status",
    "Eero device status (1=online, 0=offline)",
    ("network_id", "eero_id", "location", "model"),
    family="eeros",
    source="eeros.data[].status",
    evidence="verified",
)

EERO_IS_GATEWAY = _gauge(
    f"{PREFIX}_eero_is_gateway",
    "Whether the eero is the gateway (1=yes, 0=no)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].gateway",
    evidence="verified",
)

EERO_CONNECTED_CLIENTS = _gauge(
    f"{PREFIX}_eero_connected_clients_count",
    "Number of clients connected to this eero",
    ("network_id", "eero_id", "location", "model"),
    family="eeros",
    source="eeros.data[].connected_clients_count",
    evidence="verified",
)

EERO_CONNECTED_WIRED_CLIENTS = _gauge(
    f"{PREFIX}_eero_connected_wired_clients_count",
    "Number of wired clients connected to this eero",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].connected_wired_clients_count",
    evidence="verified",
)

EERO_CONNECTED_WIRELESS_CLIENTS = _gauge(
    f"{PREFIX}_eero_connected_wireless_clients_count",
    "Number of wireless clients connected to this eero",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].connected_wireless_clients_count",
    evidence="verified",
)

EERO_MESH_QUALITY = _gauge(
    f"{PREFIX}_eero_mesh_quality_bars",
    "Mesh quality indicator 0-5 bars.",
    ("network_id", "eero_id", "location", "model"),
    family="eeros",
    source="eeros.data[].mesh_quality_bars",
    evidence="verified",
)

EERO_UPTIME_SECONDS = _gauge(
    f"{PREFIX}_eero_uptime_seconds",
    "Eero device uptime in seconds since last reboot.",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].uptime.since_last_reboot_s",
    evidence="verified",
)

EERO_LED_ON = _gauge(
    f"{PREFIX}_eero_led_on",
    "Whether the eero LED is on (1=on, 0=off)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].led_on",
    evidence="verified",
)

EERO_UPDATE_AVAILABLE = _gauge(
    f"{PREFIX}_eero_update_available",
    "Whether an update is available (1=yes, 0=no)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].update_available",
    evidence="verified",
)

EERO_HEARTBEAT_OK = _gauge(
    f"{PREFIX}_eero_heartbeat_ok",
    "Whether the eero heartbeat is OK (1=yes, 0=no)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].heartbeat_ok",
    evidence="verified",
)

EERO_WIRED = _gauge(
    f"{PREFIX}_eero_wired",
    "Whether the eero is wired (1=yes, 0=no)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].wired",
    evidence="verified",
)

EERO_LED_BRIGHTNESS = _gauge(
    f"{PREFIX}_eero_led_brightness",
    "Eero LED brightness level (0-100)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].led_brightness",
    evidence="verified",
)

EERO_LAST_REBOOT = _gauge(
    f"{PREFIX}_eero_last_reboot_timestamp_seconds",
    "Timestamp of last eero reboot (Unix epoch)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].last_reboot",
    evidence="verified",
)

EERO_PROVIDES_WIFI = _gauge(
    f"{PREFIX}_eero_provides_wifi",
    "Whether the eero provides WiFi (1=yes, 0=no)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].provides_wifi",
    evidence="verified",
)

EERO_WIRED_INTERNET = _gauge(
    f"{PREFIX}_eero_wired_internet",
    "Whether the eero has wired internet connection (1=yes, 0=no)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].ethernet_status.wiredInternet",
    evidence="verified",
)

EERO_NIGHTLIGHT_ENABLED = _gauge(
    f"{PREFIX}_eero_nightlight_enabled",
    "Whether nightlight is enabled (1=yes, 0=no). Null (unset) on non-Beacon nodes.",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].nightlight.enabled",
    evidence="verified",
)

EERO_NIGHTLIGHT_BRIGHTNESS = _gauge(
    f"{PREFIX}_eero_nightlight_brightness",
    "Nightlight brightness level (0-100)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].nightlight.brightness",
    evidence="inferred",
)

EERO_NIGHTLIGHT_SCHEDULE_ENABLED = _gauge(
    f"{PREFIX}_eero_nightlight_schedule_enabled",
    "Whether nightlight schedule is enabled (1=yes, 0=no)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].nightlight.schedule.enabled",
    evidence="inferred",
)

# =============================================================================
# EEROS -- commit 6 additions (§8/§11.2 of the v8 probe shape summary).
# Every field below is embedded on the same `eeros.data[]` items already
# collected above -- zero extra requests.
# =============================================================================

EERO_IS_PRIMARY = _gauge(
    f"{PREFIX}_eero_is_primary",
    "Whether this eero is the primary/gateway node of the mesh (1=yes, 0=no)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].is_primary_node",
    evidence="verified",
)

EERO_USING_WAN = _gauge(
    f"{PREFIX}_eero_using_wan",
    "Whether this eero is actively using its WAN connection (1=yes, 0=no)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].using_wan",
    evidence="verified",
)

EERO_LAST_HEARTBEAT = _gauge(
    f"{PREFIX}_eero_last_heartbeat_timestamp_seconds",
    "Timestamp of the eero's last heartbeat (Unix epoch)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].last_heartbeat",
    evidence="verified",
)

EERO_JOINED = _gauge(
    f"{PREFIX}_eero_joined_timestamp_seconds",
    "Timestamp the eero joined the mesh (Unix epoch)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].joined",
    evidence="verified",
)

EERO_BAND_SUPPORTED = _gauge(
    f"{PREFIX}_eero_band_supported",
    "Whether this eero supports a given radio band (1=supported). "
    "Only supported bands are exported, one series per band.",
    ("network_id", "eero_id", "location", "band"),
    family="eeros",
    source="eeros.data[].bands[]",
    evidence="verified",
)

EERO_RADIO_COUNT = _gauge(
    f"{PREFIX}_eero_radio_count",
    "Number of radios (BSSID/band pairs) on this eero",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="len(eeros.data[].bssids_with_bands)",
    evidence="verified",
)

EERO_POWER_SAVING_ACTIVE = _gauge(
    f"{PREFIX}_eero_power_saving_active",
    "Whether power saving is currently active on this eero (1=yes, 0=no)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].power_saving.schedule.active",
    evidence="verified",
)

EERO_POWER_SOURCE_INFO = _info(
    f"{PREFIX}_eero_power_source",
    "The eero's power source (e.g. USB, PoE)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].power_info.power_source",
    evidence="verified",
)

EERO_CONNECTION_TYPE_INFO = _info(
    f"{PREFIX}_eero_connection_type",
    "How this eero is connected to the mesh (wired/wireless)",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].connection_type (upper-cased on this resource)",
    evidence="verified",
)

# =============================================================================
# RADIO -- `eeros.data[].radio_channel_stats`, a dict keyed by the exact
# `CHANNEL_UTILIZATION_BANDS` enum (§8/§11.2). Zero extra requests: 5 bands x
# 5 numerics x E eeros, free on the eeros/network-envelope read.
# =============================================================================

EERO_RADIO_CHANNEL = _gauge(
    f"{PREFIX}_eero_radio_channel",
    "Current WiFi channel number for this eero's radio, by band",
    ("network_id", "eero_id", "location", "band"),
    family="radio",
    source="eeros.data[].radio_channel_stats[band].channel",
    evidence="verified",
)

EERO_RADIO_CHANNEL_WIDTH = _gauge(
    f"{PREFIX}_eero_radio_channel_width_mhz",
    "Current WiFi channel width in MHz for this eero's radio, by band",
    ("network_id", "eero_id", "location", "band"),
    family="radio",
    source="eeros.data[].radio_channel_stats[band].channel_width",
    evidence="verified",
)

EERO_RADIO_TX_POWER = _gauge(
    f"{PREFIX}_eero_radio_tx_power_dbm",
    "Current transmit power in dBm for this eero's radio, by band",
    ("network_id", "eero_id", "location", "band"),
    family="radio",
    source="eeros.data[].radio_channel_stats[band].tx_power",
    evidence="verified",
)

EERO_RADIO_CHANNEL_UTILIZATION = _gauge(
    f"{PREFIX}_eero_radio_channel_utilization_percent",
    "Current channel utilization percentage for this eero's radio, by band",
    ("network_id", "eero_id", "location", "band"),
    family="radio",
    source="eeros.data[].radio_channel_stats[band].channel_utilization",
    evidence="verified",
)

EERO_RADIO_CLIENT_COUNT = _gauge(
    f"{PREFIX}_eero_radio_client_count",
    "Number of clients currently connected to this eero's radio, by band",
    ("network_id", "eero_id", "location", "band"),
    family="radio",
    source="eeros.data[].radio_channel_stats[band].client_count",
    evidence="verified",
)

# =============================================================================
# ETHERNET
# =============================================================================

ETHERNET_PORT_INFO = _info(
    f"{PREFIX}_ethernet_port",
    "Information about an Ethernet port",
    ("network_id", "eero_id", "port_number"),
    family="ethernet",
    source="eeros.data[].ethernet_status.statuses[].port_name",
    evidence="verified",
)

ETHERNET_PORT_CARRIER = _gauge(
    f"{PREFIX}_ethernet_port_carrier",
    "Whether the Ethernet port has link (1=yes, 0=no)",
    ("network_id", "eero_id", "location", "port_number", "port_name"),
    family="ethernet",
    source="eeros.data[].ethernet_status.statuses[].hasCarrier",
    evidence="verified",
)

ETHERNET_PORT_SPEED = _gauge(
    f"{PREFIX}_ethernet_port_speed_mbps",
    "Ethernet port negotiated speed in megabits per second (Mbps). "
    "Common values: 100 (Fast Ethernet), 1000 (Gigabit), 2500 (2.5G).",
    ("network_id", "eero_id", "location", "port_number", "port_name"),
    family="ethernet",
    source="eeros.data[].ethernet_status.statuses[].speed (enum P10|P100|P1000|P10000)",
    evidence="verified",
)

ETHERNET_PORT_IS_WAN = _gauge(
    f"{PREFIX}_ethernet_port_is_wan",
    "Whether the Ethernet port is used for WAN (1=yes, 0=no)",
    ("network_id", "eero_id", "location", "port_number", "port_name"),
    family="ethernet",
    source="eeros.data[].ethernet_status.statuses[].isWanPort",
    evidence="verified",
)

ETHERNET_PORT_IS_LTE = _gauge(
    f"{PREFIX}_ethernet_port_is_lte",
    "Whether the Ethernet port is an LTE backup connection (1=yes, 0=no)",
    ("network_id", "eero_id", "location", "port_number", "port_name"),
    family="ethernet",
    source="eeros.data[].ethernet_status.statuses[].isLte",
    evidence="verified",
)

ETHERNET_PORT_NEIGHBOR_INFO = _info(
    f"{PREFIX}_ethernet_port_neighbor",
    "Neighbour device seen on this Ethernet port, if any (never location/URL -- "
    "only the bounded `type` enum and the numeric `port` on the neighbour side).",
    ("network_id", "eero_id", "port_number"),
    family="ethernet",
    source="eeros.data[].ethernet_status.statuses[].neighbor.{type,metadata.port}",
    evidence="verified",
)

# =============================================================================
# CLIENT DEVICES
# =============================================================================

DEVICE_INFO = _info(
    f"{PREFIX}_device",
    "Information about a connected device.",
    ("network_id", "device_id", "mac"),
    family="devices",
    source=(
        "devices.data[] (nickname/hostname/display_name, manufacturer, ip, "
        "device_type, connection_type)"
    ),
    evidence="verified",
)

DEVICE_CONNECTED = _gauge(
    f"{PREFIX}_device_connected",
    "Whether the device is connected (1=yes, 0=no)",
    (
        "network_id",
        "device_id",
        "name",
        "mac",
        "manufacturer",
        "device_type",
        "connection_type",
        "source_eero",
    ),
    family="devices",
    source="devices.data[].connected",
    evidence="verified",
)

DEVICE_WIRELESS = _gauge(
    f"{PREFIX}_device_wireless",
    "Whether the device is wireless (1=yes, 0=no)",
    ("network_id", "device_id", "name", "manufacturer", "device_type"),
    family="devices",
    source="devices.data[].wireless",
    evidence="verified",
)

DEVICE_BLOCKED = _gauge(
    f"{PREFIX}_device_blocked",
    "Whether the device is blocked (1=yes, 0=no)",
    ("network_id", "device_id", "name", "mac", "manufacturer"),
    family="devices",
    source="devices.data[].blacklisted",
    evidence="verified",
)

DEVICE_PAUSED = _gauge(
    f"{PREFIX}_device_paused",
    "Whether the device is paused (1=yes, 0=no)",
    ("network_id", "device_id", "name", "manufacturer", "device_type"),
    family="devices",
    source="devices.data[].paused",
    evidence="verified",
)

DEVICE_IS_GUEST = _gauge(
    f"{PREFIX}_device_is_guest",
    "Whether the device is on guest network (1=yes, 0=no)",
    ("network_id", "device_id", "name", "manufacturer"),
    family="devices",
    source="devices.data[].is_guest",
    evidence="verified",
)

DEVICE_PRIVATE = _gauge(
    f"{PREFIX}_device_private",
    "Whether the device is marked as private (1=yes, 0=no)",
    ("network_id", "device_id", "name", "manufacturer"),
    family="devices",
    source="devices.data[].is_private",
    evidence="verified",
)

DEVICE_CONNECTED_TO_GATEWAY = _gauge(
    f"{PREFIX}_device_connected_to_gateway",
    "Whether the device is connected directly to gateway (1=yes, 0=no)",
    ("network_id", "device_id", "name", "connection_type"),
    family="devices",
    source="devices.data[].source.is_gateway",
    evidence="verified",
)

DEVICE_SIGNAL_STRENGTH = _gauge(
    f"{PREFIX}_device_signal_strength_dbm",
    "Device signal strength in dBm (decibels relative to 1 milliwatt). "
    "Range typically -30 (excellent) to -90 (poor).",
    ("network_id", "device_id", "name", "manufacturer", "band", "source_eero"),
    family="devices",
    source="devices.data[].connectivity.signal",
    evidence="verified",
)

DEVICE_CONNECTION_SCORE = _gauge(
    f"{PREFIX}_device_connection_score",
    "Device connection quality score",
    ("network_id", "device_id", "name", "manufacturer", "connection_type", "source_eero"),
    family="devices",
    source="devices.data[].connectivity.score",
    evidence="verified",
)

DEVICE_CONNECTION_SCORE_BARS = _gauge(
    f"{PREFIX}_device_connection_score_bars",
    "Device connection quality score in bars (0-5)",
    ("network_id", "device_id", "name", "manufacturer", "connection_type", "source_eero"),
    family="devices",
    source="devices.data[].connectivity.score_bars",
    evidence="verified",
)

DEVICE_FREQUENCY = _gauge(
    f"{PREFIX}_device_frequency_mhz",
    "Device WiFi frequency in MHz",
    ("network_id", "device_id", "name", "manufacturer", "band", "source_eero"),
    family="devices",
    source="devices.data[].connectivity.frequency",
    evidence="verified",
)

DEVICE_CHANNEL = _gauge(
    f"{PREFIX}_device_channel",
    "Device WiFi channel number",
    ("network_id", "device_id", "name", "band", "source_eero"),
    family="devices",
    source="devices.data[].channel (top-level; falls back to connectivity.channel)",
    evidence="verified",
)

DEVICE_RX_BITRATE = _gauge(
    f"{PREFIX}_device_rx_bitrate_mbps",
    "Device receive (download) bitrate in megabits per second (Mbps). "
    "PHY layer rate, actual throughput may be lower.",
    ("network_id", "device_id", "name", "manufacturer", "band", "source_eero"),
    family="devices",
    source="devices.data[].connectivity.rx_rate_info.rate_bps / 1e6"
    " (primary) | connectivity.rx_bitrate (string fallback)",
    evidence="verified",
)

DEVICE_TX_BITRATE = _gauge(
    f"{PREFIX}_device_tx_bitrate_mbps",
    "Device transmit (upload) bitrate in megabits per second (Mbps). "
    "PHY layer rate, actual throughput may be lower.",
    ("network_id", "device_id", "name", "manufacturer", "band", "source_eero"),
    family="devices",
    source="devices.data[].connectivity.tx_rate_info.rate_bps / 1e6",
    evidence="verified",
)

DEVICE_RX_MCS = _gauge(
    f"{PREFIX}_device_rx_mcs",
    "Device receive MCS index",
    ("network_id", "device_id", "name", "band"),
    family="devices",
    source="devices.data[].connectivity.rx_rate_info.mcs",
    evidence="verified",
)

DEVICE_RX_NSS = _gauge(
    f"{PREFIX}_device_rx_nss",
    "Device receive number of spatial streams",
    ("network_id", "device_id", "name", "band"),
    family="devices",
    source="devices.data[].connectivity.rx_rate_info.nss",
    evidence="verified",
)

DEVICE_TX_MCS = _gauge(
    f"{PREFIX}_device_tx_mcs",
    "Device transmit MCS index",
    ("network_id", "device_id", "name", "band"),
    family="devices",
    source="devices.data[].connectivity.tx_rate_info.mcs",
    evidence="verified",
)

DEVICE_TX_NSS = _gauge(
    f"{PREFIX}_device_tx_nss",
    "Device transmit number of spatial streams",
    ("network_id", "device_id", "name", "band"),
    family="devices",
    source="devices.data[].connectivity.tx_rate_info.nss",
    evidence="verified",
)

DEVICE_LAST_ACTIVE_TIMESTAMP = _gauge(
    f"{PREFIX}_device_last_active_timestamp_seconds",
    "Last time device was active (Unix epoch)",
    ("network_id", "device_id", "name", "manufacturer"),
    family="devices",
    source="devices.data[].last_active",
    evidence="verified",
)

DEVICE_FIRST_SEEN_TIMESTAMP = _gauge(
    f"{PREFIX}_device_first_seen_timestamp_seconds",
    "When device was first seen on network (Unix epoch)",
    ("network_id", "device_id", "name", "manufacturer"),
    family="devices",
    source="devices.data[].first_active | first_seen",
    evidence="verified",
)

DEVICE_WIFI_GENERATION = _gauge(
    f"{PREFIX}_device_wifi_generation",
    "WiFi standard (4=WiFi 4, 5=WiFi 5, 6=WiFi 6, 7=WiFi 7)",
    ("network_id", "device_id", "name", "manufacturer"),
    family="devices",
    source="derived: devices.data[].connectivity.{frequency,rx_rate_info.mode}",
    evidence="inferred",
)

# =============================================================================
# CLIENT DEVICES -- commit 6 additions (§8/§11.3 of the v8 probe shape
# summary). All free on the already-fetched `devices.data[]` items; the
# `profile` label on `DEVICE_INFO` (added via the .info() call, not a new
# constructor label) is bounded by the profile count, per the v8 migration
# plan §5.4.
# =============================================================================

DEVICE_SUBNET_KIND_INFO = _info(
    f"{PREFIX}_device_subnet_kind",
    "Which subnet kind (main/guest) this device is on",
    ("network_id", "device_id"),
    family="devices",
    source="devices.data[].subnet_kind",
    evidence="verified",
)

DEVICE_PACKET_STATS_RX_PACKETS = _gauge(
    f"{PREFIX}_device_packet_stats_rx_packets",
    "Total received packets reported for this device (lifetime counter reported "
    "as a gauge -- the API gives no reset semantics)",
    ("network_id", "device_id"),
    family="devices",
    source="devices.data[].connectivity.packet_stats.rx_packets",
    evidence="verified",
)

DEVICE_PACKET_STATS_TX_PACKETS = _gauge(
    f"{PREFIX}_device_packet_stats_tx_packets",
    "Total transmitted packets reported for this device",
    ("network_id", "device_id"),
    family="devices",
    source="devices.data[].connectivity.packet_stats.tx_packets",
    evidence="verified",
)

DEVICE_PACKET_STATS_TOTAL_PACKETS = _gauge(
    f"{PREFIX}_device_packet_stats_total_packets",
    "Total packets (rx+tx) reported for this device",
    ("network_id", "device_id"),
    family="devices",
    source="devices.data[].connectivity.packet_stats.total_packets",
    evidence="verified",
)

DEVICE_PACKET_STATS_RX_DROPS = _gauge(
    f"{PREFIX}_device_packet_stats_rx_drops",
    "Total dropped received packets reported for this device",
    ("network_id", "device_id"),
    family="devices",
    source="devices.data[].connectivity.packet_stats.rx_drops",
    evidence="verified",
)

DEVICE_PACKET_STATS_TX_RETRIES = _gauge(
    f"{PREFIX}_device_packet_stats_tx_retries",
    "Total transmit retries reported for this device",
    ("network_id", "device_id"),
    family="devices",
    source="devices.data[].connectivity.packet_stats.tx_retries",
    evidence="verified",
)

DEVICE_PACKET_STATS_TX_RETRANSMIT_PPM = _gauge(
    f"{PREFIX}_device_packet_stats_tx_retransmit_ppm",
    "Transmit retransmit rate in parts-per-million for this device",
    ("network_id", "device_id"),
    family="devices",
    source="devices.data[].connectivity.packet_stats.tx_retransmit_ppm",
    evidence="verified",
)

DEVICE_PACKET_STATS_TX_FAIL_PPM = _gauge(
    f"{PREFIX}_device_packet_stats_tx_fail_ppm",
    "Transmit failure rate in parts-per-million for this device",
    ("network_id", "device_id"),
    family="devices",
    source="devices.data[].connectivity.packet_stats.tx_fail_ppm",
    evidence="verified",
)

DEVICE_PACKET_STATS_RX_DROP_PPM = _gauge(
    f"{PREFIX}_device_packet_stats_rx_drop_ppm",
    "Receive drop rate in parts-per-million for this device",
    ("network_id", "device_id"),
    family="devices",
    source="devices.data[].connectivity.packet_stats.rx_drop_ppm",
    evidence="verified",
)

# =============================================================================
# PROFILES
# =============================================================================

PROFILE_PAUSED = _gauge(
    f"{PREFIX}_profile_paused",
    "Whether the profile is paused (1=yes, 0=no)",
    ("network_id", "profile_id", "name"),
    family="profiles",
    source="profiles.data[].paused",
    evidence="verified",
)

PROFILE_DEVICES_COUNT = _gauge(
    f"{PREFIX}_profile_devices_count",
    "Number of devices in the profile",
    ("network_id", "profile_id", "name"),
    family="profiles",
    source="len(profiles.data[].devices)",
    evidence="verified",
)

# Commit 6 additions (§8/§11.4 of the v8 probe shape summary) -- all free on
# the already-fetched `profiles.data[]` items.

PROFILE_CONNECTED_DEVICES_COUNT = _gauge(
    f"{PREFIX}_profile_connected_devices_count",
    "Number of currently-connected devices in the profile",
    ("network_id", "profile_id", "name"),
    family="profiles",
    source="sum(profiles.data[].devices[].connected)",
    evidence="verified",
)

PROFILE_SCHEDULES_COUNT = _gauge(
    f"{PREFIX}_profile_schedules_count",
    "Number of schedules configured on the profile",
    ("network_id", "profile_id", "name"),
    family="profiles",
    source="len(profiles.data[].schedule)",
    evidence="verified",
)

PROFILE_BLOCKED_APPLICATIONS_COUNT = _gauge(
    f"{PREFIX}_profile_blocked_applications_count",
    "Number of applications blocked on the profile",
    ("network_id", "profile_id", "name"),
    family="profiles",
    source="len(profiles.data[].premium_dns.blocked_applications)",
    evidence="verified",
)

PROFILE_CONTENT_FILTERS_SET = _gauge(
    f"{PREFIX}_profile_content_filters_set",
    "Whether unified content filters are configured on the profile (1=yes, 0=no)",
    ("network_id", "profile_id", "name"),
    family="profiles",
    source="profiles.data[].unified_content_filters.is_content_filters_set",
    evidence="verified",
)

# =============================================================================
# DATA USAGE
# =============================================================================

# The "period" label is one of day/week/month for the current calendar
# window; "cadence" is the sample granularity eero used (hourly for day,
# daily otherwise); "direction" is download or upload.

NETWORK_DATA_USAGE_BYTES = _gauge(
    f"{PREFIX}_network_data_usage_bytes",
    "Network data usage in bytes from the eero data_usage endpoint for the current period.",
    ("network_id", "period", "cadence", "direction"),
    family="data_usage",
    source="get_data_usage().data.series[].sum, keyed by .type",
    evidence="verified",
)

DEVICE_DATA_USAGE_BYTES = _gauge(
    f"{PREFIX}_device_data_usage_bytes",
    "Device data usage in bytes from the eero data_usage endpoint for the current period.",
    ("network_id", "device_id", "name", "period", "cadence", "direction"),
    family="data_usage",
    source="get_data_usage_breakdown().data.devices[].{upload,download}",
    evidence="verified",
)

EERO_DATA_USAGE_BYTES = _gauge(
    f"{PREFIX}_eero_data_usage_bytes",
    "Eero node data usage in bytes from the eero data_usage endpoint for the current period.",
    ("network_id", "eero_id", "location", "period", "cadence", "direction"),
    family="data_usage",
    source="get_data_usage_breakdown().data.eeros[].{upload,download}",
    evidence="verified",
)

DATA_USAGE_DOWNLOAD_BYTES = _gauge(
    f"{PREFIX}_data_usage_download_bytes",
    "Network data usage download bytes for the trailing collection window.",
    ("network_id",),
    family="data_usage",
    source="get_data_usage().data.series[type=download].sum",
    evidence="verified",
)

DATA_USAGE_UPLOAD_BYTES = _gauge(
    f"{PREFIX}_data_usage_upload_bytes",
    "Network data usage upload bytes for the trailing collection window.",
    ("network_id",),
    family="data_usage",
    source="get_data_usage().data.series[type=upload].sum",
    evidence="verified",
)

DATA_USAGE_ACTIVE_CLIENTS = _gauge(
    f"{PREFIX}_data_usage_active_clients",
    "Number of active clients observed in the trailing collection window.",
    ("network_id",),
    family="data_usage",
    source="get_data_usage().data.totals.active_clients",
    evidence="inferred",
)

DEVICE_DATA_USAGE_DOWNLOAD_BYTES = _gauge(
    f"{PREFIX}_device_data_usage_download_bytes",
    "Device data usage download bytes for the trailing collection window.",
    ("network_id", "device_id", "name", "manufacturer", "device_type"),
    family="data_usage",
    source="get_data_usage_breakdown().data.devices[].download",
    evidence="verified",
)

DEVICE_DATA_USAGE_UPLOAD_BYTES = _gauge(
    f"{PREFIX}_device_data_usage_upload_bytes",
    "Device data usage upload bytes for the trailing collection window.",
    ("network_id", "device_id", "name", "manufacturer", "device_type"),
    family="data_usage",
    source="get_data_usage_breakdown().data.devices[].upload",
    evidence="verified",
)

# =============================================================================
# INSIGHTS
# =============================================================================

INSIGHTS_ADBLOCK_TOTAL = _gauge(
    f"{PREFIX}_insights_adblock_total",
    "Total ad-block events observed in the insights window, by category.",
    ("network_id", "category"),
    family="insights",
    source="get_insights(insight_type=adblock).data.series[].sum",
    evidence="verified",
)

INSIGHTS_BLOCKED_TOTAL = _gauge(
    f"{PREFIX}_insights_blocked_total",
    "Total blocked-threat events observed in the insights window, by category.",
    ("network_id", "category"),
    family="insights",
    source="get_insights(insight_type=blocked).data.series[].sum",
    evidence="verified",
)

INSIGHTS_INSPECTED_TOTAL = _gauge(
    f"{PREFIX}_insights_inspected_total",
    "Total inspected-traffic events observed in the insights window, by category.",
    ("network_id", "category"),
    family="insights",
    source="get_insights(insight_type=inspected).data.series[].sum",
    evidence="verified",
)

# =============================================================================
# THREAD
# =============================================================================

# `eero_thread_device_count`/`eero_thread_border_router` were removed in
# 4.0.0 -- `get_thread` has neither key (§11.11). `NETWORK_THREAD_ENABLED`
# (the one thread-related value with a source) lives in the network_features
# family above, read straight off the network envelope.
_register_family("thread", "core")

# =============================================================================
# PORT FORWARDING
# =============================================================================

NETWORK_PORT_FORWARDS_COUNT = _gauge(
    f"{PREFIX}_network_port_forwards_count",
    "Total number of port forwarding rules",
    ("network_id", "name"),
    family="port_forwards",
    source="len(get_forwards())",
    evidence="verified",
)

PORT_FORWARD_INFO = _info(
    f"{PREFIX}_port_forward",
    "Port forward rule information (never the forwarded IP address)",
    ("network_id", "forward_id"),
    family="port_forwards",
    source="get_forwards()[] (client_port, gateway_port, protocol, description;"
    " falls back to legacy port/external_port/internal_port/nickname)."
    " routing.data.forwards.data was empty (len 0) on the probed mesh --"
    " the remapped keys are unverified.",
    evidence="inferred",
)

PORT_FORWARD_ENABLED = _gauge(
    f"{PREFIX}_port_forward_enabled",
    "Whether the port forward is enabled (1=yes, 0=no)",
    ("network_id", "forward_id", "gateway_port", "protocol"),
    family="port_forwards",
    source="get_forwards()[].enabled",
    evidence="inferred",
)

# =============================================================================
# DHCP RESERVATIONS
# =============================================================================

NETWORK_DHCP_RESERVATIONS_COUNT = _gauge(
    f"{PREFIX}_network_dhcp_reservations_count",
    "Number of DHCP reservations configured",
    ("network_id", "name"),
    family="reservations",
    source="len(get_reservations())",
    evidence="verified",
)

# =============================================================================
# BLACKLIST
# =============================================================================

NETWORK_BLACKLISTED_DEVICES_COUNT = _gauge(
    f"{PREFIX}_network_blacklisted_devices_count",
    "Number of blacklisted/blocked devices",
    ("network_id", "name"),
    family="blacklist",
    source="len(get_blacklist())",
    evidence="verified",
)

# =============================================================================
# PREMIUM
# =============================================================================

# `NETWORK_PREMIUM_ENABLED` (network_features) and
# `ACCOUNT_PREMIUM_NEXT_RENEWAL` (account) already carry the premium signals
# with a real source; this family is a placeholder for the extended-tier
# premium reads (`get_backup_internet`, `list_backup_access_points`,
# entitlement features) a later commit will add.
_register_family("premium", "core")


def reset_all_metrics() -> None:
    """Reset all metrics to their default state.

    This is useful when re-scraping to avoid stale data.
    """
    # Note: Info metrics cannot be reset, they are idempotent
    # Gauges need to be cleared per label set, which we handle in the collector
    pass


def describe_metrics() -> list[MetricProvenance]:
    """Return provenance for every declared metric, for docs generation.

    A docs agent can use this to regenerate ``wiki/Metrics.md`` without
    re-deriving family/tier/source information by hand.

    Returns:
        One :class:`MetricProvenance` per declared metric, sorted by name.
    """
    return [_METRIC_PROVENANCE[name] for name in sorted(_METRIC_PROVENANCE)]


def register_metrics(config: Any, registry: Any = REGISTRY) -> None:
    """Register every metric whose tier/family is enabled by ``config``.

    Core-tier families are always registered unless they have their own
    per-family ``include_*`` flag (data_usage, devices, ...), which then
    gates them the same way it always gated the collector's own reads. Every
    other tier is gated by the matching ``ExporterConfig.include_<tier>``
    flag. Safe to call more than once (with the same or a different
    ``registry``) -- metrics already registered into a given registry are
    silently skipped rather than raising.

    Args:
        config: The active ``ExporterConfig``.
        registry: The Prometheus registry to register into. Defaults to the
            global default registry ``generate_latest()`` reads from.
    """
    for family, metrics in _FAMILY_METRICS.items():
        tier = FAMILY_TIER[family]
        if tier == "core":
            flag_name = _FAMILY_INCLUDE_FLAG.get(family)
        else:
            flag_name = _TIER_INCLUDE_FLAG[tier]

        if flag_name is not None and not getattr(config, flag_name, True):
            continue

        for metric in metrics:
            try:
                registry.register(metric)
            except ValueError:
                # Already registered into this registry -- idempotent no-op.
                pass
