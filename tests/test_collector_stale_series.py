"""Regression tests for the stale per-item metric series bug (4.0.1).

Prior to this fix, `EeroCollector` never removed a Prometheus label set once
written: when a device roamed to another eero, changed connection type, was
renamed, or left the network entirely, the previous label combination stayed
frozen at its last value forever. In production this measured as
`count(eero_device_connected == 1)` overstating the true device count by
~54% (212 vs. 138) and growing with pod uptime, plus broken `group_left`
joins from a `device_id` mapping to multiple `name` series.

These tests run two (or more) consecutive `collect()` cycles against a
mocked adapter and inspect the metric objects directly (`metric._metrics`,
the `prometheus_client` child-cache keyed by the exact label-value tuple)
to assert that:

- A renamed/roamed device leaves exactly one series behind.
- A departed device leaves zero series behind.
- A failed family fetch never prunes the prior cycle's good series.
- Two networks never prune each other's series.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eero_exporter.collector import EeroCollector
from eero_exporter.config import ExporterConfig
from eero_exporter.eero_adapter import EeroTransportError
from eero_exporter.metrics import DEVICE_CONNECTED, DEVICE_PAUSED, DEVICE_SIGNAL_STRENGTH

FIXTURES = Path(__file__).parent / "fixtures" / "v8"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _minimal_client(
    *,
    network_id: str = "net-1",
    devices_side_effect: list[Any] | None = None,
) -> MagicMock:
    """A mock client answering only what a devices-only-tier cycle issues.

    `include_devices` is the only family flag left on by the tests below
    (every other core/extended/rf flag is disabled via `_config()`), so the
    only per-cycle adapter surface is `get_networks`/`get_network`/
    `get_eeros`/`get_devices`.
    """
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    client.get_networks = AsyncMock(
        return_value=[
            {"id": network_id, "name": "Test Network", "url": f"/2.2/networks/{network_id}"}
        ]
    )
    client.get_network = AsyncMock(return_value={"status": "connected"})
    client.get_eeros = AsyncMock(return_value=[])

    if devices_side_effect is not None:
        client.get_devices = AsyncMock(side_effect=devices_side_effect)
    else:
        client.get_devices = AsyncMock(return_value=[])

    return client


def _config(**overrides: object) -> ExporterConfig:
    defaults: dict[str, object] = {
        "eeros_from_envelope": False,
        "include_devices": True,
        "include_profiles": False,
        "include_data_usage": False,
        "include_premium": False,
        "include_ethernet": False,
        "include_thread": False,
        "include_port_forwards": False,
        "include_reservations": False,
        "include_blacklist": False,
        "include_insights": False,
        "include_extended": False,
        "include_rf": False,
        "include_per_profile": False,
        "include_per_device": False,
        "include_per_eero": False,
        "include_unverified": False,
    }
    defaults.update(overrides)
    return ExporterConfig(**defaults)


def _device_keys(metric: Any, network_id: str, device_id: str) -> list[tuple[str, ...]]:
    """Every label-tuple `metric` currently holds for one (network, device)."""
    labelnames = metric._labelnames
    net_idx = labelnames.index("network_id")
    dev_idx = labelnames.index("device_id")
    return [
        key for key in metric._metrics if key[net_idx] == network_id and key[dev_idx] == device_id
    ]


def _device(
    device_id: str,
    *,
    name: str = "Phone",
    location: str = "Living Room",
    wireless: bool = True,
    connected: bool = True,
) -> dict[str, Any]:
    return {
        "url": f"/2.2/devices/{device_id}",
        "mac": f"AA:BB:CC:00:00:{device_id.zfill(2)}",
        "display_name": name,
        "connected": connected,
        "wireless": wireless,
        "manufacturer": "Acme",
        "device_type": "phone",
        "source": {"location": location},
        "connectivity": {"signal": "-45 dBm"},
    }


@pytest.mark.asyncio
async def test_device_rename_and_roam_leaves_a_single_series() -> None:
    """A device that changes name/eero/connection-type must not fork into two series."""
    network_id = "net-rename"
    device_id = "d-rename-1"
    cycle_1 = [_device(device_id, name="Old Name", location="Living Room", wireless=True)]
    cycle_2 = [_device(device_id, name="New Name", location="Bedroom", wireless=False)]

    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(),
    )
    client = _minimal_client(network_id=network_id, devices_side_effect=[cycle_1, cycle_2])

    with patch("eero_exporter.collector.EeroClient", return_value=client):
        assert await collector.collect() is True
        assert await collector.collect() is True

    for metric in (DEVICE_CONNECTED, DEVICE_PAUSED, DEVICE_SIGNAL_STRENGTH):
        keys = _device_keys(metric, network_id, device_id)
        assert len(keys) == 1, f"{metric._name}: expected 1 series, found {keys}"

    # And it reflects the *new* label set, not the one from cycle 1.
    labelnames = DEVICE_CONNECTED._labelnames
    (key,) = _device_keys(DEVICE_CONNECTED, network_id, device_id)
    labels = dict(zip(labelnames, key, strict=True))
    assert labels["name"] == "New Name"
    assert labels["connection_type"] == "wired"


@pytest.mark.asyncio
async def test_departed_device_leaves_zero_series() -> None:
    """A device present in cycle 1 and absent in cycle 2 must be fully pruned."""
    network_id = "net-departed"
    device_id = "d-departed-1"
    cycle_1 = [_device(device_id)]
    cycle_2: list[dict[str, Any]] = []

    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(),
    )
    client = _minimal_client(network_id=network_id, devices_side_effect=[cycle_1, cycle_2])

    with patch("eero_exporter.collector.EeroClient", return_value=client):
        assert await collector.collect() is True
        assert len(_device_keys(DEVICE_CONNECTED, network_id, device_id)) == 1

        assert await collector.collect() is True

    assert _device_keys(DEVICE_CONNECTED, network_id, device_id) == []
    assert _device_keys(DEVICE_PAUSED, network_id, device_id) == []
    assert _device_keys(DEVICE_SIGNAL_STRENGTH, network_id, device_id) == []


@pytest.mark.asyncio
async def test_failed_cycle_does_not_prune_prior_good_series() -> None:
    """A transient failure fetching devices must never blank the dashboard."""
    network_id = "net-failed"
    device_id = "d-failed-1"
    cycle_1 = [_device(device_id)]

    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(),
    )
    client = _minimal_client(
        network_id=network_id,
        devices_side_effect=[cycle_1, EeroTransportError("boom")],
    )

    with patch("eero_exporter.collector.EeroClient", return_value=client):
        assert await collector.collect() is True
        (key_before,) = _device_keys(DEVICE_CONNECTED, network_id, device_id)

        # Cycle 2's devices fetch raises -- the family fetch failed, so the
        # collector must leave cycle 1's series untouched rather than prune.
        assert await collector.collect() is True

    keys_after = _device_keys(DEVICE_CONNECTED, network_id, device_id)
    assert keys_after == [key_before]


@pytest.mark.asyncio
async def test_two_networks_do_not_prune_each_other() -> None:
    """Pruning must be scoped per network_id, never applied account-wide."""
    network_a = "net-a"
    network_b = "net-b"
    device_a = "d-a-1"
    device_b = "d-b-1"

    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(),
    )

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get_networks = AsyncMock(
        return_value=[
            {"id": network_a, "name": "A", "url": f"/2.2/networks/{network_a}"},
            {"id": network_b, "name": "B", "url": f"/2.2/networks/{network_b}"},
        ]
    )
    client.get_network = AsyncMock(return_value={"status": "connected"})
    client.get_eeros = AsyncMock(return_value=[])

    devices_by_network = {
        network_a: [_device(device_a)],
        network_b: [_device(device_b)],
    }

    async def _get_devices(net_id: str) -> list[dict[str, Any]]:
        return devices_by_network[net_id]

    client.get_devices = AsyncMock(side_effect=_get_devices)

    with patch("eero_exporter.collector.EeroClient", return_value=client):
        assert await collector.collect() is True
        assert await collector.collect() is True

    assert len(_device_keys(DEVICE_CONNECTED, network_a, device_a)) == 1
    assert len(_device_keys(DEVICE_CONNECTED, network_b, device_b)) == 1
    # Neither network's device was ever observed under the other network_id.
    assert _device_keys(DEVICE_CONNECTED, network_a, device_b) == []
    assert _device_keys(DEVICE_CONNECTED, network_b, device_a) == []
