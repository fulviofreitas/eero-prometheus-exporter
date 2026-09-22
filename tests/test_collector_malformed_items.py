"""Malformed-item / per-item-isolation coverage for the collector's
list-processing sub-collectors, plus a couple of network-level edge cases
identified by the coverage report (missing network id, non-list envelope
eeros).

Each sub-collector is called directly (not through the full `collect()`
cycle) with a hand-built client mock, mirroring the direct-call style
already used by `test_collector_readonly.py`/`test_collector_parsers.py`.
A malformed (non-dict) item is placed ahead of a well-formed one in every
list to prove the per-item `except Exception: ... continue` isolation
lets the family survive and still export the good item's metrics.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from eero_exporter.collector import EeroCollector
from eero_exporter.config import ExporterConfig
from eero_exporter.metrics import (
    DEVICE_INFO,
    DEVICE_WIFI_GENERATION,
    EERO_STATUS,
    NETWORK_EEROS_COUNT,
    PROFILE_PAUSED,
)


def _collector(**overrides: object) -> EeroCollector:
    return EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=ExporterConfig(**overrides),
    )


def _mock_client(**overrides: object) -> MagicMock:
    client = MagicMock()
    for name, value in overrides.items():
        setattr(client, name, value)
    return client


# ---------------------------------------------------------------------------
# _collect_network_metrics: unresolvable network id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_network_with_no_id_and_no_url_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    collector = _collector()
    client = _mock_client()

    with caplog.at_level(logging.WARNING, logger="eero_exporter.collector"):
        await collector._collect_network_metrics(client, {"name": "Orphan Network"})

    assert "Could not extract network ID" in caplog.text
    # Nothing further was attempted -- no get_network call.
    client.get_network.assert_not_called()


# ---------------------------------------------------------------------------
# _collect_eero_metrics: envelope eeros not a list -> coerced to []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eeros_from_envelope_non_list_coerces_to_empty() -> None:
    collector = _collector(eeros_from_envelope=True)
    client = _mock_client()

    result = await collector._collect_eero_metrics(
        client,
        "net-1",
        "Test Network",
        {"eeros": {"data": "not-a-list"}},
    )

    assert result == []
    NETWORK_EEROS_COUNT.labels(network_id="net-1", name="Test Network")._value.get()


# ---------------------------------------------------------------------------
# _collect_eero_metrics: a malformed (non-dict) eero item is skipped, the
# well-formed item that follows is still processed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_eero_item_is_skipped_good_item_survives(
    caplog: pytest.LogCaptureFixture,
) -> None:
    collector = _collector(eeros_from_envelope=False, include_ethernet=False)
    good_eero = {
        "url": "/2.2/networks/net-1/eeros/eero-good",
        "location": "Living Room",
        "model": "eero Pro 6",
        "serial": "SERIAL123",
        "status": "green",
    }
    client = _mock_client(get_eeros=AsyncMock(return_value=["not-a-dict", good_eero]))

    with caplog.at_level(logging.WARNING, logger="eero_exporter.collector"):
        result = await collector._collect_eero_metrics(client, "net-1", "Test Network", {})

    assert "Skipping eero item" in caplog.text
    assert result == ["not-a-dict", good_eero]
    status = EERO_STATUS.labels(
        network_id="net-1", eero_id="eero-good", location="Living Room", model="eero Pro 6"
    )._value.get()
    assert status == 1


# ---------------------------------------------------------------------------
# _collect_device_metrics: malformed device item skipped; good item's
# WiFi-generation gauge (2032-2040) is exercised too.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_device_item_is_skipped_good_item_survives(
    caplog: pytest.LogCaptureFixture,
) -> None:
    collector = _collector()
    good_device = {
        "url": "/2.2/networks/net-1/devices/dev-good",
        "display_name": "Laptop",
        "mac": "aa:bb:cc:dd:ee:ff",
        "connected": True,
        "connectivity": {"frequency": 6115},
    }
    client = _mock_client(get_devices=AsyncMock(return_value=[123, good_device]))

    with caplog.at_level(logging.WARNING, logger="eero_exporter.collector"):
        result = await collector._collect_device_metrics(client, "net-1", "Test Network")

    assert "Skipping device item" in caplog.text
    assert result == [123, good_device]
    info = DEVICE_INFO.labels(
        network_id="net-1", device_id="dev-good", mac="aa:bb:cc:dd:ee:ff"
    )._value
    assert info["name"] == "Laptop"
    wifi_gen = DEVICE_WIFI_GENERATION.labels(
        network_id="net-1", device_id="dev-good", name="Laptop", manufacturer="unknown"
    )._value.get()
    assert wifi_gen == 6


@pytest.mark.asyncio
async def test_devices_read_failure_returns_none() -> None:
    from eero_exporter.eero_adapter import EeroAPIError

    collector = _collector()
    client = _mock_client(get_devices=AsyncMock(side_effect=EeroAPIError("boom", status_code=500)))

    result = await collector._collect_device_metrics(client, "net-1", "Test Network")

    assert result is None


# ---------------------------------------------------------------------------
# _collect_profile_metrics: malformed (non-dict) profile item is skipped
# without raising, good item survives.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_profile_item_is_skipped_good_item_survives(
    caplog: pytest.LogCaptureFixture,
) -> None:
    collector = _collector()
    good_profile = {
        "url": "/2.2/networks/net-1/profiles/profile-good",
        "name": "Kids",
        "paused": True,
    }
    client = _mock_client(
        get_profiles=AsyncMock(return_value=[["nested", "list", "not", "a", "dict"], good_profile])
    )

    with caplog.at_level(logging.WARNING, logger="eero_exporter.collector"):
        result = await collector._collect_profile_metrics(client, "net-1")

    assert "Unexpected profile format" in caplog.text
    assert result == [["nested", "list", "not", "a", "dict"], good_profile]
    paused = PROFILE_PAUSED.labels(
        network_id="net-1", profile_id="profile-good", name="Kids"
    )._value.get()
    assert paused == 1


@pytest.mark.asyncio
async def test_profiles_read_failure_returns_none() -> None:
    from eero_exporter.eero_adapter import EeroAPIError

    collector = _collector()
    client = _mock_client(get_profiles=AsyncMock(side_effect=EeroAPIError("boom", status_code=500)))

    result = await collector._collect_profile_metrics(client, "net-1")

    assert result is None
