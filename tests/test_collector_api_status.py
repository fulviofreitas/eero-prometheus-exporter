"""Tests for `_record_api_result`'s status classification (commit 3, §4).

Covers: every local exception class maps to the correct bounded status
label, the enum never leaks an unmapped value, premium/feature-unavailable/
not-found never touch `EXPORTER_SCRAPE_ERRORS`, and `collect()`'s top-level
handling of auth/transport/rate-limit errors.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eero_exporter.collector import EeroCollector, _record_api_result
from eero_exporter.eero_adapter import (
    EeroAccessDeniedError,
    EeroAPIError,
    EeroAuthError,
    EeroFeatureUnavailableError,
    EeroNotFoundError,
    EeroPremiumRequiredError,
    EeroRateLimitError,
    EeroTransportError,
    EeroValidationError,
)
from eero_exporter.metrics import API_STATUS_VALUES, EXPORTER_API_REQUESTS, EXPORTER_SCRAPE_ERRORS


def _counter_value(metric: object, **labels: str) -> float:
    return metric.labels(**labels)._value.get()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        (None, "success"),
        (EeroAuthError("expired"), "auth"),
        (EeroNotFoundError("missing"), "not_found"),
        (EeroAccessDeniedError("denied"), "access_denied"),
        (EeroPremiumRequiredError("plus only"), "premium_required"),
        (EeroFeatureUnavailableError("no beacon"), "feature_unavailable"),
        (EeroRateLimitError("slow down"), "rate_limited"),
        (EeroValidationError("bad cadence"), "validation"),
        (EeroTransportError("timeout"), "transport"),
        (EeroAPIError("generic domain error"), "error"),
    ],
)
def test_record_api_result_maps_each_exception_class(
    exc: Exception | None, expected_status: str
) -> None:
    endpoint = f"test_endpoint_{expected_status}"
    before = _counter_value(EXPORTER_API_REQUESTS, endpoint=endpoint, status=expected_status)

    status = _record_api_result(endpoint, exc)

    assert status == expected_status
    assert status in API_STATUS_VALUES
    after = _counter_value(EXPORTER_API_REQUESTS, endpoint=endpoint, status=expected_status)
    assert after == before + 1


def test_record_api_result_never_emits_outside_the_enum() -> None:
    exceptions = [
        None,
        EeroAuthError(),
        EeroNotFoundError(),
        EeroAccessDeniedError(),
        EeroPremiumRequiredError(),
        EeroFeatureUnavailableError(),
        EeroRateLimitError(),
        EeroValidationError(),
        EeroTransportError(),
        EeroAPIError(),
    ]
    for exc in exceptions:
        status = _record_api_result("enum_probe", exc)
        assert status in API_STATUS_VALUES


@pytest.mark.parametrize(
    "exc",
    [
        EeroPremiumRequiredError("plus only"),
        EeroFeatureUnavailableError("no beacon"),
        EeroNotFoundError("missing"),
    ],
)
@pytest.mark.asyncio
async def test_expected_states_never_touch_scrape_errors(exc: Exception) -> None:
    """Premium/feature-unavailable/not-found are expected states, not scrape errors."""
    collector = EeroCollector(session_file="/tmp/session.json")  # nosec B108
    before = EXPORTER_SCRAPE_ERRORS.labels(error_type="api")._value.get()

    async def _raise() -> None:
        raise exc

    result, returned_exc = await collector._api_get("expected_state_probe", _raise())

    assert result is None
    assert returned_exc is exc
    after = EXPORTER_SCRAPE_ERRORS.labels(error_type="api")._value.get()
    assert after == before


@pytest.mark.asyncio
async def test_premium_required_resets_is_premium_for_the_cycle() -> None:
    collector = EeroCollector(session_file="/tmp/session.json")  # nosec B108
    collector._is_premium = True

    async def _raise() -> None:
        raise EeroPremiumRequiredError("plus only")

    await collector._api_get("premium_probe", _raise())

    assert collector._is_premium is False


def _mock_client_raising_on_get_networks(exc: Exception) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get_networks = AsyncMock(side_effect=exc)
    return client


@pytest.mark.asyncio
async def test_collect_auth_error_aborts_with_eero_up_zero() -> None:
    from eero_exporter.metrics import EERO_UP

    collector = EeroCollector(session_file="/tmp/session.json")  # nosec B108
    mock_client = _mock_client_raising_on_get_networks(EeroAuthError("expired"))
    before = EXPORTER_SCRAPE_ERRORS.labels(error_type="auth")._value.get()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        success = await collector.collect()

    assert success is False
    assert collector.last_error_kind == "auth"
    assert EERO_UP._value.get() == 0
    assert EXPORTER_SCRAPE_ERRORS.labels(error_type="auth")._value.get() == before + 1


@pytest.mark.asyncio
async def test_collect_transport_error_classified_as_network() -> None:
    collector = EeroCollector(session_file="/tmp/session.json")  # nosec B108
    mock_client = _mock_client_raising_on_get_networks(EeroTransportError("timeout"))
    before = EXPORTER_SCRAPE_ERRORS.labels(error_type="network")._value.get()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        success = await collector.collect()

    assert success is False
    assert collector.last_error_kind == "network"
    assert EXPORTER_SCRAPE_ERRORS.labels(error_type="network")._value.get() == before + 1


@pytest.mark.asyncio
async def test_collect_rate_limit_error_classified_as_rate_limit() -> None:
    collector = EeroCollector(session_file="/tmp/session.json")  # nosec B108
    mock_client = _mock_client_raising_on_get_networks(EeroRateLimitError("slow down"))
    before = EXPORTER_SCRAPE_ERRORS.labels(error_type="rate_limit")._value.get()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        success = await collector.collect()

    assert success is False
    assert EXPORTER_SCRAPE_ERRORS.labels(error_type="rate_limit")._value.get() == before + 1


@pytest.mark.asyncio
async def test_collect_generic_api_error_classified_as_api() -> None:
    collector = EeroCollector(session_file="/tmp/session.json")  # nosec B108
    mock_client = _mock_client_raising_on_get_networks(EeroAPIError("generic"))
    before = EXPORTER_SCRAPE_ERRORS.labels(error_type="api")._value.get()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        success = await collector.collect()

    assert success is False
    assert EXPORTER_SCRAPE_ERRORS.labels(error_type="api")._value.get() == before + 1


@pytest.mark.asyncio
async def test_collect_unexpected_exception_classified_as_unknown() -> None:
    collector = EeroCollector(session_file="/tmp/session.json")  # nosec B108
    mock_client = _mock_client_raising_on_get_networks(RuntimeError("boom"))
    before = EXPORTER_SCRAPE_ERRORS.labels(error_type="unknown")._value.get()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        success = await collector.collect()

    assert success is False
    assert EXPORTER_SCRAPE_ERRORS.labels(error_type="unknown")._value.get() == before + 1
