"""Adapter to bridge eero-client library with the Prometheus exporter.

This module provides a compatibility layer that wraps the official eero-client
library, converting its Pydantic models to dictionaries for backward compatibility
with the exporter's metrics collection logic.
"""

import logging
from typing import Any, Dict, List, Optional

from eero import EeroClient as OfficialEeroClient
from eero.exceptions import EeroAPIError, EeroAuthError

__all__ = [
    "EeroClient",
    "EeroAPIError",
    "EeroAuthError",
]

_LOGGER = logging.getLogger(__name__)


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
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model) if hasattr(model, "__iter__") else {}


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
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        user_token: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        """Initialize the eero client adapter.

        Args:
            session_id: The session ID for authenticated requests
            user_token: The user token (used during login flow)
            timeout: Request timeout in seconds
        """
        self._session_id = session_id
        self._user_token = user_token
        self._timeout = timeout
        self._client: Optional[OfficialEeroClient] = None
        self._preferred_network_id: Optional[str] = None

    @property
    def is_authenticated(self) -> bool:
        """Check if the client is authenticated."""
        return bool(self._session_id)

    async def __aenter__(self) -> "EeroClient":
        """Enter async context manager."""
        # Initialize the official client with session credentials
        self._client = OfficialEeroClient(
            session_id=self._session_id,
            user_token=self._user_token,
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
            User token for verification step
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        user_token = await self._client.login(identifier)
        self._user_token = user_token
        return user_token

    async def verify(self, code: str) -> Dict[str, Any]:
        """Verify login with the code sent to the user.

        Args:
            code: Verification code from email/SMS

        Returns:
            Session data including session_id and network info
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        result = await self._client.verify(code)

        # Convert result to dictionary format expected by exporter
        if hasattr(result, "model_dump"):
            session_data = result.model_dump()
        else:
            session_data = {
                "session_id": getattr(result, "session_id", self._user_token),
                "user_token": self._user_token,
                "preferred_network_id": getattr(result, "preferred_network_id", None),
            }

        self._session_id = session_data.get("session_id")
        self._preferred_network_id = session_data.get("preferred_network_id")

        return session_data

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
            parts = network_url.rstrip("/").split("/")
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
        """Get the latest speed test results."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        speed = await self._client.get_speed_test(network_id)
        return _model_to_dict(speed) if speed else None
