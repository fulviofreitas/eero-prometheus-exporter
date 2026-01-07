"""Lightweight eero API client for the Prometheus exporter."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)

# API Constants
API_BASE_URL = "https://api-user.e2ro.com"
API_VERSION = "2.2"
LOGIN_ENDPOINT = f"{API_BASE_URL}/{API_VERSION}/login"
LOGIN_VERIFY_ENDPOINT = f"{API_BASE_URL}/{API_VERSION}/login/verify"
ACCOUNT_ENDPOINT = f"{API_BASE_URL}/{API_VERSION}/account"

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "eero-prometheus-exporter/1.0.0",
}


class EeroAPIError(Exception):
    """Base exception for eero API errors."""

    pass


class EeroAuthError(EeroAPIError):
    """Authentication error."""

    pass


class EeroClient:
    """Lightweight async eero API client for the exporter."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        user_token: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        """Initialize the eero client.

        Args:
            session_id: The session ID for authenticated requests
            user_token: The user token (used during login flow)
            timeout: Request timeout in seconds
        """
        self._session_id = session_id
        self._user_token = user_token
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._preferred_network_id: Optional[str] = None

    @property
    def is_authenticated(self) -> bool:
        """Check if the client is authenticated."""
        return bool(self._session_id)

    async def __aenter__(self) -> "EeroClient":
        """Enter async context manager."""
        self._http_session = aiohttp.ClientSession(
            timeout=self._timeout,
            headers=DEFAULT_HEADERS,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager."""
        if self._http_session:
            await self._http_session.close()

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make an authenticated request to the eero API.

        Args:
            method: HTTP method
            url: Full URL to request
            **kwargs: Additional arguments for aiohttp request

        Returns:
            JSON response data

        Raises:
            EeroAuthError: If authentication fails
            EeroAPIError: If the API returns an error
        """
        if not self._http_session:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        cookies = kwargs.pop("cookies", {})
        if self._session_id:
            cookies["s"] = self._session_id

        try:
            _LOGGER.debug(f"API request: {method} {url}")
            async with self._http_session.request(
                method, url, cookies=cookies, **kwargs
            ) as response:
                text = await response.text()

                if response.status == 200:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError as e:
                        raise EeroAPIError(f"Invalid JSON response: {e}")
                elif response.status == 401:
                    raise EeroAuthError(
                        "Authentication failed. Please re-authenticate."
                    )
                elif response.status == 429:
                    raise EeroAPIError(
                        "Rate limit exceeded. Please wait before retrying."
                    )
                else:
                    _LOGGER.error(f"API error on {method} {url}: {response.status}")
                    raise EeroAPIError(f"API error {response.status}: {text}")
        except asyncio.TimeoutError:
            raise EeroAPIError("Request timed out")
        except aiohttp.ClientError as e:
            raise EeroAPIError(f"Network error: {e}")

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
        if not self._http_session:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        async with self._http_session.post(
            LOGIN_ENDPOINT,
            json={"login": identifier},
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise EeroAuthError(f"Login failed: {text}")

            data = await response.json()
            self._user_token = data.get("data", {}).get("user_token")

            if not self._user_token:
                raise EeroAuthError("No user token in response")

            return self._user_token

    async def verify(self, code: str) -> Dict[str, Any]:
        """Verify login with the code sent to the user.

        Args:
            code: Verification code from email/SMS

        Returns:
            Session data including session_id and network info
        """
        if not self._http_session:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        if not self._user_token:
            raise EeroAuthError("No user token. Call login() first.")

        async with self._http_session.post(
            LOGIN_VERIFY_ENDPOINT,
            cookies={"s": self._user_token},
            json={"code": code},
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise EeroAuthError(f"Verification failed: {text}")

            # On success, user_token becomes session_id
            self._session_id = self._user_token
            data = await response.json()

            # Extract preferred network ID
            networks = data.get("data", {}).get("networks", {}).get("data", [])
            if networks:
                network_url = networks[0].get("url", "")
                parts = network_url.rstrip("/").split("/")
                if parts:
                    self._preferred_network_id = parts[-1]

            return {
                "session_id": self._session_id,
                "user_token": self._user_token,
                "preferred_network_id": self._preferred_network_id,
                "session_expiry": (datetime.now().replace(microsecond=0)).isoformat(),
            }

    # =========================================================================
    # Account & Networks
    # =========================================================================

    async def get_account(self) -> Dict[str, Any]:
        """Get account information."""
        response = await self._request("GET", ACCOUNT_ENDPOINT)
        return response.get("data", {})

    async def get_networks(self) -> List[Dict[str, Any]]:
        """Get list of networks from account data."""
        # First get account info which contains network URLs
        account = await self._request("GET", ACCOUNT_ENDPOINT)
        account_data = account.get("data", {})

        # Networks are nested in the account response
        networks_data = account_data.get("networks", {})

        # Handle different response formats
        if isinstance(networks_data, dict):
            networks = networks_data.get("data", [])
        elif isinstance(networks_data, list):
            networks = networks_data
        else:
            networks = []

        # Set preferred network if not set
        if not self._preferred_network_id and networks:
            network_url = networks[0].get("url", "")
            parts = network_url.rstrip("/").split("/")
            if parts:
                self._preferred_network_id = parts[-1]

        return networks

    async def get_network(self, network_id: str) -> Dict[str, Any]:
        """Get detailed network information."""
        url = f"{API_BASE_URL}/{API_VERSION}/networks/{network_id}"
        response = await self._request("GET", url)
        network_data = response.get("data", {})

        # Cache the network data for extracting eeros/devices if separate endpoints fail
        self._cached_network_data = network_data
        return network_data

    # =========================================================================
    # Eero Devices
    # =========================================================================

    async def get_eeros(self, network_id: str) -> List[Dict[str, Any]]:
        """Get list of eero devices in a network."""
        # First try to get from cached network data
        if hasattr(self, "_cached_network_data") and self._cached_network_data:
            eeros_data = self._cached_network_data.get("eeros", {})
            if isinstance(eeros_data, dict):
                eeros = eeros_data.get("data", [])
            elif isinstance(eeros_data, list):
                eeros = eeros_data
            else:
                eeros = []
            if eeros:
                _LOGGER.debug(f"Got {len(eeros)} eeros from network data")
                return eeros

        # Fallback to separate endpoint
        try:
            url = f"{API_BASE_URL}/{API_VERSION}/networks/{network_id}/eeros"
            response = await self._request("GET", url)
            # Handle different response formats
            data = response.get("data", response)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data.get("data", [])
            return []
        except EeroAPIError as e:
            _LOGGER.warning(f"Eeros endpoint failed: {e}, trying network data")
            return []

    # =========================================================================
    # Client Devices
    # =========================================================================

    async def get_devices(self, network_id: str) -> List[Dict[str, Any]]:
        """Get list of client devices in a network."""
        # First try to get from cached network data
        if hasattr(self, "_cached_network_data") and self._cached_network_data:
            devices_data = self._cached_network_data.get("devices", {})
            if isinstance(devices_data, dict):
                devices = devices_data.get("data", [])
            elif isinstance(devices_data, list):
                devices = devices_data
            else:
                devices = []
            if devices:
                _LOGGER.debug(f"Got {len(devices)} devices from network data")
                return devices

        # Fallback to separate endpoint
        try:
            url = f"{API_BASE_URL}/{API_VERSION}/networks/{network_id}/devices"
            response = await self._request("GET", url)
            # Handle different response formats
            data = response.get("data", response)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data.get("data", [])
            return []
        except EeroAPIError as e:
            _LOGGER.warning(f"Devices endpoint failed: {e}, trying network data")
            return []

    # =========================================================================
    # Profiles
    # =========================================================================

    async def get_profiles(self, network_id: str) -> List[Dict[str, Any]]:
        """Get list of profiles in a network."""
        # First try to get from cached network data
        if hasattr(self, "_cached_network_data") and self._cached_network_data:
            profiles_data = self._cached_network_data.get("profiles", {})
            if isinstance(profiles_data, dict):
                profiles = profiles_data.get("data", [])
            elif isinstance(profiles_data, list):
                profiles = profiles_data
            else:
                profiles = []
            if profiles:
                _LOGGER.debug(f"Got {len(profiles)} profiles from network data")
                return profiles

        # Fallback to separate endpoint
        try:
            url = f"{API_BASE_URL}/{API_VERSION}/networks/{network_id}/profiles"
            response = await self._request("GET", url)
            # Handle different response formats
            data = response.get("data", response)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data.get("data", [])
            return []
        except EeroAPIError as e:
            _LOGGER.warning(f"Profiles endpoint failed: {e}")
            return []

    # =========================================================================
    # Speed Test
    # =========================================================================

    async def get_speed_test(self, network_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest speed test results from network data."""
        network = await self.get_network(network_id)
        return network.get("speed", {}) or network.get("speed_test", {})
