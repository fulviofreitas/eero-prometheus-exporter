"""Tests for the adapter's error-mapping layer (v8 typed exception classes).

Constructs real eero-api 8.0.1 exception instances (never message-text
doubles) as ``AsyncMock`` side effects on the underlying SDK client, and
asserts the adapter maps each to the documented local class with
``status_code``/``error_code``/``group`` populated, and that the upstream
response envelope never leaks into a local exception's message.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from eero.exceptions import (  # type: ignore[import-untyped]
    EeroAccessDeniedException,
    EeroAPIException,
    EeroAuthenticationException,
    EeroClientBlockedException,
    EeroException,
    EeroFeatureUnavailableException,
    EeroNetworkException,
    EeroNotFoundException,
    EeroPremiumRequiredException,
    EeroRateLimitException,
    EeroTimeoutException,
    EeroValidationException,
)

from eero_exporter.eero_adapter import (
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
)

# A marker planted inside every test envelope. It must never appear in a
# local exception's message -- the envelope can carry account data and is
# never logged or included in a message anywhere in the adapter.
MARKER = "sk_live_should_never_leak_into_a_message_or_log_line"


def _envelope() -> dict[str, Any]:
    """Build a response envelope carrying the leak-detection marker."""
    return {"meta": {"code": 599}, "data": {"secret_field": MARKER}}


# ---------------------------------------------------------------------------
# Full class-mapping matrix (plan §3.2 mapping table)
# ---------------------------------------------------------------------------

MAPPING_CASES = [
    pytest.param(
        EeroAuthenticationException(
            "unrecognised error string", envelope=_envelope(), error_code="error.session.expired"
        ),
        EeroAuthError,
        None,
        "error.session.expired",
        "session",
        id="authentication",
    ),
    pytest.param(
        EeroNotFoundException(
            "network",
            "net-404",
            status_code=404,
            envelope=_envelope(),
            error_code="error.network.not.found",
        ),
        EeroNotFoundError,
        404,
        "error.network.not.found",
        "not_found",
        id="not_found",
    ),
    pytest.param(
        EeroAccessDeniedException(
            403, "access denied", envelope=_envelope(), error_code="error.access.denied"
        ),
        EeroAccessDeniedError,
        403,
        "error.access.denied",
        "access_denied",
        id="access_denied",
    ),
    pytest.param(
        EeroPremiumRequiredException(
            "Backup internet",
            status_code=402,
            envelope=_envelope(),
            error_code="error.premium.user_not_subscribed",
        ),
        EeroPremiumRequiredError,
        402,
        "error.premium.user_not_subscribed",
        "premium",
        id="premium_required",
    ),
    pytest.param(
        EeroFeatureUnavailableException(
            "Backup", status_code=409, envelope=_envelope(), error_code="error.eero.offline"
        ),
        EeroFeatureUnavailableError,
        409,
        "error.eero.offline",
        "feature_unavailable",
        id="feature_unavailable",
    ),
    pytest.param(
        EeroRateLimitException("rate limited", envelope=_envelope(), error_code="error.rate.limit"),
        EeroRateLimitError,
        None,
        "error.rate.limit",
        "rate_limit",
        id="rate_limit",
    ),
    pytest.param(
        EeroValidationException("cadence", "must be daily or hourly", envelope=_envelope()),
        EeroValidationError,
        None,
        None,
        None,
        id="validation",
    ),
    pytest.param(
        EeroNetworkException("connection refused", envelope=_envelope()),
        EeroTransportError,
        None,
        None,
        None,
        id="network",
    ),
    pytest.param(
        EeroTimeoutException("timed out", envelope=_envelope()),
        EeroTransportError,
        None,
        None,
        None,
        id="timeout",
    ),
    pytest.param(
        EeroClientBlockedException(
            426, "client blocked", envelope=_envelope(), error_code="error.app.version.blocked"
        ),
        EeroAPIError,
        426,
        "error.app.version.blocked",
        "client_blocked",
        id="client_blocked",
    ),
    pytest.param(
        EeroAPIException(
            500, "domain error", envelope=_envelope(), error_code="error.reservation.failed"
        ),
        EeroAPIError,
        500,
        "error.reservation.failed",
        "domain",
        id="domain_api_exception",
    ),
    pytest.param(
        EeroException("unclassified base exception", envelope=_envelope()),
        EeroAPIError,
        None,
        None,
        None,
        id="unrecognised_base_exception",
    ),
]


@pytest.mark.parametrize(
    ("upstream_exc", "local_cls", "status_code", "error_code", "group"), MAPPING_CASES
)
async def test_error_mapping(
    upstream_exc: EeroException,
    local_cls: type[Exception],
    status_code: int | None,
    error_code: str | None,
    group: str | None,
) -> None:
    """Every upstream exception class maps to its documented local class."""
    adapter = EeroClient()
    facade = AsyncMock()
    facade.get_network = AsyncMock(side_effect=upstream_exc)
    adapter._client = facade

    with pytest.raises(local_cls) as exc_info:
        await adapter.get_network("net-1")

    raised = exc_info.value
    assert raised.status_code == status_code  # type: ignore[attr-defined]
    assert raised.error_code == error_code  # type: ignore[attr-defined]
    assert raised.group == group  # type: ignore[attr-defined]
    assert MARKER not in str(raised)
    assert raised.__cause__ is upstream_exc


def test_eero_auth_error_is_not_an_eero_api_error() -> None:
    """EeroAuthError is a sibling of EeroAPIError, not a subclass (plan D3)."""
    assert not issubclass(EeroAuthError, EeroAPIError)
    assert not issubclass(EeroAPIError, EeroAuthError)


async def test_calling_outside_context_manager_raises_clear_error() -> None:
    """Calling an adapter method before entering the context manager is clear, not a crash."""
    adapter = EeroClient()
    with pytest.raises(EeroAPIError, match="Client not initialized"):
        await adapter.get_network("net-1")


# ---------------------------------------------------------------------------
# 8.0.1 id validation (plan §1.2a) -- validated before any HTTP request
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["net-1/", "net-1?evil=1", "../etc/passwd"])
async def test_malformed_network_id_rejected_without_any_request(
    tmp_path: Any, bad_id: str
) -> None:
    """A caller-supplied id with a path separator or query is rejected cleanly.

    Exercises the real eero-api 8.0.1 identifier validation
    (``eero.api.links.validate_identifier``) end to end through the
    adapter's error mapping. No HTTP mock is needed: the SDK validates the
    id synchronously, before building any request, so this test performs no
    network I/O -- only a local, in-memory session token is set so the
    adapter reaches the validation code past the "not authenticated" check.
    """
    adapter = EeroClient(cookie_file=str(tmp_path / "session.json"), use_keyring=False)
    async with adapter:
        assert adapter._client is not None
        await adapter._client.set_session_token("test-token")  # noqa: S106 - test fixture only

        with pytest.raises(EeroValidationError):
            await adapter.get_network(bad_id)
