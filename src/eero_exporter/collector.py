"""Collector module for gathering eero metrics."""

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .eero_adapter import EeroAPIError, EeroAuthError, EeroClient
from .metrics import (
    ACCOUNT_NETWORKS_COUNT,
    BACKUP_ACTIVE,
    BACKUP_CONNECTED,
    BACKUP_ENABLED,
    BACKUP_SIGNAL_STRENGTH,
    DATA_USAGE_ACTIVE_CLIENTS,
    DATA_USAGE_DOWNLOAD_BYTES,
    DATA_USAGE_UPLOAD_BYTES,
    DEVICE_ADBLOCK_ENABLED,
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
    DEVICE_IS_GUEST,
    DEVICE_LAST_ACTIVE_TIMESTAMP,
    DEVICE_PAUSED,
    DEVICE_PRIORITIZED,
    DEVICE_PRIVATE,
    DEVICE_RX_BANDWIDTH,
    DEVICE_RX_BITRATE,
    DEVICE_RX_MCS,
    DEVICE_RX_NSS,
    DEVICE_SIGNAL_AVG,
    DEVICE_SIGNAL_STRENGTH,
    DEVICE_TX_BANDWIDTH,
    DEVICE_TX_BITRATE,
    DEVICE_TX_MCS,
    DEVICE_TX_NSS,
    DEVICE_WIFI_GENERATION,
    DEVICE_WIRELESS,
    DIAGNOSTICS_DNS_LATENCY,
    DIAGNOSTICS_GATEWAY_LATENCY,
    DIAGNOSTICS_INTERNET_LATENCY,
    DIAGNOSTICS_LAST_RUN_TIMESTAMP,
    DNS_CONFIG_INFO,
    EERO_BACKUP_CONNECTION,
    EERO_CONNECTED_CLIENTS,
    EERO_CONNECTED_WIRED_CLIENTS,
    EERO_CONNECTED_WIRELESS_CLIENTS,
    EERO_DATA_USAGE_BYTES,
    EERO_HEARTBEAT_OK,
    EERO_INFO,
    EERO_IS_GATEWAY,
    EERO_LAST_REBOOT,
    EERO_LED_BRIGHTNESS,
    EERO_LED_ON,
    EERO_MEMORY_USAGE,
    EERO_MESH_QUALITY,
    EERO_NIGHTLIGHT_AMBIENT_ENABLED,
    EERO_NIGHTLIGHT_BRIGHTNESS,
    EERO_NIGHTLIGHT_ENABLED,
    EERO_NIGHTLIGHT_SCHEDULE_ENABLED,
    EERO_OS_VERSION_INFO,
    EERO_PROVIDES_WIFI,
    EERO_STATUS,
    EERO_TEMPERATURE,
    EERO_UP,
    EERO_UPDATE_AVAILABLE,
    EERO_UPTIME_SECONDS,
    EERO_WIRED,
    EERO_WIRED_INTERNET,
    ETHERNET_PORT_CARRIER,
    ETHERNET_PORT_INFO,
    ETHERNET_PORT_IS_WAN,
    ETHERNET_PORT_POWER_SAVING,
    ETHERNET_PORT_SPEED,
    EXPORTER_API_REQUESTS,
    EXPORTER_COLLECTION_INTERVAL,
    EXPORTER_LAST_COLLECTION_TIMESTAMP,
    EXPORTER_SCRAPE_DURATION,
    EXPORTER_SCRAPE_ERRORS,
    EXPORTER_SCRAPE_SUCCESS,
    GUEST_NETWORK_ACCESS_DURATION_ENABLED,
    GUEST_NETWORK_CONNECTED_CLIENTS,
    GUEST_NETWORK_INFO,
    HEALTH_STATUS,
    INSIGHTS_ADBLOCK_TOTAL,
    INSIGHTS_BLOCKED_TOTAL,
    INSIGHTS_INSPECTED_TOTAL,
    NETWORK_AD_BLOCK_ENABLED,
    NETWORK_AUTO_UPDATE_ENABLED,
    NETWORK_BACKUP_INTERNET_ENABLED,
    NETWORK_BAND_STEERING_ENABLED,
    NETWORK_BLACKLISTED_DEVICES_COUNT,
    NETWORK_CLIENTS_COUNT,
    NETWORK_CUSTOM_DNS_ENABLED,
    NETWORK_DATA_USAGE_BYTES,
    NETWORK_DHCP_RESERVATIONS_COUNT,
    NETWORK_DNS_CACHING_ENABLED,
    NETWORK_DNS_SERVER_COUNT,
    NETWORK_EEROS_COUNT,
    NETWORK_GUEST_ENABLED,
    NETWORK_INFO,
    NETWORK_IPV6_ENABLED,
    NETWORK_PORT_FORWARDS_COUNT,
    NETWORK_POWER_SAVING_ENABLED,
    NETWORK_PREMIUM_ENABLED,
    NETWORK_SQM_ENABLED,
    NETWORK_STATUS,
    NETWORK_THREAD_ENABLED,
    NETWORK_UPDATES_AVAILABLE,
    NETWORK_UPNP_ENABLED,
    NETWORK_WPA3_ENABLED,
    PORT_FORWARD_ENABLED,
    PORT_FORWARD_INFO,
    PROFILE_DEVICES_COUNT,
    PROFILE_PAUSED,
    SPEED_DOWNLOAD_MBPS,
    SPEED_TEST_TIMESTAMP,
    SPEED_UPLOAD_MBPS,
    SQM_DOWNLOAD_BANDWIDTH,
    SQM_UPLOAD_BANDWIDTH,
    THREAD_BORDER_ROUTER,
    THREAD_DEVICE_COUNT,
)

_LOGGER = logging.getLogger(__name__)


def _extract_id_from_url(url: Any) -> str:
    """Extract ID from an API URL."""
    if not url:
        return ""
    url_str = str(url)
    parts = url_str.rstrip("/").split("/")
    return parts[-1] if parts else ""


def _parse_signal_strength(signal_str: str | None) -> float | None:
    """Parse signal strength string to float."""
    if not signal_str:
        return None
    try:
        return float(signal_str.replace(" dBm", "").strip())
    except (ValueError, AttributeError):
        return None


def _parse_bitrate(bitrate_str: str | None) -> float | None:
    """Parse bitrate string to Mbps float."""
    if not bitrate_str:
        return None
    try:
        cleaned = bitrate_str.replace(" Mbit/s", "").replace(" Mbps", "").strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return None


def _parse_speed_mbps(speed_str: str | None) -> float | None:
    """Parse ethernet speed string to Mbps."""
    if not speed_str:
        return None
    try:
        speed_str = speed_str.strip().upper()
        if "GBPS" in speed_str or speed_str.endswith("G"):
            num = float(speed_str.replace("GBPS", "").replace("G", "").strip())
            return num * 1000
        if "MBPS" in speed_str or speed_str.endswith("M"):
            num = float(speed_str.replace("MBPS", "").replace("M", "").strip())
            return num
        return float(speed_str)
    except (ValueError, AttributeError):
        return None


def _parse_timestamp(timestamp_str: str | None) -> float | None:
    """Parse ISO timestamp string to Unix epoch."""
    if not timestamp_str:
        return None
    try:
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


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
        include_devices: bool = True,
        include_profiles: bool = True,
        include_premium: bool = True,
        include_ethernet: bool = True,
        include_thread: bool = True,
        include_port_forwards: bool = True,
        include_reservations: bool = True,
        include_blacklist: bool = True,
        include_diagnostics: bool = True,
        include_insights: bool = True,
        include_data_usage: bool = True,
        timeout: int = 30,
        cookie_file: str | None = None,
    ) -> None:
        """Initialize the collector.

        Args:
            include_devices: Whether to collect device metrics
            include_profiles: Whether to collect profile metrics
            include_premium: Whether to collect premium features metrics
            include_ethernet: Whether to collect ethernet port metrics
            include_thread: Whether to collect Thread network metrics
            include_port_forwards: Whether to collect port forward metrics
            include_reservations: Whether to collect DHCP reservation metrics
            include_blacklist: Whether to collect blacklist metrics
            include_diagnostics: Whether to collect diagnostics metrics
            include_insights: Whether to collect insights metrics
            include_data_usage: Whether to collect data usage metrics
            timeout: Request timeout in seconds
            cookie_file: Path to session/cookie file for authentication
        """
        self._include_devices = include_devices
        self._include_profiles = include_profiles
        self._include_premium = include_premium
        self._include_ethernet = include_ethernet
        self._include_thread = include_thread
        self._include_port_forwards = include_port_forwards
        self._include_reservations = include_reservations
        self._include_blacklist = include_blacklist
        self._include_diagnostics = include_diagnostics
        self._include_insights = include_insights
        self._include_data_usage = include_data_usage
        self._timeout = timeout
        self._cookie_file = cookie_file
        self._last_collection_time: float = 0
        self._cached_data: dict[str, Any] = {}
        self._is_premium: bool = False
        self._networks_count: int = 0
        self._collection_interval: int = 60  # Default, can be overridden

    async def collect(self) -> bool:
        """Collect metrics from the eero API."""
        start_time = time.monotonic()
        success = False

        try:
            async with EeroClient(
                timeout=self._timeout,
                cookie_file=self._cookie_file,
            ) as client:
                networks = await client.get_networks()
                EXPORTER_API_REQUESTS.labels(endpoint="networks", status="success").inc()

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
            EXPORTER_SCRAPE_SUCCESS.set(1)  # Deprecated, kept for compatibility

        except EeroAuthError as e:
            _LOGGER.error(f"Authentication error: {e}")
            EXPORTER_SCRAPE_ERRORS.labels(error_type="auth").inc()
            EERO_UP.set(0)
            EXPORTER_SCRAPE_SUCCESS.set(0)

        except EeroAPIError as e:
            _LOGGER.error(f"API error during collection: {e}")
            EXPORTER_SCRAPE_ERRORS.labels(error_type="api").inc()
            EERO_UP.set(0)
            if not self._cached_data:
                EXPORTER_SCRAPE_SUCCESS.set(0)

        except Exception as e:
            _LOGGER.error(f"Unexpected error during collection: {e}", exc_info=True)
            EXPORTER_SCRAPE_ERRORS.labels(error_type="unknown").inc()
            EERO_UP.set(0)
            EXPORTER_SCRAPE_SUCCESS.set(0)

        finally:
            duration = time.monotonic() - start_time
            EXPORTER_SCRAPE_DURATION.set(duration)
            self._last_collection_time = time.time()
            # Set timestamp metrics for cache monitoring
            EXPORTER_LAST_COLLECTION_TIMESTAMP.set(self._last_collection_time)
            EXPORTER_COLLECTION_INTERVAL.set(self._collection_interval)
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

        try:
            network_details = await client.get_network(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="network", status="success").inc()
        except EeroAPIError as e:
            _LOGGER.warning(f"Failed to get network details: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="network", status="error").inc()
            network_details = network_data

        # Extract status - may be nested {"status": "online"} or just "online"
        raw_status = network_details.get("status", "unknown")
        if isinstance(raw_status, dict):
            status_str = raw_status.get("status", "unknown")
        else:
            status_str = str(raw_status)

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

        # Extract public_ip - may be in public_ip or wan_ip
        public_ip = network_details.get("public_ip") or network_details.get("wan_ip")

        NETWORK_INFO.labels(network_id=network_id).info(
            {
                "name": network_name,
                "status": status_str,
                "isp": isp_name or "unknown",
                "public_ip": public_ip or "unknown",
                "wan_type": network_details.get("wan_type") or "unknown",
                "gateway_ip": network_details.get("gateway_ip") or "unknown",
            }
        )

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
            if "date" in speed:
                try:
                    from datetime import datetime

                    dt = datetime.fromisoformat(speed["date"].replace("Z", "+00:00"))
                    SPEED_TEST_TIMESTAMP.labels(network_id=network_id).set(dt.timestamp())
                except (ValueError, TypeError):
                    pass
                except Exception:
                    _LOGGER.warning("Failed to set SPEED_TEST_TIMESTAMP for network %s", network_id)

        await self._collect_network_feature_flags(client, network_id, network_name, network_details)
        await self._collect_sqm_metrics(client, network_id)
        await self._collect_eero_metrics(client, network_id, network_name)

        if self._include_devices:
            await self._collect_device_metrics(client, network_id, network_name)

        if self._include_data_usage:
            await self._collect_data_usage_metrics(client, network_id, network_details)

        if self._include_profiles:
            await self._collect_profile_metrics(client, network_id)

        if self._include_premium:
            await self._collect_premium_metrics(client, network_id, network_name)

        if self._include_thread:
            await self._collect_thread_metrics(client, network_id)

        if self._include_port_forwards:
            await self._collect_port_forward_metrics(client, network_id, network_name)

        if self._include_reservations:
            await self._collect_reservation_metrics(client, network_id, network_name)

        if self._include_blacklist:
            await self._collect_blacklist_metrics(client, network_id, network_name)

        if self._include_diagnostics:
            await self._collect_diagnostics_metrics(client, network_id)

        if self._include_insights:
            await self._collect_insights_metrics(client, network_id)

    async def _collect_eero_metrics(
        self, client: EeroClient, network_id: str, network_name: str
    ) -> None:
        """Collect metrics for eero devices."""
        try:
            eeros = await client.get_eeros(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="eeros", status="success").inc()
        except EeroAPIError as e:
            _LOGGER.warning(f"Failed to get eeros: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="eeros", status="error").inc()
            return

        NETWORK_EEROS_COUNT.labels(network_id=network_id, name=network_name).set(len(eeros))

        # Count eeros with updates available
        updates_count = sum(1 for e in eeros if e.get("update_available", False))
        NETWORK_UPDATES_AVAILABLE.labels(network_id=network_id, name=network_name).set(
            updates_count
        )

        for eero in eeros:
            eero_url = eero.get("url", "")
            eero_id = _extract_id_from_url(eero_url)
            location = eero.get("location", "Unknown")
            model = eero.get("model", "Unknown")
            serial = eero.get("serial", "Unknown")
            status = eero.get("status", "").lower()

            if not eero_id:
                continue

            os_version = eero.get("os_version") or eero.get("os") or "unknown"

            EERO_INFO.labels(network_id=network_id, eero_id=eero_id, serial=serial).info(
                {
                    "location": location,
                    "model": model,
                    "model_number": eero.get("model_number") or "unknown",
                    "os_version": os_version,
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
            # API may return: "connected", "online", "green", "up", "active", or boolean-like values
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
            EERO_IS_GATEWAY.labels(network_id=network_id, eero_id=eero_id, location=location).set(
                is_gateway
            )

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

            uptime = _coerce_numeric(eero.get("uptime"), field_name="uptime")
            if uptime is not None:
                try:
                    EERO_UPTIME_SECONDS.labels(
                        network_id=network_id, eero_id=eero_id, location=location
                    ).set(uptime)
                except Exception:
                    _LOGGER.warning("Failed to set EERO_UPTIME_SECONDS for eero %s", eero_id)

            led_on = eero.get("led_on")
            if led_on is not None:
                EERO_LED_ON.labels(network_id=network_id, eero_id=eero_id, location=location).set(
                    1 if led_on else 0
                )

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
                EERO_WIRED.labels(network_id=network_id, eero_id=eero_id, location=location).set(
                    1 if wired else 0
                )

            # Try multiple field names for memory usage
            memory_usage = _coerce_numeric(eero.get("memory_usage"), field_name="memory_usage")
            if memory_usage is None:
                # Check nested structures
                resources = eero.get("resources", {})
                if isinstance(resources, dict):
                    memory_usage = _coerce_numeric(
                        resources.get("memory_usage") or resources.get("memory_percent"),
                        field_name="memory_usage",
                    )
                hardware = eero.get("hardware", {})
                if isinstance(hardware, dict) and memory_usage is None:
                    memory_usage = _coerce_numeric(
                        hardware.get("memory_usage") or hardware.get("memory_percent"),
                        field_name="memory_usage",
                    )
            if memory_usage is not None:
                try:
                    EERO_MEMORY_USAGE.labels(
                        network_id=network_id, eero_id=eero_id, location=location
                    ).set(memory_usage)
                except Exception:
                    _LOGGER.warning("Failed to set EERO_MEMORY_USAGE for eero %s", eero_id)

            # Try multiple field names for temperature
            temperature = _coerce_numeric(eero.get("temperature"), field_name="temperature")
            if temperature is None:
                # Check nested structures
                resources = eero.get("resources", {})
                if isinstance(resources, dict):
                    temperature = _coerce_numeric(
                        resources.get("temperature") or resources.get("temp_celsius"),
                        field_name="temperature",
                    )
                hardware = eero.get("hardware", {})
                if isinstance(hardware, dict) and temperature is None:
                    temperature = _coerce_numeric(
                        hardware.get("temperature") or hardware.get("temp_celsius"),
                        field_name="temperature",
                    )
            if temperature is not None:
                try:
                    EERO_TEMPERATURE.labels(
                        network_id=network_id, eero_id=eero_id, location=location
                    ).set(temperature)
                except Exception:
                    _LOGGER.warning("Failed to set EERO_TEMPERATURE for eero %s", eero_id)

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

            backup_connection = eero.get("backup_connection")
            if backup_connection is not None:
                try:
                    EERO_BACKUP_CONNECTION.labels(
                        network_id=network_id, eero_id=eero_id, location=location
                    ).set(1 if backup_connection else 0)
                except Exception:
                    _LOGGER.warning("Failed to set EERO_BACKUP_CONNECTION for eero %s", eero_id)

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

                nl_ambient = nightlight.get("ambient_light_enabled")
                if nl_ambient is not None:
                    try:
                        EERO_NIGHTLIGHT_AMBIENT_ENABLED.labels(
                            network_id=network_id, eero_id=eero_id, location=location
                        ).set(1 if nl_ambient else 0)
                    except Exception:
                        _LOGGER.warning(
                            "Failed to set EERO_NIGHTLIGHT_AMBIENT_ENABLED for eero %s", eero_id
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

    async def _collect_device_metrics(
        self, client: EeroClient, network_id: str, network_name: str
    ) -> None:
        """Collect metrics for client devices."""
        try:
            devices = await client.get_devices(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="devices", status="success").inc()
        except EeroAPIError as e:
            _LOGGER.warning(f"Failed to get devices: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="devices", status="error").inc()
            return

        connected_count = sum(1 for d in devices if d.get("connected", False))
        NETWORK_CLIENTS_COUNT.labels(network_id=network_id, name=network_name).set(connected_count)

        # Count guest network clients
        guest_count = sum(
            1 for d in devices if d.get("connected", False) and d.get("is_guest", False)
        )
        GUEST_NETWORK_CONNECTED_CLIENTS.labels(network_id=network_id, name=network_name).set(
            guest_count
        )

        for device in devices:
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

            DEVICE_INFO.labels(network_id=network_id, device_id=device_id, mac=mac).info(
                {
                    "name": name,
                    "manufacturer": manufacturer,
                    "ip": device.get("ip") or "unknown",
                    "device_type": device_type,
                    "hostname": device.get("hostname") or "unknown",
                    "connection_type": connection_type,
                    "source_eero": source_eero,
                }
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

                signal_avg = _parse_signal_strength(connectivity.get("signal_avg"))
                if signal_avg is not None:
                    try:
                        DEVICE_SIGNAL_AVG.labels(
                            network_id=network_id,
                            device_id=device_id,
                            name=name,
                            manufacturer=manufacturer,
                            band=band,
                            source_eero=source_eero,
                        ).set(signal_avg)
                    except Exception:
                        _LOGGER.warning("Failed to set DEVICE_SIGNAL_AVG for device %s", device_id)

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
                            "Failed to set DEVICE_CONNECTION_SCORE_BARS for device %s", device_id
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
                        _LOGGER.warning("Failed to set DEVICE_FREQUENCY for device %s", device_id)

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
                        _LOGGER.warning("Failed to set DEVICE_RX_BITRATE for device %s", device_id)

                rx_rate_info = connectivity.get("rx_rate_info", {})
                if rx_rate_info and isinstance(rx_rate_info, dict):
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

                    rx_bw = rx_rate_info.get("bandwidth")
                    if rx_bw is not None:
                        DEVICE_RX_BANDWIDTH.labels(
                            network_id=network_id,
                            device_id=device_id,
                            name=name,
                            band=band,
                        ).set(rx_bw)

                    if rx_bitrate is None:
                        rx_rate_bitrate = rx_rate_info.get("bitrate")
                        if rx_rate_bitrate is not None:
                            DEVICE_RX_BITRATE.labels(
                                network_id=network_id,
                                device_id=device_id,
                                name=name,
                                manufacturer=manufacturer,
                                band=band,
                                source_eero=source_eero,
                            ).set(rx_rate_bitrate)

                tx_rate_info = connectivity.get("tx_rate_info", {})
                if tx_rate_info and isinstance(tx_rate_info, dict):
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

                    tx_bw = tx_rate_info.get("bandwidth")
                    if tx_bw is not None:
                        DEVICE_TX_BANDWIDTH.labels(
                            network_id=network_id,
                            device_id=device_id,
                            name=name,
                            band=band,
                        ).set(tx_bw)

                    tx_bitrate = tx_rate_info.get("bitrate")
                    if tx_bitrate is not None:
                        DEVICE_TX_BITRATE.labels(
                            network_id=network_id,
                            device_id=device_id,
                            name=name,
                            manufacturer=manufacturer,
                            band=band,
                            source_eero=source_eero,
                        ).set(tx_bitrate)

            channel = device.get("channel")
            if channel is not None:
                DEVICE_CHANNEL.labels(
                    network_id=network_id,
                    device_id=device_id,
                    name=name,
                    band=band,
                    source_eero=source_eero,
                ).set(channel)

            prioritized = device.get("prioritized") or device.get("priority")
            if prioritized is not None:
                DEVICE_PRIORITIZED.labels(
                    network_id=network_id,
                    device_id=device_id,
                    name=name,
                    manufacturer=manufacturer,
                    device_type=device_type,
                ).set(1 if prioritized else 0)

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

            # Ad blocking per device
            adblock_enabled = device.get("ad_block") or device.get("ad_blocking")
            if adblock_enabled is not None:
                DEVICE_ADBLOCK_ENABLED.labels(
                    network_id=network_id,
                    device_id=device_id,
                    name=name,
                    manufacturer=manufacturer,
                ).set(1 if adblock_enabled else 0)

    async def _collect_profile_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect metrics for profiles."""
        try:
            profiles = await client.get_profiles(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="profiles", status="success").inc()
        except EeroAPIError as e:
            _LOGGER.warning(f"Failed to get profiles: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="profiles", status="error").inc()
            return

        for profile in profiles:
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

    async def _collect_data_usage_metrics(
        self,
        client: EeroClient,
        network_id: str,
        network_details: dict[str, Any],
    ) -> None:
        """Collect network, device, and eero-node data usage metrics.

        Issues one request per period (day/week/month) for the network total,
        plus per-device and per-eero breakdowns when device metrics are
        enabled. Each request is independently guarded so a partial failure
        (e.g. an account without data_usage support) degrades gracefully.
        """
        timezone = _get_timezone(network_details.get("timezone"))
        for period in ("day", "week", "month"):
            period_label, cadence, payload = _data_usage_period_payload(period, timezone)

            try:
                usage = await client.get_data_usage(network_id, payload)
                EXPORTER_API_REQUESTS.labels(
                    endpoint=f"data_usage_{period_label}", status="success"
                ).inc()
                self._set_network_data_usage(network_id, period_label, cadence, usage)
            except EeroAPIError as e:
                _LOGGER.debug(f"Failed to get {period_label} data usage: {e}")
                EXPORTER_API_REQUESTS.labels(
                    endpoint=f"data_usage_{period_label}", status="error"
                ).inc()

            if not self._include_devices:
                continue

            try:
                device_usage = await client.get_data_usage(network_id, payload, "devices")
                EXPORTER_API_REQUESTS.labels(
                    endpoint=f"data_usage_devices_{period_label}", status="success"
                ).inc()
                self._set_device_data_usage(network_id, period_label, cadence, device_usage)
            except EeroAPIError as e:
                _LOGGER.debug(f"Failed to get {period_label} device data usage: {e}")
                EXPORTER_API_REQUESTS.labels(
                    endpoint=f"data_usage_devices_{period_label}", status="error"
                ).inc()

            try:
                eero_usage = await client.get_data_usage(network_id, payload, "eeros")
                EXPORTER_API_REQUESTS.labels(
                    endpoint=f"data_usage_eeros_{period_label}", status="success"
                ).inc()
                self._set_eero_data_usage(network_id, period_label, cadence, eero_usage)
            except EeroAPIError as e:
                _LOGGER.debug(f"Failed to get {period_label} eero data usage: {e}")
                EXPORTER_API_REQUESTS.labels(
                    endpoint=f"data_usage_eeros_{period_label}", status="error"
                ).inc()

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
        usage: dict[str, Any],
    ) -> None:
        """Set per-device data usage metrics from a data_usage response."""
        values = usage.get("values", [])
        if not isinstance(values, list):
            return

        for device in values:
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

    def _set_eero_data_usage(
        self,
        network_id: str,
        period: str,
        cadence: str,
        usage: dict[str, Any],
    ) -> None:
        """Set per-eero-node data usage metrics from a data_usage response."""
        values = usage.get("values", [])
        if not isinstance(values, list):
            return

        for eero in values:
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

        dns_caching = network_details.get("dns_caching")
        settings = network_details.get("settings", {})
        if dns_caching is None and isinstance(settings, dict):
            dns_caching = settings.get("dns_caching")
        if dns_caching is not None:
            NETWORK_DNS_CACHING_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if dns_caching else 0
            )

        power_saving = network_details.get("power_saving")
        if power_saving is not None:
            NETWORK_POWER_SAVING_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if power_saving else 0
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

            access_duration = guest_network.get("access_duration_enabled")
            if access_duration is not None:
                GUEST_NETWORK_ACCESS_DURATION_ENABLED.labels(
                    network_id=network_id, name=network_name
                ).set(1 if access_duration else 0)

        # DNS configuration metrics
        custom_dns = network_details.get("custom_dns", [])
        dns_caching = network_details.get("dns_caching", False)

        if custom_dns and isinstance(custom_dns, list):
            NETWORK_CUSTOM_DNS_ENABLED.labels(network_id=network_id, name=network_name).set(1)
            NETWORK_DNS_SERVER_COUNT.labels(network_id=network_id, name=network_name).set(
                len(custom_dns)
            )
            DNS_CONFIG_INFO.labels(network_id=network_id).info(
                {
                    "mode": "custom",
                    "primary_dns": custom_dns[0] if custom_dns else "auto",
                    "secondary_dns": custom_dns[1] if len(custom_dns) > 1 else "",
                    "caching_enabled": str(dns_caching).lower(),
                }
            )
        else:
            NETWORK_CUSTOM_DNS_ENABLED.labels(network_id=network_id, name=network_name).set(0)
            NETWORK_DNS_SERVER_COUNT.labels(network_id=network_id, name=network_name).set(0)
            DNS_CONFIG_INFO.labels(network_id=network_id).info(
                {
                    "mode": "auto",
                    "primary_dns": "auto",
                    "secondary_dns": "",
                    "caching_enabled": str(dns_caching).lower(),
                }
            )

        # Ad blocking metrics (network-wide)
        ad_block = network_details.get("ad_block") or network_details.get("ad_blocking")
        if ad_block is not None:
            NETWORK_AD_BLOCK_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if ad_block else 0
            )

        # Auto-update setting
        auto_update = network_details.get("auto_update") or network_details.get(
            "auto_update_enabled"
        )
        if auto_update is not None:
            NETWORK_AUTO_UPDATE_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if auto_update else 0
            )

    async def _collect_sqm_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect SQM (Smart Queue Management) metrics."""
        try:
            sqm_settings = await client.get_sqm_settings(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="sqm", status="success").inc()

            upload_bw = _coerce_numeric(
                sqm_settings.get("upload_bandwidth"), field_name="upload_bandwidth"
            )
            if upload_bw is not None:
                try:
                    SQM_UPLOAD_BANDWIDTH.labels(network_id=network_id).set(upload_bw)
                except Exception:
                    _LOGGER.warning("Failed to set SQM_UPLOAD_BANDWIDTH for network %s", network_id)

            download_bw = _coerce_numeric(
                sqm_settings.get("download_bandwidth"), field_name="download_bandwidth"
            )
            if download_bw is not None:
                try:
                    SQM_DOWNLOAD_BANDWIDTH.labels(network_id=network_id).set(download_bw)
                except Exception:
                    _LOGGER.warning(
                        "Failed to set SQM_DOWNLOAD_BANDWIDTH for network %s", network_id
                    )

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get SQM settings: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="sqm", status="error").inc()

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

            ETHERNET_PORT_INFO.labels(
                network_id=network_id, eero_id=eero_id, port_number=port_num_str
            ).info(
                {
                    "port_name": port_name,
                    "original_speed": port_status.get("original_speed") or "unknown",
                    "derated_reason": port_status.get("derated_reason") or "none",
                }
            )

            has_carrier = port_status.get("hasCarrier")
            if has_carrier is not None:
                ETHERNET_PORT_CARRIER.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                    port_number=port_num_str,
                    port_name=port_name,
                ).set(1 if has_carrier else 0)

            speed = _parse_speed_mbps(port_status.get("speed"))
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

            power_saving = port_status.get("power_saving")
            if power_saving is not None:
                ETHERNET_PORT_POWER_SAVING.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                    port_number=port_num_str,
                    port_name=port_name,
                ).set(1 if power_saving else 0)

    async def _collect_premium_metrics(
        self, client: EeroClient, network_id: str, network_name: str
    ) -> None:
        """Collect premium features metrics (Eero Plus)."""
        try:
            is_premium = await client.is_premium(network_id)
            self._is_premium = is_premium
            NETWORK_PREMIUM_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if is_premium else 0
            )
            EXPORTER_API_REQUESTS.labels(endpoint="premium", status="success").inc()
        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get premium status: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="premium", status="error").inc()
            return

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
        end = now
        start = now - timedelta(hours=1)
        payload = {
            "start": start.replace(tzinfo=None).isoformat() + "Z",
            "end": end.replace(tzinfo=None).isoformat() + "Z",
            "cadence": "hourly",
            "timezone": "UTC",
        }

        try:
            usage = await client.get_data_usage(network_id, payload)
            EXPORTER_API_REQUESTS.labels(endpoint="current_usage", status="success").inc()

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

            totals = usage.get("totals", {})
            if isinstance(totals, dict):
                active = totals.get("active_clients") or totals.get("active_client_count")
                if active is not None:
                    try:
                        DATA_USAGE_ACTIVE_CLIENTS.labels(network_id=network_id).set(float(active))
                    except (TypeError, ValueError):
                        pass

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get current usage totals: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="current_usage", status="error").inc()

        if not self._include_devices:
            return

        try:
            device_usage = await client.get_data_usage(network_id, payload, "devices")
            EXPORTER_API_REQUESTS.labels(endpoint="current_usage_devices", status="success").inc()

            values = device_usage.get("values", [])
            if not isinstance(values, list):
                return

            for device in values:
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
                for series in device.get("series", []):
                    if not isinstance(series, dict):
                        continue
                    direction = str(series.get("type") or series.get("direction") or "").lower()
                    total = _series_sum(series)
                    if total is None:
                        continue
                    if direction == "download":
                        DEVICE_DATA_USAGE_DOWNLOAD_BYTES.labels(**labels).set(total)
                    elif direction == "upload":
                        DEVICE_DATA_USAGE_UPLOAD_BYTES.labels(**labels).set(total)

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get current device usage: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="current_usage_devices", status="error").inc()

    async def _collect_backup_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect backup network metrics (Eero Plus feature)."""
        try:
            backup_config = await client.get_backup_network(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="backup", status="success").inc()

            enabled = backup_config.get("enabled")
            if enabled is not None:
                BACKUP_ENABLED.labels(network_id=network_id).set(1 if enabled else 0)

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get backup config: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="backup", status="error").inc()
            return

        try:
            backup_status = await client.get_backup_status(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="backup_status", status="success").inc()

            active = backup_status.get("active") or backup_status.get("using_backup")
            if active is not None:
                BACKUP_ACTIVE.labels(network_id=network_id).set(1 if active else 0)

            connected = backup_status.get("connected")
            if connected is not None:
                BACKUP_CONNECTED.labels(network_id=network_id).set(1 if connected else 0)

            signal = backup_status.get("signal_strength")
            if signal is not None:
                BACKUP_SIGNAL_STRENGTH.labels(network_id=network_id).set(signal)

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get backup status: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="backup_status", status="error").inc()

    async def _collect_thread_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect Thread network metrics."""
        try:
            thread_data = await client.get_thread(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="thread", status="success").inc()

            if not thread_data:
                return

            devices = thread_data.get("devices", [])
            if isinstance(devices, list):
                THREAD_DEVICE_COUNT.labels(network_id=network_id).set(len(devices))

            border_routers = thread_data.get("border_routers", [])
            if isinstance(border_routers, list):
                THREAD_BORDER_ROUTER.labels(network_id=network_id).set(len(border_routers))

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get Thread data: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="thread", status="error").inc()

    async def _collect_port_forward_metrics(
        self, client: EeroClient, network_id: str, network_name: str
    ) -> None:
        """Collect port forwarding metrics."""
        try:
            forwards = await client.get_forwards(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="forwards", status="success").inc()

            NETWORK_PORT_FORWARDS_COUNT.labels(network_id=network_id, name=network_name).set(
                len(forwards)
            )

            for forward in forwards:
                if not isinstance(forward, dict):
                    continue

                forward_url = forward.get("url", "")
                forward_id = _extract_id_from_url(forward_url) or str(hash(str(forward)))[:8]

                port = str(forward.get("port", forward.get("external_port", "")))
                protocol = forward.get("protocol", "tcp").lower()
                enabled = forward.get("enabled", True)

                PORT_FORWARD_INFO.labels(network_id=network_id, forward_id=forward_id).info(
                    {
                        "port": port,
                        "internal_port": str(forward.get("internal_port", port)),
                        "protocol": protocol,
                        "ip_address": forward.get("ip_address", ""),
                        "nickname": forward.get("nickname", ""),
                    }
                )

                PORT_FORWARD_ENABLED.labels(
                    network_id=network_id,
                    forward_id=forward_id,
                    port=port,
                    protocol=protocol,
                ).set(1 if enabled else 0)

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get port forwards: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="forwards", status="error").inc()

    async def _collect_reservation_metrics(
        self, client: EeroClient, network_id: str, network_name: str
    ) -> None:
        """Collect DHCP reservation metrics."""
        try:
            reservations = await client.get_reservations(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="reservations", status="success").inc()

            NETWORK_DHCP_RESERVATIONS_COUNT.labels(network_id=network_id, name=network_name).set(
                len(reservations)
            )

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get DHCP reservations: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="reservations", status="error").inc()

    async def _collect_blacklist_metrics(
        self, client: EeroClient, network_id: str, network_name: str
    ) -> None:
        """Collect blacklist metrics."""
        try:
            blacklist = await client.get_blacklist(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="blacklist", status="success").inc()

            NETWORK_BLACKLISTED_DEVICES_COUNT.labels(network_id=network_id, name=network_name).set(
                len(blacklist)
            )

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get blacklist: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="blacklist", status="error").inc()

    async def _collect_diagnostics_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect diagnostics metrics."""
        try:
            diagnostics = await client.get_diagnostics(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="diagnostics", status="success").inc()

            if not diagnostics:
                _LOGGER.debug("Diagnostics response is empty")
                return

            _LOGGER.debug(f"Diagnostics keys: {list(diagnostics.keys())}")

            # Helper to extract latency from various possible structures
            def _extract_latency(data: dict, *keys: str) -> float | None:
                for key in keys:
                    if key in data:
                        val = data[key]
                        if isinstance(val, (int, float)):
                            return float(val)
                        if isinstance(val, dict):
                            for nested_key in ("latency_ms", "latency", "ms", "value"):
                                if nested_key in val and isinstance(val[nested_key], (int, float)):
                                    return float(val[nested_key])
                return None

            # Internet latency - try multiple field patterns
            internet_latency = _extract_latency(
                diagnostics,
                "internet_latency_ms",
                "internet_latency",
                "internet",
                "wan_latency_ms",
                "wan_latency",
            )
            if internet_latency is not None:
                DIAGNOSTICS_INTERNET_LATENCY.labels(network_id=network_id).set(internet_latency)

            # DNS latency
            dns_latency = _extract_latency(
                diagnostics,
                "dns_latency_ms",
                "dns_latency",
                "dns",
            )
            if dns_latency is not None:
                DIAGNOSTICS_DNS_LATENCY.labels(network_id=network_id).set(dns_latency)

            # Gateway latency
            gateway_latency = _extract_latency(
                diagnostics,
                "gateway_latency_ms",
                "gateway_latency",
                "gateway",
                "router_latency_ms",
            )
            if gateway_latency is not None:
                DIAGNOSTICS_GATEWAY_LATENCY.labels(network_id=network_id).set(gateway_latency)

            # Last run timestamp
            last_run = (
                diagnostics.get("last_run")
                or diagnostics.get("timestamp")
                or diagnostics.get("updated_at")
            )
            if last_run:
                last_run_ts = _parse_timestamp(last_run)
                if last_run_ts is not None:
                    DIAGNOSTICS_LAST_RUN_TIMESTAMP.labels(network_id=network_id).set(last_run_ts)

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get diagnostics: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="diagnostics", status="error").inc()

    async def _collect_insights_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect insights time-series metrics for all three insight types.

        Fans out to the insights endpoint once per type (adblock, blocked,
        inspected) using a 24-hour trailing window.  Each call is independently
        guarded so a 403 (insufficient subscription) on one type does not
        prevent the others from being collected.
        """
        now = datetime.now(UTC)
        end_str = now.replace(tzinfo=None).isoformat() + "Z"
        start_str = (now - timedelta(hours=24)).replace(tzinfo=None).isoformat() + "Z"

        insight_metrics = {
            "adblock": INSIGHTS_ADBLOCK_TOTAL,
            "blocked": INSIGHTS_BLOCKED_TOTAL,
            "inspected": INSIGHTS_INSPECTED_TOTAL,
        }

        for insight_type, metric in insight_metrics.items():
            try:
                data = await client.get_insights(
                    network_id,
                    start=start_str,
                    end=end_str,
                    insight_type=insight_type,
                    cadence="daily",
                )
                EXPORTER_API_REQUESTS.labels(
                    endpoint=f"insights_{insight_type}", status="success"
                ).inc()

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
                        if total is None:
                            total_raw = data.get("totals", {})
                            if isinstance(total_raw, dict):
                                raw = total_raw.get(insight_type) or total_raw.get("total")
                                try:
                                    total = float(raw) if raw is not None else None
                                except (TypeError, ValueError):
                                    total = None
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

            except EeroAPIError as e:
                _LOGGER.debug(f"Failed to get {insight_type} insights: {e}")
                EXPORTER_API_REQUESTS.labels(
                    endpoint=f"insights_{insight_type}", status="error"
                ).inc()
