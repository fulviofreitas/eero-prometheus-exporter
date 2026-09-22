"""Coverage for `_collect_insights_metrics` (network-level insights, §11 of
the v8 probe), which was previously exercised in no test (always disabled
in every other test module's config).

Covers: series-based responses, totals-fallback responses, per-insight-type
independent failure isolation, empty/missing data, and malformed shapes.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from eero_exporter.collector import EeroCollector
from eero_exporter.config import ExporterConfig
from eero_exporter.eero_adapter import EeroAPIError, EeroPremiumRequiredError
from eero_exporter.metrics import INSIGHTS_ADBLOCK_TOTAL, INSIGHTS_BLOCKED_TOTAL


def _collector() -> EeroCollector:
    return EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=ExporterConfig(include_insights=True),
    )


@pytest.mark.asyncio
async def test_series_based_response_sums_by_category() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_insights = AsyncMock(
        return_value={
            "series": [
                {"insight_type": "adblock", "sum": 7},
                {"category": "other", "values": [{"value": 1}, {"value": 2}]},
            ]
        }
    )

    await collector._collect_insights_metrics(client, "net-1")

    assert client.get_insights.await_count == 3  # adblock, blocked, inspected
    value = INSIGHTS_ADBLOCK_TOTAL.labels(network_id="net-1", category="adblock")._value.get()
    assert value == 7.0


@pytest.mark.asyncio
async def test_totals_fallback_used_when_no_series() -> None:
    collector = _collector()
    client = MagicMock()

    async def _get_insights(_network_id: str, **kwargs: object) -> dict:
        insight_type = kwargs["insight_type"]
        return {"series": [], "totals": {insight_type: 42}}

    client.get_insights = AsyncMock(side_effect=_get_insights)

    await collector._collect_insights_metrics(client, "net-1")

    value = INSIGHTS_BLOCKED_TOTAL.labels(network_id="net-1", category="blocked")._value.get()
    assert value == 42.0


@pytest.mark.asyncio
async def test_totals_fallback_uses_generic_total_key() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_insights = AsyncMock(return_value={"series": [], "totals": {"total": 5}})

    await collector._collect_insights_metrics(client, "net-1")

    value = INSIGHTS_ADBLOCK_TOTAL.labels(network_id="net-1", category="adblock")._value.get()
    assert value == 5.0


@pytest.mark.asyncio
async def test_totals_non_numeric_value_is_skipped() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_insights = AsyncMock(
        return_value={"series": [], "totals": {"adblock": "not-a-number"}}
    )

    # Must not raise.
    await collector._collect_insights_metrics(client, "net-1")


@pytest.mark.asyncio
async def test_totals_not_a_dict_is_ignored() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_insights = AsyncMock(return_value={"series": [], "totals": "not-a-dict"})

    await collector._collect_insights_metrics(client, "net-1")


@pytest.mark.asyncio
async def test_series_not_a_list_falls_back_to_empty() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_insights = AsyncMock(return_value={"series": "not-a-list", "totals": {}})

    await collector._collect_insights_metrics(client, "net-1")


@pytest.mark.asyncio
async def test_series_items_that_are_not_dicts_are_skipped() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_insights = AsyncMock(return_value={"series": ["not-a-dict", {"sum": 1}]})

    await collector._collect_insights_metrics(client, "net-1")


@pytest.mark.asyncio
async def test_empty_response_is_a_no_op() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_insights = AsyncMock(return_value={})

    await collector._collect_insights_metrics(client, "net-1")


@pytest.mark.asyncio
async def test_one_insight_type_failing_does_not_block_others() -> None:
    """A 403 (premium required) on 'adblock' doesn't stop 'blocked'/'inspected'."""
    collector = _collector()
    client = MagicMock()

    async def _get_insights(_network_id: str, **kwargs: object) -> dict:
        if kwargs["insight_type"] == "adblock":
            raise EeroPremiumRequiredError("adblock requires Eero Plus")
        return {"series": [{"sum": 3}]}

    client.get_insights = AsyncMock(side_effect=_get_insights)

    await collector._collect_insights_metrics(client, "net-1")

    value = INSIGHTS_BLOCKED_TOTAL.labels(network_id="net-1", category="blocked")._value.get()
    assert value == 3.0


@pytest.mark.asyncio
async def test_generic_api_error_is_logged_and_skipped() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_insights = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )

    # Must not raise even when every insight type fails.
    await collector._collect_insights_metrics(client, "net-1")
