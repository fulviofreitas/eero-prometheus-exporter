"""Tests for the data_usage feature: helpers, adapter wiring, upstream contract."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import eero
import pytest

from eero_exporter.collector import (
    _data_usage_period_payload,
    _get_timezone,
    _series_sum,
)
from eero_exporter.eero_adapter import EeroClient, EeroValidationError

# ---------------------------------------------------------------------------
# Upstream contract guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method",
    [
        "get_data_usage",
        "get_devices_data_usage",
        "get_eeros_data_usage_summary",
        "get_eero_data_usage",
        "get_device_data_usage",
        "get_profile_data_usage",
    ],
)
def test_eero_client_exposes_data_usage_family(method: str) -> None:
    """The pinned eero-api must expose every data-usage facade method the adapter uses.

    Guards against an upstream rename/removal of any member of the v8
    kw-only data-usage family (``eero.EeroClient.get_*data_usage*``).
    """
    assert hasattr(eero.EeroClient, method)


# ---------------------------------------------------------------------------
# _get_timezone
# ---------------------------------------------------------------------------


def test_get_timezone_from_dict_value() -> None:
    assert _get_timezone({"value": "America/New_York"}).key == "America/New_York"


def test_get_timezone_from_dict_name() -> None:
    assert _get_timezone({"name": "Europe/London"}).key == "Europe/London"


def test_get_timezone_from_string() -> None:
    assert _get_timezone("America/Chicago").key == "America/Chicago"


def test_get_timezone_unknown_falls_back_to_utc() -> None:
    assert _get_timezone("Not/ARealZone").key == "UTC"


def test_get_timezone_none_falls_back_to_utc() -> None:
    assert _get_timezone(None).key == "UTC"


def test_get_timezone_empty_dict_falls_back_to_utc() -> None:
    assert _get_timezone({}).key == "UTC"


# ---------------------------------------------------------------------------
# _data_usage_period_payload
# ---------------------------------------------------------------------------


def test_day_period_payload() -> None:
    now = datetime(2026, 1, 7, 15, 30, tzinfo=UTC)  # Wednesday
    period, cadence, payload = _data_usage_period_payload("day", ZoneInfo("UTC"), now=now)
    assert period == "day"
    assert cadence == "hourly"
    assert payload["start"] == "2026-01-07T00:00:00Z"
    assert payload["end"] == "2026-01-07T23:59:59Z"
    assert payload["cadence"] == "hourly"
    assert payload["timezone"] == "UTC"


def test_week_period_starts_on_sunday() -> None:
    # 2026-01-07 is a Wednesday; the enclosing eero week starts Sun 2026-01-04.
    now = datetime(2026, 1, 7, 9, 0, tzinfo=UTC)
    _, cadence, payload = _data_usage_period_payload("week", ZoneInfo("UTC"), now=now)
    assert cadence == "daily"
    assert payload["start"] == "2026-01-04T00:00:00Z"
    assert payload["end"] == "2026-01-10T23:59:59Z"


def test_week_period_sunday_edge_case() -> None:
    """When the reference day *is* Sunday, the week starts that same day.

    Regression guard for the off-by-one where ``weekday() + 1`` shifted a
    Sunday back a full week instead of to the start of the current week.
    """
    now = datetime(2026, 1, 4, 13, 45, tzinfo=UTC)  # Sunday
    _, _, payload = _data_usage_period_payload("week", ZoneInfo("UTC"), now=now)
    assert payload["start"] == "2026-01-04T00:00:00Z"
    assert payload["end"] == "2026-01-10T23:59:59Z"


def test_month_period_payload() -> None:
    now = datetime(2026, 3, 17, 8, 0, tzinfo=UTC)
    _, cadence, payload = _data_usage_period_payload("month", ZoneInfo("UTC"), now=now)
    assert cadence == "daily"
    assert payload["start"] == "2026-03-01T00:00:00Z"
    assert payload["end"] == "2026-03-31T23:59:59Z"


def test_month_period_december_rolls_to_next_year() -> None:
    now = datetime(2026, 12, 10, 0, 0, tzinfo=UTC)
    _, _, payload = _data_usage_period_payload("month", ZoneInfo("UTC"), now=now)
    assert payload["start"] == "2026-12-01T00:00:00Z"
    assert payload["end"] == "2026-12-31T23:59:59Z"


def test_invalid_period_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported data usage period"):
        _data_usage_period_payload("year", ZoneInfo("UTC"))


# ---------------------------------------------------------------------------
# _series_sum
# ---------------------------------------------------------------------------


def test_series_sum_uses_sum_field() -> None:
    assert _series_sum({"sum": 1024}) == 1024.0


def test_series_sum_computes_from_values() -> None:
    series = {"values": [{"value": 10}, {"value": 20}, {"value": 5}]}
    assert _series_sum(series) == 35.0


def test_series_sum_skips_non_numeric_values() -> None:
    series = {"values": [{"value": 10}, {"value": None}, {"value": "bad"}, {}]}
    assert _series_sum(series) == 10.0


def test_series_sum_empty_returns_none() -> None:
    assert _series_sum({}) is None
    assert _series_sum({"values": []}) is None


def test_series_sum_invalid_sum_returns_none() -> None:
    assert _series_sum({"sum": "not-a-number"}) is None


# ---------------------------------------------------------------------------
# Adapter delegation -- kw-only data-usage family
# ---------------------------------------------------------------------------

PERIODS = [
    ("day", "hourly"),
    ("week", "daily"),
    ("month", "daily"),
]


@pytest.mark.parametrize(("period", "cadence"), PERIODS)
async def test_adapter_get_data_usage_delegates_kw_only(period: str, cadence: str) -> None:
    """The adapter forwards network-level usage as kw-only args and unwraps the envelope."""
    _, _, payload = _data_usage_period_payload(period, ZoneInfo("UTC"))
    adapter = EeroClient()
    facade = AsyncMock()
    facade.get_data_usage = AsyncMock(
        return_value={"meta": {"code": 200}, "data": {"series": [{"sum": 42}]}}
    )
    adapter._client = facade

    result = await adapter.get_data_usage("net-1", **payload)

    facade.get_data_usage.assert_awaited_once_with(
        "net-1",
        start=payload["start"],
        end=payload["end"],
        cadence=cadence,
        timezone=payload["timezone"],
    )
    assert result == {"series": [{"sum": 42}]}


@pytest.mark.parametrize(("period", "cadence"), PERIODS)
async def test_adapter_get_devices_data_usage_delegates_kw_only(period: str, cadence: str) -> None:
    """The adapter forwards per-device usage as kw-only args and unwraps the envelope."""
    _, _, payload = _data_usage_period_payload(period, ZoneInfo("UTC"))
    adapter = EeroClient()
    facade = AsyncMock()
    facade.get_devices_data_usage = AsyncMock(
        return_value={"meta": {"code": 200}, "data": {"values": []}}
    )
    adapter._client = facade

    result = await adapter.get_devices_data_usage("net-1", **payload)

    facade.get_devices_data_usage.assert_awaited_once_with(
        "net-1",
        start=payload["start"],
        end=payload["end"],
        cadence=cadence,
        timezone=payload["timezone"],
        profile_id=None,
    )
    assert result == {"values": []}


@pytest.mark.parametrize(("period", "cadence"), PERIODS)
async def test_adapter_get_eeros_data_usage_summary_delegates_kw_only(
    period: str, cadence: str
) -> None:
    """The adapter forwards the eeros-summary read as kw-only args and unwraps the envelope."""
    _, _, payload = _data_usage_period_payload(period, ZoneInfo("UTC"))
    adapter = EeroClient()
    facade = AsyncMock()
    facade.get_eeros_data_usage_summary = AsyncMock(
        return_value={"meta": {"code": 200}, "data": {"values": []}}
    )
    adapter._client = facade

    result = await adapter.get_eeros_data_usage_summary("net-1", **payload)

    facade.get_eeros_data_usage_summary.assert_awaited_once_with(
        "net-1",
        start=payload["start"],
        end=payload["end"],
        cadence=cadence,
        timezone=payload["timezone"],
    )
    assert result == {"values": []}


async def test_adapter_get_eero_data_usage_fallback_delegates_kw_only() -> None:
    """The per-eero fallback forwards (eero_id, network_id) positionally, then kw-only fields."""
    adapter = EeroClient()
    facade = AsyncMock()
    facade.get_eero_data_usage = AsyncMock(
        return_value={"meta": {"code": 200}, "data": {"values": []}}
    )
    adapter._client = facade

    result = await adapter.get_eero_data_usage(
        "net-1", "eero-1", start="s", end="e", cadence="daily", timezone="UTC"
    )

    facade.get_eero_data_usage.assert_awaited_once_with(
        "eero-1", "net-1", start="s", end="e", cadence="daily", timezone="UTC"
    )
    assert result == {"values": []}


async def test_adapter_get_data_usage_requires_initialized_client() -> None:
    """Calling the adapter outside its context manager raises a clear error."""
    from eero_exporter.eero_adapter import EeroAPIError

    adapter = EeroClient()
    with pytest.raises(EeroAPIError, match="Client not initialized"):
        await adapter.get_data_usage("net-1", start="s", end="e", cadence="daily")


async def test_adapter_get_data_usage_rejects_invalid_cadence() -> None:
    """A cadence the SDK rejects surfaces as EeroValidationError, not TypeError."""
    from eero.exceptions import EeroValidationException  # type: ignore[import-untyped]

    adapter = EeroClient()
    facade = AsyncMock()
    facade.get_data_usage = AsyncMock(
        side_effect=EeroValidationException("cadence", "must be one of ('daily', 'hourly')")
    )
    adapter._client = facade

    with pytest.raises(EeroValidationError):
        await adapter.get_data_usage("net-1", start="s", end="e", cadence="weekly")
