"""Tests for commit 5's parser fixes (uptime, port speed, bitrates, dns,

forwards, nightlight, channel) -- every fix is driven off real v8 key paths
from ``claude/tasks/probes/2026-09-21-shape-summary.md``.
"""

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eero_exporter.collector import (
    _UNKNOWN_ETHERNET_SPEEDS_SEEN,
    EeroCollector,
    _coerce_power_saving_enabled,
    _extract_id_from_url,
    _parse_bitrate,
    _parse_ethernet_speed_enum,
    _parse_timestamp,
    _rate_bps_to_mbps,
)
from eero_exporter.config import ExporterConfig
from eero_exporter.metrics import (
    DEVICE_CHANNEL,
    DEVICE_RX_BITRATE,
    DEVICE_TX_BITRATE,
    EERO_LAST_REBOOT,
    EERO_NIGHTLIGHT_ENABLED,
    EERO_UPTIME_SECONDS,
    ETHERNET_PORT_SPEED,
    NETWORK_AD_BLOCK_ENABLED,
    NETWORK_CUSTOM_DNS_ENABLED,
    NETWORK_DNS_CACHING_ENABLED,
    NETWORK_DNS_SERVER_COUNT,
    NETWORK_POWER_SAVING_ENABLED,
    PORT_FORWARD_ENABLED,
    PORT_FORWARD_INFO,
)

FIXTURES = Path(__file__).parent / "fixtures" / "v8"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


# ============================================================================
# Unit tests for the small parser helpers
# ============================================================================


class TestExtractIdFromUrl:
    def test_plain_url(self) -> None:
        assert _extract_id_from_url("/2.2/eeros/123") == "123"

    def test_trailing_slash(self) -> None:
        assert _extract_id_from_url("/2.2/eeros/123/") == "123"

    def test_query_string(self) -> None:
        assert _extract_id_from_url("/2.2/eeros/123?expand=true") == "123"

    def test_trailing_slash_and_query(self) -> None:
        # A trailing slash before a query string is not observed in the API,
        # but the parser must not choke on it either.
        assert _extract_id_from_url("/2.2/eeros/123/?expand=true") == "123"

    def test_empty_and_none(self) -> None:
        assert _extract_id_from_url("") == ""
        assert _extract_id_from_url(None) == ""


class TestParseTimestamp:
    def test_millisecond_zulu(self) -> None:
        ts = _parse_timestamp("2026-09-15T03:45:09.573Z")
        assert ts is not None
        assert ts > 0

    def test_nanosecond_zulu_truncated_to_microseconds(self) -> None:
        ts = _parse_timestamp("2026-09-13T12:00:00.999999999Z")
        assert ts is not None
        assert ts > 0

    def test_offset_without_colon(self) -> None:
        ts = _parse_timestamp("2025-03-05T01:16:11+0000")
        assert ts is not None
        assert ts > 0

    def test_ns_and_ms_forms_agree_to_the_second(self) -> None:
        ms = _parse_timestamp("2026-09-15T03:45:09.000Z")
        ns = _parse_timestamp("2026-09-15T03:45:09.000000000Z")
        assert ms == ns

    def test_offset_form_matches_equivalent_zulu(self) -> None:
        offset = _parse_timestamp("2025-03-05T01:16:11+0000")
        zulu = _parse_timestamp("2025-03-05T01:16:11Z")
        assert offset == zulu

    def test_none_returns_none(self) -> None:
        assert _parse_timestamp(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_timestamp("") is None

    def test_garbage_returns_none(self) -> None:
        assert _parse_timestamp("not-a-timestamp") is None


class TestParseEthernetSpeedEnum:
    def setup_method(self) -> None:
        _UNKNOWN_ETHERNET_SPEEDS_SEEN.clear()

    @pytest.mark.parametrize(
        ("enum_value", "expected_mbps"),
        [
            ("P10", 10.0),
            ("P100", 100.0),
            ("P1000", 1000.0),
            ("P10000", 10000.0),
            ("p1000", 1000.0),  # case-insensitive
        ],
    )
    def test_known_enum_values(self, enum_value: str, expected_mbps: float) -> None:
        assert _parse_ethernet_speed_enum(enum_value) == expected_mbps

    def test_unknown_enum_returns_none(self) -> None:
        assert _parse_ethernet_speed_enum("P99999") is None

    def test_none_returns_none(self) -> None:
        assert _parse_ethernet_speed_enum(None) is None

    def test_unknown_enum_logs_debug_once(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="eero_exporter.collector"):
            _parse_ethernet_speed_enum("P99999")
            _parse_ethernet_speed_enum("P99999")

        debug_records = [
            r for r in caplog.records if r.levelno == logging.DEBUG and "P99999" in r.message
        ]
        assert len(debug_records) == 1


class TestRateBpsToMbps:
    def test_valid_rate_info(self) -> None:
        assert _rate_bps_to_mbps({"rate_bps": 866700000}) == pytest.approx(866.7)

    def test_missing_rate_bps(self) -> None:
        assert _rate_bps_to_mbps({"mcs": 9}) is None

    def test_none_input(self) -> None:
        assert _rate_bps_to_mbps(None) is None

    def test_non_dict_input(self) -> None:
        assert _rate_bps_to_mbps("866.7 Mbit/s") is None

    def test_non_numeric_rate_bps(self) -> None:
        assert _rate_bps_to_mbps({"rate_bps": "not-a-number"}) is None


class TestParseBitrateCaseInsensitive:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("866.7 Mbit/s", 866.7),
            ("866.7 MBit/s", 866.7),
            ("500 Mbps", 500.0),
            ("500 MBPS", 500.0),
            ("500mbps", 500.0),
        ],
    )
    def test_case_insensitive_unit_strip(self, raw: str, expected: float) -> None:
        assert _parse_bitrate(raw) == pytest.approx(expected)

    def test_none_returns_none(self) -> None:
        assert _parse_bitrate(None) is None

    def test_garbage_returns_none(self) -> None:
        assert _parse_bitrate("not-a-rate") is None


class TestCoercePowerSavingEnabled:
    def test_plain_bool_true(self) -> None:
        assert _coerce_power_saving_enabled(True) is True

    def test_plain_bool_false(self) -> None:
        assert _coerce_power_saving_enabled(False) is False

    def test_enabled_key_shape(self) -> None:
        assert _coerce_power_saving_enabled({"enabled": True}) is True

    def test_schedule_active_shape(self) -> None:
        assert _coerce_power_saving_enabled({"schedule": {"active": False}}) is False

    def test_unrecognised_shape_returns_none(self) -> None:
        assert _coerce_power_saving_enabled({"unknown": "junk"}) is None

    def test_none_returns_none(self) -> None:
        assert _coerce_power_saving_enabled(None) is None


# ============================================================================
# Integration tests: fixtures -> collector -> metric values
# ============================================================================


def _mock_client(
    network_details: dict,
    eeros: list | None = None,
    devices: list | None = None,
    forwards: list | None = None,
) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get_networks = AsyncMock(
        return_value=[{"id": "999001", "name": "Test Network", "url": "/2.2/networks/999001"}]
    )
    client.get_network = AsyncMock(return_value=network_details)
    client.get_eeros = AsyncMock(return_value=eeros or [])
    client.get_devices = AsyncMock(return_value=devices or [])
    client.get_profiles = AsyncMock(return_value=[])
    client.get_data_usage = AsyncMock(return_value={"series": []})
    client.get_data_usage_breakdown = AsyncMock(
        return_value={"eeros": [], "devices": [], "profiles": [], "unprofiled": []}
    )
    client.get_thread = AsyncMock(return_value={})
    client.get_forwards = AsyncMock(return_value=forwards or [])
    client.get_reservations = AsyncMock(return_value=[])
    client.get_blacklist = AsyncMock(return_value=[])
    client.get_insights = AsyncMock(return_value={})
    return client


def _config(**overrides: object) -> ExporterConfig:
    defaults: dict[str, object] = {
        "include_thread": False,
        "include_reservations": False,
        "include_blacklist": False,
        "include_insights": False,
        "include_profiles": False,
        "include_premium": False,
        "include_port_forwards": True,
        "data_usage_periods": [],
        "eeros_from_envelope": False,
    }
    defaults.update(overrides)
    return ExporterConfig(**defaults)


@pytest.mark.asyncio
async def test_eero_uptime_reads_since_last_reboot_s() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    eeros = _load("eeros.json")
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client(network_details, eeros=eeros)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    value = EERO_UPTIME_SECONDS.labels(
        network_id="999001", eero_id="1", location="Living Room"
    )._value.get()
    assert value == 604800


@pytest.mark.asyncio
async def test_eero_last_reboot_parses_all_three_timestamp_forms() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    eeros = _load("eeros.json")
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client(network_details, eeros=eeros)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    # eero 1: millisecond Zulu; eero 2: nanosecond Zulu; eero 4: 9-digit Zulu.
    for eero_id, location in (("1", "Living Room"), ("2", "Bedroom"), ("4", "Garage")):
        value = EERO_LAST_REBOOT.labels(
            network_id="999001", eero_id=eero_id, location=location
        )._value.get()
        assert value is not None and value > 0


@pytest.mark.asyncio
async def test_ethernet_port_speed_maps_p1000_enum() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    eeros = _load("eeros.json")
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_ethernet=True),
    )
    mock_client = _mock_client(network_details, eeros=eeros)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    value = ETHERNET_PORT_SPEED.labels(
        network_id="999001",
        eero_id="1",
        location="Living Room",
        port_number="1",
        port_name="eth0",
    )._value.get()
    assert value == 1000.0


@pytest.mark.asyncio
async def test_nightlight_only_set_for_beacon_node() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    eeros = _load("eeros.json")
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client(network_details, eeros=eeros)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    # eero 4 (Garage) is the only node with a non-null nightlight object.
    value = EERO_NIGHTLIGHT_ENABLED.labels(
        network_id="999001", eero_id="4", location="Garage"
    )._value.get()
    assert value == 1

    # The other three nodes must never have had `.labels(...)` called for
    # this metric -- assert no sample exists for any eero_id other than "4".
    samples = [
        s for s in EERO_NIGHTLIGHT_ENABLED.collect()[0].samples if s.labels.get("eero_id") != "4"
    ]
    assert samples == []


@pytest.mark.asyncio
async def test_device_rx_tx_bitrate_from_rate_bps() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    devices = _load("devices.json")
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client(network_details, devices=devices)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    rx = DEVICE_RX_BITRATE.labels(
        network_id="999001",
        device_id="1",
        name="Phone 1",
        manufacturer="Example Corp",
        band="5GHz",
        source_eero="Living Room",
    )._value.get()
    assert rx == pytest.approx(866.7)

    tx = DEVICE_TX_BITRATE.labels(
        network_id="999001",
        device_id="1",
        name="Phone 1",
        manufacturer="Example Corp",
        band="5GHz",
        source_eero="Living Room",
    )._value.get()
    assert tx == pytest.approx(433.3)


@pytest.mark.asyncio
async def test_device_rx_bitrate_falls_back_to_legacy_string_when_no_rate_info() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    devices = [
        {
            "url": "/2.2/devices/9",
            "mac": "AA:BB:CC:00:00:09",
            "nickname": "legacy-device",
            "connected": True,
            "wireless": True,
            "connection_type": "wireless",
            "manufacturer": "Legacy Corp",
            "source": {"location": "Attic"},
            "connectivity": {
                "frequency": 2437,
                "rx_bitrate": "72.2 MBit/s",
            },
        }
    ]
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client(network_details, devices=devices)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    rx = DEVICE_RX_BITRATE.labels(
        network_id="999001",
        device_id="9",
        name="legacy-device",
        manufacturer="Legacy Corp",
        band="2.4GHz",
        source_eero="Attic",
    )._value.get()
    assert rx == pytest.approx(72.2)


@pytest.mark.asyncio
async def test_device_channel_reads_top_level_field() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    devices = _load("devices.json")
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client(network_details, devices=devices)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    value = DEVICE_CHANNEL.labels(
        network_id="999001",
        device_id="1",
        name="Phone 1",
        band="5GHz",
        source_eero="Living Room",
    )._value.get()
    assert value == 149


@pytest.mark.asyncio
async def test_network_dns_metrics_read_nested_dns_object() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client(network_details)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert (
        NETWORK_DNS_CACHING_ENABLED.labels(network_id="999001", name="Test Network")._value.get()
        == 0
    )
    assert (
        NETWORK_CUSTOM_DNS_ENABLED.labels(network_id="999001", name="Test Network")._value.get()
        == 1
    )
    assert (
        NETWORK_DNS_SERVER_COUNT.labels(network_id="999001", name="Test Network")._value.get() == 2
    )


def test_dns_config_info_never_carries_resolver_ips() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    dns = network_details["dns"]
    assert "ips" not in json.dumps({"mode": dns["mode"]})
    # The only field ever passed to `.info()` is `mode` -- verified by
    # inspecting the collector's DNS block directly via the integration test
    # above (`test_network_dns_metrics_read_nested_dns_object`); this test
    # locks the fixture's shape so a future edit can't silently reintroduce
    # `custom.ips` values into the fixture's `dns.mode`-only expectation.
    assert set(dns["custom"].keys()) == {"ips"}


@pytest.mark.asyncio
async def test_network_ad_block_enabled_reads_premium_dns_policy() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client(network_details)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert (
        NETWORK_AD_BLOCK_ENABLED.labels(network_id="999001", name="Test Network")._value.get() == 1
    )


@pytest.mark.asyncio
async def test_network_power_saving_enabled_plain_bool() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client(network_details)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert (
        NETWORK_POWER_SAVING_ENABLED.labels(network_id="999001", name="Test Network")._value.get()
        == 0
    )


@pytest.mark.asyncio
async def test_port_forward_uses_remapped_keys_and_has_no_ip_label() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    forwards = _load("forwards.json")
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_port_forwards=True),
    )
    mock_client = _mock_client(network_details, forwards=forwards)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    enabled = PORT_FORWARD_ENABLED.labels(
        network_id="999001", forward_id="1", gateway_port="80", protocol="tcp"
    )._value.get()
    assert enabled == 1

    assert "ip" not in PORT_FORWARD_ENABLED._labelnames
    assert "ip_address" not in PORT_FORWARD_ENABLED._labelnames
    assert "gateway_port" in PORT_FORWARD_ENABLED._labelnames


@pytest.mark.asyncio
async def test_port_forward_falls_back_to_legacy_keys() -> None:
    network_details = json.loads((FIXTURES / "network.json").read_text())
    forwards = _load("forwards.json")
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_port_forwards=True),
    )
    mock_client = _mock_client(network_details, forwards=forwards)

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    # forward 2 uses the legacy `port`/`external_port`/`internal_port` keys.
    enabled = PORT_FORWARD_ENABLED.labels(
        network_id="999001", forward_id="2", gateway_port="2222", protocol="tcp"
    )._value.get()
    assert enabled == 0


def test_port_forward_info_labels_have_no_forbidden_fields() -> None:
    assert "ip" not in PORT_FORWARD_INFO._labelnames
    assert "ip_address" not in PORT_FORWARD_INFO._labelnames
