"""Adapter to bridge eero-api library with the Prometheus exporter.

This module provides a compatibility layer that wraps the eero-api
library, converting its Pydantic models to dictionaries for backward compatibility
with the exporter's metrics collection logic.
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


def _model_to_dict(model: Any) -> dict[str, Any]:
    """Convert a Pydantic model to a dictionary.

    Args:
        model: A Pydantic model instance or any object

    Returns:
        Dictionary representation of the model
    """
    if model is None:
        return {}
    if isinstance(model, dict):
        return dict(model)
    if hasattr(model, "model_dump"):
        # Use mode='json' to serialize enums to their values (not repr)
        result: dict[str, Any] = model.model_dump(mode="json")
        return result
    if hasattr(model, "dict"):
        result = model.dict()
        return dict(result)
    return {}


def _models_to_dicts(models: list[Any]) -> list[dict[str, Any]]:
    """Convert a list of Pydantic models to dictionaries.

    Args:
        models: List of Pydantic model instances

    Returns:
        List of dictionary representations
    """
    if not models:
        return []
    return [_model_to_dict(m) for m in models]


class EeroClient:
    """Adapter wrapping eero-api for the Prometheus exporter.

    This class provides the same interface as the original embedded API client,
    but delegates to the eero-api library internally. Responses are
    converted from Pydantic models to dictionaries for compatibility.

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

        # Get preferred network ID
        try:
            networks = await self._client.get_networks()
            if networks:
                network = networks[0]
                if hasattr(network, "url"):
                    url = str(network.url)
                    parts = url.rstrip("/").split("/")
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

        account = await self._client.get_account()
        return _model_to_dict(account)

    @_wrap_api_call("Failed to get networks")
    async def get_networks(self) -> list[dict[str, Any]]:
        """Get list of networks."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        networks = await self._client.get_networks()
        result = _models_to_dicts(networks)

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

        network = await self._client.get_network(network_id)
        return _model_to_dict(network)

    # =========================================================================
    # Eero Devices
    # =========================================================================

    @_wrap_api_call("Failed to get eeros")
    async def get_eeros(self, network_id: str) -> list[dict[str, Any]]:
        """Get list of eero devices in a network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        eeros = await self._client.get_eeros(network_id)
        return _models_to_dicts(eeros)

    # =========================================================================
    # Client Devices
    # =========================================================================

    @_wrap_api_call("Failed to get devices")
    async def get_devices(self, network_id: str) -> list[dict[str, Any]]:
        """Get list of client devices in a network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        devices = await self._client.get_devices(network_id)
        return _models_to_dicts(devices)

    # =========================================================================
    # Profiles
    # =========================================================================

    @_wrap_api_call("Failed to get profiles")
    async def get_profiles(self, network_id: str) -> list[dict[str, Any]]:
        """Get list of profiles in a network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        profiles = await self._client.get_profiles(network_id)
        return _models_to_dicts(profiles)

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
        # eero-api returns "speed_test", but check "speed" as fallback for compatibility
        network = await self._client.get_network(network_id)
        network_dict = _model_to_dict(network)
        speed_data = network_dict.get("speed_test") or network_dict.get("speed", {})
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

        result: dict[str, Any] = await self._client.get_transfer_stats(network_id, device_id)
        return result

    # =========================================================================
    # SQM Settings
    # =========================================================================

    @_wrap_api_call("Failed to get SQM settings")
    async def get_sqm_settings(self, network_id: str) -> dict[str, Any]:
        """Get SQM (Smart Queue Management) settings."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        result: dict[str, Any] = await self._client.get_sqm_settings(network_id)
        return result

    # =========================================================================
    # Security Settings
    # =========================================================================

    @_wrap_api_call("Failed to get security settings")
    async def get_security_settings(self, network_id: str) -> dict[str, Any]:
        """Get security settings for the network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        result: dict[str, Any] = await self._client.get_security_settings(network_id)
        return result

    # =========================================================================
    # Premium Features (Eero Plus)
    # =========================================================================

    @_wrap_api_call("Failed to get premium status")
    async def get_premium_status(self, network_id: str) -> dict[str, Any]:
        """Get Eero Plus/Secure subscription status."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        result: dict[str, Any] = await self._client.get_premium_status(network_id)
        return result

    @_wrap_api_call("Failed to check premium status")
    async def is_premium(self, network_id: str) -> bool:
        """Check if the network has an active Eero Plus subscription."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        return bool(await self._client.is_premium(network_id))

    # =========================================================================
    # Activity (Eero Plus)
    # =========================================================================

    @_wrap_api_call("Failed to get activity")
    async def get_activity(self, network_id: str) -> dict[str, Any]:
        """Get network activity summary (Eero Plus feature)."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        result: dict[str, Any] = await self._client.get_activity(network_id)
        return result

    @_wrap_api_call("Failed to get activity clients")
    async def get_activity_clients(self, network_id: str) -> list[dict[str, Any]]:
        """Get per-client activity data (Eero Plus feature)."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        result: list[dict[str, Any]] = await self._client.get_activity_clients(network_id)
        return result

    @_wrap_api_call("Failed to get activity categories")
    async def get_activity_categories(self, network_id: str) -> list[dict[str, Any]]:
        """Get activity data grouped by category (Eero Plus feature)."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        result: list[dict[str, Any]] = await self._client.get_activity_categories(network_id)
        return result

    # =========================================================================
    # Backup Network (Eero Plus)
    # =========================================================================

    @_wrap_api_call("Failed to get backup network")
    async def get_backup_network(self, network_id: str) -> dict[str, Any]:
        """Get backup network configuration (Eero Plus feature)."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        result: dict[str, Any] = await self._client.get_backup_network(network_id)
        return result

    @_wrap_api_call("Failed to get backup status")
    async def get_backup_status(self, network_id: str) -> dict[str, Any]:
        """Get current backup network status (Eero Plus feature)."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        result: dict[str, Any] = await self._client.get_backup_status(network_id)
        return result

    @_wrap_api_call("Failed to check backup status")
    async def is_using_backup(self, network_id: str) -> bool:
        """Check if the network is currently using backup connection."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        return bool(await self._client.is_using_backup(network_id))

    # =========================================================================
    # Thread
    # =========================================================================

    @_wrap_api_call("Failed to get thread data")
    async def get_thread(self, network_id: str) -> dict[str, Any]:
        """Get Thread network information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        result: dict[str, Any] = await self._client.get_thread(network_id)
        return result

    # =========================================================================
    # Diagnostics
    # =========================================================================

    @_wrap_api_call("Failed to get diagnostics")
    async def get_diagnostics(self, network_id: str) -> dict[str, Any]:
        """Get network diagnostics information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        result: dict[str, Any] = await self._client.get_diagnostics(network_id)
        return result
