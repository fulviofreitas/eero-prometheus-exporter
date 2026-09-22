"""Delegation coverage for every thin read wrapper on ``EeroClient`` (the adapter).

For each public read method exposed by the adapter, asserts that:
  * the same positional/keyword arguments reach the underlying SDK method
    (accounting for the handful of methods that intentionally reorder args
    when calling the SDK -- documented inline below), and
  * the envelope returned by the SDK mock is unwrapped correctly (dict via
    ``_extract_data``, list via ``_extract_list``).

The method list is built by introspecting ``EeroClient`` for public
coroutine methods, then asserting that introspected set matches the
explicit delegation table below (minus ``login``/``verify``, which have
side effects beyond simple delegation and are covered elsewhere, and
``get_speed_test``/``is_premium``, which delegate to a *different* SDK
method and apply extra parsing -- also covered separately below). This
way, a newly added adapter method fails this test until it is added to
the table, rather than silently going uncovered.
"""

import inspect
from typing import Any
from unittest.mock import AsyncMock

import pytest

from eero_exporter.eero_adapter import EeroClient

# Methods intentionally excluded from the generic delegation table:
#   - login/verify: side-effecting auth flow, not simple delegation
#   - get_speed_test: delegates to client.get_network(), not client.get_speed_test()
#   - is_premium: delegates to client.get_premium_status() with extra parsing
_EXCLUDED = {"login", "verify", "get_speed_test", "is_premium"}


def _introspected_read_methods() -> set[str]:
    return {
        name
        for name, _fn in inspect.getmembers(EeroClient, predicate=inspect.iscoroutinefunction)
        if not name.startswith("_") and name not in _EXCLUDED
    }


# Each entry: (
#   adapter_method_name,
#   adapter_call_args, adapter_call_kwargs,
#   expected_sdk_call_args, expected_sdk_call_kwargs,
#   return_kind ("dict" | "list"),
# )
# `return_kind` selects the envelope shape used for the SDK mock's return
# value and how the adapter's result is asserted against it.
_DelegationEntry = tuple[str, tuple[Any, ...], dict[str, Any], tuple[Any, ...], dict[str, Any], str]

DELEGATION_TABLE: list[_DelegationEntry] = [
    ("get_account", (), {}, (), {}, "dict"),
    ("get_networks", (), {}, (), {}, "list"),
    ("get_network", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_eeros", ("net-1",), {}, ("net-1",), {}, "list"),
    ("get_devices", ("net-1",), {}, ("net-1",), {}, "list"),
    ("get_profiles", ("net-1",), {}, ("net-1",), {}, "list"),
    ("get_transfer_stats", ("net-1", "dev-1"), {}, ("net-1", "dev-1"), {}, "dict"),
    (
        "get_data_usage",
        ("net-1",),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "timezone": "UTC"},
        ("net-1",),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "timezone": "UTC"},
        "dict",
    ),
    (
        "get_data_usage_breakdown",
        ("net-1",),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "timezone": "UTC"},
        ("net-1",),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "timezone": "UTC"},
        "dict",
    ),
    (
        "get_devices_data_usage",
        ("net-1",),
        {
            "start": "2026-01-01",
            "end": "2026-01-02",
            "cadence": "daily",
            "timezone": "UTC",
            "profile_id": "prof-1",
        },
        ("net-1",),
        {
            "start": "2026-01-01",
            "end": "2026-01-02",
            "cadence": "daily",
            "timezone": "UTC",
            "profile_id": "prof-1",
        },
        "dict",
    ),
    (
        "get_eeros_data_usage_summary",
        ("net-1",),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "timezone": "UTC"},
        ("net-1",),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "timezone": "UTC"},
        "dict",
    ),
    (
        # Adapter takes (network_id, eero_id) but calls the SDK as
        # (eero_id, network_id) -- order intentionally swapped.
        "get_eero_data_usage",
        ("net-1", "eero-1"),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "timezone": "UTC"},
        ("eero-1", "net-1"),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "timezone": "UTC"},
        "dict",
    ),
    (
        # Adapter takes (network_id, device_mac) but calls the SDK as
        # (device_mac, network_id) -- order intentionally swapped.
        "get_device_data_usage",
        ("net-1", "aa:bb:cc:dd:ee:ff"),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "timezone": "UTC"},
        ("aa:bb:cc:dd:ee:ff", "net-1"),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "timezone": "UTC"},
        "dict",
    ),
    (
        # Adapter takes (network_id, profile_id) but calls the SDK as
        # (profile_id, network_id) -- order intentionally swapped.
        "get_profile_data_usage",
        ("net-1", "prof-1"),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "timezone": "UTC"},
        ("prof-1", "net-1"),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "timezone": "UTC"},
        "dict",
    ),
    ("get_sqm_settings", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_security_settings", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_premium_status", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_thread", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_forwards", ("net-1",), {}, ("net-1",), {}, "list"),
    ("get_reservations", ("net-1",), {}, ("net-1",), {}, "list"),
    ("get_blacklist", ("net-1",), {}, ("net-1",), {}, "list"),
    ("get_updates", ("net-1",), {}, ("net-1",), {}, "dict"),
    (
        "get_insights",
        ("net-1",),
        {"start": "2026-01-01", "end": "2026-01-02", "insight_type": "adblock", "cadence": "daily"},
        ("net-1",),
        {"start": "2026-01-01", "end": "2026-01-02", "insight_type": "adblock", "cadence": "daily"},
        "dict",
    ),
    ("get_diagnostics", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_entitlement_features", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_wpa3_per_band", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_fast_transition", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_permissions", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_members", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_notification_settings", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("has_unread_notifications", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_advanced_content_filter", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_subnets_config", ("net-1",), {}, ("net-1",), {}, "list"),
    (
        "get_profiles_insights",
        ("net-1",),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "insight_type": "blocked"},
        ("net-1",),
        {"start": "2026-01-01", "end": "2026-01-02", "cadence": "daily", "insight_type": "blocked"},
        "dict",
    ),
    (
        "get_channel_utilization",
        ("net-1",),
        {"start": "2026-01-01", "end": "2026-01-02"},
        ("net-1",),
        {"start": "2026-01-01", "end": "2026-01-02"},
        "dict",
    ),
    (
        "get_devices_insights",
        ("net-1",),
        {
            "start": "2026-01-01",
            "end": "2026-01-02",
            "cadence": "daily",
            "insight_type": "inspected",
        },
        ("net-1",),
        {
            "start": "2026-01-01",
            "end": "2026-01-02",
            "cadence": "daily",
            "insight_type": "inspected",
        },
        "dict",
    ),
    ("get_nightlight", ("eero-1", "net-1"), {}, ("eero-1", "net-1"), {}, "dict"),
    ("get_connections", ("eero-1", "net-1"), {}, ("eero-1", "net-1"), {}, "dict"),
    (
        "get_ouicheck",
        ("net-1",),
        {"serial": "ser-1", "version": "1.2.3"},
        ("net-1",),
        {"serial": "ser-1", "version": "1.2.3"},
        "dict",
    ),
    (
        "get_dns_policy_applications",
        ("prof-1", "net-1"),
        {},
        ("prof-1", "net-1"),
        {},
        "dict",
    ),
    ("get_routing", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("list_backup_access_points", ("net-1",), {}, ("net-1",), {}, "list"),
    ("get_cellular_backup_usage", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_cellular_backup_events", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_network_scan", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_speed_tests", ("net-1",), {"limit": 5}, ("net-1",), {"limit": 5}, "list"),
    ("get_multistaticip", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_ac_compat", ("net-1",), {}, ("net-1",), {}, "dict"),
    ("get_power_saving_schedules", ("net-1",), {}, ("net-1",), {}, "dict"),
]


def test_delegation_table_matches_introspected_read_methods() -> None:
    """The explicit table above must cover exactly the introspected read methods.

    Fails loudly if a new adapter method is added without a corresponding
    delegation-table entry (or excluded with a documented reason).
    """
    table_methods = {entry[0] for entry in DELEGATION_TABLE}
    assert table_methods == _introspected_read_methods()


@pytest.mark.parametrize(
    ("method_name", "call_args", "call_kwargs", "expected_args", "expected_kwargs", "kind"),
    DELEGATION_TABLE,
    ids=[entry[0] for entry in DELEGATION_TABLE],
)
async def test_adapter_delegates_and_unwraps_envelope(
    method_name: str,
    call_args: tuple[Any, ...],
    call_kwargs: dict[str, Any],
    expected_args: tuple[Any, ...],
    expected_kwargs: dict[str, Any],
    kind: str,
) -> None:
    """Each read method awaits its SDK method with matching args and unwraps the envelope."""
    adapter = EeroClient()
    facade = AsyncMock()
    payload = [{"marker": "list-item"}] if kind == "list" else {"marker": "dict-value"}
    sdk_method = AsyncMock(return_value={"meta": {"code": 200}, "data": payload})
    setattr(facade, method_name, sdk_method)
    adapter._client = facade

    result = await getattr(adapter, method_name)(*call_args, **call_kwargs)

    sdk_method.assert_awaited_once_with(*expected_args, **expected_kwargs)
    if kind == "list":
        assert result == payload
    else:
        assert result == payload


# ---------------------------------------------------------------------------
# get_speed_test: delegates to client.get_network(), not client.get_speed_test()
# ---------------------------------------------------------------------------


async def test_get_speed_test_prefers_speed_test_key() -> None:
    """get_speed_test() reads network_data['speed_test'] when present."""
    adapter = EeroClient()
    facade = AsyncMock()
    facade.get_network = AsyncMock(
        return_value={
            "meta": {"code": 200},
            "data": {"speed_test": {"down": {"value": 100}}, "speed": {"down": {"value": 1}}},
        }
    )
    adapter._client = facade

    result = await adapter.get_speed_test("net-1")

    assert result == {"down": {"value": 100}}
    facade.get_network.assert_awaited_once_with("net-1")


async def test_get_speed_test_falls_back_to_speed_key() -> None:
    """get_speed_test() falls back to network_data['speed'] when 'speed_test' is absent."""
    adapter = EeroClient()
    facade = AsyncMock()
    facade.get_network = AsyncMock(
        return_value={"meta": {"code": 200}, "data": {"speed": {"down": {"value": 1}}}}
    )
    adapter._client = facade

    result = await adapter.get_speed_test("net-1")

    assert result == {"down": {"value": 1}}


async def test_get_speed_test_returns_none_when_not_a_dict() -> None:
    """get_speed_test() returns None when neither key yields a dict."""
    adapter = EeroClient()
    facade = AsyncMock()
    facade.get_network = AsyncMock(
        return_value={"meta": {"code": 200}, "data": {"speed_test": "not-a-dict"}}
    )
    adapter._client = facade

    result = await adapter.get_speed_test("net-1")

    assert result is None


# ---------------------------------------------------------------------------
# is_premium: delegates to client.get_premium_status(), extra parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_response", "expected"),
    [
        pytest.param(True, True, id="raw_bool_true"),
        pytest.param(False, False, id="raw_bool_false"),
        pytest.param({"meta": {}, "data": {"eero_plus": True}}, True, id="eero_plus_flag"),
        pytest.param(
            {"meta": {}, "data": {"premium_status": True}}, True, id="premium_status_flag"
        ),
        pytest.param({"meta": {}, "data": {"premium_dns": True}}, True, id="premium_dns_flag"),
        pytest.param({"meta": {}, "data": {"premium": True}}, True, id="premium_flag"),
        pytest.param({"meta": {}, "data": {}}, False, id="no_flags_present"),
    ],
)
async def test_is_premium_branches(raw_response: Any, expected: bool) -> None:
    """is_premium() checks each known flag key and falls back to False."""
    adapter = EeroClient()
    facade = AsyncMock()
    facade.get_premium_status = AsyncMock(return_value=raw_response)
    adapter._client = facade

    assert await adapter.is_premium("net-1") is expected


async def test_is_premium_coerces_non_bool_non_dict_response() -> None:
    """is_premium() falls back to bool() for any other response shape."""
    adapter = EeroClient()
    facade = AsyncMock()
    facade.get_premium_status = AsyncMock(return_value="truthy-string")
    adapter._client = facade

    assert await adapter.is_premium("net-1") is True


# ---------------------------------------------------------------------------
# login/verify -- side-effecting flow (not simple delegation)
# ---------------------------------------------------------------------------


async def test_login_success_returns_none() -> None:
    """login() returns None on success and forwards the identifier as-is."""
    adapter = EeroClient()
    facade = AsyncMock()
    facade.login = AsyncMock(return_value=True)
    adapter._client = facade

    assert await adapter.login("user@example.test") is None
    facade.login.assert_awaited_once_with("user@example.test")


async def test_login_failure_raises_eero_auth_error() -> None:
    """login() raises EeroAuthError when the SDK reports failure without an exception."""
    from eero_exporter.eero_adapter import EeroAuthError

    adapter = EeroClient()
    facade = AsyncMock()
    facade.login = AsyncMock(return_value=False)
    adapter._client = facade

    with pytest.raises(EeroAuthError, match="Login request failed"):
        await adapter.login("user@example.test")


async def test_verify_failure_raises_eero_auth_error() -> None:
    """verify() raises EeroAuthError when the SDK reports failure without an exception."""
    from eero_exporter.eero_adapter import EeroAuthError

    adapter = EeroClient()
    facade = AsyncMock()
    facade.verify = AsyncMock(return_value=False)
    adapter._client = facade

    with pytest.raises(EeroAuthError, match="Verification failed"):
        await adapter.verify("123456")


async def test_verify_success_resolves_preferred_network() -> None:
    """verify() discovers and returns the first network's id after a successful verify."""
    adapter = EeroClient()
    facade = AsyncMock()
    facade.verify = AsyncMock(return_value=True)
    facade.get_networks = AsyncMock(
        return_value={"meta": {}, "data": {"networks": [{"id": "net-42"}]}}
    )
    adapter._client = facade

    result = await adapter.verify("123456")

    assert result == "net-42"


async def test_verify_success_swallows_network_discovery_failure() -> None:
    """verify() succeeds even if the follow-up get_networks() call raises."""
    from eero.exceptions import EeroNetworkException  # type: ignore[import-untyped]

    adapter = EeroClient()
    facade = AsyncMock()
    facade.verify = AsyncMock(return_value=True)
    facade.get_networks = AsyncMock(side_effect=EeroNetworkException("boom"))
    adapter._client = facade

    result = await adapter.verify("123456")

    assert result is None


async def test_verify_success_with_no_networks_returns_none() -> None:
    """verify() returns None when the account has no networks yet."""
    adapter = EeroClient()
    facade = AsyncMock()
    facade.verify = AsyncMock(return_value=True)
    facade.get_networks = AsyncMock(return_value={"meta": {}, "data": {"networks": []}})
    adapter._client = facade

    result = await adapter.verify("123456")

    assert result is None
