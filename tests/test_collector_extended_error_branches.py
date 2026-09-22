"""Coverage for the extended-tier (and a few core) sub-collectors' `exc is
not None` early-return branches -- the debug-log-and-return path taken when
the underlying adapter call fails. Each of these sub-collectors is called
directly with a hand-built client mock (no full `collect()` cycle needed).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from eero_exporter.collector import EeroCollector
from eero_exporter.config import ExporterConfig
from eero_exporter.eero_adapter import EeroAPIError

# (collector method name, client method name) -- signature (client, network_id)
_SIMPLE_NETWORK_ID_METHODS = [
    ("_collect_entitlement_metrics", "get_entitlement_features"),
    ("_collect_wpa3_metrics", "get_wpa3_per_band"),
    ("_collect_fast_transition_metrics", "get_fast_transition"),
    ("_collect_permission_metrics", "get_permissions"),
    ("_collect_member_metrics", "get_members"),
    ("_collect_subnet_metrics", "get_subnets_config"),
]


def _collector(**overrides: object) -> EeroCollector:
    return EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=ExporterConfig(**overrides),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("method_name", "client_method"), _SIMPLE_NETWORK_ID_METHODS)
async def test_api_error_is_logged_and_swallowed(method_name: str, client_method: str) -> None:
    collector = _collector()
    client = MagicMock()
    setattr(
        client,
        client_method,
        AsyncMock(side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")),
    )

    # Must not raise.
    await getattr(collector, method_name)(client, "net-1")


@pytest.mark.asyncio
async def test_dns_filter_metrics_skipped_when_include_premium_off() -> None:
    collector = _collector(include_premium=False)
    client = MagicMock()
    client.get_advanced_content_filter = AsyncMock(
        return_value={"allowed_list": [], "blocked_list": []}
    )

    await collector._collect_dns_filter_metrics(client, "net-1")

    client.get_advanced_content_filter.assert_not_called()


@pytest.mark.asyncio
async def test_dns_filter_metrics_api_error_is_logged_and_swallowed() -> None:
    collector = _collector(include_premium=True)
    client = MagicMock()
    client.get_advanced_content_filter = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )

    await collector._collect_dns_filter_metrics(client, "net-1")


@pytest.mark.asyncio
async def test_dns_filter_metrics_happy_path_sets_list_lengths() -> None:
    from eero_exporter.metrics import DNS_POLICY_ALLOWED_DOMAINS_COUNT

    collector = _collector(include_premium=True)
    client = MagicMock()
    client.get_advanced_content_filter = AsyncMock(
        return_value={"allowed_list": ["a", "b"], "blocked_list": ["c"]}
    )

    await collector._collect_dns_filter_metrics(client, "net-1")

    assert DNS_POLICY_ALLOWED_DOMAINS_COUNT.labels(network_id="net-1")._value.get() == 2


@pytest.mark.asyncio
async def test_notification_metrics_both_calls_fail_gracefully() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_notification_settings = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )
    client.has_unread_notifications = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )

    await collector._collect_notification_metrics(client, "net-1")


@pytest.mark.asyncio
async def test_notification_metrics_settings_ok_unread_fails() -> None:
    from eero_exporter.metrics import NETWORK_NOTIFICATION_ENABLED

    collector = _collector()
    client = MagicMock()
    client.get_notification_settings = AsyncMock(return_value={"security.alert": True})
    client.has_unread_notifications = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )

    await collector._collect_notification_metrics(client, "net-1")

    value = NETWORK_NOTIFICATION_ENABLED.labels(
        network_id="net-1", event="security_alert"
    )._value.get()
    assert value == 1


@pytest.mark.asyncio
async def test_notification_metrics_happy_path_sets_unread_flag() -> None:
    from eero_exporter.metrics import NETWORK_NOTIFICATIONS_UNREAD

    collector = _collector()
    client = MagicMock()
    client.get_notification_settings = AsyncMock(return_value={})
    client.has_unread_notifications = AsyncMock(return_value={"has_unread": True})

    await collector._collect_notification_metrics(client, "net-1")

    value = NETWORK_NOTIFICATIONS_UNREAD.labels(network_id="net-1")._value.get()
    assert value == 1


@pytest.mark.asyncio
async def test_reservation_metrics_api_error_returns_early() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_reservations = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )

    await collector._collect_reservation_metrics(client, "net-1", "Test Network")


@pytest.mark.asyncio
async def test_blacklist_metrics_api_error_returns_early() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_blacklist = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )

    await collector._collect_blacklist_metrics(client, "net-1", "Test Network")


@pytest.mark.asyncio
async def test_profile_insights_metrics_all_types_fail_gracefully() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_profiles_insights = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )

    await collector._collect_profile_insights_metrics(client, "net-1")

    assert client.get_profiles_insights.await_count == 3


@pytest.mark.asyncio
async def test_data_usage_metrics_period_failure_continues_to_breakdown() -> None:
    collector = _collector(data_usage_periods=["day"], include_devices=False)
    client = MagicMock()
    client.get_data_usage = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )

    # Must not raise; include_devices=False also exercises the early return
    # right after the period loop (no breakdown call issued).
    await collector._collect_data_usage_metrics(client, "net-1", {})
    client.get_data_usage.assert_awaited_once()


@pytest.mark.asyncio
async def test_data_usage_metrics_breakdown_failure_is_swallowed() -> None:
    collector = _collector(data_usage_periods=[], include_devices=True)
    client = MagicMock()
    client.get_data_usage_breakdown = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )

    await collector._collect_data_usage_metrics(client, "net-1", {})
    client.get_data_usage_breakdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_current_usage_metrics_api_error_returns_early() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_data_usage = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )

    await collector._collect_current_usage_metrics(client, "net-1")


@pytest.mark.asyncio
async def test_per_eero_metrics_empty_eeros_is_a_no_op() -> None:
    collector = _collector()
    client = MagicMock()

    await collector._collect_per_eero_metrics(client, "net-1", None)
    await collector._collect_per_eero_metrics(client, "net-1", [])

    client.get_nightlight.assert_not_called()


@pytest.mark.asyncio
async def test_per_eero_metrics_all_three_calls_fail_gracefully() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_nightlight = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )
    client.get_connections = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )
    client.get_ouicheck = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )
    eero = {
        "url": "/2.2/networks/net-1/eeros/eero-1",
        "serial": "SERIAL1",
        "os_version": "6.0",
    }

    await collector._collect_per_eero_metrics(client, "net-1", [eero])

    client.get_nightlight.assert_awaited_once()
    client.get_connections.assert_awaited_once()
    client.get_ouicheck.assert_awaited_once()


@pytest.mark.asyncio
async def test_per_eero_metrics_skips_ouicheck_without_serial_or_os_version() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_nightlight = AsyncMock(return_value={})
    client.get_connections = AsyncMock(return_value={"wireless_devices": [1, 2]})
    eero = {"url": "/2.2/networks/net-1/eeros/eero-1"}

    await collector._collect_per_eero_metrics(client, "net-1", [eero])

    client.get_ouicheck.assert_not_called()


@pytest.mark.asyncio
async def test_per_profile_metrics_empty_profiles_is_a_no_op() -> None:
    collector = _collector()
    client = MagicMock()

    await collector._collect_per_profile_metrics(client, "net-1", None)
    await collector._collect_per_profile_metrics(client, "net-1", [])

    client.get_dns_policy_applications.assert_not_called()


@pytest.mark.asyncio
async def test_per_profile_metrics_api_error_is_swallowed() -> None:
    collector = _collector()
    client = MagicMock()
    client.get_dns_policy_applications = AsyncMock(
        side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
    )
    profile = {"url": "/2.2/networks/net-1/profiles/prof-1"}

    await collector._collect_per_profile_metrics(client, "net-1", [profile])

    client.get_dns_policy_applications.assert_awaited_once()


@pytest.mark.asyncio
async def test_per_profile_metrics_malformed_item_skipped() -> None:
    collector = _collector()
    client = MagicMock()

    await collector._collect_per_profile_metrics(client, "net-1", ["not-a-dict"])

    client.get_dns_policy_applications.assert_not_called()


# All ten adapter calls the unverified tier issues (excluding the
# transfer-stats stub, handled separately below since it needs a `devices`
# list to reach its second call).
_UNVERIFIED_CLIENT_METHODS = [
    "get_thread",
    "get_routing",
    "list_backup_access_points",
    "get_cellular_backup_usage",
    "get_cellular_backup_events",
    "get_network_scan",
    "get_speed_tests",
    "get_multistaticip",
    "get_ac_compat",
    "get_power_saving_schedules",
    "get_transfer_stats",
]


@pytest.mark.asyncio
async def test_unverified_metrics_every_call_failing_is_fully_swallowed() -> None:
    """Every one of the unverified tier's ten independently-guarded reads
    failing must not raise, and (with no devices) the device-level transfer
    stats call is never attempted.
    """
    collector = _collector()
    client = MagicMock()
    api_error = EeroAPIError("boom", status_code=500, error_code="error.internal")
    for method_name in _UNVERIFIED_CLIENT_METHODS:
        setattr(client, method_name, AsyncMock(side_effect=api_error))

    await collector._collect_unverified_metrics(client, "net-1", None)

    for method_name in _UNVERIFIED_CLIENT_METHODS:
        getattr(client, method_name).assert_awaited()
    # No devices -> the device-level transfer-stats call (second
    # get_transfer_stats invocation) is never attempted.
    assert client.get_transfer_stats.await_count == 1


@pytest.mark.asyncio
async def test_unverified_metrics_multistaticip_not_found_sets_disabled() -> None:
    from eero_exporter.eero_adapter import EeroNotFoundError
    from eero_exporter.metrics import NETWORK_MULTISTATICIP_ENABLED

    collector = _collector()
    client = MagicMock()
    for method_name in _UNVERIFIED_CLIENT_METHODS:
        setattr(client, method_name, AsyncMock(return_value={}))
    client.get_multistaticip = AsyncMock(
        side_effect=EeroNotFoundError("not provisioned", status_code=404)
    )
    client.list_backup_access_points = AsyncMock(return_value=[])
    client.get_speed_tests = AsyncMock(return_value=[])

    await collector._collect_unverified_metrics(client, "net-1", None)

    value = NETWORK_MULTISTATICIP_ENABLED.labels(network_id="net-1")._value.get()
    assert value == 0


@pytest.mark.asyncio
async def test_unverified_metrics_with_devices_issues_device_transfer_call() -> None:
    collector = _collector()
    client = MagicMock()
    for method_name in _UNVERIFIED_CLIENT_METHODS:
        setattr(client, method_name, AsyncMock(return_value={}))
    client.list_backup_access_points = AsyncMock(return_value=[])
    client.get_speed_tests = AsyncMock(return_value=[])
    client.get_multistaticip = AsyncMock(return_value={"enabled": True})

    devices = ["not-a-dict", {"mac": "aa:bb:cc:dd:ee:ff"}]
    await collector._collect_unverified_metrics(client, "net-1", devices)

    assert client.get_transfer_stats.await_count == 2
    client.get_transfer_stats.assert_any_await("net-1", "aa:bb:cc:dd:ee:ff")


@pytest.mark.asyncio
async def test_unverified_metrics_happy_path_sets_counts() -> None:
    from eero_exporter.metrics import (
        BACKUP_ACCESS_POINTS_COUNT,
        NETWORK_AC_COMPAT,
        NETWORK_SCAN_CONFLICTING_SSID,
        SPEED_TESTS_TOTAL,
    )

    collector = _collector()
    client = MagicMock()
    client.get_thread = AsyncMock(return_value={"key": "value"})
    client.get_routing = AsyncMock(
        return_value={
            "devices": {"data": [1, 2]},
            "reservations": {},
            "forwards": {},
            "pinholes": {},
        }
    )
    client.list_backup_access_points = AsyncMock(
        return_value=[{"enabled": True, "connectivity": {"status": "failure"}}]
    )
    client.get_cellular_backup_usage = AsyncMock(return_value={"backup_usage_items": [1]})
    client.get_cellular_backup_events = AsyncMock(return_value={"outages": [1, 2]})
    client.get_network_scan = AsyncMock(return_value={"conflicting_ssid": True})
    client.get_speed_tests = AsyncMock(return_value=[1, 2, 3])
    client.get_multistaticip = AsyncMock(return_value={"enabled": False})
    client.get_ac_compat = AsyncMock(return_value={"enabled": True})
    client.get_power_saving_schedules = AsyncMock(return_value={"schedules": []})
    client.get_transfer_stats = AsyncMock(return_value={})

    await collector._collect_unverified_metrics(client, "net-1", None)

    assert BACKUP_ACCESS_POINTS_COUNT.labels(network_id="net-1")._value.get() == 1
    assert NETWORK_SCAN_CONFLICTING_SSID.labels(network_id="net-1")._value.get() == 1
    assert SPEED_TESTS_TOTAL.labels(network_id="net-1")._value.get() == 3
    assert NETWORK_AC_COMPAT.labels(network_id="net-1")._value.get() == 1


@pytest.mark.asyncio
async def test_current_usage_metrics_happy_path_and_bad_active_clients_type() -> None:
    from eero_exporter.metrics import DATA_USAGE_DOWNLOAD_BYTES

    collector = _collector()
    client = MagicMock()
    client.get_data_usage = AsyncMock(
        return_value={
            "series": [{"type": "download", "sum": 100}],
            "totals": {"active_clients": "not-a-number"},
        }
    )

    # Must not raise even though active_clients can't be coerced to float.
    await collector._collect_current_usage_metrics(client, "net-1")

    value = DATA_USAGE_DOWNLOAD_BYTES.labels(network_id="net-1")._value.get()
    assert value == 100.0
