"""Tests for the extended tier (commit 7, §9 #12-19, §11.6/§11.8-11.10 of the
v8 probe shape summary): entitlements, WPA3 per band, fast transition,
permissions, members, notifications, DNS advanced content filter, subnets,
and profile-level insights.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from eero_exporter.collector import EeroCollector
from eero_exporter.config import ExporterConfig
from eero_exporter.eero_adapter import EeroPremiumRequiredError
from eero_exporter.metrics import (
    ACCOUNT_ENTITLEMENT_CREATED_TIMESTAMP,
    ACCOUNT_ENTITLEMENT_PRODUCT_INFO,
    ACCOUNT_ENTITLEMENT_STATE,
    DNS_POLICY_ALLOWED_DOMAINS_COUNT,
    DNS_POLICY_BLOCKED_DOMAINS_COUNT,
    EERO_NETWORK_WPA3_BAND_MODE,
    EXPORTER_API_REQUESTS,
    FAMILY_TIER,
    NETWORK_FAST_TRANSITION_ENABLED,
    NETWORK_FEATURE_ENTITLED,
    NETWORK_MEMBERS_COUNT,
    NETWORK_NOTIFICATION_ENABLED,
    NETWORK_NOTIFICATIONS_UNREAD,
    NETWORK_PERMISSION,
    PROFILE_INSIGHTS_TOTAL,
    SUBNET_ENABLED,
    SUBNET_LAN_ACCESS,
    SUBNET_OPEN_NETWORK,
    SUBNET_WAN_ACCESS,
    register_metrics,
)

FIXTURES = Path(__file__).parent / "fixtures" / "v8"


def _load(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text())


def _load_network_fixture() -> dict:
    return json.loads((FIXTURES / "network.json").read_text())


def _mock_client(**overrides: object) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get_networks = AsyncMock(
        return_value=[{"id": "999001", "name": "Test Network", "url": "/2.2/networks/999001"}]
    )
    client.get_network = AsyncMock(return_value=_load_network_fixture())
    client.get_eeros = AsyncMock(return_value=[])
    client.get_devices = AsyncMock(return_value=[])
    client.get_profiles = AsyncMock(return_value=[])
    client.get_data_usage = AsyncMock(return_value={"series": []})
    client.get_data_usage_breakdown = AsyncMock(
        return_value={"eeros": [], "devices": [], "profiles": [], "unprofiled": []}
    )
    client.get_thread = AsyncMock(return_value={})
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
    client.get_channel_utilization = AsyncMock(return_value={})

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
        "include_profiles": False,
        "include_devices": False,
        "include_data_usage": False,
        "include_premium": True,
        "data_usage_periods": [],
    }
    defaults.update(overrides)
    return ExporterConfig(**defaults)


@pytest.mark.asyncio
async def test_entitlement_features_set_capability_and_state() -> None:
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert (
        NETWORK_FEATURE_ENTITLED.labels(
            network_id="999001", feature="channel_utilization"
        )._value.get()
        == 1
    )
    assert (
        NETWORK_FEATURE_ENTITLED.labels(network_id="999001", feature="ad_blocking")._value.get()
        == 0
    )
    assert ACCOUNT_ENTITLEMENT_STATE.labels(network_id="999001", state="active")._value.get() == 1
    assert (
        ACCOUNT_ENTITLEMENT_PRODUCT_INFO.labels(network_id="999001", type="premium")._value.get()
        == 1
    )
    assert ACCOUNT_ENTITLEMENT_CREATED_TIMESTAMP.labels(network_id="999001")._value.get() > 0


@pytest.mark.asyncio
async def test_entitlement_features_skips_features_without_capability_key() -> None:
    """`multi_ssid`/`one_password` have no `capability` key -- must not raise or export."""
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    registry = CollectorRegistry(auto_describe=True)
    register_metrics(_config(), registry=registry)
    output = generate_latest(registry).decode()
    assert 'feature="multi_ssid"' not in output
    assert 'feature="one_password"' not in output


@pytest.mark.asyncio
async def test_wpa3_band_mode_is_a_state_set_gauge() -> None:
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    # band_2_4_ghz observed mode is WPA2.
    assert (
        EERO_NETWORK_WPA3_BAND_MODE.labels(
            network_id="999001", band="2_4_ghz", mode="WPA2"
        )._value.get()
        == 1
    )
    assert (
        EERO_NETWORK_WPA3_BAND_MODE.labels(
            network_id="999001", band="2_4_ghz", mode="WPA3"
        )._value.get()
        == 0
    )
    assert (
        EERO_NETWORK_WPA3_BAND_MODE.labels(
            network_id="999001", band="2_4_ghz", mode="WPA2_WPA3"
        )._value.get()
        == 0
    )
    # band_6_ghz observed mode is WPA3 -- three bands, not two.
    assert (
        EERO_NETWORK_WPA3_BAND_MODE.labels(
            network_id="999001", band="6_ghz", mode="WPA3"
        )._value.get()
        == 1
    )


@pytest.mark.asyncio
async def test_fast_transition_enabled_reads_boolean() -> None:
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert NETWORK_FAST_TRANSITION_ENABLED.labels(network_id="999001")._value.get() == 0


@pytest.mark.asyncio
async def test_permissions_export_role_and_read_capability() -> None:
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert NETWORK_PERMISSION.labels(network_id="999001", capability="network")._value.get() == 1
    assert (
        NETWORK_PERMISSION.labels(network_id="999001", capability="network_transfer")._value.get()
        == 0
    )


@pytest.mark.asyncio
async def test_permissions_skip_redacted_and_per_eero_keys() -> None:
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    registry = CollectorRegistry(auto_describe=True)
    register_metrics(_config(), registry=registry)
    output = generate_latest(registry).decode()
    for skipped_capability in (
        "network_subnets_main_password",
        "network_multi_ssid",
        "network_multistatic_ip",
        "user_conversations_token",
        "per_eero",
    ):
        assert f'capability="{skipped_capability}"' not in output


@pytest.mark.asyncio
async def test_members_count_only_never_names() -> None:
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert NETWORK_MEMBERS_COUNT.labels(network_id="999001")._value.get() == 2

    registry = CollectorRegistry(auto_describe=True)
    register_metrics(_config(), registry=registry)
    output = generate_latest(registry).decode()
    assert "Fake Person One" not in output
    assert "Fake Person Two" not in output
    assert "fake-user-1" not in output
    assert "fake-user-2" not in output


@pytest.mark.asyncio
async def test_notification_settings_and_unread_flag() -> None:
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert (
        NETWORK_NOTIFICATION_ENABLED.labels(
            network_id="999001", event="port_security_blocked"
        )._value.get()
        == 1
    )
    assert (
        NETWORK_NOTIFICATION_ENABLED.labels(network_id="999001", event="device_new")._value.get()
        == 0
    )
    # The API returns a bool, not a count.
    assert NETWORK_NOTIFICATIONS_UNREAD.labels(network_id="999001")._value.get() == 1


@pytest.mark.asyncio
async def test_dns_filter_counts_list_lengths_when_premium() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",
        config=_config(include_premium=True),  # nosec B108
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert DNS_POLICY_ALLOWED_DOMAINS_COUNT.labels(network_id="999001")._value.get() == 0
    assert DNS_POLICY_BLOCKED_DOMAINS_COUNT.labels(network_id="999001")._value.get() == 1


@pytest.mark.asyncio
async def test_dns_filter_not_called_when_premium_disabled() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",
        config=_config(include_premium=False),  # nosec B108
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    mock_client.get_advanced_content_filter.assert_not_awaited()


@pytest.mark.asyncio
async def test_dns_filter_premium_required_is_not_a_scrape_error() -> None:
    mock_client = _mock_client(
        get_advanced_content_filter=AsyncMock(side_effect=EeroPremiumRequiredError("plus only"))
    )
    collector = EeroCollector(
        session_file="/tmp/session.json",
        config=_config(include_premium=True),  # nosec B108
    )

    before = EXPORTER_API_REQUESTS.labels(
        endpoint="dns_filter", status="premium_required"
    )._value.get()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        success = await collector.collect()

    assert success is True
    after = EXPORTER_API_REQUESTS.labels(
        endpoint="dns_filter", status="premium_required"
    )._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_subnets_export_bools_and_never_name_or_password() -> None:
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert (
        SUBNET_ENABLED.labels(
            network_id="999001", subnet_kind="main", subnet_type="main"
        )._value.get()
        == 1
    )
    assert (
        SUBNET_WAN_ACCESS.labels(
            network_id="999001", subnet_kind="guest", subnet_type="guest"
        )._value.get()
        == 1
    )
    assert (
        SUBNET_LAN_ACCESS.labels(
            network_id="999001", subnet_kind="guest", subnet_type="guest"
        )._value.get()
        == 0
    )
    assert (
        SUBNET_OPEN_NETWORK.labels(
            network_id="999001", subnet_kind="guest", subnet_type="guest"
        )._value.get()
        == 1
    )

    registry = CollectorRegistry(auto_describe=True)
    register_metrics(_config(), registry=registry)
    output = generate_latest(registry).decode()
    assert "should-never-leak" not in output
    for line in output.splitlines():
        if line.startswith(f"{SUBNET_ENABLED._name}{{") or line.startswith(
            f"{SUBNET_WAN_ACCESS._name}{{"
        ):
            assert "Main" not in line
            assert "Guest" not in line
            assert "subnet_id" not in line


@pytest.mark.asyncio
async def test_subnets_bad_item_does_not_drop_the_family() -> None:
    bad_subnets = [
        "not-a-dict",
        {
            "subnet_kind": "main",
            "subnet_type": "main",
            "enabled": True,
            "wan_access": True,
        },
    ]
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client(get_subnets_config=AsyncMock(return_value=bad_subnets))

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert (
        SUBNET_ENABLED.labels(
            network_id="999001", subnet_kind="main", subnet_type="main"
        )._value.get()
        == 1
    )


@pytest.mark.asyncio
async def test_profile_insights_total_keyed_by_profile_id_and_type() -> None:
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    assert (
        PROFILE_INSIGHTS_TOTAL.labels(
            network_id="999001", profile_id="1", type="adblock"
        )._value.get()
        == 3
    )
    assert (
        PROFILE_INSIGHTS_TOTAL.labels(
            network_id="999001", profile_id="2", type="blocked"
        )._value.get()
        == 0
    )
    # Called once per insight type (list-level -- covers every profile).
    assert mock_client.get_profiles_insights.await_count == 3


@pytest.mark.asyncio
async def test_include_extended_false_skips_every_extended_call() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",
        config=_config(include_extended=False),  # nosec B108
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await collector.collect() is True

    mock_client.get_entitlement_features.assert_not_awaited()
    mock_client.get_wpa3_per_band.assert_not_awaited()
    mock_client.get_fast_transition.assert_not_awaited()
    mock_client.get_permissions.assert_not_awaited()
    mock_client.get_members.assert_not_awaited()
    mock_client.get_notification_settings.assert_not_awaited()
    mock_client.has_unread_notifications.assert_not_awaited()
    mock_client.get_advanced_content_filter.assert_not_awaited()
    mock_client.get_subnets_config.assert_not_awaited()
    mock_client.get_profiles_insights.assert_not_awaited()


def test_extended_families_are_registered_under_the_extended_tier() -> None:
    extended_families = {
        "entitlements",
        "security",
        "permissions",
        "members",
        "notifications",
        "dns_policy",
        "subnets",
        "profile_insights",
    }
    for family in extended_families:
        assert FAMILY_TIER[family] == "extended"


def test_include_extended_false_deregisters_extended_families() -> None:
    config = _config(include_extended=False)
    registry = CollectorRegistry(auto_describe=True)
    register_metrics(config, registry=registry)

    output = generate_latest(registry).decode()
    assert f"# HELP {NETWORK_FEATURE_ENTITLED._name} " not in output
    assert f"# HELP {SUBNET_ENABLED._name} " not in output
    assert f"# HELP {PROFILE_INSIGHTS_TOTAL._name} " not in output
