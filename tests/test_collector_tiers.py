"""Tests for the commit-8 tiers: `rf` (default on), `per_device`, `per_eero`,
`per_profile`, and `unverified` (all default off).

Covers: metrics populated from fixtures, tier-off => no adapter calls and no
registry entries, expected-state exceptions classified without a scrape
error, and unverified key-logging stubs that never leak a fixture value.
"""

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from eero_exporter.collector import EeroCollector
from eero_exporter.config import ExporterConfig
from eero_exporter.eero_adapter import EeroNotFoundError, EeroPremiumRequiredError
from eero_exporter.metrics import (
    BACKUP_ACCESS_POINT_ENABLED,
    BACKUP_ACCESS_POINTS_COUNT,
    CELLULAR_BACKUP_OUTAGES_COUNT,
    CELLULAR_BACKUP_USAGE_ITEMS_COUNT,
    DEVICE_INSIGHTS_TOTAL,
    EERO_CHANNEL_BUSY_MINUTES,
    EERO_CHANNEL_UTILIZATION_AVG_PERCENT,
    EERO_EERO_CONNECTIONS_COUNT,
    EERO_OUICHECK_CAN_ADD,
    EXPORTER_API_REQUESTS,
    EXPORTER_SCRAPE_ERRORS,
    FAMILY_TIER,
    NETWORK_AC_COMPAT,
    NETWORK_MULTISTATICIP_ENABLED,
    NETWORK_POWER_SAVING_SCHEDULES_COUNT,
    NETWORK_ROUTING_DEVICES_COUNT,
    NETWORK_SCAN_CONFLICTING_SSID,
    PROFILE_DNS_POLICY_APPLICATIONS_COUNT,
    SPEED_TESTS_TOTAL,
    register_metrics,
)

FIXTURES = Path(__file__).parent / "fixtures" / "v8"


def _load(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text())


def _load_network_fixture() -> dict:
    return json.loads((FIXTURES / "network.json").read_text())


def _mock_client(**overrides: object) -> MagicMock:
    """Every core/extended/tier call the collector may issue, all mocked."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get_networks = AsyncMock(
        return_value=[{"id": "999001", "name": "Test Network", "url": "/2.2/networks/999001"}]
    )
    client.get_network = AsyncMock(return_value=_load_network_fixture())
    client.get_eeros = AsyncMock(return_value=_load("eeros.json"))
    client.get_devices = AsyncMock(return_value=_load("devices.json"))
    client.get_profiles = AsyncMock(return_value=_load("profiles.json"))
    client.get_data_usage = AsyncMock(return_value={"series": []})
    client.get_data_usage_breakdown = AsyncMock(
        return_value={"eeros": [], "devices": [], "profiles": [], "unprofiled": []}
    )
    client.get_forwards = AsyncMock(return_value=[])
    client.get_reservations = AsyncMock(return_value=[])
    client.get_blacklist = AsyncMock(return_value=[])
    client.get_insights = AsyncMock(return_value={})

    client.get_entitlement_features = AsyncMock(return_value=_load("entitlements.json"))
    client.get_wpa3_per_band = AsyncMock(return_value=_load("wpa3.json"))
    client.get_fast_transition = AsyncMock(return_value=_load("fast_transition.json"))
    client.get_permissions = AsyncMock(return_value=_load("permissions.json"))
    client.get_members = AsyncMock(return_value=_load("members.json"))
    client.get_notification_settings = AsyncMock(return_value=_load("notifications.json"))
    client.has_unread_notifications = AsyncMock(return_value={"has_unread": True})
    client.get_advanced_content_filter = AsyncMock(return_value=_load("dns_filter.json"))
    client.get_subnets_config = AsyncMock(return_value=_load("subnets.json"))
    client.get_profiles_insights = AsyncMock(return_value=_load("profiles_insights.json"))

    # rf tier
    client.get_channel_utilization = AsyncMock(return_value=_load("channel_utilization.json"))

    # per_device tier
    client.get_devices_insights = AsyncMock(return_value=_load("devices_insights.json"))

    # per_eero tier
    client.get_nightlight = AsyncMock(return_value={})
    client.get_connections = AsyncMock(return_value=_load("eero_connections.json"))
    client.get_ouicheck = AsyncMock(return_value=_load("ouicheck.json"))

    # per_profile tier
    client.get_dns_policy_applications = AsyncMock(
        return_value=_load("dns_policy_applications.json")
    )

    # unverified tier
    client.get_thread = AsyncMock(return_value=_load("thread.json"))
    client.get_routing = AsyncMock(return_value=_load("routing.json"))
    client.list_backup_access_points = AsyncMock(return_value=_load("backup_access_points.json"))
    client.get_cellular_backup_usage = AsyncMock(return_value=_load("cellular_usage.json"))
    client.get_cellular_backup_events = AsyncMock(return_value=_load("cellular_events.json"))
    client.get_network_scan = AsyncMock(return_value=_load("network_scan.json"))
    client.get_speed_tests = AsyncMock(return_value=_load("speed_tests.json"))
    client.get_multistaticip = AsyncMock(return_value={"enabled": False})
    client.get_ac_compat = AsyncMock(return_value=_load("ac_compat.json"))
    client.get_power_saving_schedules = AsyncMock(return_value=_load("power_saving_schedules.json"))
    client.get_transfer_stats = AsyncMock(return_value={})

    for name, value in overrides.items():
        setattr(client, name, value)

    return client


def _config(**overrides: object) -> ExporterConfig:
    defaults: dict[str, object] = {
        "include_thread": False,
        "include_port_forwards": False,
        "include_reservations": False,
        "include_blacklist": False,
        "include_insights": False,
        "include_profiles": True,
        "include_devices": True,
        "include_data_usage": False,
        "include_premium": True,
        "include_extended": False,
        "include_rf": False,
        "include_per_profile": False,
        "include_per_device": False,
        "include_per_eero": False,
        "include_unverified": False,
        "data_usage_periods": [],
    }
    defaults.update(overrides)
    return ExporterConfig(**defaults)


# ---------------------------------------------------------------------------
# rf tier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rf_tier_populates_channel_utilization_metrics() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_rf=True),
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    mock_client.get_channel_utilization.assert_awaited_once()
    value = EERO_CHANNEL_UTILIZATION_AVG_PERCENT.labels(
        network_id="999001", eero_id="1", band="band_2_4GHz"
    )._value.get()
    assert value == 12

    busy = EERO_CHANNEL_BUSY_MINUTES.labels(
        network_id="999001", eero_id="1", band="band_2_4GHz"
    )._value.get()
    assert busy == 3


@pytest.mark.asyncio
async def test_rf_tier_off_skips_channel_utilization_call() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_rf=False),
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    mock_client.get_channel_utilization.assert_not_awaited()


def test_rf_family_registration_gated_by_include_rf() -> None:
    assert FAMILY_TIER["rf"] == "rf"
    on_registry = CollectorRegistry()
    register_metrics(_config(include_rf=True), registry=on_registry)
    assert "eero_channel_utilization_avg_percent" in generate_latest(on_registry).decode()

    off_registry = CollectorRegistry()
    register_metrics(_config(include_rf=False), registry=off_registry)
    assert "eero_channel_utilization_avg_percent" not in generate_latest(off_registry).decode()


# ---------------------------------------------------------------------------
# per_device tier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_device_tier_populates_device_insights_total() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_per_device=True),
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert mock_client.get_devices_insights.await_count == 3
    value = DEVICE_INSIGHTS_TOTAL.labels(
        network_id="999001", device_id="aa:bb:cc:dd:ee:01", type="adblock"
    )._value.get()
    assert value == 4


@pytest.mark.asyncio
async def test_per_device_tier_off_skips_devices_insights_call() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_per_device=False),
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    mock_client.get_devices_insights.assert_not_awaited()


# ---------------------------------------------------------------------------
# per_eero tier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_eero_tier_populates_connections_and_ouicheck() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_per_eero=True),
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert mock_client.get_nightlight.await_count == 4
    assert mock_client.get_connections.await_count == 4
    assert mock_client.get_ouicheck.await_count == 4

    value = EERO_EERO_CONNECTIONS_COUNT.labels(network_id="999001", eero_id="1")._value.get()
    assert value == 2

    can_add = EERO_OUICHECK_CAN_ADD.labels(network_id="999001", eero_id="1")._value.get()
    assert can_add == 1


@pytest.mark.asyncio
async def test_per_eero_nightlight_feature_unavailable_is_not_a_scrape_error() -> None:
    from eero_exporter.eero_adapter import EeroFeatureUnavailableError

    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_per_eero=True),
    )
    mock_client = _mock_client(
        get_nightlight=AsyncMock(side_effect=EeroFeatureUnavailableError("no beacon"))
    )
    before = EXPORTER_SCRAPE_ERRORS.labels(error_type="api")._value.get()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    after = EXPORTER_SCRAPE_ERRORS.labels(error_type="api")._value.get()
    assert after == before
    status = EXPORTER_API_REQUESTS.labels(
        endpoint="nightlight", status="feature_unavailable"
    )._value.get()
    assert status >= 1


@pytest.mark.asyncio
async def test_per_eero_tier_off_skips_all_three_calls() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_per_eero=False),
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    mock_client.get_nightlight.assert_not_awaited()
    mock_client.get_connections.assert_not_awaited()
    mock_client.get_ouicheck.assert_not_awaited()


# ---------------------------------------------------------------------------
# per_profile tier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_profile_tier_populates_dns_policy_applications_count() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_per_profile=True),
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert mock_client.get_dns_policy_applications.await_count == 2
    value = PROFILE_DNS_POLICY_APPLICATIONS_COUNT.labels(
        network_id="999001", profile_id="1"
    )._value.get()
    assert value == 2


@pytest.mark.asyncio
async def test_per_profile_premium_required_is_not_a_scrape_error() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_per_profile=True),
    )
    mock_client = _mock_client(
        get_dns_policy_applications=AsyncMock(
            side_effect=EeroPremiumRequiredError("premium required")
        )
    )
    before = EXPORTER_SCRAPE_ERRORS.labels(error_type="api")._value.get()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    after = EXPORTER_SCRAPE_ERRORS.labels(error_type="api")._value.get()
    assert after == before


@pytest.mark.asyncio
async def test_per_profile_tier_off_skips_the_call() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_per_profile=False),
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    mock_client.get_dns_policy_applications.assert_not_awaited()


# ---------------------------------------------------------------------------
# unverified tier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unverified_tier_populates_counts_and_booleans() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_unverified=True),
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert NETWORK_ROUTING_DEVICES_COUNT.labels(network_id="999001")._value.get() == 1
    assert BACKUP_ACCESS_POINTS_COUNT.labels(network_id="999001")._value.get() == 2
    assert BACKUP_ACCESS_POINT_ENABLED.labels(network_id="999001", index="0")._value.get() == 1
    assert CELLULAR_BACKUP_USAGE_ITEMS_COUNT.labels(network_id="999001")._value.get() == 0
    assert CELLULAR_BACKUP_OUTAGES_COUNT.labels(network_id="999001")._value.get() == 0
    assert NETWORK_SCAN_CONFLICTING_SSID.labels(network_id="999001")._value.get() == 0
    assert SPEED_TESTS_TOTAL.labels(network_id="999001")._value.get() == 2
    assert NETWORK_MULTISTATICIP_ENABLED.labels(network_id="999001")._value.get() == 0
    assert NETWORK_AC_COMPAT.labels(network_id="999001")._value.get() == 0
    assert NETWORK_POWER_SAVING_SCHEDULES_COUNT.labels(network_id="999001")._value.get() == 0


@pytest.mark.asyncio
async def test_unverified_multistaticip_not_found_maps_to_zero_not_a_scrape_error() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_unverified=True),
    )
    mock_client = _mock_client(
        get_multistaticip=AsyncMock(
            side_effect=EeroNotFoundError("error.network.multistaticip_not_found")
        )
    )
    before = EXPORTER_SCRAPE_ERRORS.labels(error_type="api")._value.get()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    after = EXPORTER_SCRAPE_ERRORS.labels(error_type="api")._value.get()
    assert after == before
    assert NETWORK_MULTISTATICIP_ENABLED.labels(network_id="999001")._value.get() == 0


@pytest.mark.asyncio
async def test_unverified_transfer_stub_exports_nothing_but_logs_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_unverified=True),
    )
    mock_client = _mock_client(
        get_transfer_stats=AsyncMock(return_value={"secret_value": "should-never-appear"})
    )

    with caplog.at_level(logging.DEBUG, logger="eero_exporter.collector"):
        with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
            assert await collector.collect() is True

    # The stub must never turn the payload's *value* into a metric or a log
    # line -- only the key set is DEBUG-logged.
    assert "should-never-appear" not in caplog.text
    assert "secret_value" in caplog.text


@pytest.mark.asyncio
async def test_unverified_thread_key_logs_without_leaking_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_unverified=True),
    )
    mock_client = _mock_client()

    with caplog.at_level(logging.DEBUG, logger="eero_exporter.collector"):
        with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
            assert await collector.collect() is True

    assert "REDACTED" not in caplog.text
    assert "enable_credential_syncing" in caplog.text


@pytest.mark.asyncio
async def test_unverified_tier_off_skips_every_call() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(include_unverified=False),
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    mock_client.get_routing.assert_not_awaited()
    mock_client.list_backup_access_points.assert_not_awaited()
    mock_client.get_cellular_backup_usage.assert_not_awaited()
    mock_client.get_cellular_backup_events.assert_not_awaited()
    mock_client.get_network_scan.assert_not_awaited()
    mock_client.get_speed_tests.assert_not_awaited()
    mock_client.get_multistaticip.assert_not_awaited()
    mock_client.get_ac_compat.assert_not_awaited()
    mock_client.get_power_saving_schedules.assert_not_awaited()
    mock_client.get_transfer_stats.assert_not_awaited()
    # `get_thread` is only called by the unverified tier now (§ commit 8
    # deliverable 6) -- off means it is never called either.
    mock_client.get_thread.assert_not_awaited()


# ---------------------------------------------------------------------------
# registry gating for every new tier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "family,tier,flag,sample_metric",
    [
        ("device_insights", "per_device", "include_per_device", "eero_device_insights_total"),
        ("per_eero", "per_eero", "include_per_eero", "eero_eero_connections_count"),
        (
            "per_profile",
            "per_profile",
            "include_per_profile",
            "eero_profile_dns_policy_applications_count",
        ),
        ("unverified", "unverified", "include_unverified", "eero_network_scan_conflicting_ssid"),
    ],
)
def test_tier_registration_gated_by_its_flag(
    family: str, tier: str, flag: str, sample_metric: str
) -> None:
    assert FAMILY_TIER[family] == tier

    on_registry = CollectorRegistry()
    register_metrics(_config(**{flag: True}), registry=on_registry)
    assert sample_metric in generate_latest(on_registry).decode()

    off_registry = CollectorRegistry()
    register_metrics(_config(**{flag: False}), registry=off_registry)
    assert sample_metric not in generate_latest(off_registry).decode()
