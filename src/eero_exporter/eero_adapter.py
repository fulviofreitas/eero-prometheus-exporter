"""Adapter to bridge eero-api library with the Prometheus exporter.

This module provides a compatibility layer that wraps the eero-api
library, extracting data from raw API responses for the exporter's
metrics collection logic.

As of eero-api v2.0.0, all responses are raw JSON in the format:
    {"meta": {...}, "data": {...}}

This adapter handles data extraction from the envelope.

This adapter exposes no write methods: every method here issues a GET
against the eero cloud API, with the sole exception of ``login``/``verify``
(and ``logout``, unused today), which are the only POSTs the exporter is
permitted to issue. Nothing here calls a ``set_*``/``create_*``/``delete_*``/
``update_*``/``run_*``/``pause_*``/``block_*``/``reboot_*``/``apply_*``/
``request_support``/``discover_*`` method on the underlying SDK client.

Upstream (eero-api 8.0.1) exception -> local exception mapping
================================================================

======================================  ==============================
Upstream (``eero.exceptions``)          Local (this module)
======================================  ==============================
``EeroAuthenticationException``         ``EeroAuthError`` (sibling, not
                                         a subclass of ``EeroAPIError``)
``EeroNotFoundException``               ``EeroNotFoundError``
``EeroAccessDeniedException``           ``EeroAccessDeniedError``
``EeroPremiumRequiredException``        ``EeroPremiumRequiredError``
``EeroFeatureUnavailableException``     ``EeroFeatureUnavailableError``
``EeroRateLimitException``              ``EeroRateLimitError``
``EeroValidationException``             ``EeroValidationError``
``EeroNetworkException``                ``EeroTransportError``
``EeroTimeoutException``                ``EeroTransportError``
``EeroClientBlockedException``          ``EeroAPIError`` (generic; the
                                         ``error_code``/``group`` still
                                         identify it)
``EeroAPIException`` (domain errors,    ``EeroAPIError``
and anything else)
``EeroException`` (any other subclass)  ``EeroAPIError`` (fallback)
======================================  ==============================

Every local exception in the ``EeroAPIError`` family carries ``status_code``,
``error_code``, and ``group`` (from ``eero.classify_error_code``). The raw
response envelope attached to the upstream exception is never read here and
never reaches a local exception's message -- it can carry account data.
Classification is always by exception class and ``error_code``, never by
matching message text.
"""

import logging
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, NoReturn, TypeVar

from eero import EeroClient as BaseEeroClient  # type: ignore[import-untyped]
from eero import classify_error_code  # type: ignore[import-untyped]
from eero.exceptions import (  # type: ignore[import-untyped]
    EeroAccessDeniedException,
    EeroAuthenticationException,
    EeroException,
    EeroFeatureUnavailableException,
    EeroNetworkException,
    EeroNotFoundException,
    EeroPremiumRequiredException,
    EeroRateLimitException,
    EeroTimeoutException,
    EeroValidationException,
)

F = TypeVar("F", bound=Callable[..., Any])


# Local exception classes decouple the adapter (and the collector) from the
# upstream eero-api exception hierarchy. Every member of the EeroAPIError
# family carries status_code/error_code/group; EeroAuthError is a sibling of
# EeroAPIError, not a subclass, since an authentication failure aborts a
# network scrape differently from every other API failure (see collector.py).
class EeroAPIError(Exception):
    """Base for every non-auth API failure raised by the eero adapter.

    Attributes:
        status_code: The HTTP status code, when known.
        error_code: The value of ``envelope["meta"]["error"]``, when known.
        group: The catalogue group name (``eero.ErrorGroup``) that
            ``error_code`` classifies into, or ``None`` when it does not
            classify into any known group.
    """

    def __init__(
        self,
        message: str = "API call failed",
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        group: str | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable message. Never includes the upstream
                response envelope.
            status_code: The HTTP status code, when known.
            error_code: The value of ``envelope["meta"]["error"]``, when known.
            group: The catalogue group name the error_code classifies into.
        """
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.group = group


class EeroAuthError(Exception):
    """Authentication error raised by the eero adapter.

    A sibling of :class:`EeroAPIError`, not a subclass: an authentication
    failure aborts the whole network scrape rather than being treated as a
    per-endpoint failure like the rest of the ``EeroAPIError`` family.

    Attributes:
        status_code: The HTTP status code, when known (the upstream SDK does
            not currently attach one to authentication failures).
        error_code: The value of ``envelope["meta"]["error"]``, when known.
        group: The catalogue group name ``error_code`` classifies into.
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        group: str | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable message. Never includes the upstream
                response envelope.
            status_code: The HTTP status code, when known.
            error_code: The value of ``envelope["meta"]["error"]``, when known.
            group: The catalogue group name the error_code classifies into.
        """
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.group = group


class EeroNotFoundError(EeroAPIError):
    """A requested resource does not exist (HTTP 404)."""


class EeroAccessDeniedError(EeroAPIError):
    """The caller is authenticated but not permitted to perform this read (HTTP 403)."""


class EeroPremiumRequiredError(EeroAPIError):
    """The requested feature requires an Eero Plus subscription. An expected, non-error state."""


class EeroFeatureUnavailableError(EeroAPIError):
    """The requested feature is not available on this device/network. An expected state."""


class EeroRateLimitError(EeroAPIError):
    """The API rate-limited this request (HTTP 429, or ``error.rate.limit`` on any status)."""


class EeroTransportError(EeroAPIError):
    """A network or timeout failure occurred before any response was classified."""


class EeroValidationError(EeroAPIError):
    """A request parameter failed validation, locally (before any request) or via the API."""


__all__ = [
    "EeroClient",
    "EeroAPIError",
    "EeroAuthError",
    "EeroNotFoundError",
    "EeroAccessDeniedError",
    "EeroPremiumRequiredError",
    "EeroFeatureUnavailableError",
    "EeroRateLimitError",
    "EeroTransportError",
    "EeroValidationError",
    "_parse_network_status",
]

_LOGGER = logging.getLogger(__name__)


def _group_value(error_code: str | None) -> str | None:
    """Classify an ``error_code`` into its catalogue group name.

    Args:
        error_code: The value of ``envelope["meta"]["error"]``, or ``None``.

    Returns:
        The ``eero.ErrorGroup`` value the error code classifies into, or
        ``None`` when ``error_code`` is ``None`` or unrecognised.
    """
    group = classify_error_code(error_code)
    return group.value if group is not None else None


def _reraise_as_local(exc: EeroException) -> NoReturn:
    """Classify an upstream ``EeroException`` and raise the local equivalent.

    The single place classification happens for this adapter -- both
    ``_wrap_api_call`` and ``EeroClient.__aenter__`` route every upstream
    exception through this function, so the mapping table in the module
    docstring has exactly one implementation. Classification is by
    exception class only, most specific first; message text is never
    matched. The upstream response envelope (``exc.envelope``) is
    intentionally never read here -- it can carry account data -- so it
    never reaches a local exception's message.

    Args:
        exc: The upstream exception to classify.

    Raises:
        EeroAuthError: If ``exc`` is an ``EeroAuthenticationException``.
        EeroNotFoundError: If ``exc`` is an ``EeroNotFoundException``.
        EeroAccessDeniedError: If ``exc`` is an ``EeroAccessDeniedException``.
        EeroPremiumRequiredError: If ``exc`` is an ``EeroPremiumRequiredException``.
        EeroFeatureUnavailableError: If ``exc`` is an ``EeroFeatureUnavailableException``.
        EeroRateLimitError: If ``exc`` is an ``EeroRateLimitException``.
        EeroValidationError: If ``exc`` is an ``EeroValidationException``.
        EeroTransportError: If ``exc`` is an ``EeroNetworkException`` or
            ``EeroTimeoutException``.
        EeroAPIError: For every other ``EeroException`` (including
            ``EeroClientBlockedException``, domain errors carried as a
            generic ``EeroAPIException``, and any unrecognised subclass).
    """
    message = str(exc)
    error_code = exc.error_code
    group = _group_value(error_code)
    status_code = getattr(exc, "status_code", None)

    if isinstance(exc, EeroAuthenticationException):
        raise EeroAuthError(
            message, status_code=status_code, error_code=error_code, group=group
        ) from exc
    if isinstance(exc, EeroNotFoundException):
        raise EeroNotFoundError(
            message, status_code=status_code, error_code=error_code, group=group
        ) from exc
    if isinstance(exc, EeroAccessDeniedException):
        raise EeroAccessDeniedError(
            message, status_code=status_code, error_code=error_code, group=group
        ) from exc
    if isinstance(exc, EeroPremiumRequiredException):
        raise EeroPremiumRequiredError(
            message, status_code=status_code, error_code=error_code, group=group
        ) from exc
    if isinstance(exc, EeroFeatureUnavailableException):
        raise EeroFeatureUnavailableError(
            message, status_code=status_code, error_code=error_code, group=group
        ) from exc
    if isinstance(exc, EeroRateLimitException):
        raise EeroRateLimitError(
            message, status_code=status_code, error_code=error_code, group=group
        ) from exc
    if isinstance(exc, EeroValidationException):
        raise EeroValidationError(
            message, status_code=status_code, error_code=error_code, group=group
        ) from exc
    if isinstance(exc, (EeroNetworkException, EeroTimeoutException)):
        raise EeroTransportError(
            message, status_code=status_code, error_code=error_code, group=group
        ) from exc
    # EeroClientBlockedException, every recognised "domain" EeroAPIException,
    # and any other EeroException subclass not enumerated above: a generic
    # API error, keeping status_code/error_code/group for callers that want
    # to branch on them.
    raise EeroAPIError(
        message, status_code=status_code, error_code=error_code, group=group
    ) from exc


def _wrap_api_call() -> Callable[[F], F]:
    """Decorator that maps every upstream ``EeroException`` to a local one.

    See :func:`_reraise_as_local` for the classification logic and the
    module docstring for the full mapping table.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except EeroException as e:
                _reraise_as_local(e)

        return wrapper  # type: ignore[return-value]

    return decorator


# Default session file path - used as cookie storage for eero-api
# This keeps backward compatibility with existing Docker setups using session.json
DEFAULT_SESSION_FILE = Path.home() / ".config" / "eero-exporter" / "session.json"


def _extract_data(raw_response: Any) -> Any:
    """Extract data from raw API response envelope.

    eero-api v2.0.0+ returns raw responses in format: {"meta": {...}, "data": {...}}

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


def _parse_network_status(raw_status: Any) -> str:
    """Normalize a network status value into a plain string.

    The eero API sometimes returns the network status as a plain string
    (e.g. ``"connected"``) and sometimes as a nested dict
    (e.g. ``{"status": "connected"}``). This helper defensively handles
    both shapes, plus the genuinely-absent case, so callers never have to
    duplicate the parsing logic.

    Args:
        raw_status: The raw ``status`` value from a network payload. May be
            a string, a dict, ``None``, or another type.

    Returns:
        The normalized status string, or ``"unknown"`` if the status is
        missing or cannot be determined.
    """
    if isinstance(raw_status, dict):
        return str(raw_status.get("status", "unknown"))
    if raw_status is None:
        return "unknown"
    return str(raw_status)


def _extract_network_id(network: dict[str, Any]) -> str | None:
    """Extract network ID from a network dict, trying direct id then URL fallback."""
    net_id = network.get("id")
    if net_id:
        return str(net_id)
    url = network.get("url", "")
    if url:
        parts = str(url).rstrip("/").split("/")
        if parts:
            return parts[-1]
    return None


class EeroClient:
    """Adapter wrapping eero-api for the Prometheus exporter.

    This class provides the same interface as the original embedded API client,
    but delegates to the eero-api library internally. Responses are
    extracted from the raw API envelope format.

    eero-api v2.0.0+ returns raw responses in format: {"meta": {...}, "data": {...}}

    The eero-api library handles authentication via:
    - System keyring (default, for desktop use)
    - Cookie file (for Docker/headless environments)

    For Docker deployments, use cookie_file parameter to persist credentials.

    This adapter exposes no write methods -- see the module docstring.
    """

    def __init__(
        self,
        cookie_file: str | None = None,
        use_keyring: bool = False,
        *,
        send_legacy_cookie: bool = True,
        accept_language: str = "en-US",
        get_retries: int = 0,
    ) -> None:
        """Initialize the eero client adapter.

        Args:
            cookie_file: Path to cookie file for credential storage
            use_keyring: Whether to use system keyring (default: False for Docker)
            send_legacy_cookie: When True (default), also send the session
                token as the legacy ``s=<token>`` cookie, per request.
                Forwarded to the SDK unchanged.
            accept_language: Value sent as the ``X-Accept-Language`` header
                on every request. Forwarded to the SDK unchanged.
            get_retries: Number of additional attempts the SDK makes for GET
                requests that fail with a transport error or a 5xx response.
                0 (default) disables retrying. Never applies to writes.
        """
        self._cookie_file = cookie_file or str(DEFAULT_SESSION_FILE)
        self._use_keyring = use_keyring
        self._send_legacy_cookie = send_legacy_cookie
        self._accept_language = accept_language
        self._get_retries = get_retries
        self._client: BaseEeroClient | None = None
        self._preferred_network_id: str | None = None

    @property
    def is_authenticated(self) -> bool:
        """Report whether a session token is present.

        There is no client-side session expiry in eero-api 8 -- the server
        is the sole authority on session validity, signalled via 401
        responses. This property only reports whether a token is present,
        not whether it is still valid.
        """
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
            send_legacy_cookie=self._send_legacy_cookie,
            accept_language=self._accept_language,
            get_retries=self._get_retries,
        )
        try:
            await self._client.__aenter__()
        except EeroException as e:
            _reraise_as_local(e)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context manager."""
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)

    # =========================================================================
    # Authentication
    # =========================================================================

    @_wrap_api_call()
    async def login(self, identifier: str) -> None:
        """Start login flow by requesting a verification code.

        Args:
            identifier: Email address or phone number.

        Returns:
            None. The verification code is delivered out of band
            (email/SMS); there is nothing meaningful to return once the
            request succeeds.

        Raises:
            EeroAuthError: If the login request is rejected -- including a
                server-rejected identifier, which eero-api 8.0.1 re-wraps as
                an authentication failure.
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        success = await self._client.login(identifier)
        if not success:
            raise EeroAuthError("Login request failed")

    @_wrap_api_call()
    async def verify(self, code: str) -> str | None:
        """Verify login with the code sent to the user.

        Args:
            code: Verification code from email/SMS.

        Returns:
            The account's preferred network ID once discovered, or ``None``
            when no network could be resolved (e.g. a brand-new account
            with no networks yet).

        Raises:
            EeroAuthError: If verification fails.
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        success = await self._client.verify(code)
        if not success:
            raise EeroAuthError("Verification failed")

        try:
            raw_networks = await self._client.get_networks()
            networks = _extract_list(raw_networks, "networks")
            if networks:
                self._preferred_network_id = _extract_network_id(networks[0])
        except EeroException as e:
            # Verification itself already succeeded; a follow-up failure to
            # discover the preferred network is not fatal here -- the caller
            # can look it up again later via get_networks().
            _LOGGER.debug("Could not resolve preferred network after verify: %s", e)

        return self._preferred_network_id

    # =========================================================================
    # Account & Networks
    # =========================================================================

    @_wrap_api_call()
    async def get_account(self) -> dict[str, Any]:
        """Get account information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_account()
        return dict(_extract_data(raw_response))

    @_wrap_api_call()
    async def get_networks(self) -> list[dict[str, Any]]:
        """Get list of networks."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_networks()
        result = _extract_list(raw_response, "networks")

        # Set preferred network if not set
        if not self._preferred_network_id and result:
            self._preferred_network_id = _extract_network_id(result[0])

        return result

    @_wrap_api_call()
    async def get_network(self, network_id: str) -> dict[str, Any]:
        """Get detailed network information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_network(network_id)
        return dict(_extract_data(raw_response))

    # =========================================================================
    # Eero Devices
    # =========================================================================

    @_wrap_api_call()
    async def get_eeros(self, network_id: str) -> list[dict[str, Any]]:
        """Get list of eero devices in a network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_eeros(network_id)
        return _extract_list(raw_response, "eeros")

    # =========================================================================
    # Client Devices
    # =========================================================================

    @_wrap_api_call()
    async def get_devices(self, network_id: str) -> list[dict[str, Any]]:
        """Get list of client devices in a network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_devices(network_id)
        return _extract_list(raw_response, "devices")

    # =========================================================================
    # Profiles
    # =========================================================================

    @_wrap_api_call()
    async def get_profiles(self, network_id: str) -> list[dict[str, Any]]:
        """Get list of profiles in a network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_profiles(network_id)
        return _extract_list(raw_response, "profiles")

    # =========================================================================
    # Speed Test
    # =========================================================================

    @_wrap_api_call()
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

    @_wrap_api_call()
    async def get_transfer_stats(
        self, network_id: str, device_id: str | None = None
    ) -> dict[str, Any]:
        """Get transfer statistics for network or device."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_transfer_stats(network_id, device_id)
        return dict(_extract_data(raw_response))

    # =========================================================================
    # Data Usage
    # =========================================================================

    @_wrap_api_call()
    async def get_data_usage(
        self,
        network_id: str,
        *,
        start: str,
        end: str,
        cadence: str,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Get network-level data usage.

        The API requires ``start``, ``end``, and ``cadence`` on this
        endpoint; a ``cadence`` the API rejects surfaces as
        ``EeroValidationError``.

        Args:
            network_id: Network identifier.
            start: Window start, ISO 8601 timestamp (e.g. ``"2026-07-21T00:00:00Z"``).
            end: Window end, ISO 8601 timestamp.
            cadence: Bucket size for the returned series, ``"daily"`` or ``"hourly"``.
            timezone: Optional IANA timezone name applied to the bucketing.

        Returns:
            Extracted data usage payload from the response envelope.
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_data_usage(
            network_id, start=start, end=end, cadence=cadence, timezone=timezone
        )
        return dict(_extract_data(raw_response))

    @_wrap_api_call()
    async def get_data_usage_breakdown(
        self,
        network_id: str,
        *,
        start: str,
        end: str,
        cadence: str | None = None,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Get the network/eero/device/profile data usage breakdown in one call.

        A single request returns network totals plus per-eero, per-device,
        per-profile, and unprofiled breakdowns (``data.eeros``,
        ``data.devices``, ``data.profiles``, ``data.unprofiled``) -- see the
        v8 probe shape summary §11.5. Preferred over
        ``get_devices_data_usage``/``get_eeros_data_usage_summary`` (neither
        of which carries a per-eero dimension).

        Args:
            network_id: Network identifier.
            start: Window start, ISO 8601 timestamp.
            end: Window end, ISO 8601 timestamp.
            cadence: Optional bucket size, ``"daily"`` or ``"hourly"``.
            timezone: Optional IANA timezone name.

        Returns:
            Extracted data usage breakdown payload from the response envelope.
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_data_usage_breakdown(
            network_id, start=start, end=end, cadence=cadence, timezone=timezone
        )
        return dict(_extract_data(raw_response))

    @_wrap_api_call()
    async def get_devices_data_usage(
        self,
        network_id: str,
        *,
        start: str,
        end: str,
        cadence: str | None = None,
        timezone: str | None = None,
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        """Get per-device data usage.

        Args:
            network_id: Network identifier.
            start: Window start, ISO 8601 timestamp.
            end: Window end, ISO 8601 timestamp.
            cadence: Optional bucket size, ``"daily"`` or ``"hourly"``.
                Omitted from the request when ``None``.
            timezone: Optional IANA timezone name.
            profile_id: Optional profile ID to scope results to a single profile.

        Returns:
            Extracted data usage payload from the response envelope.
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_devices_data_usage(
            network_id,
            start=start,
            end=end,
            cadence=cadence,
            timezone=timezone,
            profile_id=profile_id,
        )
        return dict(_extract_data(raw_response))

    @_wrap_api_call()
    async def get_eeros_data_usage_summary(
        self,
        network_id: str,
        *,
        start: str,
        end: str,
        cadence: str,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Get a summary of data usage across all eero devices.

        Args:
            network_id: Network identifier.
            start: Window start, ISO 8601 timestamp.
            end: Window end, ISO 8601 timestamp.
            cadence: Bucket size for the returned series, ``"daily"`` or ``"hourly"``.
            timezone: Optional IANA timezone name.

        Returns:
            Extracted data usage payload from the response envelope.
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_eeros_data_usage_summary(
            network_id, start=start, end=end, cadence=cadence, timezone=timezone
        )
        return dict(_extract_data(raw_response))

    @_wrap_api_call()
    async def get_eero_data_usage(
        self,
        network_id: str,
        eero_id: str,
        *,
        start: str,
        end: str,
        cadence: str,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Get data usage for a single eero device.

        Fallback for when ``get_eeros_data_usage_summary`` is unavailable or
        insufficient -- queries one eero at a time.

        Args:
            network_id: Network identifier.
            eero_id: ID of the eero device to query.
            start: Window start, ISO 8601 timestamp.
            end: Window end, ISO 8601 timestamp.
            cadence: Bucket size for the returned series, ``"daily"`` or ``"hourly"``.
            timezone: Optional IANA timezone name.

        Returns:
            Extracted data usage payload from the response envelope.
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_eero_data_usage(
            eero_id, network_id, start=start, end=end, cadence=cadence, timezone=timezone
        )
        return dict(_extract_data(raw_response))

    @_wrap_api_call()
    async def get_device_data_usage(
        self,
        network_id: str,
        device_mac: str,
        *,
        start: str,
        end: str,
        cadence: str,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Get data usage for a single device.

        Args:
            network_id: Network identifier.
            device_mac: MAC address of the device to query.
            start: Window start, ISO 8601 timestamp.
            end: Window end, ISO 8601 timestamp.
            cadence: Bucket size for the returned series, ``"daily"`` or ``"hourly"``.
            timezone: Optional IANA timezone name.

        Returns:
            Extracted data usage payload from the response envelope.
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_device_data_usage(
            device_mac, network_id, start=start, end=end, cadence=cadence, timezone=timezone
        )
        return dict(_extract_data(raw_response))

    @_wrap_api_call()
    async def get_profile_data_usage(
        self,
        network_id: str,
        profile_id: str,
        *,
        start: str,
        end: str,
        cadence: str,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Get data usage for a single profile.

        Args:
            network_id: Network identifier.
            profile_id: ID of the profile to query.
            start: Window start, ISO 8601 timestamp.
            end: Window end, ISO 8601 timestamp.
            cadence: Bucket size for the returned series, ``"daily"`` or ``"hourly"``.
            timezone: Optional IANA timezone name.

        Returns:
            Extracted data usage payload from the response envelope.
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_profile_data_usage(
            profile_id, network_id, start=start, end=end, cadence=cadence, timezone=timezone
        )
        return dict(_extract_data(raw_response))

    # =========================================================================
    # SQM Settings
    # =========================================================================

    @_wrap_api_call()
    async def get_sqm_settings(self, network_id: str) -> dict[str, Any]:
        """Get SQM (Smart Queue Management) settings."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_sqm_settings(network_id)
        return dict(_extract_data(raw_response))

    # =========================================================================
    # Security Settings
    # =========================================================================

    @_wrap_api_call()
    async def get_security_settings(self, network_id: str) -> dict[str, Any]:
        """Get security settings for the network."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_security_settings(network_id)
        return dict(_extract_data(raw_response))

    # =========================================================================
    # Premium Features (Eero Plus)
    # =========================================================================

    @_wrap_api_call()
    async def get_premium_status(self, network_id: str) -> dict[str, Any]:
        """Get Eero Plus/Secure subscription status."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_premium_status(network_id)
        return dict(_extract_data(raw_response))

    @_wrap_api_call()
    async def is_premium(self, network_id: str) -> bool:
        """Check if the network has an active Eero Plus subscription."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        # get_premium_status returns network data with premium status fields
        raw_response = await self._client.get_premium_status(network_id)
        if isinstance(raw_response, bool):
            return raw_response
        if isinstance(raw_response, dict):
            data = _extract_data(raw_response)
            # Check various fields that indicate premium status
            # eero_plus, premium_status, premium_dns, or premium
            if data.get("eero_plus"):
                return True
            if data.get("premium_status"):
                return True
            if data.get("premium_dns"):
                return True
            if data.get("premium"):
                return True
            return False
        return bool(raw_response)

    # =========================================================================
    # Thread
    # =========================================================================

    @_wrap_api_call()
    async def get_thread(self, network_id: str) -> dict[str, Any]:
        """Get Thread network information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_thread(network_id)
        return dict(_extract_data(raw_response))

    # =========================================================================
    # Port Forwards
    # =========================================================================

    @_wrap_api_call()
    async def get_forwards(self, network_id: str) -> list[dict[str, Any]]:
        """Get list of port forwarding rules."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_forwards(network_id)
        return _extract_list(raw_response, "forwards")

    # =========================================================================
    # DHCP Reservations
    # =========================================================================

    @_wrap_api_call()
    async def get_reservations(self, network_id: str) -> list[dict[str, Any]]:
        """Get list of DHCP reservations."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_reservations(network_id)
        return _extract_list(raw_response, "reservations")

    # =========================================================================
    # Blacklist
    # =========================================================================

    @_wrap_api_call()
    async def get_blacklist(self, network_id: str) -> list[dict[str, Any]]:
        """Get list of blacklisted devices."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_blacklist(network_id)
        return _extract_list(raw_response, "blacklist")

    # =========================================================================
    # Updates
    # =========================================================================

    @_wrap_api_call()
    async def get_updates(self, network_id: str) -> dict[str, Any]:
        """Get firmware update information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_updates(network_id)
        return dict(_extract_data(raw_response))

    # =========================================================================
    # Insights
    # =========================================================================

    @_wrap_api_call()
    async def get_insights(
        self,
        network_id: str,
        *,
        start: str,
        end: str,
        insight_type: str,
        cadence: str = "daily",
    ) -> dict[str, Any]:
        """Get network insights time-series data for one insight type.

        Args:
            network_id: Network identifier.
            start: Window start as an ISO 8601 UTC timestamp (e.g. ``"2026-07-21T00:00:00Z"``).
            end: Window end as an ISO 8601 UTC timestamp.
            insight_type: One of ``"adblock"``, ``"blocked"``, or ``"inspected"``.
            cadence: Bucket size — ``"hourly"``, ``"daily"``, or ``"weekly"``.
                Defaults to ``"daily"``. A value the API rejects surfaces as
                ``EeroValidationError`` before any request is made.

        Returns:
            Extracted data payload from the response envelope.
        """
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_insights(
            network_id,
            start=start,
            end=end,
            insight_type=insight_type,
            cadence=cadence,
        )
        return dict(_extract_data(raw_response))

    # =========================================================================
    # Diagnostics
    # =========================================================================

    @_wrap_api_call()
    async def get_diagnostics(self, network_id: str) -> dict[str, Any]:
        """Get network diagnostics information."""
        if not self._client:
            raise EeroAPIError("Client not initialized. Use async context manager.")

        raw_response = await self._client.get_diagnostics(network_id)
        return dict(_extract_data(raw_response))
