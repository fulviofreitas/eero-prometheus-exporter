"""Collector module for gathering eero metrics."""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from .api import EeroAPIError, EeroAuthError, EeroClient
from .config import SessionData
from .metrics import (
    DEVICE_BLOCKED,
    DEVICE_CONNECTED,
    DEVICE_CONNECTION_SCORE,
    DEVICE_CONNECTION_SCORE_BARS,
    DEVICE_INFO,
    DEVICE_IS_GUEST,
    DEVICE_PAUSED,
    DEVICE_SIGNAL_STRENGTH,
    DEVICE_WIRELESS,
    EERO_CONNECTED_CLIENTS,
    EERO_CONNECTED_WIRED_CLIENTS,
    EERO_CONNECTED_WIRELESS_CLIENTS,
    EERO_HEARTBEAT_OK,
    EERO_INFO,
    EERO_IS_GATEWAY,
    EERO_LED_ON,
    EERO_MESH_QUALITY,
    EERO_STATUS,
    EERO_UPDATE_AVAILABLE,
    EERO_UPTIME_SECONDS,
    EERO_WIRED,
    EXPORTER_API_REQUESTS,
    EXPORTER_SCRAPE_DURATION,
    EXPORTER_SCRAPE_ERRORS,
    EXPORTER_SCRAPE_SUCCESS,
    HEALTH_STATUS,
    NETWORK_CLIENTS_COUNT,
    NETWORK_EEROS_COUNT,
    NETWORK_INFO,
    NETWORK_STATUS,
    PROFILE_DEVICES_COUNT,
    PROFILE_PAUSED,
    SPEED_DOWNLOAD_MBPS,
    SPEED_TEST_TIMESTAMP,
    SPEED_UPLOAD_MBPS,
)

_LOGGER = logging.getLogger(__name__)


def _extract_id_from_url(url: str) -> str:
    """Extract ID from an API URL."""
    if not url:
        return ""
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else ""


def _parse_signal_strength(signal_str: Optional[str]) -> Optional[float]:
    """Parse signal strength string to float.

    Args:
        signal_str: Signal strength like "-42 dBm"

    Returns:
        Signal strength as float, or None if parsing fails
    """
    if not signal_str:
        return None
    try:
        # Remove " dBm" suffix and convert
        return float(signal_str.replace(" dBm", "").strip())
    except (ValueError, AttributeError):
        return None


class EeroCollector:
    """Collector for eero metrics."""

    def __init__(
        self,
        session: SessionData,
        include_devices: bool = True,
        include_profiles: bool = True,
        timeout: int = 30,
    ) -> None:
        """Initialize the collector.

        Args:
            session: Session data for authentication
            include_devices: Whether to collect device metrics
            include_profiles: Whether to collect profile metrics
            timeout: Request timeout in seconds
        """
        self._session = session
        self._include_devices = include_devices
        self._include_profiles = include_profiles
        self._timeout = timeout
        self._last_collection_time: float = 0
        self._cached_data: Dict[str, Any] = {}

    async def collect(self) -> bool:
        """Collect metrics from the eero API.

        Returns:
            True if collection was successful, False otherwise
        """
        start_time = time.monotonic()
        success = False

        try:
            if not self._session.is_valid:
                raise EeroAuthError("No valid session. Please authenticate first.")

            async with EeroClient(
                session_id=self._session.session_id,
                user_token=self._session.user_token,
                timeout=self._timeout,
            ) as client:
                # Get networks
                networks = await client.get_networks()
                EXPORTER_API_REQUESTS.labels(
                    endpoint="networks", status="success"
                ).inc()

                if not networks:
                    _LOGGER.warning("No networks found")
                    return False

                # Collect metrics for each network
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
            # Don't set success to 0 if we got partial data
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

        # Get detailed network info
        try:
            network_details = await client.get_network(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="network", status="success").inc()
        except EeroAPIError as e:
            _LOGGER.warning(f"Failed to get network details: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="network", status="error").inc()
            network_details = network_data

        # Network info
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

        # Network status
        status = network_details.get("status", "").lower()
        is_online = 1 if status in ("connected", "online") else 0
        NETWORK_STATUS.labels(network_id=network_id, name=network_name).set(is_online)

        # Health status
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

        # Speed test
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

        # Collect eero device metrics
        await self._collect_eero_metrics(client, network_id, network_name)

        # Collect client device metrics
        if self._include_devices:
            await self._collect_device_metrics(client, network_id, network_name)

        # Collect profile metrics
        if self._include_profiles:
            await self._collect_profile_metrics(client, network_id)

    async def _collect_eero_metrics(
        self,
        client: EeroClient,
        network_id: str,
        network_name: str,
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

            # Eero info
            EERO_INFO.labels(
                network_id=network_id,
                eero_id=eero_id,
                serial=serial,
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

            # Status
            is_online = 1 if status in ("connected", "online") else 0
            EERO_STATUS.labels(
                network_id=network_id,
                eero_id=eero_id,
                location=location,
                model=model,
            ).set(is_online)

            # Gateway
            is_gateway = 1 if eero.get("gateway", False) else 0
            EERO_IS_GATEWAY.labels(
                network_id=network_id,
                eero_id=eero_id,
                location=location,
            ).set(is_gateway)

            # Connected clients
            clients_count = eero.get("connected_clients_count", 0)
            EERO_CONNECTED_CLIENTS.labels(
                network_id=network_id,
                eero_id=eero_id,
                location=location,
                model=model,
            ).set(clients_count)

            wired_clients = eero.get("connected_wired_clients_count")
            if wired_clients is not None:
                EERO_CONNECTED_WIRED_CLIENTS.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                ).set(wired_clients)

            wireless_clients = eero.get("connected_wireless_clients_count")
            if wireless_clients is not None:
                EERO_CONNECTED_WIRELESS_CLIENTS.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                ).set(wireless_clients)

            # Mesh quality
            mesh_quality = eero.get("mesh_quality_bars")
            if mesh_quality is not None:
                EERO_MESH_QUALITY.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                    model=model,
                ).set(mesh_quality)

            # Uptime
            uptime = eero.get("uptime")
            if uptime is not None:
                EERO_UPTIME_SECONDS.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                ).set(uptime)

            # LED
            led_on = eero.get("led_on")
            if led_on is not None:
                EERO_LED_ON.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                ).set(1 if led_on else 0)

            # Update available
            update_available = eero.get("update_available")
            if update_available is not None:
                EERO_UPDATE_AVAILABLE.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                ).set(1 if update_available else 0)

            # Heartbeat
            heartbeat_ok = eero.get("heartbeat_ok")
            if heartbeat_ok is not None:
                EERO_HEARTBEAT_OK.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                ).set(1 if heartbeat_ok else 0)

            # Wired
            wired = eero.get("wired")
            if wired is not None:
                EERO_WIRED.labels(
                    network_id=network_id,
                    eero_id=eero_id,
                    location=location,
                ).set(1 if wired else 0)

    async def _collect_device_metrics(
        self,
        client: EeroClient,
        network_id: str,
        network_name: str,
    ) -> None:
        """Collect metrics for client devices."""
        try:
            devices = await client.get_devices(network_id)
            EXPORTER_API_REQUESTS.labels(endpoint="devices", status="success").inc()
        except EeroAPIError as e:
            _LOGGER.warning(f"Failed to get devices: {e}")
            EXPORTER_API_REQUESTS.labels(endpoint="devices", status="error").inc()
            return

        # Count connected devices
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

            # Device info
            DEVICE_INFO.labels(
                network_id=network_id,
                device_id=device_id,
                mac=mac,
            ).info(
                {
                    "name": name,
                    "manufacturer": device.get("manufacturer") or "unknown",
                    "ip": device.get("ip") or "unknown",
                    "device_type": device.get("device_type") or "unknown",
                    "hostname": device.get("hostname") or "unknown",
                }
            )

            # Connected
            connected = device.get("connected", False)
            DEVICE_CONNECTED.labels(
                network_id=network_id,
                device_id=device_id,
                name=name,
                mac=mac,
            ).set(1 if connected else 0)

            # Wireless
            wireless = device.get("wireless", False)
            DEVICE_WIRELESS.labels(
                network_id=network_id,
                device_id=device_id,
                name=name,
            ).set(1 if wireless else 0)

            # Blocked
            blocked = device.get("blacklisted", False)
            DEVICE_BLOCKED.labels(
                network_id=network_id,
                device_id=device_id,
                name=name,
                mac=mac,
            ).set(1 if blocked else 0)

            # Paused
            paused = device.get("paused", False)
            DEVICE_PAUSED.labels(
                network_id=network_id,
                device_id=device_id,
                name=name,
            ).set(1 if paused else 0)

            # Guest
            is_guest = device.get("is_guest", False)
            DEVICE_IS_GUEST.labels(
                network_id=network_id,
                device_id=device_id,
                name=name,
            ).set(1 if is_guest else 0)

            # Connectivity metrics
            connectivity = device.get("connectivity", {})
            if connectivity:
                # Signal strength
                signal = _parse_signal_strength(connectivity.get("signal"))
                if signal is not None:
                    DEVICE_SIGNAL_STRENGTH.labels(
                        network_id=network_id,
                        device_id=device_id,
                        name=name,
                    ).set(signal)

                # Connection score
                score = connectivity.get("score")
                if score is not None:
                    DEVICE_CONNECTION_SCORE.labels(
                        network_id=network_id,
                        device_id=device_id,
                        name=name,
                    ).set(score)

                score_bars = connectivity.get("score_bars")
                if score_bars is not None:
                    DEVICE_CONNECTION_SCORE_BARS.labels(
                        network_id=network_id,
                        device_id=device_id,
                        name=name,
                    ).set(score_bars)

    async def _collect_profile_metrics(
        self,
        client: EeroClient,
        network_id: str,
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
            # Handle case where profile might not be a dict
            if not isinstance(profile, dict):
                _LOGGER.warning(f"Unexpected profile format: {type(profile)}")
                continue

            profile_url = profile.get("url", "")
            profile_id = _extract_id_from_url(profile_url)
            name = profile.get("name", "Unknown")

            if not profile_id:
                continue

            # Paused
            paused = profile.get("paused", False)
            PROFILE_PAUSED.labels(
                network_id=network_id,
                profile_id=profile_id,
                name=name,
            ).set(1 if paused else 0)

            # Device count - handle different data formats
            devices_data = profile.get("devices", [])
            if isinstance(devices_data, dict):
                devices = devices_data.get("data", [])
            elif isinstance(devices_data, list):
                devices = devices_data
            else:
                devices = []
            PROFILE_DEVICES_COUNT.labels(
                network_id=network_id,
                profile_id=profile_id,
                name=name,
            ).set(len(devices))
