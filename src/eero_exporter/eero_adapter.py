"""Adapter to bridge eero-client library with the Prometheus exporter.

This module provides a compatibility layer that wraps the official eero-client
library, converting its Pydantic models to dictionaries for backward compatibility
with the exporter's metrics collection logic.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from eero import EeroClient as OfficialEeroClient
from eero.exceptions import (
    EeroAPIException,
    EeroAuthenticationException,
    EeroException,
)

# Re-export exceptions with legacy names for backward compatibility
EeroAPIError = EeroAPIException
EeroAuthError = EeroAuthenticationException

__all__ = [
    "EeroClient",
    "EeroAPIError",
    "EeroAuthError",
]

_LOGGER = logging.getLogger(__name__)

# Default cookie file path for Docker/headless environments
DEFAULT_COOKIE_FILE = Path.home() / ".config" / "eero-exporter" / "cookies.json"


def _model_to_dict(model: Any) -> Dict[str, Any]:
    """Convert a Pydantic model to a dictionary.

    Args:
        model: A Pydantic model instance or any object

    Returns:
        Dictionary representation of the model
    """
    if model is None:
        return {}
    if isinstance(model, dict):
        return model
    if hasattr(model, "model_dump"):
        # Use mode='json' to serialize enums to their values (not repr)
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return {}


def _models_to_dicts(models: List[Any]) -> List[Dict[str, Any]]:
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
    """Adapter wrapping eero-client for the Prometheus exporter.

    This class provides the same interface as the original embedded API client,
    but delegates to the official eero-client library internally. Responses are
    converted from Pydantic models to dictionaries for compatibility.

    The eero-client library handles authentication via:
    - System keyring (default, for desktop use)
    - Cookie file (for Docker/headless environments)

    For Docker deployments, use cookie_file parameter to persist credentials.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        user_token: Optional[str] = None,
        timeout: int = 30,
        cookie_file: Optional[str] = None,
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
        # Note: session_id and user_token are ignored - eero-client manages auth internally
        self._timeout = timeout
        self._cookie_file = cookie_file or str(DEFAULT_COOKIE_FILE)
        self._use_keyring = use_keyring
        self._client: Optional[OfficialEeroClient] = None
        self._preferred_network_id: Optional[str] = None

    @property
    def is_authenticated(self) -> bool:
        """Check if the client is authenticated."""
        if self._client:
            return self._client.is_authenticated
        return False

    async def __aenter__(self) -> "EeroClient":
        """Enter async context manager."""
        # Ensure cookie directory exists
        cookie_path = Path(self._cookie_file)
        cookie_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize the official client
        self._client = OfficialEeroClient(
            cookie_file=self._cookie_file,
            use_keyring=self._use_keyring,
        )
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context manager."""
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)

    # =========================================================================
    # Authentication
    # =========================================================================

    async def login(self, identifier: str) -> str:
        """Start login flow by requesting a verification code.

        Args:
            identifier: Email address or phone number

        Returns:
            A placeholder token (actual auth is managed by eero-client)
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        success = await self._client.login(identifier)
        if not success:
            raise EeroAuthError("Login request failed")

        # Return a placeholder - actual token management is internal to eero-client
        return "pending_verification"

    async def verify(self, code: str) -> Dict[str, Any]:
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

    async def get_account(self) -> Dict[str, Any]:
        """Get account information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        account = await self._client.get_account()
        return _model_to_dict(account)

    async def get_networks(self) -> List[Dict[str, Any]]:
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

    async def get_network(self, network_id: str) -> Dict[str, Any]:
        """Get detailed network information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        network = await self._client.get_network(network_id)
        return _model_to_dict(network)

    # =========================================================================
    # Eero Devices
    # =========================================================================

    async def get_eeros(self, network_id: str) -> List[Dict[str, Any]]:
        """Get list of eero devices in a network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        eeros = await self._client.get_eeros(network_id)
        return _models_to_dicts(eeros)

    # =========================================================================
    # Client Devices
    # =========================================================================

    async def get_devices(self, network_id: str) -> List[Dict[str, Any]]:
        """Get list of client devices in a network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        devices = await self._client.get_devices(network_id)
        return _models_to_dicts(devices)

    # =========================================================================
    # Profiles
    # =========================================================================

    async def get_profiles(self, network_id: str) -> List[Dict[str, Any]]:
        """Get list of profiles in a network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        profiles = await self._client.get_profiles(network_id)
        return _models_to_dicts(profiles)

    # =========================================================================
    # Speed Test
    # =========================================================================

    async def get_speed_test(self, network_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest speed test results.

        Note: eero-client uses run_speed_test() to trigger new tests.
        This method gets the last known speed data from network info.
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        # Get speed data from network info
        network = await self._client.get_network(network_id)
        network_dict = _model_to_dict(network)
        return network_dict.get("speed", {})
