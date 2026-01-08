"""Collector module for gathering eero metrics."""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from .eero_adapter import EeroAPIError, EeroAuthError, EeroClient
from .metrics import (  # Device metrics; Device wireless metrics; Device additional metrics; Eero device metrics; Eero hardware metrics; Ethernet port metrics; Nightlight metrics; Network metrics; Network feature flags; Network transfer metrics; SQM metrics; Backup metrics; Activity metrics; Thread metrics; Profile metrics; Speed metrics
    ACTIVITY_ACTIVE_CLIENTS,
    ACTIVITY_CATEGORY_BYTES,
    ACTIVITY_DOWNLOAD_BYTES,
    ACTIVITY_UPLOAD_BYTES,
    BACKUP_ACTIVE,
    BACKUP_CONNECTED,
    BACKUP_DATA_USED,
    BACKUP_ENABLED,
    BACKUP_SIGNAL_STRENGTH,
    DEVICE_ACTIVITY_DOWNLOAD_BYTES,
    DEVICE_ACTIVITY_UPLOAD_BYTES,
    DEVICE_BLOCKED,
    DEVICE_CHANNEL,
    DEVICE_CONNECTED,
    DEVICE_CONNECTED_TO_GATEWAY,
    DEVICE_CONNECTION_SCORE,
    DEVICE_CONNECTION_SCORE_BARS,
    DEVICE_DOWNLOAD_BYTES,
    DEVICE_FREQUENCY,
    DEVICE_INFO,
    DEVICE_IS_GUEST,
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
    DEVICE_UPLOAD_BYTES,
    DEVICE_WIRELESS,
    EERO_BACKUP_CONNECTION,
    EERO_CONNECTED_CLIENTS,
    EERO_CONNECTED_WIRED_CLIENTS,
    EERO_CONNECTED_WIRELESS_CLIENTS,
    EERO_CPU_USAGE,
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
    EERO_PROVIDES_WIFI,
    EERO_STATUS,
    EERO_TEMPERATURE,
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
    EXPORTER_SCRAPE_DURATION,
    EXPORTER_SCRAPE_ERRORS,
    EXPORTER_SCRAPE_SUCCESS,
    HEALTH_STATUS,
    NETWORK_BACKUP_INTERNET_ENABLED,
    NETWORK_BAND_STEERING_ENABLED,
    NETWORK_CLIENTS_COUNT,
    NETWORK_DNS_CACHING_ENABLED,
    NETWORK_DOWNLOAD_BYTES,
    NETWORK_EEROS_COUNT,
    NETWORK_GUEST_ENABLED,
    NETWORK_INFO,
    NETWORK_IPV6_ENABLED,
    NETWORK_POWER_SAVING_ENABLED,
    NETWORK_PREMIUM_ENABLED,
    NETWORK_SQM_ENABLED,
    NETWORK_STATUS,
    NETWORK_THREAD_ENABLED,
    NETWORK_UPLOAD_BYTES,
    NETWORK_UPNP_ENABLED,
    NETWORK_WPA3_ENABLED,
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


def _parse_signal_strength(signal_str: Optional[str]) -> Optional[float]:
    """Parse signal strength string to float."""
    if not signal_str:
        return None
    try:
        return float(signal_str.replace(" dBm", "").strip())
    except (ValueError, AttributeError):
        return None


def _parse_bitrate(bitrate_str: Optional[str]) -> Optional[float]:
    """Parse bitrate string to Mbps float."""
    if not bitrate_str:
        return None
    try:
        cleaned = bitrate_str.replace(" Mbit/s", "").replace(" Mbps", "").strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return None


def _parse_speed_mbps(speed_str: Optional[str]) -> Optional[float]:
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


def _parse_timestamp(timestamp_str: Optional[str]) -> Optional[float]:
    """Parse ISO timestamp string to Unix epoch."""
    if not timestamp_str:
        return None
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
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
        timeout: int = 30,
    ) -> None:
        """Initialize the collector."""
        self._include_devices = include_devices
        self._include_profiles = include_profiles
        self._include_premium = include_premium
        self._include_ethernet = include_ethernet
        self._include_thread = include_thread
        self._timeout = timeout
        self._last_collection_time: float = 0
        self._cached_data: Dict[str, Any] = {}
        self._is_premium: bool = False

    async def collect(self) -> bool:
        """Collect metrics from the eero API."""
        start_time = time.monotonic()
        success = False

        try:
            async with EeroClient(timeout=self._timeout) as client:
                networks = await client.get_networks()
                EXPORTER_API_REQUESTS.labels(
                    endpoint="networks", status="success"
                ).inc()

                if not networks:
                    _LOGGER.warning("No networks found")
                    return False

                for network_data in networks:
                    await self._collect_network_metrics(client, network_data)

            success = True
            EXPORTER_SCRAPE_SUCCESS.set(1)

        except EeroAuthError as e:
            _LOGGER.error(f"Authentication error: {e}")
            EXPORTER_SCRAPE_ERRORS.labels(error_type="auth").inc()
            EXPORTER_SCRAPE_SUCCESS.set(0)

        except EeroAPIError as e:
            _LOGGER.error(f"API error during collection: {e}")
            EXPORTER_SCRAPE_ERRORS.labels(error_type="api").inc()
            if not self._cached_data:
                EXPORTER_SCRAPE_SUCCESS.set(0)

        except Exception as e:
            _LOGGER.error(f"Unexpected error during collection: {e}", exc_info=True)
            EXPORTER_SCRAPE_ERRORS.labels(error_type="unknown").inc()
            EXPORTER_SCRAPE_SUCCESS.set(0)

        finally:
            duration = time.monotonic() - start_time
            EXPORTER_SCRAPE_DURATION.set(duration)
            self._last_collection_time = time.time()
            _LOGGER.info(f"Collection completed in {duration:.2f}s (success={success})")

        return success

    async def _collect_network_metrics(
        self,
        client: EeroClient,
        network_data: Dict[str, Any],
    ) -> None:
        """Collect metrics for a single network."""
        network_url = network_data.get("url", "")
        network_id = _extract_id_from_url(network_url)
        network_name = network_data.get("name", "Unknown")

        if not network_id:
            _LOGGER.warning(f"Could not extract network ID from {network_url}")
            return

        _LOGGER.debug(f"Collecting metrics for network: {network_name} ({network_id})")

        try:
            network_details = await client.get_network(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="network", status="success").inc()
        except EeroAPIError as e:
            _LOGGER.warning(f"Failed to get network details: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="network", status="error").inc()
            network_details = network_data

        NETWORK_INFO.labels(network_id=network_id).info(
            {
                "name": network_name,
                "status": network_details.get("status", "unknown"),
                "isp": network_details.get("isp_name") or "unknown",
                "public_ip": network_details.get("public_ip") or "unknown",
                "wan_type": network_details.get("wan_type") or "unknown",
                "gateway_ip": network_details.get("gateway_ip") or "unknown",
            }
        )

        status = network_details.get("status", "").lower()
        is_online = 1 if status in ("connected", "online") else 0
        NETWORK_STATUS.labels(network_id=network_id, name=network_name).set(is_online)

        health = network_details.get("health", {})
        if health:
            internet_health = health.get("internet", {})
            eero_health = health.get("eero_network", {})
            if internet_health:
                is_healthy = 1 if internet_health.get("status") == "connected" else 0
                HEALTH_STATUS.labels(network_id=network_id, source="internet").set(
                    is_healthy
                )
            if eero_health:
                is_healthy = 1 if eero_health.get("status") == "connected" else 0
                HEALTH_STATUS.labels(network_id=network_id, source="eero_network").set(
                    is_healthy
                )

        speed = network_details.get("speed", {})
        if speed:
            upload = speed.get("up", {})
            download = speed.get("down", {})
            if upload and "value" in upload:
                SPEED_UPLOAD_MBPS.labels(network_id=network_id).set(upload["value"])
            if download and "value" in download:
                SPEED_DOWNLOAD_MBPS.labels(network_id=network_id).set(download["value"])
            if "date" in speed:
                try:
                    from datetime import datetime

                    dt = datetime.fromisoformat(speed["date"].replace("Z", "+00:00"))
                    SPEED_TEST_TIMESTAMP.labels(network_id=network_id).set(
                        dt.timestamp()
                    )
                except (ValueError, TypeError):
                    pass

        await self._collect_network_feature_flags(
            client, network_id, network_name, network_details
        )
        await self._collect_sqm_metrics(client, network_id)
        await self._collect_eero_metrics(client, network_id, network_name)

        if self._include_devices:
            await self._collect_device_metrics(client, network_id, network_name)

        if self._include_profiles:
            await self._collect_profile_metrics(client, network_id)

        if self._include_premium:
            await self._collect_premium_metrics(client, network_id, network_name)

        if self._include_thread:
            await self._collect_thread_metrics(client, network_id)

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

        NETWORK_EEROS_COUNT.labels(network_id=network_id, name=network_name).set(
            len(eeros)
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

            EERO_INFO.labels(
                network_id=network_id, eero_id=eero_id, serial=serial
            ).info(
                {
                    "location": location,
                    "model": model,
                    "model_number": eero.get("model_number") or "unknown",
                    "os_version": eero.get("os_version") or eero.get("os") or "unknown",
                    "mac_address": eero.get("mac_address") or "unknown",
                    "ip_address": eero.get("ip_address") or "unknown",
                }
            )

            is_online = 1 if status in ("connected", "online") else 0
            EERO_STATUS.labels(
                network_id=network_id, eero_id=eero_id, location=location, model=model
            ).set(is_online)

            is_gateway = 1 if eero.get("gateway", False) else 0
            EERO_IS_GATEWAY.labels(
                network_id=network_id, eero_id=eero_id, location=location
            ).set(is_gateway)

            clients_count = eero.get("connected_clients_count", 0)
            EERO_CONNECTED_CLIENTS.labels(
                network_id=network_id, eero_id=eero_id, location=location, model=model
            ).set(clients_count)

            wired_clients = eero.get("connected_wired_clients_count")
            if wired_clients is not None:
                EERO_CONNECTED_WIRED_CLIENTS.labels(
                    network_id=network_id, eero_id=eero_id, location=location
                ).set(wired_clients)

            wireless_clients = eero.get("connected_wireless_clients_count")
            if wireless_clients is not None:
                EERO_CONNECTED_WIRELESS_CLIENTS.labels(
                    network_id=network_id, eero_id=eero_id, location=location
                ).set(wireless_clients)

            mesh_quality = eero.get("mesh_quality_bars")
            if mesh_quality is not None:
                EERO_MESH_QUALITY.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                    model=model,
                ).set(mesh_quality)

            uptime = eero.get("uptime")
            if uptime is not None:
                EERO_UPTIME_SECONDS.labels(
                    network_id=network_id, eero_id=eero_id, location=location
                ).set(uptime)

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

            memory_usage = eero.get("memory_usage")
            if memory_usage is not None:
                EERO_MEMORY_USAGE.labels(
                    network_id=network_id, eero_id=eero_id, location=location
                ).set(memory_usage)

            cpu_usage = eero.get("cpu_usage")
            if cpu_usage is not None:
                EERO_CPU_USAGE.labels(
                    network_id=network_id, eero_id=eero_id, location=location
                ).set(cpu_usage)

            temperature = eero.get("temperature")
            if temperature is not None:
                EERO_TEMPERATURE.labels(
                    network_id=network_id, eero_id=eero_id, location=location
                ).set(temperature)

            led_brightness = eero.get("led_brightness")
            if led_brightness is not None:
                EERO_LED_BRIGHTNESS.labels(
                    network_id=network_id, eero_id=eero_id, location=location
                ).set(led_brightness)

            last_reboot = eero.get("last_reboot")
            if last_reboot:
                reboot_ts = _parse_timestamp(last_reboot)
                if reboot_ts is not None:
                    EERO_LAST_REBOOT.labels(
                        network_id=network_id, eero_id=eero_id, location=location
                    ).set(reboot_ts)

            provides_wifi = eero.get("provides_wifi")
            if provides_wifi is not None:
                EERO_PROVIDES_WIFI.labels(
                    network_id=network_id, eero_id=eero_id, location=location
                ).set(1 if provides_wifi else 0)

            backup_connection = eero.get("backup_connection")
            if backup_connection is not None:
                EERO_BACKUP_CONNECTION.labels(
                    network_id=network_id, eero_id=eero_id, location=location
                ).set(1 if backup_connection else 0)

            if self._include_ethernet:
                await self._collect_ethernet_port_metrics(
                    network_id, eero_id, location, eero
                )

            nightlight = eero.get("nightlight", {})
            if nightlight and isinstance(nightlight, dict):
                nl_enabled = nightlight.get("enabled")
                if nl_enabled is not None:
                    EERO_NIGHTLIGHT_ENABLED.labels(
                        network_id=network_id, eero_id=eero_id, location=location
                    ).set(1 if nl_enabled else 0)

                nl_brightness = nightlight.get("brightness") or nightlight.get(
                    "brightness_percentage"
                )
                if nl_brightness is not None:
                    EERO_NIGHTLIGHT_BRIGHTNESS.labels(
                        network_id=network_id, eero_id=eero_id, location=location
                    ).set(nl_brightness)

                nl_ambient = nightlight.get("ambient_light_enabled")
                if nl_ambient is not None:
                    EERO_NIGHTLIGHT_AMBIENT_ENABLED.labels(
                        network_id=network_id, eero_id=eero_id, location=location
                    ).set(1 if nl_ambient else 0)

                nl_schedule = nightlight.get("schedule", {})
                if nl_schedule and isinstance(nl_schedule, dict):
                    schedule_enabled = nl_schedule.get("enabled")
                    if schedule_enabled is not None:
                        EERO_NIGHTLIGHT_SCHEDULE_ENABLED.labels(
                            network_id=network_id, eero_id=eero_id, location=location
                        ).set(1 if schedule_enabled else 0)

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
        NETWORK_CLIENTS_COUNT.labels(network_id=network_id, name=network_name).set(
            connected_count
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

            DEVICE_INFO.labels(
                network_id=network_id, device_id=device_id, mac=mac
            ).info(
                {
                    "name": name,
                    "manufacturer": device.get("manufacturer") or "unknown",
                    "ip": device.get("ip") or "unknown",
                    "device_type": device.get("device_type") or "unknown",
                    "hostname": device.get("hostname") or "unknown",
                }
            )

            connected = device.get("connected", False)
            DEVICE_CONNECTED.labels(
                network_id=network_id, device_id=device_id, name=name, mac=mac
            ).set(1 if connected else 0)

            wireless = device.get("wireless", False)
            DEVICE_WIRELESS.labels(
                network_id=network_id, device_id=device_id, name=name
            ).set(1 if wireless else 0)

            blocked = device.get("blacklisted", False)
            DEVICE_BLOCKED.labels(
                network_id=network_id, device_id=device_id, name=name, mac=mac
            ).set(1 if blocked else 0)

            paused = device.get("paused", False)
            DEVICE_PAUSED.labels(
                network_id=network_id, device_id=device_id, name=name
            ).set(1 if paused else 0)

            is_guest = device.get("is_guest", False)
            DEVICE_IS_GUEST.labels(
                network_id=network_id, device_id=device_id, name=name
            ).set(1 if is_guest else 0)

            connectivity = device.get("connectivity", {})
            if connectivity:
                signal = _parse_signal_strength(connectivity.get("signal"))
                if signal is not None:
                    DEVICE_SIGNAL_STRENGTH.labels(
                        network_id=network_id, device_id=device_id, name=name
                    ).set(signal)

                signal_avg = _parse_signal_strength(connectivity.get("signal_avg"))
                if signal_avg is not None:
                    DEVICE_SIGNAL_AVG.labels(
                        network_id=network_id, device_id=device_id, name=name
                    ).set(signal_avg)

                score = connectivity.get("score")
                if score is not None:
                    DEVICE_CONNECTION_SCORE.labels(
                        network_id=network_id, device_id=device_id, name=name
                    ).set(score)

                score_bars = connectivity.get("score_bars")
                if score_bars is not None:
                    DEVICE_CONNECTION_SCORE_BARS.labels(
                        network_id=network_id, device_id=device_id, name=name
                    ).set(score_bars)

                frequency = connectivity.get("frequency")
                if frequency is not None:
                    DEVICE_FREQUENCY.labels(
                        network_id=network_id, device_id=device_id, name=name
                    ).set(frequency)

                rx_bitrate = _parse_bitrate(connectivity.get("rx_bitrate"))
                if rx_bitrate is not None:
                    DEVICE_RX_BITRATE.labels(
                        network_id=network_id, device_id=device_id, name=name
                    ).set(rx_bitrate)

                rx_rate_info = connectivity.get("rx_rate_info", {})
                if rx_rate_info and isinstance(rx_rate_info, dict):
                    rx_mcs = rx_rate_info.get("mcs")
                    if rx_mcs is not None:
                        DEVICE_RX_MCS.labels(
                            network_id=network_id, device_id=device_id, name=name
                        ).set(rx_mcs)

                    rx_nss = rx_rate_info.get("nss")
                    if rx_nss is not None:
                        DEVICE_RX_NSS.labels(
                            network_id=network_id, device_id=device_id, name=name
                        ).set(rx_nss)

                    rx_bw = rx_rate_info.get("bandwidth")
                    if rx_bw is not None:
                        DEVICE_RX_BANDWIDTH.labels(
                            network_id=network_id, device_id=device_id, name=name
                        ).set(rx_bw)

                    if rx_bitrate is None:
                        rx_rate_bitrate = rx_rate_info.get("bitrate")
                        if rx_rate_bitrate is not None:
                            DEVICE_RX_BITRATE.labels(
                                network_id=network_id, device_id=device_id, name=name
                            ).set(rx_rate_bitrate)

                tx_rate_info = connectivity.get("tx_rate_info", {})
                if tx_rate_info and isinstance(tx_rate_info, dict):
                    tx_mcs = tx_rate_info.get("mcs")
                    if tx_mcs is not None:
                        DEVICE_TX_MCS.labels(
                            network_id=network_id, device_id=device_id, name=name
                        ).set(tx_mcs)

                    tx_nss = tx_rate_info.get("nss")
                    if tx_nss is not None:
                        DEVICE_TX_NSS.labels(
                            network_id=network_id, device_id=device_id, name=name
                        ).set(tx_nss)

                    tx_bw = tx_rate_info.get("bandwidth")
                    if tx_bw is not None:
                        DEVICE_TX_BANDWIDTH.labels(
                            network_id=network_id, device_id=device_id, name=name
                        ).set(tx_bw)

                    tx_bitrate = tx_rate_info.get("bitrate")
                    if tx_bitrate is not None:
                        DEVICE_TX_BITRATE.labels(
                            network_id=network_id, device_id=device_id, name=name
                        ).set(tx_bitrate)

            channel = device.get("channel")
            if channel is not None:
                DEVICE_CHANNEL.labels(
                    network_id=network_id, device_id=device_id, name=name
                ).set(channel)

            prioritized = device.get("prioritized") or device.get("priority")
            if prioritized is not None:
                DEVICE_PRIORITIZED.labels(
                    network_id=network_id, device_id=device_id, name=name
                ).set(1 if prioritized else 0)

            is_private = device.get("is_private")
            if is_private is not None:
                DEVICE_PRIVATE.labels(
                    network_id=network_id, device_id=device_id, name=name
                ).set(1 if is_private else 0)

            source = device.get("source", {})
            if source and isinstance(source, dict):
                source_is_gateway = source.get("is_gateway")
                if source_is_gateway is not None:
                    DEVICE_CONNECTED_TO_GATEWAY.labels(
                        network_id=network_id, device_id=device_id, name=name
                    ).set(1 if source_is_gateway else 0)

    async def _collect_profile_metrics(
        self, client: EeroClient, network_id: str
    ) -> None:
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
            PROFILE_PAUSED.labels(
                network_id=network_id, profile_id=profile_id, name=name
            ).set(1 if paused else 0)

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

    async def _collect_network_feature_flags(
        self,
        client: EeroClient,
        network_id: str,
        network_name: str,
        network_details: Dict[str, Any],
    ) -> None:
        """Collect network feature flag metrics."""
        wpa3 = network_details.get("wpa3")
        if wpa3 is not None:
            NETWORK_WPA3_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if wpa3 else 0
            )

        band_steering = network_details.get("band_steering")
        if band_steering is not None:
            NETWORK_BAND_STEERING_ENABLED.labels(
                network_id=network_id, name=network_name
            ).set(1 if band_steering else 0)

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
            NETWORK_DNS_CACHING_ENABLED.labels(
                network_id=network_id, name=network_name
            ).set(1 if dns_caching else 0)

        power_saving = network_details.get("power_saving")
        if power_saving is not None:
            NETWORK_POWER_SAVING_ENABLED.labels(
                network_id=network_id, name=network_name
            ).set(1 if power_saving else 0)

        guest_enabled = network_details.get("guest_network_enabled")
        if guest_enabled is not None:
            NETWORK_GUEST_ENABLED.labels(network_id=network_id, name=network_name).set(
                1 if guest_enabled else 0
            )

        backup_enabled = network_details.get("backup_internet_enabled")
        if backup_enabled is not None:
            NETWORK_BACKUP_INTERNET_ENABLED.labels(
                network_id=network_id, name=network_name
            ).set(1 if backup_enabled else 0)

    async def _collect_sqm_metrics(self, client: EeroClient, network_id: str) -> None:
        """Collect SQM (Smart Queue Management) metrics."""
        try:
            sqm_settings = await client.get_sqm_settings(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="sqm", status="success").inc()

            upload_bw = sqm_settings.get("upload_bandwidth")
            if upload_bw is not None:
                SQM_UPLOAD_BANDWIDTH.labels(network_id=network_id).set(upload_bw)

            download_bw = sqm_settings.get("download_bandwidth")
            if download_bw is not None:
                SQM_DOWNLOAD_BANDWIDTH.labels(network_id=network_id).set(download_bw)

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get SQM settings: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="sqm", status="error").inc()

    async def _collect_ethernet_port_metrics(
        self, network_id: str, eero_id: str, location: str, eero: Dict[str, Any]
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
            NETWORK_PREMIUM_ENABLED.labels(
                network_id=network_id, name=network_name
            ).set(1 if is_premium else 0)
            EXPORTER_API_REQUESTS.labels(endpoint="premium", status="success").inc()
        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get premium status: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="premium", status="error").inc()
            return

        if not self._is_premium:
            return

        await self._collect_activity_metrics(client, network_id)
        await self._collect_backup_metrics(client, network_id)

    async def _collect_activity_metrics(
        self, client: EeroClient, network_id: str
    ) -> None:
        """Collect activity metrics (Eero Plus feature)."""
        try:
            activity = await client.get_activity(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="activity", status="success").inc()

            if not activity:
                return

            total_usage = activity.get("total_usage", {})
            if total_usage:
                download = total_usage.get("download") or total_usage.get(
                    "download_bytes", 0
                )
                if download:
                    ACTIVITY_DOWNLOAD_BYTES.labels(network_id=network_id).set(download)

                upload = total_usage.get("upload") or total_usage.get("upload_bytes", 0)
                if upload:
                    ACTIVITY_UPLOAD_BYTES.labels(network_id=network_id).set(upload)

            active_clients = activity.get("active_client_count")
            if active_clients is not None:
                ACTIVITY_ACTIVE_CLIENTS.labels(network_id=network_id).set(
                    active_clients
                )

            top_clients = activity.get("top_clients", [])
            for client_act in top_clients:
                if not isinstance(client_act, dict):
                    continue

                device_id = client_act.get("device_id", "")
                if not device_id:
                    url = client_act.get("url", "")
                    device_id = _extract_id_from_url(url)

                name = (
                    client_act.get("nickname")
                    or client_act.get("display_name")
                    or client_act.get("hostname")
                    or device_id
                )

                usage = client_act.get("usage", {})
                if usage and isinstance(usage, dict):
                    dl = usage.get("download_bytes", 0)
                    if dl:
                        DEVICE_ACTIVITY_DOWNLOAD_BYTES.labels(
                            network_id=network_id, device_id=device_id, name=name
                        ).set(dl)
                    ul = usage.get("upload_bytes", 0)
                    if ul:
                        DEVICE_ACTIVITY_UPLOAD_BYTES.labels(
                            network_id=network_id, device_id=device_id, name=name
                        ).set(ul)

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get activity: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="activity", status="error").inc()

        try:
            categories = await client.get_activity_categories(network_id)
            EXPORTER_API_REQUESTS.labels(
                endpoint="activity_categories", status="success"
            ).inc()

            for category in categories:
                if not isinstance(category, dict):
                    continue
                cat_name = category.get("name", "unknown")
                usage = category.get("usage", {})
                if usage and isinstance(usage, dict):
                    total = usage.get("total_bytes") or usage.get("total", 0)
                    if total:
                        ACTIVITY_CATEGORY_BYTES.labels(
                            network_id=network_id, category=cat_name
                        ).set(total)

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get activity categories: {e}")
            EXPORTER_API_REQUESTS.labels(
                endpoint="activity_categories", status="error"
            ).inc()

    async def _collect_backup_metrics(
        self, client: EeroClient, network_id: str
    ) -> None:
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
            EXPORTER_API_REQUESTS.labels(
                endpoint="backup_status", status="success"
            ).inc()

            active = backup_status.get("active") or backup_status.get("using_backup")
            if active is not None:
                BACKUP_ACTIVE.labels(network_id=network_id).set(1 if active else 0)

            connected = backup_status.get("connected")
            if connected is not None:
                BACKUP_CONNECTED.labels(network_id=network_id).set(
                    1 if connected else 0
                )

            signal = backup_status.get("signal_strength")
            if signal is not None:
                BACKUP_SIGNAL_STRENGTH.labels(network_id=network_id).set(signal)

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get backup status: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="backup_status", status="error").inc()

    async def _collect_thread_metrics(
        self, client: EeroClient, network_id: str
    ) -> None:
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
                THREAD_BORDER_ROUTER.labels(network_id=network_id).set(
                    len(border_routers)
                )

        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get Thread data: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="thread", status="error").inc()
