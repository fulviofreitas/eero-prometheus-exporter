"""Tests for the read-only API probe.

Nothing here touches the network: the write guard is exercised against the
SDK's real ``BaseAPI`` class (whose methods raise before a request object is
built), and every probe run uses a fake client.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from eero import EeroClient
from eero.api import base as eero_base
from eero.exceptions import EeroNotFoundException, EeroRateLimitException
from typer.testing import CliRunner

from eero_exporter import probe as probe_mod
from eero_exporter.cli import app
from eero_exporter.probe import (
    PROBE_STEPS,
    ProbeBudgetExhausted,
    ProbeContext,
    ProbeOptions,
    ProbeStep,
    ProbeWriteBlocked,
    RequestMeter,
    build_markdown_summary,
    build_report,
    copy_session_file,
    execute_steps,
    inspect_session_file,
    install_write_guard,
    iter_probe_methods,
    redact,
    run_probe_cli,
    write_guard,
)

FIXTURES = Path(__file__).parent / "fixtures" / "probe"

#: Every value planted in the kitchen-sink fixture that must never appear in
#: the serialised redaction output.
PLANTED_SECRETS = (
    "PLANTED-NETWORK-URL",
    "PLANTED-NETWORK-ID",
    "PLANTED-NETWORK-NAME",
    "PLANTED-WIFI-PASSWORD",
    "PLANTED-PSK-VALUE",
    "PLANTED-PASSPHRASE-VALUE",
    "PLANTED-SESSION-TOKEN",
    "PLANTED-API-KEY",
    "PLANTED-COOKIE-VALUE",
    "PLANTED-SECRET-VALUE",
    "PLANTED-HOSTNAME",
    "PLANTED-SSID",
    "PLANTED-NEIGHBOUR-SSID",
    "PLANTED-DDNS-SUBDOMAIN",
    "PLANTED-CITY",
    "PLANTED-COUNTRY",
    "PLANTED-POSTCODE",
    "PLANTED-FIRST-NAME",
    "PLANTED-LAST-NAME",
    "PLANTED-MEMBER-NAME",
    "PLANTED-MEMBER-TWO",
    "PLANTED-GUEST-SSID",
    "PLANTED-GUEST-PASSWORD",
    "PLANTED-BACKUP-SSID",
    "PLANTED-BACKUP-PSK",
    "PLANTED-SUBNET-PASSWORD",
    "PLANTED-EERO-SERIAL",
    "PLANTED-EERO-SERIAL-TWO",
    "PLANTED-EERO-LOCATION",
    "PLANTED-EERO-LOCATION-TWO",
    "PLANTED-FREE-TEXT-NOTE-THAT-IS-LONG",
    "planted.person@example.invalid",
    "planted.member@example.invalid",
    "planted.two@example.invalid",
    "+15550101999",
    "203.0.113.77",
    "192.168.4.1",
    "192.168.4.2",
    "fd00:0000:0000:0000:0000:0000:0000:0001",
    "aa:bb:cc:dd:ee:ff",
    "11:22:33:44:55:66",
    "11:22:33:44:55:67",
    "9911223344",
    "9911223355",
    "12.3456",
    "-65.4321",
    "PLANTED-CHASSIS-ID",
    "PLANTED-PORT-ID",
    "PLANTED-SYSTEM-DESCRIPTION",
    "PLANTED-ORG-ID",
    "203.0.113.53",
)

#: Method-name prefixes that mean "this call can change state".
WRITE_NAME_RE = re.compile(
    r"^(login|verify|logout|set_|create_|delete_|update_|run_|reboot_|request_"
    r"|discover_|start_|pause_|unpause_|block_|unblock_|allow_|apply_|query_"
    r"|respond_|promote_|remove_|cancel_|rearrange_|add_|enable_|disable_"
    r"|clear_|configure_|node_|port_|led_|nightlight_|mark_|regenerate_"
    r"|backup_connectivity_check)"
)


@pytest.fixture
def kitchen_sink() -> dict[str, Any]:
    """The synthetic response carrying every never-export key."""
    return json.loads((FIXTURES / "kitchen_sink.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Layer 1 — write guard
# ---------------------------------------------------------------------------


class TestWriteGuard:
    """The guard must block every non-GET path on ``BaseAPI``."""

    @pytest.mark.parametrize("verb", ["post", "put", "delete"])
    async def test_verb_helpers_raise(self, verb: str) -> None:
        with write_guard():
            method = getattr(eero_base.BaseAPI, verb)
            with pytest.raises(ProbeWriteBlocked):
                await method(object(), "networks/1", json={"x": 1})

    @pytest.mark.parametrize("dispatcher", ["_request", "_request_with_get_retry"])
    @pytest.mark.parametrize("http_method", ["POST", "PUT", "DELETE", "PATCH", "post"])
    async def test_dispatchers_raise_for_non_get(self, dispatcher: str, http_method: str) -> None:
        with write_guard():
            method = getattr(eero_base.BaseAPI, dispatcher)
            with pytest.raises(ProbeWriteBlocked):
                await method(object(), http_method, "networks/1")

    @pytest.mark.parametrize("dispatcher", ["_request", "_request_with_get_retry"])
    async def test_dispatchers_delegate_for_get(self, dispatcher: str) -> None:
        seen: list[str] = []

        async def _fake(self: Any, method: str, url: str, *a: Any, **kw: Any) -> dict[str, Any]:
            seen.append(method)
            return {"ok": True}

        original = getattr(eero_base.BaseAPI, dispatcher)
        setattr(eero_base.BaseAPI, dispatcher, _fake)
        try:
            with write_guard():
                method = getattr(eero_base.BaseAPI, dispatcher)
                assert await method(object(), "GET", "networks/1") == {"ok": True}
        finally:
            setattr(eero_base.BaseAPI, dispatcher, original)
        assert seen == ["GET"]

    def test_uninstall_restores_every_attribute(self) -> None:
        names = ("get", "post", "put", "delete", "_request", "_request_with_get_retry")
        before = {name: getattr(eero_base.BaseAPI, name) for name in names}
        uninstall = install_write_guard()
        assert eero_base.BaseAPI.post is not before["post"]
        uninstall()
        uninstall()  # idempotent
        for name, original in before.items():
            assert getattr(eero_base.BaseAPI, name) is original

    def test_guard_covers_every_write_verb_the_sdk_exposes(self) -> None:
        """No non-GET verb helper on BaseAPI is left unpatched."""
        exposed = {
            name
            for name in ("get", "post", "put", "delete", "patch", "head", "options")
            if hasattr(eero_base.BaseAPI, name)
        }
        assert exposed - {"get"} <= set(probe_mod._WRITE_VERB_METHODS)


# ---------------------------------------------------------------------------
# Layer 2 — allowlist
# ---------------------------------------------------------------------------


class TestAllowlist:
    """Every allowlisted method must exist on the SDK and be a read."""

    def test_methods_exist_on_eero_client(self) -> None:
        missing = [name for name in iter_probe_methods() if not hasattr(EeroClient, name)]
        assert missing == []

    def test_no_write_named_methods(self) -> None:
        offenders = [name for name in iter_probe_methods() if WRITE_NAME_RE.match(name)]
        assert offenders == []

    def test_every_method_is_a_get_or_list_read(self) -> None:
        for name in iter_probe_methods():
            assert name.startswith(("get_", "list_", "has_")), name

    def test_labels_are_unique(self) -> None:
        labels = [step.label for step in PROBE_STEPS]
        assert len(labels) == len(set(labels))

    def test_module_source_contains_no_write_call(self) -> None:
        """A blunt grep over the probe's own source, as a belt-and-braces check."""
        source = Path(probe_mod.__file__).read_text(encoding="utf-8")
        for call in ("c.set_", "c.create_", "c.delete_", "c.update_", "c.run_", "c.reboot_"):
            assert call not in source

    def test_plan_coverage_labels_present(self) -> None:
        required = {
            "account",
            "networks",
            "network",
            "eeros",
            "devices",
            "devices-thread",
            "devices-proxied-node",
            "profiles",
            "guest-network",
            "speed-tests",
            "data-usage-eeros-summary",
            "data-usage-report-settings",
            "insights-devices",
            "insights-profiles",
            "entitlement-features",
            "premium-customer",
            "backup-internet",
            "cellular-backup-events",
            "backup-access-points",
            "wpa3-per-band",
            "fast-transition",
            "permissions",
            "members",
            "notification-history",
            "dns-policy-applications",
            "subnets-config",
            "multistaticip",
            "power-saving-schedules",
            "thread",
            "updates",
            "diagnostics",
            "routing",
            "support",
            "ac-compat",
            "transfer-device",
            "network-scan",
            "app-events",
            "eero-nightlight",
            "eero-connections",
            "eero-ouicheck",
            "device-labels",
            "profile-schedules",
        }
        assert required <= {step.label for step in PROBE_STEPS}


# ---------------------------------------------------------------------------
# Layer 4 — redaction
# ---------------------------------------------------------------------------


class TestRedaction:
    """Redaction must be lossless on shape and total on values."""

    def test_no_planted_secret_survives(self, kitchen_sink: dict[str, Any]) -> None:
        serialised = json.dumps(redact(kitchen_sink))
        leaked = [secret for secret in PLANTED_SECRETS if secret in serialised]
        assert leaked == []

    def test_shape_is_preserved(self, kitchen_sink: dict[str, Any]) -> None:
        tree = redact(kitchen_sink)
        assert set(tree) == {"meta", "data"}
        assert "guest_network" in tree["data"]
        assert tree["data"]["eeros"]["data"]["_type"] == "list"
        assert tree["data"]["eeros"]["data"]["_len"] == 2

    def test_list_item_merges_keys_across_items(self, kitchen_sink: dict[str, Any]) -> None:
        item = redact(kitchen_sink)["data"]["eeros"]["data"]["_item"]
        # `mesh_quality_bars` only exists on the second element.
        assert {"uptime", "wired", "mesh_quality_bars"} <= set(item)

    def test_enum_values_survive(self, kitchen_sink: dict[str, Any]) -> None:
        data = redact(kitchen_sink)["data"]
        assert data["status"] == "connected"
        assert data["mode"] == "auto"
        assert data["type"] == "gateway"
        assert data["health"] == "ok"
        assert data["connection_mode"] == "dhcp"
        assert data["schema_version"] == "2"
        assert data["bands"] == {
            "_type": "list",
            "_len": 2,
            "_item": {"_type": "str"},
            "_values": ["2.4", "5"],
        }

    def test_scalar_list_keeps_length_and_type_when_values_differ(
        self, kitchen_sink: dict[str, Any]
    ) -> None:
        # `bandwidth_usage` is 3 distinct numbers -- must not collapse into a
        # useless `{"_type": "mixed"}` (the bug this fix addresses).
        tree = redact(kitchen_sink)["data"]["bandwidth_usage"]
        assert tree == {"_type": "list", "_len": 3, "_item": {"_type": "int"}}

    def test_list_of_dicts_never_gets_a_bare_type_marker(
        self, kitchen_sink: dict[str, Any]
    ) -> None:
        # A real object's keys (`port`, `connected`) must survive even though
        # `connected` differs across items -- no dict may be replaced outright
        # by `{"_type": "mixed"}`.
        item = redact(kitchen_sink)["data"]["ethernet_status"]["_item"]
        assert set(item) >= {"port", "connected"}
        assert "_type" not in item

    def test_type_conflict_on_a_real_object_keeps_its_keys(
        self, kitchen_sink: dict[str, Any]
    ) -> None:
        # In one item `organization` is an object, in the other it is `null`;
        # in the other, `homekit` is an object vs. a bare bool. Neither real
        # object may be replaced by a bare `{"_type": "mixed"}` -- the bug
        # this fix addresses.
        item = redact(kitchen_sink)["data"]["device_summaries"]["_item"]
        assert "org_id" in item["organization"]
        assert item["organization"]["_note"] == "mixed"
        assert "enabled" in item["homekit"]
        assert item["homekit"]["_note"] == "mixed"

    def test_enum_survives_across_a_list_of_dicts(self, kitchen_sink: dict[str, Any]) -> None:
        # `insight_type` differs on every one of 7 series -- all 7 must
        # survive in the merged item's `_values`.
        item = redact(kitchen_sink)["data"]["insight_series"]["_item"]
        assert item["insight_type"] == {
            "_type": "str",
            "_values": [
                "adblock",
                "bandwidth",
                "blocked",
                "inspected",
                "malware",
                "spam",
                "vpn",
            ],
        }

    def test_enum_survives_nested_inside_a_list_of_dicts(
        self, kitchen_sink: dict[str, Any]
    ) -> None:
        item = redact(kitchen_sink)["data"]["utilization"]["_item"]
        assert item["band"] == {
            "_type": "str",
            "_values": ["band_2_4GHz", "band_5GHz_full"],
        }
        speeds = redact(kitchen_sink)["data"]["statuses"]["_item"]
        assert speeds["speed"] == {"_type": "str", "_values": ["100mbps", "1gbps"]}

    def test_enum_survives_across_merged_list_of_dict_items(
        self, kitchen_sink: dict[str, Any]
    ) -> None:
        item = redact(kitchen_sink)["data"]["eeros"]["data"]["_item"]
        assert item["bands"]["_values"] == ["2.4", "5", "6"]

    def test_timestamps_survive(self, kitchen_sink: dict[str, Any]) -> None:
        tree = redact(kitchen_sink)
        assert tree["meta"]["server_time"] == "2026-09-21T10:11:12Z"
        assert tree["data"]["created"] == "2024-01-02T03:04:05Z"

    def test_numbers_and_booleans_survive(self, kitchen_sink: dict[str, Any]) -> None:
        data = redact(kitchen_sink)["data"]
        assert data["client_count"] == 37
        assert data["upstream_bandwidth_mbps"] == 942.5
        assert data["sqm"] is True
        assert data["ipv6_upstream"] is None

    def test_other_strings_become_lengths(self, kitchen_sink: dict[str, Any]) -> None:
        data = redact(kitchen_sink)["data"]
        assert data["free_text_note"] == {"_type": "str", "_len": 35}
        assert data["geo_ip"]["isp"] == {"_type": "str", "_len": 16}

    def test_never_export_keys_record_type_only(self, kitchen_sink: dict[str, Any]) -> None:
        data = redact(kitchen_sink)["data"]
        assert data["password"] == {"_type": "str", "_value": "<redacted>"}
        assert data["ips"] == {"_type": "list", "_len": 2, "_value": "<redacted>"}
        assert data["bssids_with_bands"] == {"_type": "dict", "_keys": 2, "_value": "<redacted>"}

    def test_never_export_list_and_dict_under_dns_keep_shape(
        self, kitchen_sink: dict[str, Any]
    ) -> None:
        # dns.custom.ips / dns.parent.ips style: still a length, never values.
        assert redact({"ips": ["1.1.1.1", "8.8.8.8", "9.9.9.9"]})["ips"] == {
            "_type": "list",
            "_len": 3,
            "_value": "<redacted>",
        }
        assert redact({"owner": {"a": 1, "b": 2, "c": 3}})["owner"] == {
            "_type": "dict",
            "_keys": 3,
            "_value": "<redacted>",
        }

    def test_boolean_survives_under_a_never_export_key(self) -> None:
        assert redact({"conflicting_ssid": True})["conflicting_ssid"] is True
        assert redact({"enable_credential_syncing": False})["enable_credential_syncing"] is False
        assert redact({"gateway": True})["gateway"] is True
        assert redact({"multi_ssid": True})["multi_ssid"] is True
        assert redact({"one_password": False})["one_password"] is False

    def test_number_and_string_still_redacted_under_a_never_export_key(self) -> None:
        assert redact({"latitude": 12.5})["latitude"] == {
            "_type": "float",
            "_value": "<redacted>",
        }
        assert redact({"ssid": "PLANTED-SSID"})["ssid"] == {
            "_type": "str",
            "_value": "<redacted>",
        }

    def test_camel_case_keys_match_the_snake_case_rule(self) -> None:
        tree = redact({"segmentId": "abc", "chassisId": "def", "portId": "ghi"})
        assert tree["segmentId"]["_value"] == "<redacted>"
        assert tree["chassisId"]["_value"] == "<redacted>"
        assert tree["portId"]["_value"] == "<redacted>"

    def test_name_servers_mode_is_visible(self, kitchen_sink: dict[str, Any]) -> None:
        name_servers = redact(kitchen_sink)["data"]["name_servers"]
        assert name_servers["mode"] == "auto"

    def test_geo_ip_keeps_only_isp(self, kitchen_sink: dict[str, Any]) -> None:
        geo = redact(kitchen_sink)["data"]["geo_ip"]
        assert set(geo) == {"isp", "city", "countryName", "latitude", "longitude", "postalCode"}
        for key in ("city", "countryName", "latitude", "longitude", "postalCode"):
            assert geo[key]["_value"] == "<redacted>"

    def test_ddns_keeps_the_flag_but_not_the_subdomain(self, kitchen_sink: dict[str, Any]) -> None:
        ddns = redact(kitchen_sink)["data"]["ddns"]
        assert ddns["enabled"] is True
        assert ddns["subdomain"]["_value"] == "<redacted>"

    def test_identifier_shaped_dict_keys_are_replaced(self, kitchen_sink: dict[str, Any]) -> None:
        serialised = json.dumps(redact(kitchen_sink))
        assert "<key:" in serialised or "bssids_with_bands" in serialised

    def test_enum_key_holding_an_identifier_is_not_kept(self) -> None:
        assert redact({"status": "aa:bb:cc:dd:ee:ff"})["status"] == {"_type": "str", "_len": 17}
        assert redact({"type": "192.168.1.1"})["type"] == {"_type": "str", "_len": 11}

    def test_enum_key_holding_a_long_string_is_not_kept(self) -> None:
        long_value = "x" * 64
        assert redact({"mode": long_value})["mode"] == {"_type": "str", "_len": 64}

    def test_empty_list_has_no_item(self) -> None:
        assert redact({"series": []})["series"] == {"_type": "list", "_len": 0}

    def test_no_real_dict_is_ever_replaced_by_a_bare_type_marker(
        self, kitchen_sink: dict[str, Any]
    ) -> None:
        """Any dict carrying ``_type`` must be a pure marker (only ``_``-keys).

        A real object -- one with actual field names -- must never be wiped
        out and replaced by ``{"_type": ...}`` just because one key clashed
        across list items; at worst it gains a ``_note: "mixed"`` sibling.
        """

        def _walk(node: Any) -> None:
            if isinstance(node, Mapping):
                if "_type" in node:
                    non_reserved = [k for k in node if not str(k).startswith("_")]
                    assert non_reserved == [], f"real dict wiped by a type marker: {node}"
                for child in node.values():
                    _walk(child)
            elif isinstance(node, (list, tuple)):
                for child in node:
                    _walk(child)

        _walk(redact(kitchen_sink))


# ---------------------------------------------------------------------------
# Layer 3 — budget and rate limiting
# ---------------------------------------------------------------------------


class FakeClient:
    """A read-only stand-in that charges the meter exactly like the SDK GET."""

    def __init__(self, meter: RequestMeter, payload: Any) -> None:
        self._meter = meter
        self._payload = payload
        self.calls: list[str] = []

    async def _read(self, name: str) -> Any:
        self.calls.append(name)
        await self._meter.acquire()
        return self._payload

    def __getattr__(self, name: str) -> Any:
        if not name.startswith(("get_", "list_", "has_")):
            raise AttributeError(name)

        async def _call(*args: Any, **kwargs: Any) -> Any:
            return await self._read(name)

        return _call


def _tiny_steps(count: int) -> tuple[ProbeStep, ...]:
    return tuple(
        ProbeStep(f"step-{index}", "get_account", lambda c, x: c.get_account())
        for index in range(count)
    )


class TestRequestMeter:
    """Budget and pacing."""

    async def test_budget_raises_when_exhausted(self) -> None:
        meter = RequestMeter(budget=2, rate=0)
        await meter.acquire()
        await meter.acquire()
        with pytest.raises(ProbeBudgetExhausted):
            await meter.acquire()
        assert meter.remaining == 0

    async def test_rate_limiter_sleeps_between_requests(self) -> None:
        slept: list[float] = []
        now = [100.0]

        async def _sleep(seconds: float) -> None:
            slept.append(seconds)
            now[0] += seconds

        meter = RequestMeter(budget=5, rate=2.0, sleep=_sleep, clock=lambda: now[0])
        await meter.acquire()
        await meter.acquire()
        await meter.acquire()
        assert slept == [pytest.approx(0.5), pytest.approx(0.5)]

    async def test_rate_limiter_does_not_sleep_when_already_late(self) -> None:
        slept: list[float] = []

        async def _sleep(seconds: float) -> None:  # pragma: no cover - must not run
            slept.append(seconds)

        clock = iter([0.0, 10.0, 20.0])
        meter = RequestMeter(budget=5, rate=1.0, sleep=_sleep, clock=lambda: next(clock))
        await meter.acquire()
        await meter.acquire()
        assert slept == []

    async def test_execute_steps_stops_after_budget(self) -> None:
        meter = RequestMeter(budget=3, rate=0)
        client = FakeClient(meter, {"data": {}})
        results = await execute_steps(
            client, ProbeContext(start="s", end="e"), meter, steps=_tiny_steps(6)
        )
        assert len(client.calls) == 4  # 3 succeed, the 4th trips the budget
        outcomes = [result.outcome for result in results]
        assert outcomes == ["ok", "ok", "ok", "budget-exhausted"] + ["not-run-budget"] * 2


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------


class TestExecuteSteps:
    """Outcome recording, context propagation and early stops."""

    async def test_happy_path_records_redacted_tree(self, kitchen_sink: dict[str, Any]) -> None:
        meter = RequestMeter(budget=10, rate=0)
        client = FakeClient(meter, kitchen_sink)
        results = await execute_steps(
            client, ProbeContext(start="s", end="e"), meter, steps=_tiny_steps(1)
        )
        assert results[0].outcome == "ok"
        assert results[0].gets == 1
        assert results[0].top_level_keys == ["data", "meta"]
        assert "PLANTED-NETWORK-NAME" not in json.dumps(results[0].as_dict())

    async def test_error_is_classified_without_leaking_the_message(self) -> None:
        meter = RequestMeter(budget=10, rate=0)

        class Failing:
            async def get_account(self) -> dict[str, Any]:
                raise EeroNotFoundException(
                    404, "API error 404: not found", error_code="error.network.notfound"
                )

        results = await execute_steps(
            Failing(), ProbeContext(start="s", end="e"), meter, steps=_tiny_steps(1)
        )
        assert results[0].outcome == "error"
        assert results[0].exception == "EeroNotFoundException"
        assert results[0].status_code == 404
        assert results[0].error_code == "error.network.notfound"
        assert "not found" not in json.dumps(results[0].as_dict())

    async def test_rate_limit_stops_the_run(self) -> None:
        meter = RequestMeter(budget=10, rate=0)

        class Limited:
            async def get_account(self) -> dict[str, Any]:
                raise EeroRateLimitException("rate limited")

        results = await execute_steps(
            Limited(), ProbeContext(start="s", end="e"), meter, steps=_tiny_steps(3)
        )
        assert [r.outcome for r in results] == [
            "rate-limited",
            "not-run-rate-limited",
            "not-run-rate-limited",
        ]

    async def test_write_blocked_propagates(self) -> None:
        meter = RequestMeter(budget=10, rate=0)

        class Writing:
            async def get_account(self) -> dict[str, Any]:
                raise ProbeWriteBlocked("nope")

        with pytest.raises(ProbeWriteBlocked):
            await execute_steps(
                Writing(), ProbeContext(start="s", end="e"), meter, steps=_tiny_steps(1)
            )

    async def test_steps_missing_prerequisites_are_skipped(self) -> None:
        meter = RequestMeter(budget=10, rate=0)
        client = FakeClient(meter, {})
        step = ProbeStep(
            "needs-network",
            "get_network",
            lambda c, x: c.get_network(x.network_id),
            requires=("network_id",),
        )
        results = await execute_steps(
            client, ProbeContext(start="s", end="e"), meter, steps=(step,)
        )
        assert results[0].outcome == "skipped"
        assert client.calls == []

    async def test_only_runs_a_single_step(self) -> None:
        meter = RequestMeter(budget=10, rate=0)
        client = FakeClient(meter, {})
        results = await execute_steps(
            client, ProbeContext(start="s", end="e"), meter, steps=_tiny_steps(4), only="step-2"
        )
        assert [r.label for r in results] == ["step-2"]

    async def test_context_is_populated_from_earlier_responses(
        self, kitchen_sink: dict[str, Any]
    ) -> None:
        ctx = ProbeContext(start="s", end="e")
        probe_mod._extract_network(ctx, {"data": {"networks": [{"url": "/2.2/networks/4242"}]}})
        probe_mod._extract_eero(ctx, kitchen_sink["data"]["eeros"])
        probe_mod._extract_device(
            ctx, {"data": [{"url": "/2.2/devices/dev1", "mac": "aa:bb:cc:dd:ee:ff"}]}
        )
        probe_mod._extract_profile(ctx, {"data": {"profiles": [{"url": "/2.2/profiles/77"}]}})
        assert ctx.network_id == "4242"
        assert ctx.eero_id == "9911223344"
        assert ctx.eero_serial == "PLANTED-EERO-SERIAL"
        assert ctx.eero_os_version == "7.1.0-1234"
        assert ctx.device_id == "dev1"
        assert ctx.device_mac == "aa:bb:cc:dd:ee:ff"
        assert ctx.profile_id == "77"

    async def test_channel_utilization_is_a_single_unguarded_step(self) -> None:
        meter = RequestMeter(budget=10, rate=0)
        client = FakeClient(meter, {})
        ctx = ProbeContext(start="s", end="e", network_id="1")
        steps = tuple(step for step in PROBE_STEPS if step.label == "channel-utilization")
        assert len(steps) == 1
        results = await execute_steps(client, ctx, meter, steps=steps)
        assert [result.outcome for result in results] == ["ok"]


# ---------------------------------------------------------------------------
# Session handling
# ---------------------------------------------------------------------------


class TestSessionCopy:
    """The original session file is read, never written."""

    def test_copy_is_private_and_original_unchanged(self, tmp_path: Path) -> None:
        original = tmp_path / "session.json"
        original.write_text(json.dumps({"session_id": "SUPER-SECRET", "schema_version": 1}))
        original.chmod(0o600)
        digest_before = hashlib.sha256(original.read_bytes()).hexdigest()

        temp_dir, copy_path = copy_session_file(original)
        try:
            assert copy_path != original
            assert stat.S_IMODE(copy_path.stat().st_mode) == 0o600
            assert stat.S_IMODE(temp_dir.stat().st_mode) == 0o700
            assert copy_path.read_bytes() == original.read_bytes()
            copy_path.write_text(json.dumps({"session_id": "x", "schema_version": 2}))
            assert hashlib.sha256(original.read_bytes()).hexdigest() == digest_before
        finally:
            for path in (copy_path, temp_dir):
                if path.exists():
                    path.unlink() if path.is_file() else path.rmdir()

    def test_copy_requires_an_existing_source(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            copy_session_file(tmp_path / "missing.json")

    def test_inspect_reports_schema_without_the_token(self, tmp_path: Path) -> None:
        path = tmp_path / "session.json"
        path.write_text(json.dumps({"session_id": "SUPER-SECRET", "schema_version": 2}))
        path.chmod(0o600)
        info = inspect_session_file(path)
        assert info == {
            "exists": True,
            "schema_version": 2,
            "token_key": "session_id",
            "token_present": True,
            "mode": "0o600",
        }
        assert "SUPER-SECRET" not in json.dumps(info)

    def test_inspect_handles_legacy_and_missing_files(self, tmp_path: Path) -> None:
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps({"user_token": "OLD-TOKEN"}))
        info = inspect_session_file(legacy)
        assert info["schema_version"] is None
        assert info["token_key"] == "user_token"

        missing = inspect_session_file(tmp_path / "nope.json")
        assert missing["exists"] is False

        broken = tmp_path / "broken.json"
        broken.write_text("{not json")
        assert inspect_session_file(broken)["schema_version"] == "unreadable"


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


class TestReport:
    """The written artefacts carry no values."""

    async def test_report_and_summary_round_trip(
        self, tmp_path: Path, kitchen_sink: dict[str, Any]
    ) -> None:
        meter = RequestMeter(budget=5, rate=0)
        client = FakeClient(meter, kitchen_sink)
        results = await execute_steps(
            client, ProbeContext(start="s", end="e"), meter, steps=_tiny_steps(2)
        )
        report = build_report(
            results,
            meter=meter,
            session_before={"schema_version": 1, "token_present": True},
            session_after={"schema_version": 2, "token_present": True},
            window=("2026-09-20T00:00:00Z", "2026-09-21T00:00:00Z"),
        )
        json_path, md_path = probe_mod.write_report(report, tmp_path / "probes")
        blob = json_path.read_text(encoding="utf-8") + md_path.read_text(encoding="utf-8")
        assert [secret for secret in PLANTED_SECRETS if secret in blob] == []
        assert report["metadata"]["budget_used"] == 2
        assert report["metadata"]["outcomes"] == {"ok": 2}
        assert "| Step | Method | Outcome |" in build_markdown_summary(report)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestProbeCli:
    """The command surface, including the no-request dry run."""

    def test_dry_run_makes_no_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _explode(_options: ProbeOptions) -> dict[str, Any]:  # pragma: no cover
            raise AssertionError("dry run must not execute the probe")

        monkeypatch.setattr(probe_mod, "run_probe", _explode)
        result = CliRunner().invoke(app, ["probe", "--dry-run"])
        assert result.exit_code == 0
        assert "probe plan" in result.stdout
        assert "get_account" in result.stdout

    def test_dry_run_with_only_lists_one_step(self) -> None:
        result = CliRunner().invoke(app, ["probe", "--dry-run", "--only", "thread"])
        assert result.exit_code == 0
        assert "probe plan — 1 step(s)" in result.stdout

    def test_unknown_only_label_exits_one(self) -> None:
        result = CliRunner().invoke(app, ["probe", "--only", "not-a-step"])
        assert result.exit_code == 1
        assert "unknown step label" in result.stdout

    def test_missing_session_file_exits_one(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(app, ["probe", "--session-file", str(tmp_path / "absent.json")])
        assert result.exit_code == 1
        assert "session file not found" in result.stdout

    def test_every_option_has_an_env_var(self) -> None:
        command = next(
            cmd for cmd in CliRunner().invoke(app, ["--help"]).stdout.splitlines() if "probe" in cmd
        )
        assert "probe" in command
        from typer.main import get_command

        probe_cmd = get_command(app).commands["probe"]  # type: ignore[attr-defined]
        for param in probe_cmd.params:
            if param.name == "help":
                continue
            assert param.envvar, f"--{param.name} has no envvar"
            assert str(param.envvar).startswith("EERO_EXPORTER_PROBE_")

    def test_options_default_to_the_documented_values(self) -> None:
        options = ProbeOptions(session_file=Path("/tmp/x.json"))
        assert options.budget == 80
        assert options.rate == 1.0
        assert options.dry_run is False
        assert options.keep_copy is False

    def test_run_probe_cli_reports_a_blocked_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _blocked(_options: ProbeOptions) -> dict[str, Any]:
            raise ProbeWriteBlocked("blocked a PUT")

        monkeypatch.setattr(probe_mod, "run_probe", _blocked)
        code = run_probe_cli(ProbeOptions(session_file=tmp_path / "s.json"))
        assert code == 2
