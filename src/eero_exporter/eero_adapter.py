"""Adapter to bridge eero-api library with the Prometheus exporter.

This module provides a compatibility layer that wraps the eero-api
library, extracting data from raw API responses for the exporter's
metrics collection logic.

As of eero-api v2.0.0, all responses are raw JSON in the format:
    {"meta": {...}, "data": {...}}

This adapter handles data extraction from the envelope.
"""

import logging
from pathlib import Path
from typing import Any

from eero import EeroClient as BaseEeroClient  # type: ignore[import-untyped]
from eero.exceptions import (  # type: ignore[import-untyped]
    EeroAPIException,
    EeroAuthenticationException,
)


# Define local exception classes for stable API.
# This decouples the adapter from upstream exception signature changes
# (e.g., eero-api v1.3.0+ changed EeroAPIException to require status_code).
class EeroAPIError(Exception):
    """API error raised by the eero adapter.

    This is a local exception class that provides a stable interface,
    independent of upstream eero-api exception signatures.
    """

    pass


class EeroAuthError(Exception):
    """Authentication error raised by the eero adapter.

    This is a local exception class that provides a stable interface,
    independent of upstream eero-api exception signatures.
    """

    pass


# Keep references to upstream exceptions for catching in try/except blocks
_UpstreamAPIException = EeroAPIException
_UpstreamAuthException = EeroAuthenticationException

__all__ = [
    "EeroClient",
    "EeroAPIError",
    "EeroAuthError",
]

_LOGGER = logging.getLogger(__name__)


def _wrap_api_call(message: str = "API call failed") -> Any:
    """Decorator to wrap API calls and convert upstream exceptions to local ones.

    This ensures that any EeroAPIException or EeroAuthenticationException raised
    by the eero-api library is converted to our local EeroAPIError or EeroAuthError.
    """
    from collections.abc import Callable
    from functools import wraps
    from typing import TypeVar

    F = TypeVar("F", bound=Callable[..., Any])

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except _UpstreamAuthException as e:
                raise EeroAuthError(str(e)) from e
            except _UpstreamAPIException as e:
                raise EeroAPIError(str(e)) from e

        return wrapper  # type: ignore[return-value]

    return decorator


# Default session file path - used as cookie storage for eero-api
# This keeps backward compatibility with existing Docker setups using session.json
DEFAULT_SESSION_FILE = Path.home() / ".config" / "eero-exporter" / "session.json"


def _extract_data(raw_response: Any) -> Any:
    """Extract data from raw API response envelope.

    eero-api v2.0.0 returns raw responses in format: {"meta": {...}, "data": {...}}

    Args:
        raw_response: Raw response from eero-api

    Returns:
        Extracted data, or the original value if not in envelope format
    """
    if raw_response is None:
        return {}
    if not isinstance(raw_response, dict):
        return raw_response
    # If it has "meta" and "data" keys, it's an envelope - extract data
    if "meta" in raw_response and "data" in raw_response:
        return raw_response.get("data", {})
    # Otherwise return as-is (already extracted or different format)
    return raw_response


def _extract_list(raw_response: Any, list_key: str | None = None) -> list[dict[str, Any]]:
    """Extract a list from raw API response.

    Handles various nested structures from the Eero API:
    - {"meta": {...}, "data": [...]}
    - {"meta": {...}, "data": {"networks": {"data": [...]}}}
    - {"meta": {...}, "data": {"eeros": [...]}}
    - {"meta": {...}, "data": {"devices": [...]}}

    Args:
        raw_response: Raw response from eero-api
        list_key: Optional key for the list within data (e.g., "networks", "eeros")

    Returns:
        Extracted list of dictionaries
    """
    if raw_response is None:
        return []
    if isinstance(raw_response, list):
        return list(raw_response)

    data = _extract_data(raw_response)

    if isinstance(data, list):
        return list(data)

    if isinstance(data, dict):
        # Try specific list_key first
        if list_key and list_key in data:
            result = data[list_key]
            # Handle nested {"key": {"data": [...]}} structure
            if isinstance(result, dict) and "data" in result:
                nested = result["data"]
                if isinstance(nested, list):
                    return list(nested)
            if isinstance(result, list):
                return list(result)

        # Try common list keys
        for key in ["data", "networks", "eeros", "devices", "profiles"]:
            if key in data:
                result = data[key]
                # Handle nested structure
                if isinstance(result, dict) and "data" in result:
                    nested = result["data"]
                    if isinstance(nested, list):
                        return list(nested)
                if isinstance(result, list):
                    return list(result)

    return []


class EeroClient:
    """Adapter wrapping eero-api for the Prometheus exporter.

    This class provides the same interface as the original embedded API client,
    but delegates to the eero-api library internally. Responses are
    extracted from the raw API envelope format.

    eero-api v2.0.0 returns raw responses in format: {"meta": {...}, "data": {...}}

    The eero-api library handles authentication via:
    - System keyring (default, for desktop use)
    - Cookie file (for Docker/headless environments)

    For Docker deployments, use cookie_file parameter to persist credentials.
    """

    def __init__(
        self,
        session_id: str | None = None,
        user_token: str | None = None,
        timeout: int = 30,
        cookie_file: str | None = None,
        use_keyring: bool = False,
    ) -> None:
        """Initialize the eero client adapter.

        Args:
            session_id: Ignored (kept for backward compatibility)
            user_token: Ignored (kept for backward compatibility)
            timeout: Request timeout in seconds (currently unused)
            cookie_file: Path to cookie file for credential storage
            use_keyring: Whether to use system keyring (default: False for Docker)
        """
        # Note: session_id and user_token are ignored - eero-api manages auth internally
        self._timeout = timeout
        self._cookie_file = cookie_file or str(DEFAULT_SESSION_FILE)
        self._use_keyring = use_keyring
        self._client: BaseEeroClient | None = None
        self._preferred_network_id: str | None = None

    @property
    def is_authenticated(self) -> bool:
        """Check if the client is authenticated."""
        if self._client:
            return bool(self._client.is_authenticated)
        return False

    async def __aenter__(self) -> "EeroClient":
        """Enter async context manager."""
        # Ensure cookie directory exists
        cookie_path = Path(self._cookie_file)
        cookie_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize the eero client
        self._client = BaseEeroClient(
            cookie_file=self._cookie_file,
            use_keyring=self._use_keyring,
        )
        try:
            await self._client.__aenter__()
        except _UpstreamAuthException as e:
            raise EeroAuthError(str(e)) from e
        except _UpstreamAPIException as e:
            raise EeroAPIError(str(e)) from e
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context manager."""
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)

    # =========================================================================
    # Authentication
    # =========================================================================

    @_wrap_api_call("Login failed")
    async def login(self, identifier: str) -> str:
        """Start login flow by requesting a verification code.

        Args:
            identifier: Email address or phone number

        Returns:
            A placeholder token (actual auth is managed by eero-api)
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        success = await self._client.login(identifier)
        if not success:
            raise EeroAuthError("Login request failed")

        # Return a placeholder - actual token management is internal to eero-api
        return "pending_verification"

    @_wrap_api_call("Verification failed")
    async def verify(self, code: str) -> dict[str, Any]:
        """Verify login with the code sent to the user.

        Args:
            code: Verification code from email/SMS

        Returns:
            Session data (placeholder for compatibility)
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        success = await self._client.verify(code)
        if not success:
            raise EeroAuthError("Verification failed")

        # Get preferred network ID from raw response
        try:
            raw_networks = await self._client.get_networks()
            networks = _extract_list(raw_networks, "networks")
            if networks:
                network = networks[0]
                url = network.get("url", "")
                if url:
                    parts = str(url).rstrip("/").split("/")
                    if parts:
                        self._preferred_network_id = parts[-1]
        except Exception:
            pass

        return {
            "session_id": "managed_by_eero_client",
            "user_token": "managed_by_eero_client",
            "preferred_network_id": self._preferred_network_id,
        }

    # =========================================================================
    # Account & Networks
    # =========================================================================

    @_wrap_api_call("Failed to get account")
    async def get_account(self) -> dict[str, Any]:
        """Get account information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_account()
        return dict(_extract_data(raw_response))

    @_wrap_api_call("Failed to get networks")
    async def get_networks(self) -> list[dict[str, Any]]:
        """Get list of networks."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_networks()
        result = _extract_list(raw_response, "networks")

        # Set preferred network if not set
        if not self._preferred_network_id and result:
            network_url = result[0].get("url", "")
            parts = str(network_url).rstrip("/").split("/")
            if parts:
                self._preferred_network_id = parts[-1]

        return result

    @_wrap_api_call("Failed to get network")
    async def get_network(self, network_id: str) -> dict[str, Any]:
        """Get detailed network information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_network(network_id)
        return dict(_extract_data(raw_response))

    # =========================================================================
    # Eero Devices
    # =========================================================================

    @_wrap_api_call("Failed to get eeros")
    async def get_eeros(self, network_id: str) -> list[dict[str, Any]]:
        """Get list of eero devices in a network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_eeros(network_id)
        return _extract_list(raw_response, "eeros")

    # =========================================================================
    # Client Devices
    # =========================================================================

    @_wrap_api_call("Failed to get devices")
    async def get_devices(self, network_id: str) -> list[dict[str, Any]]:
        """Get list of client devices in a network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_devices(network_id)
        return _extract_list(raw_response, "devices")

    # =========================================================================
    # Profiles
    # =========================================================================

    @_wrap_api_call("Failed to get profiles")
    async def get_profiles(self, network_id: str) -> list[dict[str, Any]]:
        """Get list of profiles in a network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_profiles(network_id)
        return _extract_list(raw_response, "profiles")

    # =========================================================================
    # Speed Test
    # =========================================================================

    @_wrap_api_call("Failed to get speed test")
    async def get_speed_test(self, network_id: str) -> dict[str, Any] | None:
        """Get the latest speed test results.

        Note: eero-api uses run_speed_test() to trigger new tests.
        This method gets the last known speed data from network info.
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        # Get speed data from network info
        raw_response = await self._client.get_network(network_id)
        network_data = _extract_data(raw_response)
        # eero-api returns "speed_test", but check "speed" as fallback for compatibility
        speed_data = network_data.get("speed_test") or network_data.get("speed", {})
        if isinstance(speed_data, dict):
            return speed_data
        return None

    # =========================================================================
    # Transfer Stats
    # =========================================================================

    @_wrap_api_call("Failed to get transfer stats")
    async def get_transfer_stats(
        self, network_id: str, device_id: str | None = None
    ) -> dict[str, Any]:
        """Get transfer statistics for network or device."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_transfer_stats(network_id, device_id)
        return dict(_extract_data(raw_response))

    # =========================================================================
    # SQM Settings
    # =========================================================================

    @_wrap_api_call("Failed to get SQM settings")
    async def get_sqm_settings(self, network_id: str) -> dict[str, Any]:
        """Get SQM (Smart Queue Management) settings."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_sqm_settings(network_id)
        return dict(_extract_data(raw_response))

    # =========================================================================
    # Security Settings
    # =========================================================================

    @_wrap_api_call("Failed to get security settings")
    async def get_security_settings(self, network_id: str) -> dict[str, Any]:
        """Get security settings for the network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_security_settings(network_id)
        return dict(_extract_data(raw_response))

    # =========================================================================
    # Premium Features (Eero Plus)
    # =========================================================================

    @_wrap_api_call("Failed to get premium status")
    async def get_premium_status(self, network_id: str) -> dict[str, Any]:
        """Get Eero Plus/Secure subscription status."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_premium_status(network_id)
        return dict(_extract_data(raw_response))

    @_wrap_api_call("Failed to check premium status")
    async def is_premium(self, network_id: str) -> bool:
        """Check if the network has an active Eero Plus subscription."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.is_premium(network_id)
        # is_premium may return raw response or bool
        if isinstance(raw_response, bool):
            return raw_response
        if isinstance(raw_response, dict):
            data = _extract_data(raw_response)
            return bool(data.get("premium", False))
        return bool(raw_response)

    # =========================================================================
    # Activity (Eero Plus)
    # =========================================================================

    @_wrap_api_call("Failed to get activity")
    async def get_activity(self, network_id: str) -> dict[str, Any]:
        """Get network activity summary (Eero Plus feature)."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_activity(network_id)
        return dict(_extract_data(raw_response))

    @_wrap_api_call("Failed to get activity clients")
    async def get_activity_clients(self, network_id: str) -> list[dict[str, Any]]:
        """Get per-client activity data (Eero Plus feature)."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_activity_clients(network_id)
        return _extract_list(raw_response, "clients")

    @_wrap_api_call("Failed to get activity categories")
    async def get_activity_categories(self, network_id: str) -> list[dict[str, Any]]:
        """Get activity data grouped by category (Eero Plus feature)."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_activity_categories(network_id)
        return _extract_list(raw_response, "categories")

    # =========================================================================
    # Backup Network (Eero Plus)
    # =========================================================================

    @_wrap_api_call("Failed to get backup network")
    async def get_backup_network(self, network_id: str) -> dict[str, Any]:
        """Get backup network configuration (Eero Plus feature)."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_backup_network(network_id)
        return dict(_extract_data(raw_response))

    @_wrap_api_call("Failed to get backup status")
    async def get_backup_status(self, network_id: str) -> dict[str, Any]:
        """Get current backup network status (Eero Plus feature)."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_backup_status(network_id)
        return dict(_extract_data(raw_response))

    @_wrap_api_call("Failed to check backup status")
    async def is_using_backup(self, network_id: str) -> bool:
        """Check if the network is currently using backup connection."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.is_using_backup(network_id)
        if isinstance(raw_response, bool):
            return raw_response
        if isinstance(raw_response, dict):
            data = _extract_data(raw_response)
            return bool(data.get("using_backup", False))
        return bool(raw_response)

    # =========================================================================
    # Thread
    # =========================================================================

    @_wrap_api_call("Failed to get thread data")
    async def get_thread(self, network_id: str) -> dict[str, Any]:
        """Get Thread network information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_thread(network_id)
        return dict(_extract_data(raw_response))

    # =========================================================================
    # Diagnostics
    # =========================================================================

    @_wrap_api_call("Failed to get diagnostics")
    async def get_diagnostics(self, network_id: str) -> dict[str, Any]:
        """Get network diagnostics information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_diagnostics(network_id)
        return dict(_extract_data(raw_response))
