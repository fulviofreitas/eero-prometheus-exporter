"""Regression tests for issue #139: ``AttributeError`` aborted every collection cycle.

A network with automatic DNS and no custom resolvers ever configured returns
``dns.custom`` as JSON ``null``. ``_collect_network_feature_flags`` chained
``dns_obj.get("custom", {}).get("ips")`` -- the ``{}`` default only applies to a
*missing* key, so a present-but-null ``custom`` raised ``AttributeError``. Every
family collected after the network flags (eeros, devices, profiles, data usage,
extended, rf, ...) was lost, and ``collect()`` reported ``success=False`` with only
the exception class name in the log.

These tests drive the real adapter (only the SDK client is faked, returning raw
``{"meta", "data"}`` envelopes) so the full path the reporter hit is covered:
``/2.2/networks`` with an integer id -> ``/2.2/networks/<id>`` -> every sub-collector.
"""

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from eero_exporter.collector import EeroCollector
from eero_exporter.config import ExporterConfig
from eero_exporter.eero_adapter import EeroClient
from eero_exporter.metrics import (
    DNS_CONFIG_INFO,
    EERO_UP,
    EXPORTER_SCRAPE_ERRORS,
    NETWORK_CUSTOM_DNS_ENABLED,
    NETWORK_DHCP_MODE_INFO,
    NETWORK_DNS_SERVER_COUNT,
    register_metrics,
)

FIXTURES = Path(__file__).parent / "fixtures" / "v8"
NETWORK_ID = "9999424"
# The `name` label comes from the `/networks` list entry, not the envelope.
NETWORK_NAME = "Issue 139"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _envelope(data: Any) -> dict[str, Any]:
    return {"meta": {"code": 200, "server_time": "2026-09-28T06:15:37.000Z"}, "data": data}


class _FakeSdkClient:
    """Stands in for ``eero.EeroClient``: every read returns a raw API envelope.

    Reads without a dedicated fixture answer ``{"data": []}``, which the adapter
    turns into ``[]`` for list reads and ``{}`` for dict reads -- the same thing a
    real but empty endpoint produces.
    """

    def __init__(self, network_envelope: dict[str, Any], **_kwargs: Any) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._answers: dict[str, Any] = {
            # The reporter's account returns the network id as a JSON integer.
            "get_networks": _envelope(
                [
                    {
                        "id": int(NETWORK_ID),
                        "name": NETWORK_NAME,
                        "url": f"/2.2/networks/{NETWORK_ID}",
                    }
                ]
            ),
            "get_network": network_envelope,
            "get_eeros": _envelope(_load("eeros.json")),
            "get_devices": _envelope(_load("devices.json")),
            "get_profiles": _envelope(_load("profiles.json")),
        }
        self.is_authenticated = True

    async def __aenter__(self) -> "_FakeSdkClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    def __getattr__(self, name: str) -> AsyncMock:
        if name.startswith("_"):
            raise AttributeError(name)
        answer = self._answers.get(name, _envelope([]))

        async def _call(*args: Any, **_kwargs: Any) -> Any:
            self.calls.append((name, args))
            return answer

        return AsyncMock(side_effect=_call)


def _config(**overrides: object) -> ExporterConfig:
    values: dict[str, object] = {"data_usage_periods": ["day"]}
    values.update(overrides)
    return ExporterConfig(**values)


async def _run_cycle(
    network_envelope: dict[str, Any], config: ExporterConfig
) -> tuple[bool, _FakeSdkClient]:
    fake = _FakeSdkClient(network_envelope)
    collector = EeroCollector(session_file="/tmp/session.json", config=config)  # nosec B108
    with patch("eero_exporter.eero_adapter.BaseEeroClient", return_value=fake):
        success = await collector.collect()
    return success, fake


def _exposition(config: ExporterConfig) -> str:
    registry = CollectorRegistry()
    register_metrics(config, registry)
    return generate_latest(registry).decode()


def _families_with_series_for(text: str, network_id: str) -> set[str]:
    families = set()
    for line in text.splitlines():
        if line.startswith("#") or f'network_id="{network_id}"' not in line:
            continue
        families.add(line.split("{", 1)[0])
    return families


class TestIssue139Reproduction:
    """The reporter's shape, end to end through the real adapter."""

    @pytest.mark.asyncio
    async def test_null_dns_custom_completes_the_cycle(self) -> None:
        success, _fake = await _run_cycle(_load("network_issue_139.json"), _config())

        assert success is True
        assert EERO_UP._value.get() == 1

    @pytest.mark.asyncio
    async def test_families_beyond_network_and_speed_are_emitted(self) -> None:
        config = _config()
        success, _fake = await _run_cycle(_load("network_issue_139.json"), config)
        assert success is True

        families = _families_with_series_for(_exposition(config), NETWORK_ID)
        # Before the fix only `eero_network_*` / `eero_speed_*` (plus the health
        # gauge read ahead of the crash) carried this network's id.
        for expected in (
            "eero_eero_status",
            "eero_eero_connected_clients_count",
            "eero_device_connected",
            "eero_health_status",
            "eero_network_custom_dns_enabled",
            "eero_dns_config_info",
            "eero_profile_paused",
        ):
            assert expected in families, f"{expected} missing; got {sorted(families)}"
        assert any(f.startswith(("eero_eero_", "eero_device_")) for f in families)

    @pytest.mark.asyncio
    async def test_dns_metrics_reflect_automatic_mode(self) -> None:
        success, _fake = await _run_cycle(_load("network_issue_139.json"), _config())
        assert success is True

        labels = {"network_id": NETWORK_ID, "name": NETWORK_NAME}
        assert NETWORK_CUSTOM_DNS_ENABLED.labels(**labels)._value.get() == 0
        assert NETWORK_DNS_SERVER_COUNT.labels(**labels)._value.get() == 0
        assert DNS_CONFIG_INFO.labels(network_id=NETWORK_ID)._value == {"mode": "automatic"}

    @pytest.mark.asyncio
    async def test_integer_network_id_reaches_the_sdk_as_a_string(self) -> None:
        """eero-api 8.0.5 fixed int ids leaking out of the SDK's own auto-select path;
        the exporter always passes an explicit id, and it must already be a ``str``."""
        success, fake = await _run_cycle(_load("network_issue_139.json"), _config())
        assert success is True

        get_network_args = [args for name, args in fake.calls if name == "get_network"]
        assert get_network_args == [(NETWORK_ID,)]
        assert all(isinstance(args[0], str) for args in get_network_args)

    @pytest.mark.asyncio
    async def test_all_tiers_on_complete_the_cycle(self) -> None:
        config = _config(
            include_per_profile=True,
            include_per_device=True,
            include_per_eero=True,
            include_unverified=True,
            eeros_from_envelope=True,
        )
        success, _fake = await _run_cycle(_load("network_issue_139.json"), config)
        assert success is True

    @pytest.mark.asyncio
    async def test_dhcp_custom_mode_is_reported_verbatim(self) -> None:
        """eero-api 8.0.5 (#136): eero's wire word for a manual range is "custom"."""
        success, _fake = await _run_cycle(_load("network_issue_139.json"), _config())
        assert success is True
        assert NETWORK_DHCP_MODE_INFO.labels(network_id=NETWORK_ID)._value == {"mode": "custom"}


class TestDnsCustomShapes:
    """Every non-dict ``dns.custom`` must degrade to "no custom servers", not raise."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("custom", [None, "x", [], 0, {"ips": None}, {"ips": "1.1.1.1"}])
    async def test_dns_custom_shape_does_not_abort(self, custom: Any) -> None:
        envelope = _load("network_issue_139.json")
        envelope["data"]["dns"]["custom"] = custom
        success, _fake = await _run_cycle(envelope, _config())

        assert success is True
        labels = {"network_id": NETWORK_ID, "name": NETWORK_NAME}
        assert NETWORK_DNS_SERVER_COUNT.labels(**labels)._value.get() == 0

    @pytest.mark.asyncio
    async def test_custom_dns_list_is_still_counted(self) -> None:
        envelope = _load("network_issue_139.json")
        envelope["data"]["dns"] = {"mode": "custom", "custom": {"ips": ["192.0.2.1", "192.0.2.2"]}}
        success, _fake = await _run_cycle(envelope, _config())

        assert success is True
        labels = {"network_id": NETWORK_ID, "name": NETWORK_NAME}
        assert NETWORK_CUSTOM_DNS_ENABLED.labels(**labels)._value.get() == 1
        assert NETWORK_DNS_SERVER_COUNT.labels(**labels)._value.get() == 2


class TestEnvelopeNestedShapes:
    """Nested envelope objects read before the sub-collectors must tolerate any type."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("path", "value"),
        [
            (("health",), "degraded"),
            (("health", "internet"), "connected"),
            (("health", "eero_network"), "connected"),
            (("speed",), "fast"),
            (("speed", "up"), 500),
            (("speed", "down"), [500]),
            (("status",), {"status": None}),
        ],
    )
    async def test_wrong_typed_envelope_field_does_not_abort(
        self, path: tuple[str, ...], value: Any
    ) -> None:
        envelope = _load("network_issue_139.json")
        target = envelope["data"]
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

        success, _fake = await _run_cycle(envelope, _config())
        assert success is True

    @pytest.mark.asyncio
    async def test_null_data_envelope_falls_back_to_the_networks_list_entry(self) -> None:
        success, _fake = await _run_cycle({"meta": {"code": 200}, "data": None}, _config())
        assert success is True


class TestAdapterShapeBoundary:
    """``dict``-returning adapter reads must never raise on a non-dict ``data``."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", [None, [], [{"a": 1}], "x", 0])
    async def test_dict_reads_return_empty_dict_for_non_dict_data(self, data: Any) -> None:
        fake = _FakeSdkClient(_envelope(data))
        fake._answers["get_members"] = _envelope(data)
        with patch("eero_exporter.eero_adapter.BaseEeroClient", return_value=fake):
            async with EeroClient(cookie_file="/tmp/session.json") as client:  # nosec B108
                assert await client.get_network(NETWORK_ID) == {}
                assert await client.get_members(NETWORK_ID) == {}

    @pytest.mark.asyncio
    async def test_dict_reads_pass_dicts_through(self) -> None:
        envelope = _load("network_issue_139.json")
        fake = _FakeSdkClient(envelope)
        with patch("eero_exporter.eero_adapter.BaseEeroClient", return_value=fake):
            async with EeroClient(cookie_file="/tmp/session.json") as client:  # nosec B108
                assert await client.get_network(NETWORK_ID) == envelope["data"]

    @pytest.mark.asyncio
    async def test_integer_network_id_becomes_a_string_preferred_id(self) -> None:
        fake = _FakeSdkClient(_load("network_issue_139.json"))
        with patch("eero_exporter.eero_adapter.BaseEeroClient", return_value=fake):
            async with EeroClient(cookie_file="/tmp/session.json") as client:  # nosec B108
                await client.get_networks()
                assert client._preferred_network_id == NETWORK_ID


class TestSubCollectorIsolation:
    """A bug in one family is logged with its traceback and does not cost the others."""

    @pytest.mark.asyncio
    async def test_failing_sub_collector_is_isolated(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        before = EXPORTER_SCRAPE_ERRORS.labels(error_type="collector")._value.get()
        config = _config()

        def _boom(*_args: Any, **_kwargs: Any) -> None:
            raise AttributeError("'NoneType' object has no attribute 'get'")

        with (
            patch.object(EeroCollector, "_collect_network_feature_flags", side_effect=_boom),
            caplog.at_level(logging.ERROR, logger="eero_exporter.collector"),
        ):
            success, _fake = await _run_cycle(_load("network_issue_139.json"), config)

        assert success is True
        assert EXPORTER_SCRAPE_ERRORS.labels(error_type="collector")._value.get() == before + 1

        records = [r for r in caplog.records if "network_feature_flags" in r.getMessage()]
        assert records, [r.getMessage() for r in caplog.records]
        assert records[0].exc_info is not None
        assert records[0].exc_info[0] is AttributeError

        families = _families_with_series_for(_exposition(config), NETWORK_ID)
        assert "eero_eero_status" in families
        assert "eero_device_connected" in families

    @pytest.mark.asyncio
    async def test_auth_error_inside_a_sub_collector_still_aborts(self) -> None:
        from eero_exporter.eero_adapter import EeroAuthError

        with patch.object(
            EeroCollector, "_collect_device_metrics", side_effect=EeroAuthError("expired")
        ):
            success, _fake = await _run_cycle(_load("network_issue_139.json"), _config())

        assert success is False

    @pytest.mark.asyncio
    async def test_unexpected_top_level_error_logs_the_traceback(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch.object(
                EeroCollector,
                "_collect_network_metrics",
                side_effect=AttributeError("'NoneType' object has no attribute 'get'"),
            ),
            caplog.at_level(logging.ERROR, logger="eero_exporter.collector"),
        ):
            success, _fake = await _run_cycle(_load("network_issue_139.json"), _config())

        assert success is False
        records = [r for r in caplog.records if "Unexpected error during collection" in r.message]
        assert len(records) == 1
        assert records[0].exc_info is not None
        assert "AttributeError" in records[0].getMessage()
        assert "has no attribute 'get'" in records[0].getMessage()
