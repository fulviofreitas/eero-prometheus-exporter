"""Read-only guard test for the full collection cycle (commit 8 deliverable 7).

Builds a collector with EVERY tier and family flag on, mocks the adapter's
client so every read returns a fixture, and runs `collect()` inside
`probe.write_guard()`. Asserts:

1. The cycle completes without `ProbeWriteBlocked`.
2. None of the mock method names called during the cycle match a write-verb
   pattern (`set_*`, `create_*`, `delete_*`, `update_*`, `run_*`, `pause_*`,
   `block_*`, `reboot_*`, `apply_*`, `request_*`, `discover_*`, `start_*`).
3. The total adapter call count for the fixture mesh (E=4, D=3, P=2),
   measured via `EXPORTER_API_REQUESTS_LAST_CYCLE`:

   - **defaults** (every `ExporterConfig()` default -- core families,
     `include_extended`, and the always-on `rf` tier; every other new tier
     off): **29** adapter calls. Roughly: 5 bootstrap/envelope/eeros/
     devices/profiles reads + 4 data-usage (3 periods + 1 breakdown) + 3
     network insights + 3 core list families (port forwards/reservations/
     blacklist) + 9 extended-tier fixed-cost reads + 3 profile-insights +
     1 `get_channel_utilization`.
   - **all tiers on** (`per_profile`/`per_device`/`per_eero`/`unverified`
     also enabled): **58** adapter calls -- the 29 above, plus 3
     (`per_device`'s 3 insight-type calls), plus 3*E=12 (`per_eero`'s
     nightlight/connections/ouicheck per eero), plus P=2 (`per_profile`'s
     DNS-policy-applications per profile), plus 12 (`unverified`'s reads,
     including one `get_transfer_stats` device call since the fixture mesh
     has a device with a MAC).

   Both numbers are asserted directly (not just printed) so a budget
   regression fails the suite, not just a manual read of the docstring.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eero_exporter.collector import EeroCollector
from eero_exporter.config import ExporterConfig
from eero_exporter.metrics import EXPORTER_API_REQUESTS_LAST_CYCLE
from eero_exporter.probe import ProbeWriteBlocked, write_guard

FIXTURES = Path(__file__).parent / "fixtures" / "v8"

# Every non-GET verb pattern the module docstrings/hard rules forbid an
# adapter method from matching.
_WRITE_PREFIXES = (
    "set_",
    "create_",
    "delete_",
    "update_",
    "run_",
    "pause_",
    "block_",
    "reboot_",
    "apply_",
    "request_",
    "discover_",
    "start_",
)


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _full_mock_client() -> MagicMock:
    """A mock client answering every adapter call the collector can issue."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    client.get_networks = AsyncMock(
        return_value=[{"id": "999001", "name": "Test Network", "url": "/2.2/networks/999001"}]
    )
    client.get_network = AsyncMock(return_value=_load("network.json"))
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

    # rf
    client.get_channel_utilization = AsyncMock(return_value=_load("channel_utilization.json"))

    # per_device
    client.get_devices_insights = AsyncMock(return_value=_load("devices_insights.json"))

    # per_eero
    client.get_nightlight = AsyncMock(return_value={})
    client.get_connections = AsyncMock(return_value=_load("eero_connections.json"))
    client.get_ouicheck = AsyncMock(return_value=_load("ouicheck.json"))

    # per_profile
    client.get_dns_policy_applications = AsyncMock(
        return_value=_load("dns_policy_applications.json")
    )

    # unverified
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

    return client


def _config(**overrides: object) -> ExporterConfig:
    defaults: dict[str, object] = {
        "eeros_from_envelope": False,
        "data_usage_periods": ["day", "week", "month"],
    }
    defaults.update(overrides)
    return ExporterConfig(**defaults)


def _called_method_names(mock_client: MagicMock) -> list[str]:
    """Every top-level method name invoked on the mock during the cycle."""
    names = []
    for entry in mock_client.mock_calls:
        # `call.get_network(...)` -> name "get_network"; skip dunder/context
        # manager plumbing (`__aenter__`/`__aexit__`) and chained calls.
        name = entry[0]
        if not name or name.startswith("__") or "()" in name or "." in name:
            continue
        names.append(name)
    return names


@pytest.mark.asyncio
async def test_full_cycle_is_read_only_under_the_probe_write_guard() -> None:
    collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(
            include_per_profile=True,
            include_per_device=True,
            include_per_eero=True,
            include_unverified=True,
        ),
    )
    mock_client = _full_mock_client()

    with write_guard():
        with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
            success = await collector.collect()

    assert success is True

    called_names = _called_method_names(mock_client)
    assert called_names, "expected at least one adapter method to have been called"
    for name in called_names:
        assert not name.startswith(_WRITE_PREFIXES), f"write-verb-shaped call: {name}"


@pytest.mark.asyncio
async def test_write_guard_does_not_interfere_with_a_normal_cycle() -> None:
    """`probe.write_guard()` patches the real SDK's `BaseAPI`, not our mock --
    composing it around `collect()` must be a pure no-op here, proving the
    guard and the mocked collection path never fight each other.
    """
    collector = EeroCollector(session_file="/tmp/session.json", config=_config())  # nosec B108
    mock_client = _full_mock_client()

    try:
        with write_guard():
            with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
                success = await collector.collect()
    except ProbeWriteBlocked:
        pytest.fail("write_guard() blocked a mocked (non-SDK) call")

    assert success is True


@pytest.mark.asyncio
async def test_get_count_defaults_vs_all_tiers_on_for_the_fixture_mesh() -> None:
    """Fixture mesh: E=4 eeros, D=3 devices, P=2 profiles (§ tests/fixtures/v8)."""
    # -- defaults: every core/extended flag at its ExporterConfig() default,
    # plus the always-on `rf` tier; every other new tier off.
    defaults_collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(),
    )
    mock_client = _full_mock_client()
    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        assert await defaults_collector.collect() is True
    defaults_count = EXPORTER_API_REQUESTS_LAST_CYCLE._value.get()

    # -- all tiers on.
    all_on_collector = EeroCollector(
        session_file="/tmp/session.json",  # nosec B108
        config=_config(
            include_per_profile=True,
            include_per_device=True,
            include_per_eero=True,
            include_unverified=True,
        ),
    )
    mock_client_all_on = _full_mock_client()
    with patch("eero_exporter.collector.EeroClient", return_value=mock_client_all_on):
        assert await all_on_collector.collect() is True
    all_on_count = EXPORTER_API_REQUESTS_LAST_CYCLE._value.get()

    # See the module docstring for the itemised arithmetic behind these two
    # numbers, for this exact fixture mesh (E=4, D=3, P=2).
    assert defaults_count == 29
    assert all_on_count == 58
    assert all_on_count > defaults_count
