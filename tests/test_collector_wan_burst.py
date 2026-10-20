"""The ``--wan-burst`` family: the exporter's one opt-in non-authentication POST.

Every test runs a full ``collect()`` against the fixture mesh from
``tests/test_collector_readonly.py`` with the settle wait patched to zero, and
asserts what the collector may and may not send: at most one burst per
network per cycle, never within the cooldown, never retried, skipped in
bridge mode, disabled by the circuit breaker, and "unknown beats zero" --
the gauges are absent whenever no fresh sample exists.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from prometheus_client import CollectorRegistry

from eero_exporter import collector as collector_mod
from eero_exporter.collector import EeroCollector, _sum_device_usage
from eero_exporter.config import ExporterConfig
from eero_exporter.eero_adapter import (
    EeroAccessDeniedError,
    EeroTransportError,
    EeroValidationError,
)
from eero_exporter.metrics import (
    EXPORTER_API_REQUESTS_LAST_CYCLE,
    EXPORTER_SCRAPE_DURATION,
    WAN_BURST_ENABLED,
    WAN_BURST_SAMPLE_TIMESTAMP,
    WAN_BURST_WAIT_SECONDS,
    WAN_DOWNLOAD_MBPS,
    WAN_UPLOAD_MBPS,
    register_metrics,
)
from tests.test_collector_readonly import _config, _full_mock_client, _load

NETWORK_ID = "999001"


def _device(down: Any, up: Any, *, connected: bool = True, mac: str = "aa") -> dict[str, Any]:
    return {
        "url": f"/2.2/networks/{NETWORK_ID}/devices/{mac}",
        "mac": mac,
        "connected": connected,
        "usage": {"down_mbps": down, "up_mbps": up},
    }


BURST_DEVICES = [
    _device(10.5, 1.5, mac="a1"),
    _device(20.0, 2.0, mac="a2"),
    _device(999.0, 999.0, connected=False, mac="a3"),  # excluded
]


def _samples(metric: Any) -> dict[tuple[str, ...], float]:
    return {
        tuple(s.labels.values()): s.value for family in metric.collect() for s in family.samples
    }


def _clear_wan_series() -> None:
    for metric in (WAN_DOWNLOAD_MBPS, WAN_UPLOAD_MBPS, WAN_BURST_SAMPLE_TIMESTAMP):
        metric.clear()


def _client(devices_after_burst: list[dict[str, Any]] | None = None) -> Any:
    client = _full_mock_client()
    client.request_wan_burst = AsyncMock(return_value=None)
    normal = _load("devices.json")
    burst = BURST_DEVICES if devices_after_burst is None else devices_after_burst

    async def get_devices(network_id: str, *, refresh_cache: bool = False) -> Any:
        return burst if refresh_cache else normal

    client.get_devices = AsyncMock(side_effect=get_devices)
    return client


def _collector(**overrides: Any) -> EeroCollector:
    return EeroCollector(
        session_file="/tmp/session.json", config=_config(wan_burst=True, **overrides)  # nosec B108
    )


async def _run(coll: EeroCollector, client: Any) -> bool:
    with patch("eero_exporter.collector.EeroClient", return_value=client):
        return await coll.collect()


@pytest.fixture(autouse=True)
def _fast_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_wan_series()
    monkeypatch.setattr(collector_mod, "_WAN_BURST_SETTLE_SECONDS", 0.0)


# ---------------------------------------------------------------------------
# Flag off: nothing changes
# ---------------------------------------------------------------------------


async def test_flag_off_never_requests_a_burst() -> None:
    client = _client()
    coll = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    assert await _run(coll, client) is True
    client.request_wan_burst.assert_not_called()
    assert all(not c.kwargs.get("refresh_cache") for c in client.get_devices.call_args_list)
    assert EXPORTER_API_REQUESTS_LAST_CYCLE._value.get() == 29
    assert _samples(WAN_DOWNLOAD_MBPS) == {}


def test_flag_off_does_not_register_the_family() -> None:
    registry = CollectorRegistry()
    register_metrics(ExporterConfig(), registry)
    names = {m.name for m in registry.collect()}
    assert "eero_network_wan_download_mbps" not in names
    assert "eero_exporter_wan_burst_enabled" not in names

    registry_on = CollectorRegistry()
    register_metrics(ExporterConfig(wan_burst=True), registry_on)
    names_on = {m.name for m in registry_on.collect()}
    assert {"eero_network_wan_download_mbps", "eero_network_wan_upload_mbps"} <= names_on


# ---------------------------------------------------------------------------
# Flag on: one POST, one cache-bypassing GET, summed over connected devices
# ---------------------------------------------------------------------------


async def test_flag_on_bursts_once_then_reads_devices_fresh() -> None:
    client = _client()
    coll = _collector()
    assert await _run(coll, client) is True

    client.request_wan_burst.assert_awaited_once_with(NETWORK_ID)
    fresh = [c for c in client.get_devices.call_args_list if c.kwargs.get("refresh_cache")]
    assert len(fresh) == 1
    assert EXPORTER_API_REQUESTS_LAST_CYCLE._value.get() == 29 + 2

    labels = (NETWORK_ID, "Test Network")
    assert _samples(WAN_DOWNLOAD_MBPS)[labels] == pytest.approx(30.5)
    assert _samples(WAN_UPLOAD_MBPS)[labels] == pytest.approx(3.5)
    assert _samples(WAN_BURST_SAMPLE_TIMESTAMP)[labels] > 0
    assert WAN_BURST_ENABLED._value.get() == 1
    assert WAN_BURST_WAIT_SECONDS._value.get() == 0.0


async def test_settle_wait_is_excluded_from_scrape_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collector_mod, "_WAN_BURST_SETTLE_SECONDS", 0.05)
    coll = _collector()
    assert await _run(coll, _client()) is True
    assert WAN_BURST_WAIT_SECONDS._value.get() == pytest.approx(0.05)
    # The cycle itself takes well under 50 ms against mocks, so an unadjusted
    # duration would exceed the settle wait.
    assert EXPORTER_SCRAPE_DURATION._value.get() < 0.05


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


async def test_second_cycle_inside_cooldown_keeps_the_sample_without_a_post() -> None:
    client = _client()
    coll = _collector()
    assert await _run(coll, client) is True
    assert await _run(coll, client) is True

    client.request_wan_burst.assert_awaited_once()
    assert EXPORTER_API_REQUESTS_LAST_CYCLE._value.get() == 29  # no burst, no extra GET
    assert _samples(WAN_DOWNLOAD_MBPS)[(NETWORK_ID, "Test Network")] == pytest.approx(30.5)


async def test_bursts_again_once_the_cooldown_has_elapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    coll = _collector()
    assert await _run(coll, client) is True

    real = collector_mod.time.monotonic
    monkeypatch.setattr(collector_mod.time, "monotonic", lambda: real() + 61.0)
    assert await _run(coll, client) is True
    assert client.request_wan_burst.await_count == 2


async def test_cooldown_is_per_network() -> None:
    client = _client()
    client.get_networks = AsyncMock(
        return_value=[
            {"id": NETWORK_ID, "name": "Test Network"},
            {"id": "654321", "name": "Second"},
        ]
    )
    coll = _collector()
    assert await _run(coll, client) is True
    assert sorted(c.args[0] for c in client.request_wan_burst.await_args_list) == sorted(
        [NETWORK_ID, "654321"]
    )


# ---------------------------------------------------------------------------
# Skips and absence
# ---------------------------------------------------------------------------


async def test_bridge_mode_network_is_skipped() -> None:
    client = _client()
    network = dict(_load("network.json"))
    network["connection"] = {"mode": "bridge"}
    client.get_network = AsyncMock(return_value=network)
    coll = _collector()
    assert await _run(coll, client) is True
    client.request_wan_burst.assert_not_called()
    assert _samples(WAN_DOWNLOAD_MBPS) == {}


async def test_unknown_usage_leaves_the_gauge_absent_not_zero() -> None:
    devices = [
        _device(None, 4.0, mac="b1"),
        _device("12", True, mac="b2"),  # string and bool are not numbers
        _device(7.0, 1.0, connected=False, mac="b3"),
    ]
    coll = _collector()
    assert await _run(coll, _client(devices)) is True
    assert _samples(WAN_DOWNLOAD_MBPS) == {}
    assert _samples(WAN_UPLOAD_MBPS)[(NETWORK_ID, "Test Network")] == pytest.approx(4.0)


async def test_no_connected_devices_leaves_everything_absent() -> None:
    coll = _collector()
    assert await _run(coll, _client([_device(5.0, 5.0, connected=False)])) is True
    assert _samples(WAN_DOWNLOAD_MBPS) == {}
    assert _samples(WAN_UPLOAD_MBPS) == {}
    assert _samples(WAN_BURST_SAMPLE_TIMESTAMP) == {}


def test_sum_device_usage_ignores_malformed_items() -> None:
    devices: list[Any] = ["junk", None, {"connected": True, "usage": "n/a"}, _device(1, 2)]
    assert _sum_device_usage(devices, "down_mbps") == 1.0
    assert _sum_device_usage(devices, "up_mbps") == 2.0
    assert _sum_device_usage([], "down_mbps") is None


# ---------------------------------------------------------------------------
# Failures: never retried, cooldown consumed, breaker
# ---------------------------------------------------------------------------


async def test_failed_burst_is_not_retried_and_prunes_the_sample() -> None:
    client = _client()
    coll = _collector()
    assert await _run(coll, client) is True  # a good sample first
    assert _samples(WAN_DOWNLOAD_MBPS)

    coll._wan_burst_last.clear()  # open the window again
    client.request_wan_burst = AsyncMock(side_effect=EeroTransportError("boom"))
    assert await _run(coll, client) is True
    client.request_wan_burst.assert_awaited_once()
    fresh = [c for c in client.get_devices.call_args_list if c.kwargs.get("refresh_cache")]
    assert len(fresh) == 1  # only the first cycle's read
    assert _samples(WAN_DOWNLOAD_MBPS) == {}
    assert _samples(WAN_BURST_SAMPLE_TIMESTAMP) == {}

    # The failed attempt consumed the cooldown: the next cycle does not POST.
    assert await _run(coll, client) is True
    client.request_wan_burst.assert_awaited_once()


async def test_failed_post_burst_read_prunes_the_sample() -> None:
    client = _client()

    async def get_devices(network_id: str, *, refresh_cache: bool = False) -> Any:
        if refresh_cache:
            raise EeroTransportError("timeout")
        return _load("devices.json")

    client.get_devices = AsyncMock(side_effect=get_devices)
    coll = _collector()
    assert await _run(coll, client) is True
    assert _samples(WAN_DOWNLOAD_MBPS) == {}


async def test_breaker_trips_after_three_definitive_failures() -> None:
    client = _client()
    client.request_wan_burst = AsyncMock(side_effect=EeroAccessDeniedError("no"))
    coll = _collector()
    for _ in range(3):
        coll._wan_burst_last.clear()
        assert await _run(coll, client) is True
    assert coll._wan_burst_tripped is True
    assert WAN_BURST_ENABLED._value.get() == 0

    coll._wan_burst_last.clear()
    client.request_wan_burst = AsyncMock(return_value=None)
    assert await _run(coll, client) is True
    client.request_wan_burst.assert_not_called()


async def test_transport_and_validation_mix_only_counts_definitive_failures() -> None:
    client = _client()
    coll = _collector()
    outcomes = [
        EeroValidationError("bad"),
        EeroTransportError("net"),  # resets nothing, counts nothing
        EeroValidationError("bad"),
    ]
    for exc in outcomes:
        coll._wan_burst_last.clear()
        client.request_wan_burst = AsyncMock(side_effect=exc)
        assert await _run(coll, client) is True
    assert coll._wan_burst_tripped is False
    assert coll._wan_burst_failures == 2
    assert WAN_BURST_ENABLED._value.get() == 1


async def test_success_resets_the_failure_count() -> None:
    client = _client()
    coll = _collector()
    coll._wan_burst_failures = 2
    assert await _run(coll, client) is True
    assert coll._wan_burst_failures == 0
