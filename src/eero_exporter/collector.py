"""Collector module for gathering eero metrics."""

import logging
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import ExporterConfig
from .eero_adapter import (
    EeroAccessDeniedError,
    EeroAPIError,
    EeroAuthError,
    EeroClient,
    EeroFeatureUnavailableError,
    EeroNotFoundError,
    EeroPremiumRequiredError,
    EeroRateLimitError,
    EeroTransportError,
    EeroValidationError,
    _parse_network_status,
)
from .metrics import (
    ACCOUNT_ENTITLEMENT_CREATED_TIMESTAMP,
    ACCOUNT_ENTITLEMENT_PRODUCT_INFO,
    ACCOUNT_ENTITLEMENT_STATE,
    ACCOUNT_NETWORKS_COUNT,
    ACCOUNT_PREMIUM_NEXT_RENEWAL,
    API_STATUS_VALUES,
    BACKUP_ACCESS_POINT_CONNECTIVITY_INFO,
    BACKUP_ACCESS_POINT_ENABLED,
    BACKUP_ACCESS_POINTS_COUNT,
    CELLULAR_BACKUP_OUTAGES_COUNT,
    CELLULAR_BACKUP_USAGE_ITEMS_COUNT,
    DATA_USAGE_DOWNLOAD_BYTES,
    DATA_USAGE_UPLOAD_BYTES,
    DEVICE_BLOCKED,
    DEVICE_CHANNEL,
    DEVICE_CONNECTED,
    DEVICE_CONNECTED_TO_GATEWAY,
    DEVICE_CONNECTION_SCORE,
    DEVICE_CONNECTION_SCORE_BARS,
    DEVICE_DATA_USAGE_BYTES,
    DEVICE_DATA_USAGE_DOWNLOAD_BYTES,
    DEVICE_DATA_USAGE_UPLOAD_BYTES,
    DEVICE_FIRST_SEEN_TIMESTAMP,
    DEVICE_FREQUENCY,
    DEVICE_INFO,
    DEVICE_INSIGHTS_TOTAL,
    DEVICE_IS_GUEST,
    DEVICE_LAST_ACTIVE_TIMESTAMP,
    DEVICE_PACKET_STATS_RX_DROP_PPM,
    DEVICE_PACKET_STATS_RX_DROPS,
    DEVICE_PACKET_STATS_RX_PACKETS,
    DEVICE_PACKET_STATS_TOTAL_PACKETS,
    DEVICE_PACKET_STATS_TX_FAIL_PPM,
    DEVICE_PACKET_STATS_TX_PACKETS,
    DEVICE_PACKET_STATS_TX_RETRANSMIT_PPM,
    DEVICE_PACKET_STATS_TX_RETRIES,
    DEVICE_PAUSED,
    DEVICE_PRIVATE,
    DEVICE_RX_BITRATE,
    DEVICE_RX_MCS,
    DEVICE_RX_NSS,
    DEVICE_SIGNAL_STRENGTH,
    DEVICE_SUBNET_KIND_INFO,
    DEVICE_TX_BITRATE,
    DEVICE_TX_MCS,
    DEVICE_TX_NSS,
    DEVICE_WIFI_GENERATION,
    DEVICE_WIRELESS,
    DNS_CONFIG_INFO,
    DNS_POLICY_ALLOWED_DOMAINS_COUNT,
    DNS_POLICY_BLOCKED_DOMAINS_COUNT,
    EERO_BAND_SUPPORTED,
    EERO_CHANNEL_ACS_EVENTS_TOTAL,
    EERO_CHANNEL_BUSY_LAST,
    EERO_CHANNEL_BUSY_MINUTES,
    EERO_CHANNEL_INFO,
    EERO_CHANNEL_NOISE_LAST,
    EERO_CHANNEL_RX_OTHER_LAST,
    EERO_CHANNEL_RX_TX_LAST,
    EERO_CHANNEL_UTILIZATION_AVG_PERCENT,
    EERO_CHANNEL_UTILIZATION_MAX_PERCENT,
    EERO_CHANNEL_UTILIZATION_P99_PERCENT,
    EERO_CONNECTED_CLIENTS,
    EERO_CONNECTED_WIRED_CLIENTS,
    EERO_CONNECTED_WIRELESS_CLIENTS,
    EERO_CONNECTION_TYPE_INFO,
    EERO_DATA_USAGE_BYTES,
    EERO_EERO_CONNECTIONS_COUNT,
    EERO_EERO_ROLE_INFO,
    EERO_HEARTBEAT_OK,
    EERO_INFO,
    EERO_IS_GATEWAY,
    EERO_IS_PRIMARY,
    EERO_JOINED,
    EERO_LAST_HEARTBEAT,
    EERO_LAST_REBOOT,
    EERO_LED_BRIGHTNESS,
    EERO_LED_ON,
    EERO_MESH_QUALITY,
    EERO_NETWORK_WPA3_BAND_MODE,
    EERO_NIGHTLIGHT_BRIGHTNESS,
    EERO_NIGHTLIGHT_ENABLED,
    EERO_NIGHTLIGHT_SCHEDULE_ENABLED,
    EERO_OS_VERSION_INFO,
    EERO_OUICHECK_CAN_ADD,
    EERO_OUICHECK_MUST_UPDATE,
    EERO_POWER_SAVING_ACTIVE,
    EERO_POWER_SOURCE_INFO,
    EERO_PROVIDES_WIFI,
    EERO_RADIO_CHANNEL,
    EERO_RADIO_CHANNEL_UTILIZATION,
    EERO_RADIO_CHANNEL_WIDTH,
    EERO_RADIO_CLIENT_COUNT,
    EERO_RADIO_COUNT,
    EERO_RADIO_TX_POWER,
    EERO_STATUS,
    EERO_UP,
    EERO_UPDATE_AVAILABLE,
    EERO_UPTIME_SECONDS,
    EERO_USING_WAN,
    EERO_WIRED,
    EERO_WIRED_INTERNET,
    ETHERNET_PORT_CARRIER,
    ETHERNET_PORT_INFO,
    ETHERNET_PORT_IS_LTE,
    ETHERNET_PORT_IS_WAN,
    ETHERNET_PORT_NEIGHBOR_INFO,
    ETHERNET_PORT_SPEED,
    EXPORTER_API_REQUESTS,
    EXPORTER_API_REQUESTS_LAST_CYCLE,
    EXPORTER_COLLECTION_INTERVAL,
    EXPORTER_LAST_COLLECTION_TIMESTAMP,
    EXPORTER_SCRAPE_DURATION,
    EXPORTER_SCRAPE_ERRORS,
    GUEST_NETWORK_CONNECTED_CLIENTS,
    GUEST_NETWORK_INFO,
    HEALTH_STATUS,
    INSIGHTS_ADBLOCK_TOTAL,
    INSIGHTS_BLOCKED_TOTAL,
    INSIGHTS_INSPECTED_TOTAL,
    NETWORK_AC_COMPAT,
    NETWORK_AD_BLOCK_ENABLED,
    NETWORK_BACKUP_INTERNET_ENABLED,
    NETWORK_BAND_STEERING_ENABLED,
    NETWORK_BLACKLISTED_DEVICES_COUNT,
    NETWORK_CAPABILITY,
    NETWORK_CLIENTS_COUNT,
    NETWORK_CONNECTION_MODE_INFO,
    NETWORK_CUSTOM_DNS_ENABLED,
    NETWORK_DATA_USAGE_BYTES,
    NETWORK_DDNS_ENABLED,
    NETWORK_DHCP_MODE_INFO,
    NETWORK_DHCP_RESERVATIONS_COUNT,
    NETWORK_DNS_CACHING_ENABLED,
    NETWORK_DNS_MODE_INFO,
    NETWORK_DNS_PARENT_SERVER_COUNT,
    NETWORK_DNS_SERVER_COUNT,
    NETWORK_DOUBLE_NAT_DETECTED,
    NETWORK_EEROS_COUNT,
    NETWORK_FAST_TRANSITION_ENABLED,
    NETWORK_FEATURE_ENTITLED,
    NETWORK_GUEST_ENABLED,
    NETWORK_INFO,
    NETWORK_IPV6_ENABLED,
    NETWORK_ISP_UP,
    NETWORK_LAST_REBOOT,
    NETWORK_MALWARE_BLOCK_ENABLED,
    NETWORK_MEMBERS_COUNT,
    NETWORK_MLO_MODE_INFO,
    NETWORK_MULTISTATICIP_ENABLED,
    NETWORK_NOTIFICATION_ENABLED,
    NETWORK_NOTIFICATIONS_UNREAD,
    NETWORK_PER_EERO_PERMISSION,
    NETWORK_PERMISSION,
    NETWORK_PORT_FORWARDS_COUNT,
    NETWORK_POWER_SAVING_ENABLED,
    NETWORK_POWER_SAVING_SCHEDULES_COUNT,
    NETWORK_PREMIUM_ENABLED,
    NETWORK_ROLE_INFO,
    NETWORK_ROUTING_DEVICES_COUNT,
    NETWORK_ROUTING_FORWARDS_COUNT,
    NETWORK_ROUTING_PINHOLES_COUNT,
    NETWORK_ROUTING_RESERVATIONS_COUNT,
    NETWORK_SCAN_CONFLICTING_SSID,
    NETWORK_SQM_ENABLED,
    NETWORK_STATUS,
    NETWORK_THREAD_ENABLED,
    NETWORK_TIMEZONE_INFO,
    NETWORK_UPDATE_AVAILABLE,
    NETWORK_UPDATE_TARGET_INFO,
    NETWORK_UPDATES_AVAILABLE,
    NETWORK_UPNP_ENABLED,
    NETWORK_WAN_TYPE_INFO,
    NETWORK_WIRELESS_MODE_INFO,
    NETWORK_WPA3_ENABLED,
    PORT_FORWARD_ENABLED,
    PORT_FORWARD_INFO,
    PROFILE_BLOCKED_APPLICATIONS_COUNT,
    PROFILE_CONNECTED_DEVICES_COUNT,
    PROFILE_CONTENT_FILTERS_SET,
    PROFILE_DATA_USAGE_BYTES,
    PROFILE_DEVICES_COUNT,
    PROFILE_DNS_POLICY_APPLICATIONS_COUNT,
    PROFILE_INSIGHTS_DEVICES,
    PROFILE_INSIGHTS_TOTAL,
    PROFILE_PAUSED,
    PROFILE_SCHEDULES_COUNT,
    SPEED_DOWNLOAD_MBPS,
    SPEED_TEST_TIMESTAMP,
    SPEED_TESTS_TOTAL,
    SPEED_UPLOAD_MBPS,
    SUBNET_ENABLED,
    SUBNET_IGMP_SNOOPING_ENABLED,
    SUBNET_LAN_ACCESS,
    SUBNET_NAT_PORT_RANDOMIZATION,
    SUBNET_OPEN_NETWORK,
    SUBNET_WAN_ACCESS,
    UNPROFILED_DATA_USAGE_BYTES,
)

_LOGGER = logging.getLogger(__name__)


def _extract_id_from_url(url: Any) -> str:
    """Extract ID from an API URL.

    Strips a trailing slash and any ``?query`` suffix before taking the last
    path segment (v8 migration plan §1.2a) -- the eero API has never been
    observed to return either, but a defensive parser should not silently
    misparse if it ever does.
    """
    if not url:
        return ""
    url_str = str(url).split("?", 1)[0]
    parts = url_str.rstrip("/").split("/")
    return parts[-1] if parts else ""


_PROFILE_ID_RE = re.compile(r"/profiles/([^/?]+)")


def _extract_profile_id_from_url(url: Any) -> str:
    """Extract a profile ID from a ``.../profiles/<id>/...`` URL path.

    Falls back to :func:`_extract_id_from_url` (last path segment) if the
    ``profiles/<id>`` pattern is not present, since the exact URL shape of
    ``insights_url`` was redacted in the v8 probe (§11.6).
    """
    if not url:
        return ""
    match = _PROFILE_ID_RE.search(str(url))
    if match:
        return match.group(1)
    return _extract_id_from_url(url)


_DEVICE_ID_RE = re.compile(r"/devices/([^/?]+)")


def _extract_device_id_from_url(url: Any) -> str:
    """Extract a device ID from a ``.../devices/<id>/...`` URL path.

    Falls back to :func:`_extract_id_from_url` (last path segment) if the
    ``devices/<id>`` pattern is not present, since the exact URL shape of
    device-level ``insights_url`` was redacted in the v8 probe (§11.6).
    """
    if not url:
        return ""
    match = _DEVICE_ID_RE.search(str(url))
    if match:
        return match.group(1)
    return _extract_id_from_url(url)


def _parse_signal_strength(signal_str: str | None) -> float | None:
    """Parse signal strength string to float."""
    if not signal_str:
        return None
    try:
        return float(signal_str.replace(" dBm", "").strip())
    except (ValueError, AttributeError):
        return None


_BITRATE_UNIT_RE = re.compile(r"\s*mbit/s\s*$|\s*mbps\s*$", re.IGNORECASE)


def _parse_bitrate(bitrate_str: str | None) -> float | None:
    """Parse a legacy bitrate string (e.g. ``"866.7 Mbit/s"``) to a Mbps float.

    Case-insensitive: the eero API and its SDK have both been observed to
    use ``Mbit/s`` and ``Mbps`` with varying case.
    """
    if not bitrate_str:
        return None
    try:
        cleaned = _BITRATE_UNIT_RE.sub("", bitrate_str).strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return None


def _rate_bps_to_mbps(rate_info: Any) -> float | None:
    """Read ``rate_bps`` off a ``{rx,tx}_rate_info`` object and convert to Mbps.

    Args:
        rate_info: The ``connectivity.{rx,tx}_rate_info`` dict, or None.

    Returns:
        The rate in Mbps, or None if ``rate_info`` is missing or has no
        numeric ``rate_bps``.
    """
    if not isinstance(rate_info, dict):
        return None
    rate_bps = rate_info.get("rate_bps")
    if rate_bps is None:
        return None
    try:
        return float(rate_bps) / 1e6
    except (TypeError, ValueError):
        return None


# Ethernet port speed enum -> Mbps, per §11.2/§7 of the v8 probe shape
# summary (`eeros[].ethernet_status.statuses[].speed` and
# `devices[].connectivity.ethernet_status.speed`). Unknown enum values are
# left unset -- never guessed -- and DEBUG-logged (key only, never a payload
# value).
_ETHERNET_SPEED_MBPS: dict[str, float] = {
    "P10": 10.0,
    "P100": 100.0,
    "P1000": 1000.0,
    "P10000": 10000.0,
}

# Module-level set to deduplicate "unknown ethernet speed enum" DEBUG log
# entries, keyed by the raw enum string.
_UNKNOWN_ETHERNET_SPEEDS_SEEN: set[str] = set()


def _parse_ethernet_speed_enum(speed: str | None) -> float | None:
    """Map the eero ethernet port speed enum to a Mbps value.

    Args:
        speed: The raw ``speed`` enum value, e.g. ``"P1000"``.

    Returns:
        The speed in Mbps, or None if ``speed`` is missing or not one of the
        observed enum values (``P10``, ``P100``, ``P1000``, ``P10000``).
    """
    if not speed:
        return None
    key = str(speed).strip().upper()
    mapped = _ETHERNET_SPEED_MBPS.get(key)
    if mapped is None and key not in _UNKNOWN_ETHERNET_SPEEDS_SEEN:
        _UNKNOWN_ETHERNET_SPEEDS_SEEN.add(key)
        _LOGGER.debug("Unknown ethernet port speed enum %r", key)
    return mapped


# The exact `radio_channel_stats` band vocabulary (§8/§11.2 of the v8 probe
# shape summary) -- also `eeros[].bands[]`'s enum. Keys outside this set are
# skipped defensively rather than exported under an unbounded label value.
_CHANNEL_UTILIZATION_BANDS: frozenset[str] = frozenset(
    {"band_2_4GHz", "band_5GHz_low", "band_5GHz_high", "band_5GHz_full", "band_6GHz"}
)

_LABEL_SANITIZE_RE = re.compile(r"[^a-z0-9_]")


def _sanitize_label_value(value: str) -> str:
    """Sanitise an API-provided key for use as a Prometheus label value.

    Used for the eero API's own bounded vocabularies (capability names,
    notification-setting keys) that may contain characters Prometheus label
    values tolerate but that are worth normalising for consistency --
    lower-cased, with every run of non ``[a-z0-9_]`` characters collapsed to
    a single underscore.

    Args:
        value: The raw key/name from the API.

    Returns:
        The sanitised label value.
    """
    return _LABEL_SANITIZE_RE.sub("_", value.strip().lower())


# WPA3-per-band field name -> band label, and the closed 3-value mode enum
# (§11.10 of the v8 probe shape summary). The SDK's setter only accepts two
# bands; the API has three.
_WPA3_BAND_FIELDS: dict[str, str] = {
    "band_2_4_ghz": "2_4_ghz",
    "band_5_ghz": "5_ghz",
    "band_6_ghz": "6_ghz",
}
_WPA3_MODES: tuple[str, ...] = ("WPA2", "WPA2_WPA3", "WPA3")

# Permission dict keys skipped defensively -- redacted-class shapes
# (`*.password`, `*.multi_ssid`) or keys with no useful CRUD signal
# (`network.multistatic_ip`, `user.conversations_token`); `per_eero` is a
# list, not a CRUD dict, and is skipped by its own explicit check (§11.9).
_PERMISSION_SKIP_SUFFIXES: tuple[str, ...] = (".password", ".multi_ssid")
_PERMISSION_SKIP_KEYS: frozenset[str] = frozenset(
    {"network.multistatic_ip", "user.conversations_token"}
)

# Subnet boolean field -> metric, populated after the metrics module is
# imported (see the import block above); §11.10 of the v8 probe.
_SUBNET_BOOL_FIELDS: dict[str, Any] = {
    "enabled": SUBNET_ENABLED,
    "wan_access": SUBNET_WAN_ACCESS,
    "lan_access": SUBNET_LAN_ACCESS,
    "open_network": SUBNET_OPEN_NETWORK,
    "nat_port_randomization": SUBNET_NAT_PORT_RANDOMIZATION,
    "igmp_snooping_enable": SUBNET_IGMP_SNOOPING_ENABLED,
}

# The three insight types the API supports, shared by network-, profile-, and
# device-level insights (§11.6).
_INSIGHT_TYPES: tuple[str, ...] = ("adblock", "blocked", "inspected")

# Bound on `get_speed_tests(limit=...)` for the unverified tier's speed-test
# history read (§9 #27) -- a small fixed window, not the full history.
_SPEED_TESTS_LIMIT = 5

# Module-level set to deduplicate "unverified-tier payload keys" DEBUG log
# entries within a single collection cycle, keyed by (endpoint, network_id).
# Cleared at the start of every collect() cycle so a key set that reappears
# in a later cycle is logged again (schema drift should stay visible).
_UNVERIFIED_KEYS_LOGGED_THIS_CYCLE: set[tuple[str, str]] = set()


def _log_observed_keys_once(endpoint: str, network_id: str, payload: Any) -> None:
    """DEBUG-log the top-level key set of an unverified-tier payload, once per cycle.

    Never logs a value -- only the key names -- so a schema change is
    discoverable without risking a leak of account data (§ hard rules).

    Args:
        endpoint: The endpoint label the payload came from.
        network_id: The network the payload was collected for.
        payload: The raw (post-envelope-extraction) payload. Only ``dict``
            payloads produce a key set; anything else is a no-op.
    """
    if not isinstance(payload, dict):
        return
    dedup_key = (endpoint, network_id)
    if dedup_key in _UNVERIFIED_KEYS_LOGGED_THIS_CYCLE:
        return
    _UNVERIFIED_KEYS_LOGGED_THIS_CYCLE.add(dedup_key)
    _LOGGER.debug(
        "%s: observed top-level keys for network %s: %s",
        endpoint,
        network_id,
        sorted(payload.keys()),
    )


# Three timestamp shapes coexist across the eero API (§11.0 of the v8 probe
# shape summary):
#   1. `...T..:..:...mmmZ`        -- millisecond fraction, Zulu suffix
#   2. `...T..:..:...nnnnnnnnnZ`  -- 9-digit (nanosecond) fraction, Zulu
#      suffix; `datetime.fromisoformat` rejects anything but 3 or 6 fraction
#      digits, so this is truncated to microsecond precision before parsing.
#   3. `...T..:..:..+0000`        -- UTC offset with no colon (`eeros[].joined`,
#      `speed_tests[].date`); `datetime.fromisoformat` on Python < 3.11 (and
#      the colon-less form on any version prior to 3.11) rejects this too, so
#      a colon is inserted defensively.
_TIMESTAMP_FRACTION_RE = re.compile(r"\.(\d{7,9})Z$")
_TIMESTAMP_OFFSET_RE = re.compile(r"([+-]\d{2})(\d{2})$")


def _parse_timestamp(timestamp_str: str | None) -> float | None:
    """Parse any of the eero API's three ISO-8601 timestamp shapes to Unix epoch.

    Args:
        timestamp_str: The raw timestamp string.

    Returns:
        The Unix epoch seconds, or None if ``timestamp_str`` is missing or
        unparseable.
    """
    if not timestamp_str:
        return None
    candidate = timestamp_str.strip()

    # Truncate an over-long fractional-seconds field (nanoseconds) to
    # microseconds -- `datetime.fromisoformat` only accepts 3 or 6 digits.
    fraction_match = _TIMESTAMP_FRACTION_RE.search(candidate)
    if fraction_match:
        fraction = fraction_match.group(1)[:6]
        candidate = candidate[: fraction_match.start()] + f".{fraction}Z"

    candidate = candidate.replace("Z", "+00:00")

    # Insert a colon into a colon-less UTC offset (`+0000` -> `+00:00`).
    offset_match = _TIMESTAMP_OFFSET_RE.search(candidate)
    if offset_match:
        candidate = (
            candidate[: offset_match.start()] + f"{offset_match.group(1)}:{offset_match.group(2)}"
        )

    try:
        dt = datetime.fromisoformat(candidate)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _format_utc_z(dt: datetime) -> str:
    """Format a UTC datetime as ``YYYY-MM-DDTHH:MM:SSZ`` (no fractional seconds)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_timezone(timezone_data: Any) -> ZoneInfo:
    """Resolve a network's timezone, falling back to UTC.

    Args:
        timezone_data: The ``timezone`` field from network details. May be a
            dict (``{"value": ...}`` or ``{"name": ...}``), a plain string,
            or None.

    Returns:
        A ZoneInfo for the network timezone, or UTC if it cannot be resolved.
    """
    timezone_name = "UTC"
    if isinstance(timezone_data, dict):
        timezone_name = str(timezone_data.get("value") or timezone_data.get("name") or "UTC")
    elif timezone_data:
        timezone_name = str(timezone_data)

    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        _LOGGER.debug("Unknown eero timezone %s; using UTC", timezone_name)
        return ZoneInfo("UTC")


def _data_usage_period_payload(
    period: str,
    timezone: ZoneInfo,
    now: datetime | None = None,
) -> tuple[str, str, dict[str, str]]:
    """Build an eero data_usage request payload for the current calendar period.

    Args:
        period: One of ``"day"``, ``"week"``, or ``"month"``.
        timezone: Network timezone used to anchor the period boundaries.
        now: Reference time; defaults to the current time in ``timezone``.
            Exposed for deterministic testing.

    Returns:
        A tuple of ``(period, cadence, payload)`` where ``payload`` carries the
        ISO-8601 ``start``/``end`` (UTC), ``cadence``, and ``timezone`` fields.

    Raises:
        ValueError: If ``period`` is not a supported value.
    """
    if now is None:
        now = datetime.now(timezone)

    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1) - timedelta(seconds=1)
        cadence = "hourly"
    elif period == "week":
        # eero activity weeks start on Sunday, matching the official app.
        # weekday() is Mon=0..Sun=6; (weekday + 1) % 7 days back reaches the
        # most recent Sunday, and correctly yields 0 when today is Sunday.
        days_since_sunday = (now.weekday() + 1) % 7
        start = now - timedelta(days=days_since_sunday)
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(weeks=1) - timedelta(seconds=1)
        cadence = "daily"
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        end = next_month - timedelta(seconds=1)
        cadence = "daily"
    else:
        raise ValueError(f"Unsupported data usage period: {period}")

    payload = {
        "start": start.astimezone(UTC).replace(tzinfo=None).isoformat() + "Z",
        "end": end.astimezone(UTC).replace(tzinfo=None).isoformat() + "Z",
        "cadence": cadence,
        "timezone": timezone.key,
    }
    return period, cadence, payload


def _series_sum(series: dict[str, Any]) -> float | None:
    """Return a usage series total, computing it from values when needed.

    Args:
        series: A single data_usage series object.

    Returns:
        The series total in bytes, or None if no numeric data is present.
    """
    value = series.get("sum")
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    values = series.get("values", [])
    if not isinstance(values, list):
        return None

    total = 0.0
    found = False
    for item in values:
        if not isinstance(item, dict) or item.get("value") is None:
            continue
        try:
            total += float(item["value"])
            found = True
        except (TypeError, ValueError):
            continue
    return total if found else None


def _record_api_result(endpoint: str, exc: Exception | None) -> str:
    """Classify an adapter call's outcome and record it as an API-request metric.

    The single place per-endpoint status classification happens for the
    collector -- replaces the 18 hand-written ``except EeroAPIError`` blocks
    that used to duplicate this logic. Classification is always by exception
    class, never by matching message text (see eero_adapter.py's mapping
    table). Log severity reflects how expected the outcome is: absent
    features/subscriptions/resources are DEBUG, permission and validation
    problems are WARNING, and nothing here logs at ERROR -- only top-level
    ``collect()`` failures do.

    Args:
        endpoint: A label-safe endpoint name for the ``EXPORTER_API_REQUESTS``
            metric. Never derived from request parameters or identifiers.
        exc: The exception raised by the adapter call, or ``None`` on success.

    Returns:
        The status label recorded, one of :data:`metrics.API_STATUS_VALUES`.
    """
    if exc is None:
        status = "success"
    elif isinstance(exc, EeroAuthError):
        status = "auth"
    elif isinstance(exc, EeroNotFoundError):
        status = "not_found"
    elif isinstance(exc, EeroAccessDeniedError):
        status = "access_denied"
    elif isinstance(exc, EeroPremiumRequiredError):
        status = "premium_required"
    elif isinstance(exc, EeroFeatureUnavailableError):
        status = "feature_unavailable"
    elif isinstance(exc, EeroRateLimitError):
        status = "rate_limited"
    elif isinstance(exc, EeroValidationError):
        status = "validation"
    elif isinstance(exc, EeroTransportError):
        status = "transport"
    else:
        # Generic EeroAPIError (e.g. EeroClientBlockedException, or any
        # domain error not mapped to a more specific local class).
        status = "error"

    if status not in API_STATUS_VALUES:  # pragma: no cover - defensive
        _LOGGER.error(
            "Unmapped API status %r for endpoint %s; coercing to 'error'", status, endpoint
        )
        status = "error"

    EXPORTER_API_REQUESTS.labels(endpoint=endpoint, status=status).inc()

    if status in ("premium_required", "feature_unavailable", "not_found"):
        _LOGGER.debug("%s: %s (%s)", endpoint, status, exc)
    elif status in ("access_denied", "validation", "rate_limited"):
        _LOGGER.warning("%s: %s (%s)", endpoint, status, exc)

    return status


def _parse_premium_enabled(premium_status: Any, premium_details: Any) -> bool:
    """Derive an eero-plus-active boolean from the network envelope's premium fields.

    There is no single boolean on the envelope for this -- ``premium_status``
    is a free-form string (e.g. ``"active"``, ``"none"``) and
    ``premium_details`` is a dict that is populated only when a subscription
    exists. Both are read defensively since either may be absent or of an
    unexpected type.

    Args:
        premium_status: The ``premium_status`` field from the network envelope.
        premium_details: The ``premium_details`` field from the network envelope.

    Returns:
        True if the network appears to have an active Eero Plus/Secure
        subscription, False otherwise.
    """
    status_str = str(premium_status).strip().lower() if premium_status else ""
    if status_str and status_str not in ("none", "false", "free", "inactive"):
        return True
    if isinstance(premium_details, dict) and premium_details:
        tier = premium_details.get("tier")
        if tier:
            return True
    return False


# Module-level set to deduplicate "unknown dict shape" DEBUG log entries.
# Keyed by (field_name, sorted-keys-tuple) so we log only once per unique
# field + key combination rather than every 5-minute scrape cycle.
_COERCE_UNKNOWN_SHAPES_SEEN: set[tuple[str, tuple[str, ...]]] = set()

_COERCE_DICT_KEYS = ("seconds", "value", "current", "total", "count")


def _coerce_numeric(value: Any, field_name: str = "") -> float | None:
    """Coerce a value of unknown type to float, handling dict shapes defensively.

    The Eero Cloud API may change numeric fields from plain numbers to dicts
    (e.g. ``uptime`` changed from ``int`` to ``{"seconds": N}``). This helper
    normalises all plausible shapes so a schema migration on one field cannot
    abort an entire collection cycle.

    Args:
        value: The raw value from the API response.
        field_name: Name of the field (used for deduplicated DEBUG logging).

    Returns:
        The value as a float, or None if the value cannot be coerced.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in _COERCE_DICT_KEYS:
            if key in value:
                return _coerce_numeric(value[key], field_name=field_name)
        # No known key found — log once per (field_name, keys) combo.
        sorted_keys = tuple(sorted(value.keys()))
        dedup_key = (field_name, sorted_keys)
        if dedup_key not in _COERCE_UNKNOWN_SHAPES_SEEN:
            _COERCE_UNKNOWN_SHAPES_SEEN.add(dedup_key)
            _LOGGER.debug(
                "Cannot coerce dict to numeric for field %r: unknown keys %s",
                field_name,
                sorted_keys,
            )
        return None
    return None


def _coerce_power_saving_enabled(value: Any) -> bool | None:
    """Coerce a power-saving field to a bool, defensively across shapes.

    The v8 probe observed a plain bool at the network level
    (``network.data.power_saving``) and an object at the eero level
    (``eeros[].power_saving.schedule.active``, §7 of the v8 probe shape
    summary). Both shapes -- plus a flatter ``{"enabled": bool}`` some
    firmwares have used -- are handled so a schema change on either path
    degrades gracefully instead of aborting collection.

    Args:
        value: The raw ``power_saving`` field.

    Returns:
        The resolved boolean, or None if the shape is unrecognised.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        if "enabled" in value:
            enabled = value.get("enabled")
            return bool(enabled) if isinstance(enabled, bool) else None
        schedule = value.get("schedule")
        if isinstance(schedule, dict):
            active = schedule.get("active")
            if isinstance(active, bool):
                return active
    return None


def _frequency_to_band(frequency: int | None) -> str:
    """Convert frequency in MHz to WiFi band label.

    Args:
        frequency: Frequency in MHz (e.g., 2412, 5180, 6115)

    Returns:
        Band label: "2.4GHz", "5GHz", "6GHz", or "unknown"
    """
    if not frequency:
        return "unknown"
    if 2400 <= frequency <= 2500:
        return "2.4GHz"
    if 5150 <= frequency <= 5925:
        return "5GHz"
    if 5925 <= frequency <= 7125:
        return "6GHz"
    return "unknown"


def _normalize_manufacturer(manufacturer: str | None) -> str:
    """Normalize manufacturer name for consistent labeling.

    Args:
        manufacturer: Raw manufacturer string from API

    Returns:
        Normalized manufacturer name or "unknown"
    """
    if not manufacturer:
        return "unknown"
    # Truncate long manufacturer names and normalize
    name = manufacturer.strip()[:50]
    return name if name else "unknown"


def _normalize_device_type(device_type: str | None) -> str:
    """Normalize device type for consistent labeling.

    Args:
        device_type: Raw device type from API

    Returns:
        Normalized device type or "unknown"
    """
    if not device_type:
        return "unknown"
    return device_type.strip().lower()[:30] or "unknown"


def _get_connection_type(device: dict[str, Any]) -> str:
    """Determine connection type from device data.

    Args:
        device: Device dictionary from API

    Returns:
        "wired", "wireless", or "unknown"
    """
    wireless = device.get("wireless")
    if wireless is True:
        return "wireless"
    if wireless is False:
        return "wired"
    # Check connection_type field as fallback
    conn_type = device.get("connection_type", "")
    if conn_type:
        return conn_type.lower() if conn_type.lower() in ("wired", "wireless") else "unknown"
    return "unknown"


def _get_source_eero_location(device: dict[str, Any]) -> str:
    """Extract the location of the eero the device is connected to.

    Args:
        device: Device dictionary from API

    Returns:
        Location string of source eero or "unknown"
    """
    source = device.get("source", {})
    if source and isinstance(source, dict):
        location = source.get("location")
        if location:
            return str(location)[:50]
    return "unknown"


def _get_wifi_generation(device: dict[str, Any]) -> int | None:
    """Determine WiFi generation from device connectivity data.

    Args:
        device: Device dictionary from API

    Returns:
        WiFi generation (4, 5, 6, 7) or None if not determinable
    """
    connectivity = device.get("connectivity", {})
    if not connectivity:
        return None

    # Check for explicit wifi_generation field
    wifi_gen = connectivity.get("wifi_generation")
    if wifi_gen is not None:
        return int(wifi_gen)

    # Infer from frequency and capabilities
    frequency = connectivity.get("frequency")
    rx_rate_info = connectivity.get("rx_rate_info", {})

    if not frequency:
        return None

    # Check for WiFi 6E (6GHz band)
    if frequency and 5925 <= frequency <= 7125:
        return 6  # WiFi 6E uses WiFi 6 standard

    # Check for HE (High Efficiency = WiFi 6) indicators
    if rx_rate_info:
        # WiFi 6 uses HE (High Efficiency) mode
        mode = rx_rate_info.get("mode", "")
        if mode and "he" in str(mode).lower():
            return 6
        if mode and "ax" in str(mode).lower():
            return 6
        # WiFi 5 uses VHT (Very High Throughput)
        if mode and "vht" in str(mode).lower():
            return 5
        if mode and "ac" in str(mode).lower():
            return 5
        # WiFi 4 uses HT (High Throughput)
        if mode and "ht" in str(mode).lower():
            return 4
        if mode and "n" in str(mode).lower():
            return 4

    return None


class EeroCollector:
    """Collector for eero metrics."""

    def __init__(
        self,
        session_file: str | None = None,
        config: ExporterConfig | None = None,
    ) -> None:
        """Initialize the collector.

        Args:
            session_file: Path to session/cookie file for authentication.
                Overrides ``config.session_file`` when given (the CLI's
                ``test`` command and ``server.run_server`` both resolve the
                session path themselves before constructing the collector).
            config: The exporter configuration. Every ``include_*`` /
                collection-tier flag and every eero-api SDK client option
                (``get_retries``, ``send_legacy_cookie``, ``accept_language``)
                is read from here. Defaults to ``ExporterConfig()`` when
                omitted, so existing single-argument construction keeps
                working. Tier flags with no consuming family yet
                (``include_extended``/``include_rf``/``include_per_profile``/
                ``include_per_device``/``include_per_eero``/
                ``include_unverified``) are stored as attributes for a later
                commit.
        """
        self._config = config or ExporterConfig()
        cfg = self._config

        self._include_devices = cfg.include_devices
        self._include_profiles = cfg.include_profiles
        self._include_premium = cfg.include_premium
        self._include_ethernet = cfg.include_ethernet
        self._include_thread = cfg.include_thread
        self._include_port_forwards = cfg.include_port_forwards
        self._include_reservations = cfg.include_reservations
        self._include_blacklist = cfg.include_blacklist
        self._include_insights = cfg.include_insights
        self._include_data_usage = cfg.include_data_usage

        # Collection tiers (§4.2). Not yet consumed by any family -- wired in
        # a later commit -- but stored so config/CLI/env/YAML round-trip
        # cleanly ahead of that work.
        self._include_extended = cfg.include_extended
        self._include_rf = cfg.include_rf
        self._include_per_profile = cfg.include_per_profile
        self._include_per_device = cfg.include_per_device
        self._include_per_eero = cfg.include_per_eero
        self._include_unverified = cfg.include_unverified

        self._data_usage_periods = list(cfg.data_usage_periods)
        self._eeros_from_envelope = cfg.eeros_from_envelope
        self._expose_public_ip = cfg.expose_public_ip

        self._cookie_file = session_file if session_file is not None else str(cfg.session_file)
        self._send_legacy_cookie = cfg.send_legacy_cookie
        self._accept_language = cfg.accept_language
        self._get_retries = cfg.get_retries

        self._last_collection_time: float = 0
        self._cached_data: dict[str, Any] = {}
        self._is_premium: bool = False
        self._networks_count: int = 0
        self._collection_interval: int = cfg.collection_interval
        # Number of eero API requests issued so far in the collection cycle
        # currently in progress. Reset at the start of collect(), published
        # to EXPORTER_API_REQUESTS_LAST_CYCLE once the cycle finishes.
        self._api_requests_this_cycle: int = 0
        # Set when the most recent collect() call ended in an EeroAuthError;
        # None otherwise (success or a non-auth failure). Consumed by
        # server.py to implement `--auth-failure-exit` (§2).
        self.last_error_kind: str | None = None

    async def _api_get(self, endpoint: str, coro: Any) -> tuple[Any, Exception | None]:
        """Await an eero API call, classify+record its outcome, and count it.

        Centralises what used to be 18 duplicated
        ``try/except EeroAPIError`` blocks: every adapter call in this
        collector should be awaited through here (or through
        :func:`_record_api_result` directly, for the top-level ``networks``
        call which must let ``EeroAuthError`` propagate unclassified).

        Args:
            endpoint: A label-safe endpoint name, passed to
                :func:`_record_api_result`.
            coro: The adapter coroutine to await, e.g. ``client.get_network(id)``.

        Returns:
            ``(result, None)`` on success; ``(None, exc)`` on any
            :class:`EeroAPIError`. ``EeroAuthError`` is never caught here --
            it always propagates to abort the whole ``collect()`` cycle.
        """
        self._api_requests_this_cycle += 1
        try:
            result = await coro
        except EeroAPIError as e:
            status = _record_api_result(endpoint, e)
            if status == "premium_required":
                self._is_premium = False
            return None, e
        else:
            _record_api_result(endpoint, None)
            return result, None

    async def collect(self) -> bool:
        """Collect metrics from the eero API.

        Default GET budget per network per cycle (§9 of the v8 probe shape
        summary): 2 (account+networks) + network envelope (1) + eeros (1,
        skipped when `eeros_from_envelope`) + devices (1) + profiles (1) +
        data usage (len(data_usage_periods) + 1 breakdown) + insights (3) +
        profile insights (3) -- roughly 21 with every core/extended family
        on. Commit 7 adds the "extended" tier's 9 fixed-cost reads
        (entitlements, wpa3, fast_transition, permissions, members,
        notifications x2, dns_filter, subnets) plus the 3 profile-insights
        calls, all gated by `include_extended` (and `dns_filter` additionally
        by `include_premium`).

        Commit 8 adds the remaining tiers, each independently gated:

        - `rf` (default ON): +1 GET/network -- one unparameterised
          `get_channel_utilization` call covers every eero and every band.
        - `per_device` (default OFF): +3 GETs/network -- one list-level
          `get_devices_insights` call per insight type (adblock/blocked/
          inspected); covers every device on the network in those 3 calls,
          not 3·D.
        - `per_eero` (default OFF): +3 GETs/eero -- `get_nightlight`,
          `get_connections`, `get_ouicheck`, each independently guarded.
        - `per_profile` (default OFF): +1 GET/profile --
          `get_dns_policy_applications`, premium-gated.
        - `unverified` (default OFF): +12 GETs/network -- thread (key-log
          only), routing, backup access points, cellular usage + events,
          network scan, speed-test history, multistaticip, ac-compat,
          power-saving schedules, and a transfer-stats stub (network + first
          device, if any) that exports nothing.

        GET counts here never scale with D or P except through the
        per_device/per_eero/per_profile tiers (fixed-cost 3 GETs, 3·E GETs,
        and P GETs respectively) -- every core/extended read is list-level.
        For the unit-test fixture mesh (E=4, D=3, P=2, see
        `tests/test_collector_readonly.py`) this measures as **29** adapter
        calls with only defaults on, and **58** with every tier on (29 + 3
        `per_device` + 3·E=12 `per_eero` + P=2 `per_profile` + 12
        `unverified`). For the probed mesh (E=4, D=137, P=10) defaults are
        the same **29** (mesh-size-independent), and all-tiers-on is
        **29 + 3 + 12 + 10 + 12 = 66**.
        """
        start_time = time.monotonic()
        success = False
        self.last_error_kind = None
        self._api_requests_this_cycle = 0
        _UNVERIFIED_KEYS_LOGGED_THIS_CYCLE.clear()

        try:
            async with EeroClient(
                cookie_file=self._cookie_file,
                send_legacy_cookie=self._send_legacy_cookie,
                accept_language=self._accept_language,
                get_retries=self._get_retries,
            ) as client:
                self._api_requests_this_cycle += 1
                networks = await client.get_networks()
                _record_api_result("networks", None)

                if not networks:
                    _LOGGER.warning("No networks found")
                    return False

                # Track total networks count
                self._networks_count = len(networks)
                ACCOUNT_NETWORKS_COUNT.set(self._networks_count)

                for network_data in networks:
                    await self._collect_network_metrics(client, network_data)

            success = True
            # Standard Prometheus "up" metric pattern
            EERO_UP.set(1)

        except EeroAuthError as e:
            _LOGGER.error(f"Authentication error: {e}")
            self.last_error_kind = "auth"
            EXPORTER_SCRAPE_ERRORS.labels(error_type="auth").inc()
            EERO_UP.set(0)

        except EeroTransportError as e:
            _LOGGER.warning(f"Transport error during collection: {e}")
            self.last_error_kind = "network"
            EXPORTER_SCRAPE_ERRORS.labels(error_type="network").inc()
            EERO_UP.set(0)

        except EeroRateLimitError as e:
            _LOGGER.warning(f"Rate limited during collection: {e}")
            EXPORTER_SCRAPE_ERRORS.labels(error_type="rate_limit").inc()
            EERO_UP.set(0)

        except EeroAPIError as e:
            _LOGGER.error(f"API error during collection: {e}")
            EXPORTER_SCRAPE_ERRORS.labels(error_type="api").inc()
            EERO_UP.set(0)

        except Exception as e:
            _LOGGER.error("Unexpected error during collection: %s", type(e).__name__)
            EXPORTER_SCRAPE_ERRORS.labels(error_type="unknown").inc()
            EERO_UP.set(0)

        finally:
            duration = time.monotonic() - start_time
            EXPORTER_SCRAPE_DURATION.set(duration)
            self._last_collection_time = time.time()
            # Set timestamp metrics for cache monitoring
            EXPORTER_LAST_COLLECTION_TIMESTAMP.set(self._last_collection_time)
            EXPORTER_COLLECTION_INTERVAL.set(self._collection_interval)
            EXPORTER_API_REQUESTS_LAST_CYCLE.set(self._api_requests_this_cycle)
            _LOGGER.info(f"Collection completed in {duration:.2f}s (success={success})")

        return success

    async def _collect_network_metrics(
        self,
        client: EeroClient,
        network_data: dict[str, Any],
    ) -> None:
        """Collect metrics for a single network."""
        raw_id = network_data.get("id")
        network_id = str(raw_id) if raw_id else _extract_id_from_url(network_data.get("url", ""))
        network_name = network_data.get("name", "Unknown")

        if not network_id:
            _LOGGER.warning(
                "Could not extract network ID from network data (name=%s)", network_name
            )
            return

        _LOGGER.debug(f"Collecting metrics for network: {network_name} ({network_id})")

        # The network envelope is fetched exactly once per network per
        # cycle and passed to every sub-collector below -- it carries sqm,
        # premium, updates, guest-network and all E eeros inline, so those
        # families no longer issue their own GETs (§11.1 of the v8 probe).
        network_details, exc = await self._api_get("network", client.get_network(network_id))
        if exc is not None:
            _LOGGER.warning(f"Failed to get network details: {exc}")
            network_details = network_data

        # Extract status - may be nested {"status": "online"} or just "online"
        status_str = _parse_network_status(network_details.get("status"))

        # Extract ISP - may be in geo_ip.isp or isp.name or isp_name
        isp_name = network_details.get("isp_name")
        if not isp_name:
            geo_ip = network_details.get("geo_ip", {})
            if isinstance(geo_ip, dict):
                isp_name = geo_ip.get("isp")
        if not isp_name:
            isp_data = network_details.get("isp", {})
            if isinstance(isp_data, dict):
                isp_name = isp_data.get("name")
            elif isp_data:
                isp_name = str(isp_data)

        network_info: dict[str, str] = {
            "name": network_name,
            "status": status_str,
            "isp": isp_name or "unknown",
            "wan_type": network_details.get("wan_type") or "unknown",
            "gateway_ip": network_details.get("gateway_ip") or "unknown",
        }
        # `public_ip` is only exported behind `--expose-public-ip` (D13) --
        # off by default, the key is omitted entirely rather than masked.
        if self._expose_public_ip:
            ip_settings = network_details.get("ip_settings")
            public_ip = (
                ip_settings.get("public_ip") if isinstance(ip_settings, dict) else None
            ) or network_details.get("public_ip")
            network_info["public_ip"] = public_ip or "unknown"

        NETWORK_INFO.labels(network_id=network_id).info(network_info)

        is_online = 1 if status_str.lower() in ("connected", "online") else 0
        NETWORK_STATUS.labels(network_id=network_id, name=network_name).set(is_online)

        health = network_details.get("health", {})
        if health:
            internet_health = health.get("internet", {})
            eero_health = health.get("eero_network", {})
            if internet_health:
                is_healthy = 1 if internet_health.get("status") == "connected" else 0
                try:
                    HEALTH_STATUS.labels(network_id=network_id, source="internet").set(is_healthy)
                except Exception:
                    _LOGGER.warning(
                        "Failed to set HEALTH_STATUS[internet] for network %s", network_id
                    )
            if eero_health:
                is_healthy = 1 if eero_health.get("status") == "connected" else 0
                try:
                    HEALTH_STATUS.labels(network_id=network_id, source="eero_network").set(
                        is_healthy
                    )
                except Exception:
                    _LOGGER.warning(
                        "Failed to set HEALTH_STATUS[eero_network] for network %s", network_id
                    )

        # Check for speedtest data - eero-api returns "speed_test", but older versions
        # or direct API calls may return "speed"
        speed = network_details.get("speed_test") or network_details.get("speed", {})
        if speed:
            upload = speed.get("up", {})
            download = speed.get("down", {})
            if upload and "value" in upload:
                try:
                    SPEED_UPLOAD_MBPS.labels(network_id=network_id).set(upload["value"])
                except Exception:
                    _LOGGER.warning("Failed to set SPEED_UPLOAD_MBPS for network %s", network_id)
            if download and "value" in download:
                try:
                    SPEED_DOWNLOAD_MBPS.labels(network_id=network_id).set(download["value"])
                except Exception:
                    _LOGGER.warning("Failed to set SPEED_DOWNLOAD_MBPS for network %s", network_id)
            speed_ts = _parse_timestamp(speed.get("date"))
            if speed_ts is not None:
                try:
                    SPEED_TEST_TIMESTAMP.labels(network_id=network_id).set(speed_ts)
                except Exception:
                    _LOGGER.warning("Failed to set SPEED_TEST_TIMESTAMP for network %s", network_id)

        await self._collect_network_feature_flags(client, network_id, network_name, network_details)
        self._collect_network_envelope_extras(network_id, network_name, network_details)
        self._collect_network_capabilities(network_id, network_details)
        eeros = await self._collect_eero_metrics(client, network_id, network_name, network_details)

        devices: list[dict[str, Any]] | None = None
        if self._include_devices:
            devices = await self._collect_device_metrics(client, network_id, network_name)

        if self._include_data_usage:
            await self._collect_data_usage_metrics(client, network_id, network_details)

        profiles: list[dict[str, Any]] | None = None
        if self._include_profiles:
            profiles = await self._collect_profile_metrics(client, network_id)

        if self._include_premium:
            await self._collect_premium_metrics(client, network_id, network_name, network_details)

        # NOTE (commit 4, metrics reorganisation): `_collect_thread_metrics`
        # (eero_thread_device_count/eero_thread_border_router) and
        # `_collect_diagnostics_metrics` (all eero_diagnostics_*) are no
        # longer called -- `get_thread` has neither a device count nor a
        # border-router count, and `get_diagnostics` returns only a status
        # string (§11.11 of the v8 probe shape summary). `include_thread` is
        # kept for a later commit's Thread family; `include_diagnostics` has
        # been removed entirely since nothing in the API backs it.

        if self._include_port_forwards:
            await self._collect_port_forward_metrics(client, network_id, network_name)

        if self._include_reservations:
            await self._collect_reservation_metrics(client, network_id, network_name)

        if self._include_blacklist:
            await self._collect_blacklist_metrics(client, network_id, network_name)

        if self._include_insights:
            await self._collect_insights_metrics(client, network_id)

        if self._include_extended:
            await self._collect_extended_metrics(client, network_id)

        if self._include_rf:
            await self._collect_rf_metrics(client, network_id)

        if self._include_per_device:
            await self._collect_per_device_metrics(client, network_id)

        if self._include_per_eero:
            await self._collect_per_eero_metrics(client, network_id, eeros)

        if self._include_per_profile:
            profiles_for_tier = profiles
            if profiles_for_tier is None:
                profiles_for_tier, _exc = await self._api_get(
                    "profiles", client.get_profiles(network_id)
                )
                profiles_for_tier = profiles_for_tier or []
            await self._collect_per_profile_metrics(client, network_id, profiles_for_tier)

        if self._include_unverified:
            await self._collect_unverified_metrics(client, network_id, devices)

    async def _collect_eero_metrics(
        self,
        client: EeroClient,
        network_id: str,
        network_name: str,
        network_details: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Collect metrics for eero devices.

        Returns:
            The raw eero list (possibly empty), so callers (the `per_eero`
            tier) can reuse it without an extra GET.
        """
        if self._eeros_from_envelope:
            # The network envelope already embeds every eero inline
            # (`network.data.eeros.data`) -- skip the extra GET entirely.
            envelope_eeros = network_details.get("eeros", {})
            eeros = envelope_eeros.get("data", []) if isinstance(envelope_eeros, dict) else []
            if not isinstance(eeros, list):
                eeros = []
        else:
            eeros, exc = await self._api_get("eeros", client.get_eeros(network_id))
            if exc is not None:
                _LOGGER.warning(f"Failed to get eeros: {exc}")
                return []

        NETWORK_EEROS_COUNT.labels(network_id=network_id, name=network_name).set(len(eeros))

        # Count eeros with updates available. `isinstance` guard so a single
        # malformed (non-dict) item can't crash this count before the
        # per-item try/except loop below gets a chance to isolate it.
        updates_count = sum(
            1 for e in eeros if isinstance(e, dict) and e.get("update_available", False)
        )
        NETWORK_UPDATES_AVAILABLE.labels(network_id=network_id, name=network_name).set(
            updates_count
        )

        for idx, eero in enumerate(eeros):
            try:
                eero_url = eero.get("url", "")
                eero_id = _extract_id_from_url(eero_url)
                location = eero.get("location", "Unknown")
                model = eero.get("model", "Unknown")
                serial = eero.get("serial", "Unknown")
                status = eero.get("status", "").lower()

                if not eero_id:
                    continue

                os_version = eero.get("os_version") or eero.get("os") or "unknown"

                EERO_INFO.labels(network_id=network_id, eero_id=eero_id).info(
                    {
                        "location": location,
                        "model": model,
                        "model_number": eero.get("model_number") or "unknown",
                        "os_version": os_version,
                        "serial": serial,
                        "mac_address": eero.get("mac_address") or "unknown",
                        "ip_address": eero.get("ip_address") or "unknown",
                    }
                )

                # Separate OS version info for easier alerting
                EERO_OS_VERSION_INFO.labels(
                    network_id=network_id, eero_id=eero_id, location=location
                ).info(
                    {
                        "version": os_version,
                        "model": model,
                    }
                )

                # Check multiple possible status values indicating online state
                # API may return: "connected", "online", "green", "up", "active",
                # or boolean-like values
                online_statuses = ("connected", "online", "green", "up", "active", "ok", "healthy")
                is_online = 1 if status in online_statuses else 0
                # If status is empty/unknown but heartbeat is ok, consider it online
                if is_online == 0 and eero.get("heartbeat_ok", False):
                    is_online = 1
                _LOGGER.debug(f"Eero {eero_id} status='{status}' -> is_online={is_online}")
                EERO_STATUS.labels(
                    network_id=network_id, eero_id=eero_id, location=location, model=model
                ).set(is_online)

                is_gateway = 1 if eero.get("gateway", False) else 0
                EERO_IS_GATEWAY.labels(
                    network_id=network_id, eero_id=eero_id, location=location
                ).set(is_gateway)

                clients_count = _coerce_numeric(
                    eero.get("connected_clients_count", 0), field_name="connected_clients_count"
                )
                try:
                    EERO_CONNECTED_CLIENTS.labels(
                        network_id=network_id, eero_id=eero_id, location=location, model=model
                    ).set(clients_count or 0)
                except Exception:
                    _LOGGER.warning("Failed to set EERO_CONNECTED_CLIENTS for eero %s", eero_id)

                wired_clients = _coerce_numeric(
                    eero.get("connected_wired_clients_count"),
                    field_name="connected_wired_clients_count",
                )
                if wired_clients is not None:
                    try:
                        EERO_CONNECTED_WIRED_CLIENTS.labels(
                            network_id=network_id, eero_id=eero_id, location=location
                        ).set(wired_clients)
                    except Exception:
                        _LOGGER.warning(
                            "Failed to set EERO_CONNECTED_WIRED_CLIENTS for eero %s", eero_id
                        )

                wireless_clients = _coerce_numeric(
                    eero.get("connected_wireless_clients_count"),
                    field_name="connected_wireless_clients_count",
                )
                if wireless_clients is not None:
                    try:
                        EERO_CONNECTED_WIRELESS_CLIENTS.labels(
                            network_id=network_id, eero_id=eero_id, location=location
                        ).set(wireless_clients)
                    except Exception:
                        _LOGGER.warning(
                            "Failed to set EERO_CONNECTED_WIRELESS_CLIENTS for eero %s", eero_id
                        )

                mesh_quality = _coerce_numeric(
                    eero.get("mesh_quality_bars"), field_name="mesh_quality_bars"
                )
                if mesh_quality is not None:
                    try:
                        EERO_MESH_QUALITY.labels(
                            network_id=network_id,
                            eero_id=eero_id,
                            location=location,
                            model=model,
                        ).set(mesh_quality)
                    except Exception:
                        _LOGGER.warning("Failed to set EERO_MESH_QUALITY for eero %s", eero_id)

                uptime_obj = eero.get("uptime")
                uptime = _coerce_numeric(
                    uptime_obj.get("since_last_reboot_s") if isinstance(uptime_obj, dict) else None,
                    field_name="uptime.since_last_reboot_s",
                )
                if uptime is not None:
                    try:
                        EERO_UPTIME_SECONDS.labels(
                            network_id=network_id, eero_id=eero_id, location=location
                        ).set(uptime)
                    except Exception:
                        _LOGGER.warning("Failed to set EERO_UPTIME_SECONDS for eero %s", eero_id)

                led_on = eero.get("led_on")
                if led_on is not None:
                    EERO_LED_ON.labels(
                        network_id=network_id, eero_id=eero_id, location=location
                    ).set(1 if led_on else 0)

                update_available = eero.get("update_available")
                if update_available is not None:
                    EERO_UPDATE_AVAILABLE.labels(
                        network_id=network_id, eero_id=eero_id, location=location
                    ).set(1 if update_available else 0)

                heartbeat_ok = eero.get("heartbeat_ok")
                if heartbeat_ok is not None:
                    EERO_HEARTBEAT_OK.labels(
                        network_id=network_id, eero_id=eero_id, location=location
                    ).set(1 if heartbeat_ok else 0)

                wired = eero.get("wired")
                if wired is not None:
                    EERO_WIRED.labels(
                        network_id=network_id, eero_id=eero_id, location=location
                    ).set(1 if wired else 0)

                led_brightness = _coerce_numeric(
                    eero.get("led_brightness"), field_name="led_brightness"
                )
                if led_brightness is not None:
                    try:
                        EERO_LED_BRIGHTNESS.labels(
                            network_id=network_id, eero_id=eero_id, location=location
                        ).set(led_brightness)
                    except Exception:
                        _LOGGER.warning("Failed to set EERO_LED_BRIGHTNESS for eero %s", eero_id)

                last_reboot = eero.get("last_reboot")
                if last_reboot:
                    reboot_ts = _parse_timestamp(last_reboot)
                    if reboot_ts is not None:
                        try:
                            EERO_LAST_REBOOT.labels(
                                network_id=network_id, eero_id=eero_id, location=location
                            ).set(reboot_ts)
                        except Exception:
                            _LOGGER.warning("Failed to set EERO_LAST_REBOOT for eero %s", eero_id)

                provides_wifi = eero.get("provides_wifi")
                if provides_wifi is not None:
                    try:
                        EERO_PROVIDES_WIFI.labels(
                            network_id=network_id, eero_id=eero_id, location=location
                        ).set(1 if provides_wifi else 0)
                    except Exception:
                        _LOGGER.warning("Failed to set EERO_PROVIDES_WIFI for eero %s", eero_id)

                self._collect_eero_envelope_extras(network_id, eero_id, location, eero)
                self._collect_eero_radio_metrics(network_id, eero_id, location, eero)

                if self._include_ethernet:
                    await self._collect_ethernet_port_metrics(network_id, eero_id, location, eero)

                nightlight = eero.get("nightlight", {})
                if nightlight and isinstance(nightlight, dict):
                    nl_enabled = nightlight.get("enabled")
                    if nl_enabled is not None:
                        try:
                            EERO_NIGHTLIGHT_ENABLED.labels(
                                network_id=network_id, eero_id=eero_id, location=location
                            ).set(1 if nl_enabled else 0)
                        except Exception:
                            _LOGGER.warning(
                                "Failed to set EERO_NIGHTLIGHT_ENABLED for eero %s", eero_id
                            )

                    nl_brightness = _coerce_numeric(
                        nightlight.get("brightness") or nightlight.get("brightness_percentage"),
                        field_name="nightlight_brightness",
                    )
                    if nl_brightness is not None:
                        try:
                            EERO_NIGHTLIGHT_BRIGHTNESS.labels(
                                network_id=network_id, eero_id=eero_id, location=location
                            ).set(nl_brightness)
                        except Exception:
                            _LOGGER.warning(
                                "Failed to set EERO_NIGHTLIGHT_BRIGHTNESS for eero %s", eero_id
                            )

                    nl_schedule = nightlight.get("schedule", {})
                    if nl_schedule and isinstance(nl_schedule, dict):
                        schedule_enabled = nl_schedule.get("enabled")
                        if schedule_enabled is not None:
                            try:
                                EERO_NIGHTLIGHT_SCHEDULE_ENABLED.labels(
                                    network_id=network_id, eero_id=eero_id, location=location
                                ).set(1 if schedule_enabled else 0)
                            except Exception:
                                _LOGGER.warning(
                                    "Failed to set EERO_NIGHTLIGHT_SCHEDULE_ENABLED for eero %s",
                                    eero_id,
                                )
            except Exception as exc:
                _LOGGER.warning("Skipping eero item %d: %s: %s", idx, type(exc).__name__, exc)
                continue

        return eeros

    def _collect_eero_envelope_extras(
        self, network_id: str, eero_id: str, location: str, eero: dict[str, Any]
    ) -> None:
        """Collect commit-6 per-eero metrics (§8/§11.2 of the v8 probe).

        Every value here is read off the eero item already collected --
        zero extra requests.
        """
        common = {"network_id": network_id, "eero_id": eero_id, "location": location}

        is_primary = eero.get("is_primary_node")
        if is_primary is not None:
            EERO_IS_PRIMARY.labels(**common).set(1 if is_primary else 0)

        using_wan = eero.get("using_wan")
        if using_wan is not None:
            EERO_USING_WAN.labels(**common).set(1 if using_wan else 0)

        last_heartbeat_ts = _parse_timestamp(eero.get("last_heartbeat"))
        if last_heartbeat_ts is not None:
            EERO_LAST_HEARTBEAT.labels(**common).set(last_heartbeat_ts)

        joined_ts = _parse_timestamp(eero.get("joined"))
        if joined_ts is not None:
            EERO_JOINED.labels(**common).set(joined_ts)

        bands = eero.get("bands")
        if isinstance(bands, list):
            for band in bands:
                if band in _CHANNEL_UTILIZATION_BANDS:
                    EERO_BAND_SUPPORTED.labels(**common, band=band).set(1)

        bssids_with_bands = eero.get("bssids_with_bands")
        if isinstance(bssids_with_bands, list):
            EERO_RADIO_COUNT.labels(**common).set(len(bssids_with_bands))

        power_saving_active = _coerce_power_saving_enabled(eero.get("power_saving"))
        if power_saving_active is not None:
            EERO_POWER_SAVING_ACTIVE.labels(**common).set(1 if power_saving_active else 0)

        power_info = eero.get("power_info")
        power_source = power_info.get("power_source") if isinstance(power_info, dict) else None
        if power_source:
            EERO_POWER_SOURCE_INFO.labels(**common).info({"source": str(power_source)})

        connection_type = eero.get("connection_type")
        if connection_type:
            EERO_CONNECTION_TYPE_INFO.labels(**common).info(
                {"connection_type": str(connection_type).upper()}
            )

    def _collect_eero_radio_metrics(
        self, network_id: str, eero_id: str, location: str, eero: dict[str, Any]
    ) -> None:
        """Collect `radio_channel_stats` metrics for one eero (§8/§11.2 of the v8 probe).

        `radio_channel_stats` is a dict keyed by the exact
        `CHANNEL_UTILIZATION_BANDS` enum, five numeric fields per band --
        free on the already-fetched eero item.
        """
        stats = eero.get("radio_channel_stats")
        if not isinstance(stats, dict):
            return

        for band, band_stats in stats.items():
            if band not in _CHANNEL_UTILIZATION_BANDS or not isinstance(band_stats, dict):
                continue
            labels = {
                "network_id": network_id,
                "eero_id": eero_id,
                "location": location,
                "band": band,
            }

            channel = _coerce_numeric(band_stats.get("channel"), field_name="radio_channel")
            if channel is not None:
                EERO_RADIO_CHANNEL.labels(**labels).set(channel)

            channel_width = _coerce_numeric(
                band_stats.get("channel_width"), field_name="radio_channel_width"
            )
            if channel_width is not None:
                EERO_RADIO_CHANNEL_WIDTH.labels(**labels).set(channel_width)

            tx_power = _coerce_numeric(band_stats.get("tx_power"), field_name="radio_tx_power")
            if tx_power is not None:
                EERO_RADIO_TX_POWER.labels(**labels).set(tx_power)

            utilization = _coerce_numeric(
                band_stats.get("channel_utilization"), field_name="radio_channel_utilization"
            )
            if utilization is not None:
                EERO_RADIO_CHANNEL_UTILIZATION.labels(**labels).set(utilization)

            client_count = _coerce_numeric(
                band_stats.get("client_count"), field_name="radio_client_count"
            )
            if client_count is not None:
                EERO_RADIO_CLIENT_COUNT.labels(**labels).set(client_count)

    async def _collect_device_metrics(
        self, client: EeroClient, network_id: str, network_name: str
    ) -> list[dict[str, Any]] | None:
        """Collect metrics for client devices.

        Returns:
            The raw device list, so callers (the unverified tier's
            transfer-stub) can reuse it without an extra GET, or ``None`` if
            the read failed.
        """
        devices, exc = await self._api_get("devices", client.get_devices(network_id))
        if exc is not None:
            _LOGGER.warning(f"Failed to get devices: {exc}")
            return None

        # `isinstance` guards so a single malformed (non-dict) item can't
        # crash these counts before the per-item try/except loop below gets
        # a chance to isolate it.
        connected_count = sum(
            1 for d in devices if isinstance(d, dict) and d.get("connected", False)
        )
        NETWORK_CLIENTS_COUNT.labels(network_id=network_id, name=network_name).set(connected_count)

        # Count guest network clients
        guest_count = sum(
            1
            for d in devices
            if isinstance(d, dict) and d.get("connected", False) and d.get("is_guest", False)
        )
        GUEST_NETWORK_CONNECTED_CLIENTS.labels(network_id=network_id, name=network_name).set(
            guest_count
        )

        for idx, device in enumerate(devices):
            try:
                device_url = device.get("url", "")
                device_id = _extract_id_from_url(device_url)
                mac = device.get("mac", "") or device.get("eui64", "")
                name = (
                    device.get("display_name")
                    or device.get("hostname")
                    or device.get("nickname")
                    or mac
                )

                if not device_id:
                    continue

                # Extract enriched labels
                manufacturer = _normalize_manufacturer(device.get("manufacturer"))
                device_type = _normalize_device_type(device.get("device_type"))
                connection_type = _get_connection_type(device)
                source_eero = _get_source_eero_location(device)

                # Get frequency for band label
                connectivity = device.get("connectivity", {})
                frequency = connectivity.get("frequency") if connectivity else None
                band = _frequency_to_band(frequency)

                # `profile.name` is bounded by the profile count (v8 migration
                # plan §5.4) -- empty string when the device has no profile.
                profile = device.get("profile")
                profile_name = str(profile.get("name") or "") if isinstance(profile, dict) else ""

                DEVICE_INFO.labels(network_id=network_id, device_id=device_id, mac=mac).info(
                    {
                        "name": name,
                        "manufacturer": manufacturer,
                        "ip": device.get("ip") or "unknown",
                        "device_type": device_type,
                        "hostname": device.get("hostname") or "unknown",
                        "connection_type": connection_type,
                        "source_eero": source_eero,
                        "profile": profile_name,
                    }
                )

                subnet_kind = device.get("subnet_kind")
                if subnet_kind:
                    DEVICE_SUBNET_KIND_INFO.labels(network_id=network_id, device_id=device_id).info(
                        {"subnet_kind": str(subnet_kind)}
                    )

                connected = device.get("connected", False)
                try:
                    DEVICE_CONNECTED.labels(
                        network_id=network_id,
                        device_id=device_id,
                        name=name,
                        mac=mac,
                        manufacturer=manufacturer,
                        device_type=device_type,
                        connection_type=connection_type,
                        source_eero=source_eero,
                    ).set(1 if connected else 0)
                except Exception:
                    _LOGGER.warning("Failed to set DEVICE_CONNECTED for device %s", device_id)

                wireless = device.get("wireless", False)
                try:
                    DEVICE_WIRELESS.labels(
                        network_id=network_id,
                        device_id=device_id,
                        name=name,
                        manufacturer=manufacturer,
                        device_type=device_type,
                    ).set(1 if wireless else 0)
                except Exception:
                    _LOGGER.warning("Failed to set DEVICE_WIRELESS for device %s", device_id)

                blocked = device.get("blacklisted", False)
                try:
                    DEVICE_BLOCKED.labels(
                        network_id=network_id,
                        device_id=device_id,
                        name=name,
                        mac=mac,
                        manufacturer=manufacturer,
                    ).set(1 if blocked else 0)
                except Exception:
                    _LOGGER.warning("Failed to set DEVICE_BLOCKED for device %s", device_id)

                paused = device.get("paused", False)
                try:
                    DEVICE_PAUSED.labels(
                        network_id=network_id,
                        device_id=device_id,
                        name=name,
                        manufacturer=manufacturer,
                        device_type=device_type,
                    ).set(1 if paused else 0)
                except Exception:
                    _LOGGER.warning("Failed to set DEVICE_PAUSED for device %s", device_id)

                is_guest = device.get("is_guest", False)
                try:
                    DEVICE_IS_GUEST.labels(
                        network_id=network_id,
                        device_id=device_id,
                        name=name,
                        manufacturer=manufacturer,
                    ).set(1 if is_guest else 0)
                except Exception:
                    _LOGGER.warning("Failed to set DEVICE_IS_GUEST for device %s", device_id)

                if connectivity:
                    signal = _parse_signal_strength(connectivity.get("signal"))
                    if signal is not None:
                        try:
                            DEVICE_SIGNAL_STRENGTH.labels(
                                network_id=network_id,
                                device_id=device_id,
                                name=name,
                                manufacturer=manufacturer,
                                band=band,
                                source_eero=source_eero,
                            ).set(signal)
                        except Exception:
                            _LOGGER.warning(
                                "Failed to set DEVICE_SIGNAL_STRENGTH for device %s", device_id
                            )

                    score = _coerce_numeric(connectivity.get("score"), field_name="score")
                    if score is not None:
                        try:
                            DEVICE_CONNECTION_SCORE.labels(
                                network_id=network_id,
                                device_id=device_id,
                                name=name,
                                manufacturer=manufacturer,
                                connection_type=connection_type,
                                source_eero=source_eero,
                            ).set(score)
                        except Exception:
                            _LOGGER.warning(
                                "Failed to set DEVICE_CONNECTION_SCORE for device %s", device_id
                            )

                    score_bars = _coerce_numeric(
                        connectivity.get("score_bars"), field_name="score_bars"
                    )
                    if score_bars is not None:
                        try:
                            DEVICE_CONNECTION_SCORE_BARS.labels(
                                network_id=network_id,
                                device_id=device_id,
                                name=name,
                                manufacturer=manufacturer,
                                connection_type=connection_type,
                                source_eero=source_eero,
                            ).set(score_bars)
                        except Exception:
                            _LOGGER.warning(
                                "Failed to set DEVICE_CONNECTION_SCORE_BARS for device %s",
                                device_id,
                            )

                    if frequency is not None:
                        try:
                            DEVICE_FREQUENCY.labels(
                                network_id=network_id,
                                device_id=device_id,
                                name=name,
                                manufacturer=manufacturer,
                                band=band,
                                source_eero=source_eero,
                            ).set(frequency)
                        except Exception:
                            _LOGGER.warning(
                                "Failed to set DEVICE_FREQUENCY for device %s", device_id
                            )

                    rx_rate_info = connectivity.get("rx_rate_info", {})
                    rx_rate_info = rx_rate_info if isinstance(rx_rate_info, dict) else {}
                    tx_rate_info = connectivity.get("tx_rate_info", {})
                    tx_rate_info = tx_rate_info if isinstance(tx_rate_info, dict) else {}

                    # Primary source: rate_bps (verified for both rx and tx).
                    # Fallback for rx only: the legacy `rx_bitrate` string --
                    # there is no `tx_bitrate` string key anywhere in the API.
                    rx_bitrate = _rate_bps_to_mbps(rx_rate_info)
                    if rx_bitrate is None:
                        rx_bitrate = _parse_bitrate(connectivity.get("rx_bitrate"))
                    if rx_bitrate is not None:
                        try:
                            DEVICE_RX_BITRATE.labels(
                                network_id=network_id,
                                device_id=device_id,
                                name=name,
                                manufacturer=manufacturer,
                                band=band,
                                source_eero=source_eero,
                            ).set(rx_bitrate)
                        except Exception:
                            _LOGGER.warning(
                                "Failed to set DEVICE_RX_BITRATE for device %s", device_id
                            )

                    tx_bitrate = _rate_bps_to_mbps(tx_rate_info)
                    if tx_bitrate is not None:
                        try:
                            DEVICE_TX_BITRATE.labels(
                                network_id=network_id,
                                device_id=device_id,
                                name=name,
                                manufacturer=manufacturer,
                                band=band,
                                source_eero=source_eero,
                            ).set(tx_bitrate)
                        except Exception:
                            _LOGGER.warning(
                                "Failed to set DEVICE_TX_BITRATE for device %s", device_id
                            )

                    if rx_rate_info:
                        rx_mcs = rx_rate_info.get("mcs")
                        if rx_mcs is not None:
                            DEVICE_RX_MCS.labels(
                                network_id=network_id,
                                device_id=device_id,
                                name=name,
                                band=band,
                            ).set(rx_mcs)

                        rx_nss = rx_rate_info.get("nss")
                        if rx_nss is not None:
                            DEVICE_RX_NSS.labels(
                                network_id=network_id,
                                device_id=device_id,
                                name=name,
                                band=band,
                            ).set(rx_nss)

                    if tx_rate_info:
                        tx_mcs = tx_rate_info.get("mcs")
                        if tx_mcs is not None:
                            DEVICE_TX_MCS.labels(
                                network_id=network_id,
                                device_id=device_id,
                                name=name,
                                band=band,
                            ).set(tx_mcs)

                        tx_nss = tx_rate_info.get("nss")
                        if tx_nss is not None:
                            DEVICE_TX_NSS.labels(
                                network_id=network_id,
                                device_id=device_id,
                                name=name,
                                band=band,
                            ).set(tx_nss)

                    self._set_device_packet_stats(network_id, device_id, connectivity)

                # `devices[].channel` is the verified top-level source; the
                # summary explicitly refutes `connectivity.channel` (§7), but
                # a fallback is kept since checking it is free.
                channel = device.get("channel")
                if channel is None and connectivity:
                    channel = connectivity.get("channel")
                if channel is not None:
                    DEVICE_CHANNEL.labels(
                        network_id=network_id,
                        device_id=device_id,
                        name=name,
                        band=band,
                        source_eero=source_eero,
                    ).set(channel)

                is_private = device.get("is_private")
                if is_private is not None:
                    DEVICE_PRIVATE.labels(
                        network_id=network_id,
                        device_id=device_id,
                        name=name,
                        manufacturer=manufacturer,
                    ).set(1 if is_private else 0)

                source = device.get("source", {})
                if source and isinstance(source, dict):
                    source_is_gateway = source.get("is_gateway")
                    if source_is_gateway is not None:
                        DEVICE_CONNECTED_TO_GATEWAY.labels(
                            network_id=network_id,
                            device_id=device_id,
                            name=name,
                            connection_type=connection_type,
                        ).set(1 if source_is_gateway else 0)

                # Extended device metrics
                last_active = device.get("last_active")
                if last_active:
                    last_active_ts = _parse_timestamp(last_active)
                    if last_active_ts is not None:
                        DEVICE_LAST_ACTIVE_TIMESTAMP.labels(
                            network_id=network_id,
                            device_id=device_id,
                            name=name,
                            manufacturer=manufacturer,
                        ).set(last_active_ts)

                first_seen = device.get("first_active") or device.get("first_seen")
                if first_seen:
                    first_seen_ts = _parse_timestamp(first_seen)
                    if first_seen_ts is not None:
                        DEVICE_FIRST_SEEN_TIMESTAMP.labels(
                            network_id=network_id,
                            device_id=device_id,
                            name=name,
                            manufacturer=manufacturer,
                        ).set(first_seen_ts)

                # WiFi generation
                wifi_gen = _get_wifi_generation(device)
                if wifi_gen is not None:
                    DEVICE_WIFI_GENERATION.labels(
                        network_id=network_id,
                        device_id=device_id,
                        name=name,
                        manufacturer=manufacturer,
                    ).set(wifi_gen)
            except Exception as exc:
                _LOGGER.warning("Skipping device item %d: %s: %s", idx, type(exc).__name__, exc)
                continue

        return cast(list[dict[str, Any]], devices)

    def _set_device_packet_stats(
        self, network_id: str, device_id: str, connectivity: dict[str, Any]
    ) -> None:
        """Set the eight `connectivity.packet_stats` gauges for one device.

        The API reports lifetime totals with no reset semantics, so these
        are exported as Gauges, not Counters (§8/§11.3 of the v8 probe).
        Every field is independently nullable.
        """
        packet_stats = connectivity.get("packet_stats")
        if not isinstance(packet_stats, dict):
            return

        labels = {"network_id": network_id, "device_id": device_id}
        field_metrics = (
            ("rx_packets", DEVICE_PACKET_STATS_RX_PACKETS),
            ("tx_packets", DEVICE_PACKET_STATS_TX_PACKETS),
            ("total_packets", DEVICE_PACKET_STATS_TOTAL_PACKETS),
            ("rx_drops", DEVICE_PACKET_STATS_RX_DROPS),
            ("tx_retries", DEVICE_PACKET_STATS_TX_RETRIES),
            ("tx_retransmit_ppm", DEVICE_PACKET_STATS_TX_RETRANSMIT_PPM),
            ("tx_fail_ppm", DEVICE_PACKET_STATS_TX_FAIL_PPM),
            ("rx_drop_ppm", DEVICE_PACKET_STATS_RX_DROP_PPM),
        )
        for field_name, metric in field_metrics:
            value = _coerce_numeric(packet_stats.get(field_name), field_name=field_name)
            if value is not None:
                metric.labels(**labels).set(value)

    async def _collect_profile_metrics(
        self, client: EeroClient, network_id: str
    ) -> list[dict[str, Any]] | None:
        """Collect metrics for profiles.

        Returns:
            The raw profile list, so callers (the `per_profile` tier) can
            reuse it without an extra GET, or ``None`` if the read failed.
        """
        profiles, exc = await self._api_get("profiles", client.get_profiles(network_id))
        if exc is not None:
            _LOGGER.warning(f"Failed to get profiles: {exc}")
            return None

        for idx, profile in enumerate(profiles):
            try:
                if not isinstance(profile, dict):
                    _LOGGER.warning(f"Unexpected profile format: {type(profile)}")
                    continue

                profile_url = profile.get("url", "")
                profile_id = _extract_id_from_url(profile_url)
                name = profile.get("name", "Unknown")

                if not profile_id:
                    continue

                paused = profile.get("paused", False)
                PROFILE_PAUSED.labels(network_id=network_id, profile_id=profile_id, name=name).set(
                    1 if paused else 0
                )

                devices_data = profile.get("devices", [])
                if isinstance(devices_data, dict):
                    devices = devices_data.get("data", [])
                elif isinstance(devices_data, list):
                    devices = devices_data
                else:
                    devices = []
                PROFILE_DEVICES_COUNT.labels(
                    network_id=network_id, profile_id=profile_id, name=name
                ).set(len(devices))

                connected_devices = sum(
                    1 for d in devices if isinstance(d, dict) and d.get("connected")
                )
                PROFILE_CONNECTED_DEVICES_COUNT.labels(
                    network_id=network_id, profile_id=profile_id, name=name
                ).set(connected_devices)

                # `schedule`/`premium_dns.blocked_applications` are free on
                # this same profile item -- never call the per-profile
                # `get_schedules`/`get_dns_policy_applications` endpoints
                # (§8/§11.4 of the v8 probe shape summary).
                schedule = profile.get("schedule")
                if isinstance(schedule, list):
                    PROFILE_SCHEDULES_COUNT.labels(
                        network_id=network_id, profile_id=profile_id, name=name
                    ).set(len(schedule))

                premium_dns = profile.get("premium_dns")
                blocked_applications = (
                    premium_dns.get("blocked_applications")
                    if isinstance(premium_dns, dict)
                    else None
                )
                if isinstance(blocked_applications, list):
                    PROFILE_BLOCKED_APPLICATIONS_COUNT.labels(
                        network_id=network_id, profile_id=profile_id, name=name
                    ).set(len(blocked_applications))

                unified_content_filters = profile.get("unified_content_filters")
                content_filters_set = (
                    unified_content_filters.get("is_content_filters_set")
                    if isinstance(unified_content_filters, dict)
                    else None
                )
                if content_filters_set is not None:
                    PROFILE_CONTENT_FILTERS_SET.labels(
                        network_id=network_id, profile_id=profile_id, name=name
                    ).set(1 if content_filters_set else 0)
            except Exception as exc:
                _LOGGER.warning("Skipping profile item %d: %s: %s", idx, type(exc).__name__, exc)
                continue

        return cast(list[dict[str, Any]], profiles)

    async def _collect_data_usage_metrics(
        self,
        client: EeroClient,
        network_id: str,
        network_details: dict[str, Any],
    ) -> None:
        """Collect network, device, and eero-node data usage metrics.

        Issues one ``get_data_usage`` request per configured period
        (``config.data_usage_periods``) for the network total, plus exactly
        one ``get_data_usage_breakdown`` call per cycle for the per-eero and
        per-device breakdowns (§11.5 of the v8 probe shape summary --
        ``get_devices_data_usage``/``get_eeros_data_usage_summary`` have no
        per-eero dimension and are superseded). Each request is
        independently guarded so a partial failure (e.g. an account without
        data_usage support) degrades gracefully.
        """
        timezone = _get_timezone(network_details.get("timezone"))
        for period in self._data_usage_periods:
            period_label, cadence, payload = _data_usage_period_payload(period, timezone)

            usage, exc = await self._api_get(
                f"data_usage_{period_label}", client.get_data_usage(network_id, **payload)
            )
            if exc is not None:
                _LOGGER.debug(f"Failed to get {period_label} data usage: {exc}")
                continue
            self._set_network_data_usage(network_id, period_label, cadence, usage)

        if not self._include_devices:
            return

        now = datetime.now(UTC)
        breakdown_payload = {
            "start": _format_utc_z(now - timedelta(hours=1)),
            "end": _format_utc_z(now),
            "cadence": "hourly",
            "timezone": "UTC",
        }
        breakdown, exc = await self._api_get(
            "data_usage_breakdown",
            client.get_data_usage_breakdown(network_id, **breakdown_payload),
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get data usage breakdown: {exc}")
            return

        eero_items = breakdown.get("eeros", [])
        self._set_eero_data_usage(
            network_id, "current", "hourly", eero_items if isinstance(eero_items, list) else []
        )
        device_items = breakdown.get("devices", [])
        device_items = device_items if isinstance(device_items, list) else []
        self._set_device_data_usage(network_id, "current", "hourly", device_items)
        self._set_device_trailing_usage(network_id, device_items)
        profile_items = breakdown.get("profiles", [])
        self._set_profile_data_usage(
            network_id,
            "current",
            "hourly",
            profile_items if isinstance(profile_items, list) else [],
        )
        unprofiled_items = breakdown.get("unprofiled", [])
        self._set_unprofiled_data_usage(
            network_id,
            "current",
            "hourly",
            unprofiled_items if isinstance(unprofiled_items, list) else [],
        )

    def _set_network_data_usage(
        self,
        network_id: str,
        period: str,
        cadence: str,
        usage: dict[str, Any],
    ) -> None:
        """Set network-level data usage metrics from a data_usage response."""
        series_list = usage.get("series", [])
        if not isinstance(series_list, list):
            return

        for series in series_list:
            if not isinstance(series, dict):
                continue
            direction = str(series.get("type") or series.get("direction") or "").lower()
            if direction not in ("download", "upload"):
                continue
            total = _series_sum(series)
            if total is None:
                continue
            NETWORK_DATA_USAGE_BYTES.labels(
                network_id=network_id,
                period=period,
                cadence=cadence,
                direction=direction,
            ).set(total)

    def _set_device_data_usage(
        self,
        network_id: str,
        period: str,
        cadence: str,
        items: list[Any],
    ) -> None:
        """Set per-device data usage metrics from a list of usage items.

        Args:
            items: Device usage items, each a dict with ``id``/``url`` and
                ``upload``/``download`` keys -- either the
                ``get_data_usage_breakdown`` ``data.devices[]`` shape or the
                legacy ``get_devices_data_usage`` ``data.values[]`` shape.
        """
        for idx, device in enumerate(items):
            try:
                if not isinstance(device, dict):
                    continue
                device_id = str(device.get("id") or _extract_id_from_url(device.get("url", "")))
                if not device_id:
                    continue
                name = (
                    device.get("nickname")
                    or device.get("display_name")
                    or device.get("hostname")
                    or device.get("name")
                    or device_id
                )
                self._set_usage_direction_metrics(
                    DEVICE_DATA_USAGE_BYTES,
                    {
                        "network_id": network_id,
                        "device_id": device_id,
                        "name": str(name),
                        "period": period,
                        "cadence": cadence,
                    },
                    device,
                )
            except Exception as exc:
                _LOGGER.warning(
                    "Skipping device data usage item %d: %s: %s", idx, type(exc).__name__, exc
                )
                continue

    def _set_profile_data_usage(
        self,
        network_id: str,
        period: str,
        cadence: str,
        items: list[Any],
    ) -> None:
        """Set per-profile data usage from the breakdown's ``data.profiles[]`` (§11.5).

        Free: the breakdown call is already made for the per-eero and
        per-device figures. The profile name is never exported -- only the id.
        """
        for idx, profile in enumerate(items):
            try:
                if not isinstance(profile, dict):
                    continue
                profile_id = str(
                    profile.get("profile_id")
                    or profile.get("id")
                    or _extract_profile_id_from_url(profile.get("url"))
                )
                if not profile_id:
                    continue
                self._set_usage_direction_metrics(
                    PROFILE_DATA_USAGE_BYTES,
                    {
                        "network_id": network_id,
                        "profile_id": profile_id,
                        "period": period,
                        "cadence": cadence,
                    },
                    profile,
                )
            except Exception as exc:
                _LOGGER.warning(
                    "Skipping profile data usage item %d: %s: %s", idx, type(exc).__name__, exc
                )
                continue

    def _set_unprofiled_data_usage(
        self,
        network_id: str,
        period: str,
        cadence: str,
        items: list[Any],
    ) -> None:
        """Set the summed data usage of devices belonging to no profile (§11.5).

        The breakdown returns one entry per unprofiled device; only the
        network-wide total is exported, so no per-device identity is exposed.
        """
        totals: dict[str, float] = {"upload": 0.0, "download": 0.0}
        seen = False
        for idx, item in enumerate(items):
            try:
                if not isinstance(item, dict):
                    continue
                for direction in totals:
                    value = item.get(direction)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        totals[direction] += float(value)
                        seen = True
            except Exception as exc:
                _LOGGER.warning(
                    "Skipping unprofiled data usage item %d: %s: %s", idx, type(exc).__name__, exc
                )
                continue
        if not seen:
            return
        for direction, total in totals.items():
            UNPROFILED_DATA_USAGE_BYTES.labels(
                network_id=network_id,
                period=period,
                cadence=cadence,
                direction=direction,
            ).set(total)

    def _set_eero_data_usage(
        self,
        network_id: str,
        period: str,
        cadence: str,
        items: list[Any],
    ) -> None:
        """Set per-eero-node data usage metrics from a list of usage items.

        Args:
            items: Eero usage items, each a dict with ``id``/``url`` and
                ``upload``/``download`` keys -- either the
                ``get_data_usage_breakdown`` ``data.eeros[]`` shape or the
                legacy ``get_eeros_data_usage_summary`` ``data.values[]`` shape.
        """
        for idx, eero in enumerate(items):
            try:
                if not isinstance(eero, dict):
                    continue
                eero_id = str(eero.get("id") or _extract_id_from_url(eero.get("url", "")))
                if not eero_id:
                    continue
                location = str(eero.get("location") or eero.get("name") or eero_id)
                self._set_usage_direction_metrics(
                    EERO_DATA_USAGE_BYTES,
                    {
                        "network_id": network_id,
                        "eero_id": eero_id,
                        "location": location,
                        "period": period,
                        "cadence": cadence,
                    },
                    eero,
                )
            except Exception as exc:
                _LOGGER.warning(
                    "Skipping eero data usage item %d: %s: %s", idx, type(exc).__name__, exc
                )
                continue

    def _set_usage_direction_metrics(
        self,
        metric: Any,
        labels: dict[str, str],
        usage: dict[str, Any],
    ) -> None:
        """Set download/upload values for a per-resource usage payload."""
        for direction in ("download", "upload"):
            value = usage.get(direction)
            if value is None:
                continue
            try:
                metric.labels(**labels, direction=direction).set(float(value))
            except (TypeError, ValueError):
                continue

    async def _collect_network_feature_flags(
        self,
        client: EeroClient,
        network_id: str,
        network_name: str,
        network_details: dict[str, Any],
    ) -> None:
        """Collect network feature flag metrics."""
        wpa3 = network_details.get("wpa3")
        if wpa3 is not None:
            NETWORK_WPA3_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if wpa3 else 0
            )

        band_steering = network_details.get("band_steering")
        if band_steering is not None:
            NETWORK_BAND_STEERING_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if band_steering else 0
            )

        sqm = network_details.get("sqm")
        if sqm is not None:
            NETWORK_SQM_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if sqm else 0
            )

        upnp = network_details.get("upnp")
        if upnp is not None:
            NETWORK_UPNP_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if upnp else 0
            )

        thread = network_details.get("thread")
        if thread is not None:
            NETWORK_THREAD_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if thread else 0
            )

        ipv6_upstream = network_details.get("ipv6_upstream")
        if ipv6_upstream is not None:
            NETWORK_IPV6_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if ipv6_upstream else 0
            )

        dns_obj = network_details.get("dns", {})
        dns_caching = dns_obj.get("caching") if isinstance(dns_obj, dict) else None
        if dns_caching is not None:
            NETWORK_DNS_CACHING_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if dns_caching else 0
            )

        power_saving_enabled = _coerce_power_saving_enabled(network_details.get("power_saving"))
        if power_saving_enabled is not None:
            NETWORK_POWER_SAVING_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if power_saving_enabled else 0
            )

        # Try multiple field names for guest network enabled
        guest_enabled = network_details.get("guest_network_enabled")
        if guest_enabled is None:
            # Check nested guest_network object
            guest_net = network_details.get("guest_network", {})
            if isinstance(guest_net, dict):
                guest_enabled = guest_net.get("enabled")
        if guest_enabled is not None:
            NETWORK_GUEST_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if guest_enabled else 0
            )
        else:
            # Default to 0 if not found to avoid "No data" in dashboard
            NETWORK_GUEST_ENABLED.labels(network_id=network_id, name=network_name).set(0)

        backup_enabled = network_details.get("backup_internet_enabled")
        if backup_enabled is not None:
            NETWORK_BACKUP_INTERNET_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if backup_enabled else 0
            )

        # Guest network metrics
        guest_network = network_details.get("guest_network", {})
        if guest_network and isinstance(guest_network, dict):
            guest_name = guest_network.get("name", "")
            GUEST_NETWORK_INFO.labels(network_id=network_id).info(
                {
                    "name": guest_name or "Guest Network",
                    "enabled": str(network_details.get("guest_network_enabled", False)).lower(),
                }
            )
            # `access_duration_enabled` was removed in 4.0.0 -- the guest
            # network object has no duration key of any kind (§11.11).

        # DNS configuration metrics -- `network.data.dns.{mode,caching,custom.ips}`
        # (§11.1 of the v8 probe shape summary). `dns.custom.ips` is never
        # read for its values, only its length -- the actual server
        # addresses are never exported as label/info values.
        dns_mode = dns_obj.get("mode") if isinstance(dns_obj, dict) else None
        custom_dns_ips = dns_obj.get("custom", {}).get("ips") if isinstance(dns_obj, dict) else None
        is_custom_dns = dns_mode == "custom"

        NETWORK_CUSTOM_DNS_ENABLED.labels(network_id=network_id, name=network_name).set(
            1 if is_custom_dns else 0
        )
        NETWORK_DNS_SERVER_COUNT.labels(network_id=network_id, name=network_name).set(
            len(custom_dns_ips) if isinstance(custom_dns_ips, list) else 0
        )
        # Non-identifying only: mode. Never the resolver IPs themselves.
        DNS_CONFIG_INFO.labels(network_id=network_id).info(
            {
                "mode": dns_mode or "unknown",
            }
        )

        # Ad blocking / malware blocking (network-wide, premium DNS policies).
        premium_dns = network_details.get("premium_dns", {})
        dns_policies = premium_dns.get("dns_policies", {}) if isinstance(premium_dns, dict) else {}
        ad_block = dns_policies.get("ad_block") if isinstance(dns_policies, dict) else None
        if ad_block is not None:
            NETWORK_AD_BLOCK_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if ad_block else 0
            )

        # `eero_network_auto_update_enabled` was removed in 4.0.0 -- neither
        # `auto_update` nor `auto_update_enabled` exists on the envelope
        # (§11.11); `updates.*` carries per-update state, not an auto-update
        # toggle.

    # NOTE (commit 3, single-envelope reads): SQM's on/off flag
    # (`NETWORK_SQM_ENABLED`) is fed from the network envelope in
    # `_collect_network_feature_flags` -- the dedicated `get_sqm_settings`
    # GET is no longer issued. The envelope carries no upload/download
    # bandwidth limits (§11.1 of the v8 probe shape summary), so
    # `SQM_UPLOAD_BANDWIDTH`/`SQM_DOWNLOAD_BANDWIDTH` are left unset until a
    # later commit finds a source for them (or removes them).

    def _collect_network_envelope_extras(
        self,
        network_id: str,
        network_name: str,
        network_details: dict[str, Any],
    ) -> None:
        """Collect commit-6 network-envelope metrics (§8/§11.1 of the v8 probe).

        Every value here is read off the already-fetched network envelope --
        zero extra requests. Synchronous (no API calls), unlike its sibling
        sub-collectors.
        """
        common = {"network_id": network_id, "name": network_name}

        health = network_details.get("health", {})
        internet_health = health.get("internet", {}) if isinstance(health, dict) else {}
        isp_up = internet_health.get("isp_up") if isinstance(internet_health, dict) else None
        if isp_up is not None:
            NETWORK_ISP_UP.labels(**common).set(1 if isp_up else 0)

        ip_settings = network_details.get("ip_settings")
        double_nat = ip_settings.get("double_nat") if isinstance(ip_settings, dict) else None
        if double_nat is not None:
            NETWORK_DOUBLE_NAT_DETECTED.labels(**common).set(1 if double_nat else 0)

        last_reboot_ts = _parse_timestamp(network_details.get("last_reboot"))
        if last_reboot_ts is not None:
            NETWORK_LAST_REBOOT.labels(**common).set(last_reboot_ts)

        connection = network_details.get("connection")
        connection_mode = connection.get("mode") if isinstance(connection, dict) else None
        if connection_mode:
            NETWORK_CONNECTION_MODE_INFO.labels(network_id=network_id).info(
                {"mode": str(connection_mode).upper()}
            )

        wan_type = network_details.get("wan_type")
        if wan_type:
            NETWORK_WAN_TYPE_INFO.labels(network_id=network_id).info({"type": str(wan_type)})

        mlo_mode = network_details.get("mlo_mode")
        if mlo_mode:
            NETWORK_MLO_MODE_INFO.labels(network_id=network_id).info({"mode": str(mlo_mode)})

        wireless_mode = network_details.get("wireless_mode")
        if wireless_mode:
            NETWORK_WIRELESS_MODE_INFO.labels(network_id=network_id).info(
                {"mode": str(wireless_mode)}
            )

        ddns = network_details.get("ddns")
        ddns_enabled = ddns.get("enabled") if isinstance(ddns, dict) else None
        if ddns_enabled is not None:
            NETWORK_DDNS_ENABLED.labels(**common).set(1 if ddns_enabled else 0)

        premium_dns = network_details.get("premium_dns")
        dns_policies = premium_dns.get("dns_policies") if isinstance(premium_dns, dict) else None
        malware_block = (
            dns_policies.get("block_malware") if isinstance(dns_policies, dict) else None
        )
        if malware_block is not None:
            NETWORK_MALWARE_BLOCK_ENABLED.labels(**common).set(1 if malware_block else 0)

        updates = network_details.get("updates")
        if isinstance(updates, dict):
            has_update = updates.get("has_update")
            if has_update is not None:
                NETWORK_UPDATE_AVAILABLE.labels(**common).set(1 if has_update else 0)
            target_firmware = updates.get("target_firmware")
            if target_firmware:
                NETWORK_UPDATE_TARGET_INFO.labels(network_id=network_id).info(
                    {"version": str(target_firmware)}
                )

        dns_obj = network_details.get("dns")
        dns_mode = dns_obj.get("mode") if isinstance(dns_obj, dict) else None
        if dns_mode:
            NETWORK_DNS_MODE_INFO.labels(network_id=network_id, family="ipv4").info(
                {"mode": str(dns_mode)}
            )
        # ipv6 DNS mode has no confirmed source on the envelope (§8/§10 --
        # no `ipv6.name_servers.mode` was ever observed); only emitted if a
        # future API response actually carries it.
        ipv6_obj = network_details.get("ipv6")
        ipv6_name_servers = ipv6_obj.get("name_servers") if isinstance(ipv6_obj, dict) else None
        ipv6_dns_mode = (
            ipv6_name_servers.get("mode") if isinstance(ipv6_name_servers, dict) else None
        )
        if ipv6_dns_mode:
            NETWORK_DNS_MODE_INFO.labels(network_id=network_id, family="ipv6").info(
                {"mode": str(ipv6_dns_mode)}
            )

        dns_parent = dns_obj.get("parent") if isinstance(dns_obj, dict) else None
        parent_ips = dns_parent.get("ips") if isinstance(dns_parent, dict) else None
        if isinstance(parent_ips, list):
            NETWORK_DNS_PARENT_SERVER_COUNT.labels(**common).set(len(parent_ips))

        dhcp_obj = network_details.get("dhcp")
        dhcp_mode = dhcp_obj.get("mode") if isinstance(dhcp_obj, dict) else None
        if dhcp_mode:
            NETWORK_DHCP_MODE_INFO.labels(network_id=network_id).info({"mode": str(dhcp_mode)})

        timezone_obj = network_details.get("timezone")
        timezone_value = (
            timezone_obj.get("value") if isinstance(timezone_obj, dict) else timezone_obj
        )
        if timezone_value:
            NETWORK_TIMEZONE_INFO.labels(network_id=network_id).info(
                {"timezone": str(timezone_value)}
            )

        premium_details = network_details.get("premium_details")
        next_renewal = (
            premium_details.get("next_billing_event_date")
            if isinstance(premium_details, dict)
            else None
        )
        next_renewal_ts = _parse_timestamp(next_renewal)
        if next_renewal_ts is not None:
            ACCOUNT_PREMIUM_NEXT_RENEWAL.labels(network_id=network_id).set(next_renewal_ts)

    def _collect_network_capabilities(
        self, network_id: str, network_details: dict[str, Any]
    ) -> None:
        """Collect the network envelope's ~119 `capabilities.<name>.capable` booleans.

        A handful of entries lack a `capable` key entirely (non-standard
        shapes, §8) -- those are skipped rather than guessed at.
        """
        capabilities = network_details.get("capabilities")
        if not isinstance(capabilities, dict):
            return
        for name, spec in capabilities.items():
            if not isinstance(spec, dict) or "capable" not in spec:
                continue
            capable = spec.get("capable")
            if not isinstance(capable, bool):
                continue
            NETWORK_CAPABILITY.labels(
                network_id=network_id, capability=_sanitize_label_value(str(name))
            ).set(1 if capable else 0)

    async def _collect_ethernet_port_metrics(
        self, network_id: str, eero_id: str, location: str, eero: dict[str, Any]
    ) -> None:
        """Collect ethernet port metrics for an eero device."""
        ethernet_status = eero.get("ethernet_status", {})
        if not ethernet_status:
            return

        wired_internet = ethernet_status.get("wiredInternet")
        if wired_internet is not None:
            EERO_WIRED_INTERNET.labels(
                network_id=network_id, eero_id=eero_id, location=location
            ).set(1 if wired_internet else 0)

        statuses = ethernet_status.get("statuses", [])
        if not statuses or not isinstance(statuses, list):
            return

        for port_status in statuses:
            if not isinstance(port_status, dict):
                continue

            port_num = port_status.get("interfaceNumber", 0)
            port_name = port_status.get("port_name", f"port{port_num}")
            port_num_str = str(port_num)

            # `original_speed`/`derated_reason` were removed in 4.0.0 -- both
            # are always null on every observed port (§11.11); `port_name`
            # is the only field with a real value.
            ETHERNET_PORT_INFO.labels(
                network_id=network_id, eero_id=eero_id, port_number=port_num_str
            ).info({"port_name": port_name})

            has_carrier = port_status.get("hasCarrier")
            if has_carrier is not None:
                ETHERNET_PORT_CARRIER.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                    port_number=port_num_str,
                    port_name=port_name,
                ).set(1 if has_carrier else 0)

            speed = _parse_ethernet_speed_enum(port_status.get("speed"))
            if speed is not None:
                ETHERNET_PORT_SPEED.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                    port_number=port_num_str,
                    port_name=port_name,
                ).set(speed)

            is_wan = port_status.get("isWanPort")
            if is_wan is not None:
                ETHERNET_PORT_IS_WAN.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                    port_number=port_num_str,
                    port_name=port_name,
                ).set(1 if is_wan else 0)

            is_lte = port_status.get("isLte")
            if is_lte is not None:
                ETHERNET_PORT_IS_LTE.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                    port_number=port_num_str,
                    port_name=port_name,
                ).set(1 if is_lte else 0)

            # `neighbor` is absent/null on unconnected ports. The only
            # label-safe fields are `type` (bounded enum) and
            # `metadata.port` (int) -- never `port_name`/`location`/`url`
            # (§8/§11.2 of the v8 probe shape summary).
            neighbor = port_status.get("neighbor")
            if isinstance(neighbor, dict):
                neighbor_type = neighbor.get("type")
                neighbor_metadata = neighbor.get("metadata")
                neighbor_port = (
                    neighbor_metadata.get("port") if isinstance(neighbor_metadata, dict) else None
                )
                if neighbor_type is not None or neighbor_port is not None:
                    ETHERNET_PORT_NEIGHBOR_INFO.labels(
                        network_id=network_id,
                        eero_id=eero_id,
                        port_number=port_num_str,
                    ).info(
                        {
                            "neighbor_type": str(neighbor_type) if neighbor_type else "unknown",
                            "neighbor_port": str(neighbor_port)
                            if neighbor_port is not None
                            else "unknown",
                        }
                    )

            # `eero_ethernet_port_power_saving` was removed in 4.0.0 in
            # favour of the network-wide `eero_network_power_saving_enabled`
            # (§11.11 lists the per-port key as removed).

    async def _collect_premium_metrics(
        self,
        client: EeroClient,
        network_id: str,
        network_name: str,
        network_details: dict[str, Any],
    ) -> None:
        """Collect premium features metrics (Eero Plus) from the network envelope.

        Premium detection no longer issues its own ``get_premium_status``
        GET -- ``premium_status``/``premium_details`` are read straight off
        the already-fetched network envelope (§11.1 of the v8 probe shape
        summary). ``self._is_premium`` may still be forced to False mid-cycle
        by ``_api_get`` if any other call raises ``EeroPremiumRequiredError``.
        """
        is_premium = _parse_premium_enabled(
            network_details.get("premium_status"), network_details.get("premium_details")
        )
        self._is_premium = is_premium
        NETWORK_PREMIUM_ENABLED.labels(network_id=network_id, name=network_name).set(
            1 if is_premium else 0
        )

        if not self._is_premium:
            return

        await self._collect_current_usage_metrics(client, network_id)
        await self._collect_backup_metrics(client, network_id)

    async def _collect_current_usage_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect trailing-hour data usage summary metrics (replaces deprecated activity endpoint).

        Builds a 1-hour trailing window payload and delegates to the data_usage
        endpoint for both network-level totals and per-device breakdowns.
        """
        now = datetime.now(UTC)
        payload = {
            "start": _format_utc_z(now - timedelta(hours=1)),
            "end": _format_utc_z(now),
            "cadence": "hourly",
            "timezone": "UTC",
        }

        # Per-device breakdown for this same trailing hour is fed separately
        # by `_collect_data_usage_metrics`'s single `get_data_usage_breakdown`
        # call (`_set_device_trailing_usage`) -- `get_devices_data_usage` is
        # never called here (§3 of the collector-single-envelope commit).
        usage, exc = await self._api_get(
            "current_usage", client.get_data_usage(network_id, **payload)
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get current usage totals: {exc}")
            return

        series_list = usage.get("series", [])
        if isinstance(series_list, list):
            for series in series_list:
                if not isinstance(series, dict):
                    continue
                direction = str(series.get("type") or series.get("direction") or "").lower()
                total = _series_sum(series)
                if total is None:
                    continue
                if direction == "download":
                    DATA_USAGE_DOWNLOAD_BYTES.labels(network_id=network_id).set(total)
                elif direction == "upload":
                    DATA_USAGE_UPLOAD_BYTES.labels(network_id=network_id).set(total)

    def _set_device_trailing_usage(self, network_id: str, items: list[Any]) -> None:
        """Set the manufacturer/device_type-labelled trailing-hour usage gauges.

        Args:
            items: ``get_data_usage_breakdown``'s ``data.devices[]`` list --
                flat ``upload``/``download`` ints per device, no time series.
        """
        for idx, device in enumerate(items):
            try:
                if not isinstance(device, dict):
                    continue
                device_id = str(device.get("id") or _extract_id_from_url(device.get("url", "")))
                if not device_id:
                    continue
                name = (
                    device.get("nickname")
                    or device.get("display_name")
                    or device.get("hostname")
                    or device.get("name")
                    or device_id
                )
                manufacturer = _normalize_manufacturer(device.get("manufacturer"))
                device_type = _normalize_device_type(device.get("device_type"))
                labels = {
                    "network_id": network_id,
                    "device_id": device_id,
                    "name": str(name),
                    "manufacturer": manufacturer,
                    "device_type": device_type,
                }
                download = device.get("download")
                if download is not None:
                    try:
                        DEVICE_DATA_USAGE_DOWNLOAD_BYTES.labels(**labels).set(float(download))
                    except (TypeError, ValueError):
                        pass
                upload = device.get("upload")
                if upload is not None:
                    try:
                        DEVICE_DATA_USAGE_UPLOAD_BYTES.labels(**labels).set(float(upload))
                    except (TypeError, ValueError):
                        pass
            except Exception as exc:
                _LOGGER.warning(
                    "Skipping device trailing-usage item %d: %s: %s", idx, type(exc).__name__, exc
                )
                continue

    async def _collect_backup_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect backup network metrics (Eero Plus feature).

        The eero-api v8 SDK removed ``get_backup_network``/``get_backup_status``
        (see the v8 migration plan §1.1) with no replacement read of the same
        shape; this sub-collector is a placeholder no-op until COLLECTOR-SME
        re-implements backup metrics against the extended-tier reads
        (``get_backup_internet``, ``list_backup_access_points``) in a later
        commit.
        """
        return

    async def _collect_port_forward_metrics(
        self, client: EeroClient, network_id: str, network_name: str
    ) -> None:
        """Collect port forwarding metrics."""
        forwards, exc = await self._api_get("forwards", client.get_forwards(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get port forwards: {exc}")
            return

        NETWORK_PORT_FORWARDS_COUNT.labels(network_id=network_id, name=network_name).set(
            len(forwards)
        )

        for idx, forward in enumerate(forwards):
            try:
                if not isinstance(forward, dict):
                    continue

                forward_url = forward.get("url", "")
                forward_id = _extract_id_from_url(forward_url) or str(hash(str(forward)))[:8]

                # `client_port`/`gateway_port` are the v8-remapped keys
                # (unverified -- the probed mesh had zero forwards); fall
                # back to the legacy `port`/`external_port`/`internal_port`
                # names. The forwarded IP is never read into a label/info
                # value.
                legacy_gateway_port = forward.get("port", forward.get("external_port", ""))
                gateway_port = str(forward.get("gateway_port", legacy_gateway_port))
                client_port = str(
                    forward.get("client_port", forward.get("internal_port", gateway_port))
                )
                protocol = str(forward.get("protocol", "tcp")).lower()
                enabled = forward.get("enabled", True)
                description = forward.get("description", forward.get("nickname", ""))

                PORT_FORWARD_INFO.labels(network_id=network_id, forward_id=forward_id).info(
                    {
                        "client_port": client_port,
                        "gateway_port": gateway_port,
                        "protocol": protocol,
                        "description": str(description),
                    }
                )

                PORT_FORWARD_ENABLED.labels(
                    network_id=network_id,
                    forward_id=forward_id,
                    gateway_port=gateway_port,
                    protocol=protocol,
                ).set(1 if enabled else 0)
            except Exception as item_exc:
                _LOGGER.warning(
                    "Skipping port forward item %d: %s: %s", idx, type(item_exc).__name__, item_exc
                )
                continue

    async def _collect_reservation_metrics(
        self, client: EeroClient, network_id: str, network_name: str
    ) -> None:
        """Collect DHCP reservation metrics."""
        reservations, exc = await self._api_get("reservations", client.get_reservations(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get DHCP reservations: {exc}")
            return

        NETWORK_DHCP_RESERVATIONS_COUNT.labels(network_id=network_id, name=network_name).set(
            len(reservations)
        )

    async def _collect_blacklist_metrics(
        self, client: EeroClient, network_id: str, network_name: str
    ) -> None:
        """Collect blacklist metrics."""
        blacklist, exc = await self._api_get("blacklist", client.get_blacklist(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get blacklist: {exc}")
            return

        NETWORK_BLACKLISTED_DEVICES_COUNT.labels(network_id=network_id, name=network_name).set(
            len(blacklist)
        )

    async def _collect_insights_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect insights time-series metrics for all three insight types.

        Fans out to the insights endpoint once per type (adblock, blocked,
        inspected) using a 24-hour trailing window.  Each call is independently
        guarded so a 403 (insufficient subscription) on one type does not
        prevent the others from being collected.
        """
        now = datetime.now(UTC)
        end_str = _format_utc_z(now)
        start_str = _format_utc_z(now - timedelta(hours=24))

        insight_metrics = {
            "adblock": INSIGHTS_ADBLOCK_TOTAL,
            "blocked": INSIGHTS_BLOCKED_TOTAL,
            "inspected": INSIGHTS_INSPECTED_TOTAL,
        }

        for insight_type, metric in insight_metrics.items():
            data, exc = await self._api_get(
                f"insights_{insight_type}",
                client.get_insights(
                    network_id,
                    start=start_str,
                    end=end_str,
                    insight_type=insight_type,
                    cadence="daily",
                ),
            )
            if exc is not None:
                _LOGGER.debug(f"Failed to get {insight_type} insights: {exc}")
                continue

            if not data:
                continue

            series_list = data.get("series", [])
            if not isinstance(series_list, list):
                series_list = []

            if series_list:
                for series in series_list:
                    if not isinstance(series, dict):
                        continue
                    category = str(
                        series.get("insight_type") or series.get("category") or insight_type
                    )
                    total = _series_sum(series)
                    if total is not None:
                        metric.labels(network_id=network_id, category=category).set(total)
            else:
                totals = data.get("totals", {})
                if isinstance(totals, dict):
                    raw = totals.get(insight_type) or totals.get("total")
                    try:
                        total = float(raw) if raw is not None else None
                    except (TypeError, ValueError):
                        total = None
                    if total is not None:
                        metric.labels(network_id=network_id, category=insight_type).set(total)

    async def _collect_extended_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect the extended tier (§9 #12-19, §11.6/§11.8-11.10 of the v8 probe).

        Nine fixed-cost verified reads, one GET each (notifications issues
        two: settings + has-unread), plus three profile-insights calls (one
        per insight type, list-level -- covers every profile in one GET
        each). Every sub-collector is independently guarded so a partial
        failure never drops the rest of the tier.
        """
        await self._collect_entitlement_metrics(client, network_id)
        await self._collect_wpa3_metrics(client, network_id)
        await self._collect_fast_transition_metrics(client, network_id)
        await self._collect_permission_metrics(client, network_id)
        await self._collect_member_metrics(client, network_id)
        await self._collect_notification_metrics(client, network_id)
        await self._collect_dns_filter_metrics(client, network_id)
        await self._collect_subnet_metrics(client, network_id)
        await self._collect_profile_insights_metrics(client, network_id)

    async def _collect_entitlement_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect entitlement features and account entitlement metadata (§11.8).

        `multi_ssid` and `one_password` have no `capability` key at all on
        the observed payload and are skipped rather than guessed at.
        """
        data, exc = await self._api_get("entitlements", client.get_entitlement_features(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get entitlement features: {exc}")
            return

        features = data.get("features")
        if isinstance(features, dict):
            for name, spec in features.items():
                if not isinstance(spec, dict):
                    continue
                capability = spec.get("capability")
                if not isinstance(capability, dict):
                    continue
                capable = capability.get("capable")
                if not isinstance(capable, bool):
                    continue
                NETWORK_FEATURE_ENTITLED.labels(
                    network_id=network_id, feature=_sanitize_label_value(str(name))
                ).set(1 if capable else 0)

        entitlements = data.get("entitlements")
        if not isinstance(entitlements, list):
            return
        for idx, item in enumerate(entitlements):
            try:
                if not isinstance(item, dict):
                    continue
                state = item.get("state")
                if state:
                    ACCOUNT_ENTITLEMENT_STATE.labels(
                        network_id=network_id, state=_sanitize_label_value(str(state))
                    ).set(1)

                product = item.get("product")
                product_type = product.get("type") if isinstance(product, dict) else None
                if product_type:
                    ACCOUNT_ENTITLEMENT_PRODUCT_INFO.labels(
                        network_id=network_id, type=_sanitize_label_value(str(product_type))
                    ).set(1)

                created_ts = _parse_timestamp(item.get("created_at"))
                if created_ts is not None:
                    ACCOUNT_ENTITLEMENT_CREATED_TIMESTAMP.labels(network_id=network_id).set(
                        created_ts
                    )
            except Exception as item_exc:
                _LOGGER.warning(
                    "Skipping entitlement item %d: %s: %s", idx, type(item_exc).__name__, item_exc
                )
                continue

    async def _collect_wpa3_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect the per-band WPA3 mode state-set gauge (§11.10).

        Three bands, closed 3-value mode enum -- 1 for the observed mode, 0
        for the other two, so a dashboard can alert on "not WPA3" cleanly.
        """
        data, exc = await self._api_get("wpa3", client.get_wpa3_per_band(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get WPA3 per-band mode: {exc}")
            return

        for field, band_label in _WPA3_BAND_FIELDS.items():
            raw_mode = data.get(field)
            # The API returns the mode in lower case ("wpa2", "wpa3"); the label
            # value is the upper-case form of the closed enum.
            mode = raw_mode.upper() if isinstance(raw_mode, str) else None
            if mode not in _WPA3_MODES:
                if raw_mode is not None:
                    _LOGGER.debug("wpa3 %s: unrecognised mode (len=%d)", field, len(str(raw_mode)))
                continue
            for candidate in _WPA3_MODES:
                EERO_NETWORK_WPA3_BAND_MODE.labels(
                    network_id=network_id, band=band_label, mode=candidate
                ).set(1 if candidate == mode else 0)

    async def _collect_fast_transition_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect the fast-transition (802.11r) boolean (§11.10)."""
        data, exc = await self._api_get("fast_transition", client.get_fast_transition(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get fast transition: {exc}")
            return

        enabled = data.get("fast_transition")
        if isinstance(enabled, bool):
            NETWORK_FAST_TRANSITION_ENABLED.labels(network_id=network_id).set(1 if enabled else 0)

    async def _collect_permission_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect the flat dotted-key permission booleans and role (§11.9).

        `permissions.permissions` is a flat dict, not a tree -- walked
        directly. `*.password`/`*.multi_ssid`/`network.multistatic_ip`/
        `user.conversations_token` are redacted-class keys and skipped;
        `per_eero` is a list, not a CRUD dict, and skipped here too.
        """
        data, exc = await self._api_get("permissions", client.get_permissions(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get permissions: {exc}")
            return

        role = data.get("role")
        if role:
            NETWORK_ROLE_INFO.labels(network_id=network_id).info({"role": str(role)})

        permissions = data.get("permissions")
        if not isinstance(permissions, dict):
            return
        for key, value in permissions.items():
            if key == "per_eero":
                self._set_per_eero_permissions(network_id, value)
                continue
            if key in _PERMISSION_SKIP_KEYS or key.endswith(_PERMISSION_SKIP_SUFFIXES):
                continue
            if not isinstance(value, dict):
                continue
            read_perm = value.get("read")
            if not isinstance(read_perm, bool):
                continue
            NETWORK_PERMISSION.labels(
                network_id=network_id, capability=_sanitize_label_value(key)
            ).set(1 if read_perm else 0)

    def _set_per_eero_permissions(self, network_id: str, items: Any) -> None:
        """Set the per-eero CRUD permission gauges (§11.9).

        The ``per_eero`` entry is a list of ``{url, eero: {create, read,
        update, delete}}`` objects rather than the flat boolean shape the
        other permission keys use, so it is parsed separately.
        """
        if not isinstance(items, list):
            return
        for idx, item in enumerate(items):
            try:
                if not isinstance(item, dict):
                    continue
                # Observed shape is {"id": int, "eero": {...}}; the url form is
                # accepted too so a future payload that publishes a link works.
                eero_id = str(item.get("id") or _extract_id_from_url(item.get("url", "")))
                verbs = item.get("eero")
                if not eero_id or not isinstance(verbs, dict):
                    continue
                for verb, allowed in verbs.items():
                    if not isinstance(allowed, bool):
                        continue
                    NETWORK_PER_EERO_PERMISSION.labels(
                        network_id=network_id,
                        eero_id=eero_id,
                        verb=_sanitize_label_value(str(verb)),
                    ).set(1 if allowed else 0)
            except Exception as item_exc:
                _LOGGER.warning(
                    "Skipping per-eero permission item %d: %s: %s",
                    idx,
                    type(item_exc).__name__,
                    item_exc,
                )
                continue

    async def _collect_member_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect the member count (§11.10). Never the member list itself."""
        data, exc = await self._api_get("members", client.get_members(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get members: {exc}")
            return

        members = data.get("members")
        if isinstance(members, list):
            NETWORK_MEMBERS_COUNT.labels(network_id=network_id).set(len(members))

    async def _collect_notification_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect notification-setting booleans and the unread flag (§11.10).

        Two independently-guarded GETs: `get_notification_settings` (flat
        dotted-key booleans) and `has_unread_notifications` (a bool, not a
        count).
        """
        settings, exc = await self._api_get(
            "notifications", client.get_notification_settings(network_id)
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get notification settings: {exc}")
        else:
            for key, value in settings.items():
                if isinstance(value, bool):
                    NETWORK_NOTIFICATION_ENABLED.labels(
                        network_id=network_id, event=_sanitize_label_value(key)
                    ).set(1 if value else 0)

        unread, exc = await self._api_get(
            "notifications_unread", client.has_unread_notifications(network_id)
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get unread-notifications flag: {exc}")
            return

        has_unread = unread.get("has_unread")
        if isinstance(has_unread, bool):
            NETWORK_NOTIFICATIONS_UNREAD.labels(network_id=network_id).set(1 if has_unread else 0)

    async def _collect_dns_filter_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect the advanced content filter's list lengths (§11.10).

        Premium-only: gated by `include_premium` in addition to
        `include_extended`. `EeroPremiumRequiredError` is an expected state
        on non-subscribed accounts, not a scrape error (handled by
        `_api_get`/`_record_api_result`, which log it at DEBUG).
        """
        if not self._include_premium:
            return

        data, exc = await self._api_get(
            "dns_filter", client.get_advanced_content_filter(network_id)
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get advanced content filter: {exc}")
            return

        allowed_list = data.get("allowed_list")
        if isinstance(allowed_list, list):
            DNS_POLICY_ALLOWED_DOMAINS_COUNT.labels(network_id=network_id).set(len(allowed_list))

        blocked_list = data.get("blocked_list")
        if isinstance(blocked_list, list):
            DNS_POLICY_BLOCKED_DOMAINS_COUNT.labels(network_id=network_id).set(len(blocked_list))

    async def _collect_subnet_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect per-subnet booleans (§11.10). Never name/password/ssid.

        Labelled by `subnet_kind` (closed enum: guest|main) and
        `subnet_type`, per the commit brief -- never `subnet_id`, `name`, or
        `password`.
        """
        subnets, exc = await self._api_get("subnets", client.get_subnets_config(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get subnets config: {exc}")
            return
        if not isinstance(subnets, list):
            return

        for idx, subnet in enumerate(subnets):
            try:
                if not isinstance(subnet, dict):
                    continue
                labels = {
                    "network_id": network_id,
                    "subnet_kind": str(subnet.get("subnet_kind") or "unknown"),
                    "subnet_type": str(subnet.get("subnet_type") or "unknown"),
                }
                for field, metric in _SUBNET_BOOL_FIELDS.items():
                    value = subnet.get(field)
                    if isinstance(value, bool):
                        metric.labels(**labels).set(1 if value else 0)
            except Exception as item_exc:
                _LOGGER.warning(
                    "Skipping subnet item %d: %s: %s", idx, type(item_exc).__name__, item_exc
                )
                continue

    async def _collect_profile_insights_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect per-profile insight totals (§11.6, list-level).

        One GET per insight type covers every profile on the network --
        `data.insights[]` carries one item per profile, keyed to a profile
        by `.insights_url` (the request-response cadence is the same
        24-hour trailing window as `_collect_insights_metrics`).
        """
        now = datetime.now(UTC)
        end_str = _format_utc_z(now)
        start_str = _format_utc_z(now - timedelta(hours=24))

        for insight_type in _INSIGHT_TYPES:
            data, exc = await self._api_get(
                "profiles_insights",
                client.get_profiles_insights(
                    network_id,
                    start=start_str,
                    end=end_str,
                    cadence="daily",
                    insight_type=insight_type,
                ),
            )
            if exc is not None:
                _LOGGER.debug(f"Failed to get {insight_type} profile insights: {exc}")
                continue

            insights = data.get("insights")
            if not isinstance(insights, list):
                continue

            for idx, item in enumerate(insights):
                try:
                    if not isinstance(item, dict):
                        continue
                    profile_id = _extract_profile_id_from_url(item.get("insights_url"))
                    if not profile_id:
                        continue
                    total = item.get("sum")
                    if total is not None:
                        PROFILE_INSIGHTS_TOTAL.labels(
                            network_id=network_id, profile_id=profile_id, type=insight_type
                        ).set(float(total))
                    num_devices = item.get("num_devices")
                    if num_devices is not None:
                        PROFILE_INSIGHTS_DEVICES.labels(
                            network_id=network_id, profile_id=profile_id, type=insight_type
                        ).set(float(num_devices))
                except Exception as item_exc:
                    _LOGGER.warning(
                        "Skipping profile insights item %d: %s: %s",
                        idx,
                        type(item_exc).__name__,
                        item_exc,
                    )
                    continue

    async def _collect_rf_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect the `rf` tier: one unparameterised channel-utilization call.

        No `band=` is passed -- the single call returns every eero and every
        band (§9 #20/#21, §11.7 of the v8 probe shape summary).
        """
        now = datetime.now(UTC)
        end_str = _format_utc_z(now)
        start_str = _format_utc_z(now - timedelta(hours=24))

        data, exc = await self._api_get(
            "channel_utilization",
            client.get_channel_utilization(network_id, start=start_str, end=end_str),
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get channel utilization: {exc}")
            return

        eeros_meta = data.get("eeros")
        if isinstance(eeros_meta, list):
            for meta_item in eeros_meta:
                if not isinstance(meta_item, dict):
                    continue
                role_eero_id = meta_item.get("eero_id")
                role = meta_item.get("role")
                if role_eero_id is not None and role:
                    EERO_EERO_ROLE_INFO.labels(
                        network_id=network_id, eero_id=str(role_eero_id)
                    ).info({"role": str(role)})

        utilization = data.get("utilization")
        if not isinstance(utilization, list):
            return

        for idx, item in enumerate(utilization):
            try:
                if not isinstance(item, dict):
                    continue
                eero_id = item.get("eero_id")
                band = item.get("band")
                if eero_id is None or band not in _CHANNEL_UTILIZATION_BANDS:
                    continue
                labels = {"network_id": network_id, "eero_id": str(eero_id), "band": band}

                avg = _coerce_numeric(
                    item.get("average_utilization"), field_name="average_utilization"
                )
                if avg is not None:
                    EERO_CHANNEL_UTILIZATION_AVG_PERCENT.labels(**labels).set(avg)

                max_utilization = _coerce_numeric(
                    item.get("max_utilization"), field_name="max_utilization"
                )
                if max_utilization is not None:
                    EERO_CHANNEL_UTILIZATION_MAX_PERCENT.labels(**labels).set(max_utilization)

                p99 = _coerce_numeric(item.get("p99_utilization"), field_name="p99_utilization")
                if p99 is not None:
                    EERO_CHANNEL_UTILIZATION_P99_PERCENT.labels(**labels).set(p99)

                busy_minutes = _coerce_numeric(
                    item.get("minutes_over_busy_threshold"),
                    field_name="minutes_over_busy_threshold",
                )
                if busy_minutes is not None:
                    EERO_CHANNEL_BUSY_MINUTES.labels(**labels).set(busy_minutes)

                channel = item.get("channel")
                center_channel = item.get("center_channel")
                channel_bandwidth = item.get("channel_bandwidth")
                frequency = item.get("frequency")
                EERO_CHANNEL_INFO.labels(**labels).info(
                    {
                        "channel": str(channel) if channel is not None else "unknown",
                        "center_channel": (
                            str(center_channel) if center_channel is not None else "unknown"
                        ),
                        "channel_bandwidth": str(channel_bandwidth or "unknown"),
                        "frequency": str(frequency) if frequency is not None else "unknown",
                    }
                )

                acs_events = item.get("acs_events")
                if isinstance(acs_events, list):
                    EERO_CHANNEL_ACS_EVENTS_TOTAL.labels(**labels).set(len(acs_events))

                time_series = item.get("time_series_data")
                if isinstance(time_series, list) and time_series:
                    last_sample = time_series[-1]
                    if isinstance(last_sample, dict):
                        busy = _coerce_numeric(last_sample.get("busy"), field_name="channel_busy")
                        if busy is not None:
                            EERO_CHANNEL_BUSY_LAST.labels(**labels).set(busy)
                        noise = _coerce_numeric(
                            last_sample.get("noise"), field_name="channel_noise"
                        )
                        if noise is not None:
                            EERO_CHANNEL_NOISE_LAST.labels(**labels).set(noise)
                        rx_tx = _coerce_numeric(
                            last_sample.get("rx_tx"), field_name="channel_rx_tx"
                        )
                        if rx_tx is not None:
                            EERO_CHANNEL_RX_TX_LAST.labels(**labels).set(rx_tx)
                        rx_other = _coerce_numeric(
                            last_sample.get("rx_other"), field_name="channel_rx_other"
                        )
                        if rx_other is not None:
                            EERO_CHANNEL_RX_OTHER_LAST.labels(**labels).set(rx_other)
            except Exception as item_exc:
                _LOGGER.warning(
                    "Skipping channel utilization item %d: %s: %s",
                    idx,
                    type(item_exc).__name__,
                    item_exc,
                )
                continue

    async def _collect_per_device_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect the `per_device` tier: device-level insights, list-level (§9 #11, §11.6).

        Three GETs total (one per insight type), each covering every device
        on the network -- not 3·D. Cardinality (D series per type), not
        request count, is why this tier defaults off.
        """
        now = datetime.now(UTC)
        end_str = _format_utc_z(now)
        start_str = _format_utc_z(now - timedelta(hours=24))

        for insight_type in _INSIGHT_TYPES:
            data, exc = await self._api_get(
                "devices_insights",
                client.get_devices_insights(
                    network_id,
                    start=start_str,
                    end=end_str,
                    cadence="daily",
                    insight_type=insight_type,
                ),
            )
            if exc is not None:
                _LOGGER.debug(f"Failed to get {insight_type} device insights: {exc}")
                continue

            insights = data.get("insights")
            if not isinstance(insights, list):
                continue

            for idx, item in enumerate(insights):
                try:
                    if not isinstance(item, dict):
                        continue
                    device_id = _extract_device_id_from_url(item.get("insights_url"))
                    if not device_id:
                        continue
                    total = item.get("sum")
                    if total is None:
                        continue
                    DEVICE_INSIGHTS_TOTAL.labels(
                        network_id=network_id, device_id=device_id, type=insight_type
                    ).set(float(total))
                except Exception as item_exc:
                    _LOGGER.warning(
                        "Skipping device insights item %d: %s: %s",
                        idx,
                        type(item_exc).__name__,
                        item_exc,
                    )
                    continue

    async def _collect_per_eero_metrics(
        self,
        client: EeroClient,
        network_id: str,
        eeros: list[dict[str, Any]] | None,
    ) -> None:
        """Collect the `per_eero` tier: nightlight, connections, ouicheck (§9 #44).

        Three independently-guarded GETs per eero. `get_nightlight` raises
        `EeroFeatureUnavailableError` on hardware without a Beacon light (an
        expected state, not a scrape error) -- no shape was ever observed
        live for this endpoint, so nothing is exported from a success
        response either; brightness/enabled/schedule are already sourced
        from the envelope (`eeros[].nightlight`).
        """
        if not eeros:
            return

        for eero in eeros:
            if not isinstance(eero, dict):
                continue
            eero_id = _extract_id_from_url(eero.get("url", ""))
            if not eero_id:
                continue

            _, exc = await self._api_get("nightlight", client.get_nightlight(eero_id, network_id))
            if exc is not None:
                _LOGGER.debug(f"Failed to get nightlight for eero {eero_id}: {exc}")

            connections, exc = await self._api_get(
                "eero_connections", client.get_connections(eero_id, network_id)
            )
            if exc is not None:
                _LOGGER.debug(f"Failed to get connections for eero {eero_id}: {exc}")
            else:
                wireless_devices = connections.get("wireless_devices")
                if isinstance(wireless_devices, list):
                    EERO_EERO_CONNECTIONS_COUNT.labels(network_id=network_id, eero_id=eero_id).set(
                        len(wireless_devices)
                    )

            serial = eero.get("serial")
            os_version = eero.get("os_version") or eero.get("os")
            if not serial or not os_version:
                continue

            ouicheck, exc = await self._api_get(
                "ouicheck",
                client.get_ouicheck(network_id, serial=str(serial), version=str(os_version)),
            )
            if exc is not None:
                _LOGGER.debug(f"Failed to get ouicheck for eero {eero_id}: {exc}")
                continue

            can_add = ouicheck.get("can_add")
            if isinstance(can_add, bool):
                EERO_OUICHECK_CAN_ADD.labels(network_id=network_id, eero_id=eero_id).set(
                    1 if can_add else 0
                )
            must_update = ouicheck.get("must_update")
            if isinstance(must_update, bool):
                EERO_OUICHECK_MUST_UPDATE.labels(network_id=network_id, eero_id=eero_id).set(
                    1 if must_update else 0
                )

    async def _collect_per_profile_metrics(
        self,
        client: EeroClient,
        network_id: str,
        profiles: list[dict[str, Any]] | None,
    ) -> None:
        """Collect the `per_profile` tier: DNS-policy applications (§9 #42).

        One GET per profile. Premium-gated in practice --
        `EeroPremiumRequiredError`/`EeroNotFoundError` are expected states on
        non-subscribed accounts or profiles with no policy configured.
        """
        if not profiles:
            return

        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            profile_id = _extract_id_from_url(profile.get("url", ""))
            if not profile_id:
                continue

            data, exc = await self._api_get(
                "profile_dns_apps",
                client.get_dns_policy_applications(profile_id, network_id),
            )
            if exc is not None:
                _LOGGER.debug(
                    f"Failed to get DNS policy applications for profile {profile_id}: {exc}"
                )
                continue

            applications = data.get("applications")
            if isinstance(applications, list):
                PROFILE_DNS_POLICY_APPLICATIONS_COUNT.labels(
                    network_id=network_id, profile_id=profile_id
                ).set(len(applications))

    async def _collect_unverified_metrics(
        self,
        client: EeroClient,
        network_id: str,
        devices: list[dict[str, Any]] | None,
    ) -> None:
        """Collect the `unverified` tier (§9 #22, #28-41 of the v8 probe shape summary).

        Every read here is a documented eero-api method whose element shape
        was never observed with real data, was empty, or was an expected
        error on the probed account. Values are exported only for keys the
        shape summary actually observed; everything else is key-logged at
        DEBUG (never a value) so schema drift is discoverable without
        guessing.
        """
        # --- thread: mostly key material, no counts on this payload
        # (§3 "thread"); key-log only. `eero_thread_enabled` is already
        # sourced from the network envelope in the core tier -- this is the
        # only place `get_thread` is called.
        thread_data, exc = await self._api_get("thread", client.get_thread(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get thread: {exc}")
        else:
            _log_observed_keys_once("thread", network_id, thread_data)

        # --- routing: counts only; all four collections were empty on
        # probed data, so the port-forward remap remains unverified.
        routing, exc = await self._api_get("routing", client.get_routing(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get routing: {exc}")
        else:
            for key, metric in (
                ("devices", NETWORK_ROUTING_DEVICES_COUNT),
                ("reservations", NETWORK_ROUTING_RESERVATIONS_COUNT),
                ("forwards", NETWORK_ROUTING_FORWARDS_COUNT),
                ("pinholes", NETWORK_ROUTING_PINHOLES_COUNT),
            ):
                collection = routing.get(key)
                items = collection.get("data") if isinstance(collection, dict) else None
                if isinstance(items, list):
                    metric.labels(network_id=network_id).set(len(items))

        # --- backup access points: status vocabulary known
        # (failure|unknown), no success value ever observed. Never exports
        # ssid/password/failure_reason (free text).
        aps, exc = await self._api_get(
            "backup_access_points", client.list_backup_access_points(network_id)
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get backup access points: {exc}")
        elif isinstance(aps, list):
            BACKUP_ACCESS_POINTS_COUNT.labels(network_id=network_id).set(len(aps))
            for idx, ap in enumerate(aps):
                if not isinstance(ap, dict):
                    continue
                index = str(idx)
                enabled = ap.get("enabled")
                if isinstance(enabled, bool):
                    BACKUP_ACCESS_POINT_ENABLED.labels(network_id=network_id, index=index).set(
                        1 if enabled else 0
                    )
                connectivity = ap.get("connectivity")
                status = connectivity.get("status") if isinstance(connectivity, dict) else None
                if isinstance(status, str):
                    BACKUP_ACCESS_POINT_CONNECTIVITY_INFO.labels(
                        network_id=network_id,
                        index=index,
                        status=_sanitize_label_value(status),
                    ).info({})

        # --- cellular backup usage/events: both verified-empty; element
        # shapes were never observed (no cellular hardware on the probed mesh).
        usage, exc = await self._api_get(
            "cellular_backup_usage", client.get_cellular_backup_usage(network_id)
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get cellular backup usage: {exc}")
        else:
            usage_items = usage.get("backup_usage_items")
            if isinstance(usage_items, list):
                CELLULAR_BACKUP_USAGE_ITEMS_COUNT.labels(network_id=network_id).set(
                    len(usage_items)
                )

        events, exc = await self._api_get(
            "cellular_backup_events", client.get_cellular_backup_events(network_id)
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get cellular backup events: {exc}")
        else:
            outages = events.get("outages")
            if isinstance(outages, list):
                CELLULAR_BACKUP_OUTAGES_COUNT.labels(network_id=network_id).set(len(outages))

        # --- network scan: one boolean.
        scan, exc = await self._api_get("network_scan", client.get_network_scan(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get network scan: {exc}")
        else:
            conflicting_ssid = scan.get("conflicting_ssid")
            if isinstance(conflicting_ssid, bool):
                NETWORK_SCAN_CONFLICTING_SSID.labels(network_id=network_id).set(
                    1 if conflicting_ssid else 0
                )

        # --- speed test history: list length in the requested window.
        speed_tests, exc = await self._api_get(
            "speed_tests", client.get_speed_tests(network_id, limit=_SPEED_TESTS_LIMIT)
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get speed test history: {exc}")
        else:
            SPEED_TESTS_TOTAL.labels(network_id=network_id).set(len(speed_tests))

        # --- multistaticip: EeroNotFoundError -> 0, an expected state
        # (feature capable and permitted, just not configured).
        multistaticip, exc = await self._api_get(
            "multistaticip", client.get_multistaticip(network_id)
        )
        if isinstance(exc, EeroNotFoundError):
            NETWORK_MULTISTATICIP_ENABLED.labels(network_id=network_id).set(0)
        elif exc is not None:
            _LOGGER.debug(f"Failed to get multistaticip: {exc}")
        else:
            enabled = multistaticip.get("enabled")
            NETWORK_MULTISTATICIP_ENABLED.labels(network_id=network_id).set(1 if enabled else 0)

        # --- ac-compat: one boolean.
        ac_compat, exc = await self._api_get("ac_compat", client.get_ac_compat(network_id))
        if exc is not None:
            _LOGGER.debug(f"Failed to get ac-compat: {exc}")
        else:
            ac_enabled = ac_compat.get("enabled")
            if isinstance(ac_enabled, bool):
                NETWORK_AC_COMPAT.labels(network_id=network_id).set(1 if ac_enabled else 0)

        # --- power-saving schedules: verified-empty, element shape unobserved.
        schedules, exc = await self._api_get(
            "power_saving_schedules", client.get_power_saving_schedules(network_id)
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get power-saving schedules: {exc}")
        else:
            schedule_items = schedules.get("schedules")
            if isinstance(schedule_items, list):
                NETWORK_POWER_SAVING_SCHEDULES_COUNT.labels(network_id=network_id).set(
                    len(schedule_items)
                )

        # --- transfer stats: never returned a payload in either probe run
        # (403 network-level / 404 device-level, both runs). Stub only --
        # record the API status, key-log if a payload ever arrives, export
        # nothing.
        transfer_network, exc = await self._api_get(
            "transfer_network", client.get_transfer_stats(network_id)
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get network transfer stats: {exc}")
        else:
            _log_observed_keys_once("transfer_network", network_id, transfer_network)

        first_device_mac: str | None = None
        if devices:
            for device in devices:
                if not isinstance(device, dict):
                    continue
                mac = device.get("mac") or device.get("eui64")
                if mac:
                    first_device_mac = str(mac)
                    break

        if not first_device_mac:
            return

        transfer_device, exc = await self._api_get(
            "transfer_device", client.get_transfer_stats(network_id, first_device_mac)
        )
        if exc is not None:
            _LOGGER.debug(f"Failed to get device transfer stats: {exc}")
        else:
            _log_observed_keys_once("transfer_device", network_id, transfer_device)
