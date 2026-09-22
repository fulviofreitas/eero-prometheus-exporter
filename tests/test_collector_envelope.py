"""Tests for single-envelope reads (commit 3, §2/§3/§8).

Verifies: `get_network` is called exactly once per network per cycle and
feeds sqm/premium/guest metrics directly (no `get_sqm_settings`,
`get_premium_status`, `get_updates` calls); `get_data_usage_breakdown` is
called exactly once per cycle and `get_devices_data_usage`/
`get_eeros_data_usage_summary` are never called; `eeros_from_envelope=True`
skips the `get_eeros` GET; and `EXPORTER_API_REQUESTS_LAST_CYCLE` tracks the
adapter call count for the cycle.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eero_exporter.collector import EeroCollector
from eero_exporter.config import ExporterConfig
from eero_exporter.metrics import (
    EXPORTER_API_REQUESTS_LAST_CYCLE,
    NETWORK_GUEST_ENABLED,
    NETWORK_PREMIUM_ENABLED,
    NETWORK_SQM_ENABLED,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "v8" / "network.json"


def _load_network_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _mock_client(network_details: dict, data_usage_periods: int = 3) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get_networks = AsyncMock(
        return_value=[{"id": "999001", "name": "Test Network", "url": "/2.2/networks/999001"}]
    )
    client.get_network = AsyncMock(return_value=network_details)
    client.get_eeros = AsyncMock(return_value=[])
    client.get_devices = AsyncMock(return_value=[])
    client.get_profiles = AsyncMock(return_value=[])
    client.get_data_usage = AsyncMock(
        return_value={"series": [{"type": "download", "sum": 100}, {"type": "upload", "sum": 50}]}
    )
    client.get_data_usage_breakdown = AsyncMock(
        return_value={
            "upload": 111,
            "download": 222,
            "eeros": [{"id": "1", "location": "Living Room", "upload": 10, "download": 20}],
            "devices": [{"id": "dev1", "nickname": "Phone", "upload": 5, "download": 15}],
            "profiles": [],
            "unprofiled": [],
        }
    )
    client.get_devices_data_usage = AsyncMock(return_value={"values": []})
    client.get_eeros_data_usage_summary = AsyncMock(return_value={"values": []})
    client.get_thread = AsyncMock(return_value={})
    client.get_forwards = AsyncMock(return_value=[])
    client.get_reservations = AsyncMock(return_value=[])
    client.get_blacklist = AsyncMock(return_value=[])
    client.get_insights = AsyncMock(return_value={})
    client.get_entitlement_features = AsyncMock(return_value={})
    client.get_wpa3_per_band = AsyncMock(return_value={})
    client.get_fast_transition = AsyncMock(return_value={})
    client.get_permissions = AsyncMock(return_value={})
    client.get_members = AsyncMock(return_value={})
    client.get_notification_settings = AsyncMock(return_value={})
    client.has_unread_notifications = AsyncMock(return_value={})
    client.get_advanced_content_filter = AsyncMock(return_value={})
    client.get_subnets_config = AsyncMock(return_value=[])
    client.get_profiles_insights = AsyncMock(return_value={})
    return client


def _base_config(**overrides: object) -> ExporterConfig:
    defaults: dict[str, object] = {
        "include_thread": False,
        "include_port_forwards": False,
        "include_reservations": False,
        "include_blacklist": False,
        "include_insights": False,
        "include_profiles": False,
        "data_usage_periods": ["day", "week", "month"],
    }
    defaults.update(overrides)
    return ExporterConfig(**defaults)


@pytest.mark.asyncio
async def test_get_network_called_once_and_legacy_gets_never_called() -> None:
    network_details = _load_network_fixture()
    collector = EeroCollector(session_file="/tmp/session.json", config=_base_config())  # nosec B108
    mock_client = _mock_client(network_details)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        success = await collector.collect()

    assert success is True
    mock_client.get_network.assert_awaited_once()
    # These GETs are subsumed by the single envelope read and must never be
    # issued -- they are not even defined on the mock, so any call would
    # raise AttributeError-free MagicMock auto-attrs; assert directly.
    assert not hasattr(mock_client, "get_sqm_settings") or not mock_client.get_sqm_settings.called
    assert (
        not hasattr(mock_client, "get_premium_status") or not mock_client.get_premium_status.called
    )
    assert not hasattr(mock_client, "is_premium") or not mock_client.is_premium.called
    assert not hasattr(mock_client, "get_updates") or not mock_client.get_updates.called


@pytest.mark.asyncio
async def test_sqm_premium_guest_fed_from_envelope() -> None:
    network_details = _load_network_fixture()
    collector = EeroCollector(session_file="/tmp/session.json", config=_base_config())  # nosec B108
    mock_client = _mock_client(network_details)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        await collector.collect()

    assert NETWORK_SQM_ENABLED.labels(network_id="999001", name="Test Network")._value.get() == 0
    assert (
        NETWORK_PREMIUM_ENABLED.labels(network_id="999001", name="Test Network")._value.get() == 1
    )
    assert NETWORK_GUEST_ENABLED.labels(network_id="999001", name="Test Network")._value.get() == 0
    assert collector._is_premium is True


@pytest.mark.asyncio
async def test_data_usage_breakdown_called_once_legacy_never_called() -> None:
    network_details = _load_network_fixture()
    config = _base_config(data_usage_periods=["day", "week"])
    collector = EeroCollector(session_file="/tmp/session.json", config=config)  # nosec B108
    mock_client = _mock_client(network_details)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        await collector.collect()

    mock_client.get_data_usage_breakdown.assert_awaited_once()
    assert (
        mock_client.get_data_usage.await_count == len(config.data_usage_periods) + 1
    )  # +trailing hour
    mock_client.get_devices_data_usage.assert_not_awaited()
    mock_client.get_eeros_data_usage_summary.assert_not_awaited()


@pytest.mark.asyncio
async def test_eeros_from_envelope_skips_get_eeros() -> None:
    network_details = _load_network_fixture()
    config = _base_config(eeros_from_envelope=True)
    collector = EeroCollector(session_file="/tmp/session.json", config=config)  # nosec B108
    mock_client = _mock_client(network_details)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        await collector.collect()

    mock_client.get_eeros.assert_not_awaited()


@pytest.mark.asyncio
async def test_eeros_from_envelope_false_calls_get_eeros() -> None:
    network_details = _load_network_fixture()
    config = _base_config(eeros_from_envelope=False)
    collector = EeroCollector(session_file="/tmp/session.json", config=config)  # nosec B108
    mock_client = _mock_client(network_details)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        await collector.collect()

    mock_client.get_eeros.assert_awaited_once()


@pytest.mark.asyncio
async def test_requests_last_cycle_matches_adapter_call_count() -> None:
    network_details = _load_network_fixture()
    config = _base_config(
        eeros_from_envelope=True,
        include_devices=False,
        include_data_usage=False,
        include_premium=False,
        include_extended=False,
    )
    collector = EeroCollector(session_file="/tmp/session.json", config=config)  # nosec B108
    mock_client = _mock_client(network_details)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        await collector.collect()

    # get_networks + get_network only, with eeros_from_envelope=True and
    # every optional family (including the extended tier) disabled.
    assert EXPORTER_API_REQUESTS_LAST_CYCLE._value.get() == 2
