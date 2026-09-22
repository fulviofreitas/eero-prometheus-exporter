"""Direct coverage for `_collect_network_feature_flags`'s defensive-parsing
branches that the full-fixture-driven tier tests never exercise (the shared
network fixture always carries `guest_network_enabled` directly).
"""

from unittest.mock import MagicMock

import pytest

from eero_exporter.collector import EeroCollector
from eero_exporter.config import ExporterConfig
from eero_exporter.metrics import NETWORK_GUEST_ENABLED


def _collector() -> EeroCollector:
    return EeroCollector(session_file="/tmp/session.json", config=ExporterConfig())  # nosec B108


@pytest.mark.asyncio
async def test_guest_enabled_falls_back_to_nested_guest_network_object() -> None:
    collector = _collector()
    client = MagicMock()

    await collector._collect_network_feature_flags(
        client,
        "net-1",
        "Test Network",
        {"guest_network": {"enabled": True}},
    )

    value = NETWORK_GUEST_ENABLED.labels(network_id="net-1", name="Test Network")._value.get()
    assert value == 1


@pytest.mark.asyncio
async def test_guest_enabled_defaults_to_zero_when_absent_everywhere() -> None:
    collector = _collector()
    client = MagicMock()

    await collector._collect_network_feature_flags(client, "net-1", "Test Network", {})

    value = NETWORK_GUEST_ENABLED.labels(network_id="net-1", name="Test Network")._value.get()
    assert value == 0


@pytest.mark.asyncio
async def test_guest_enabled_direct_field_takes_precedence() -> None:
    collector = _collector()
    client = MagicMock()

    await collector._collect_network_feature_flags(
        client,
        "net-1",
        "Test Network",
        {"guest_network_enabled": True, "guest_network": {"enabled": False}},
    )

    value = NETWORK_GUEST_ENABLED.labels(network_id="net-1", name="Test Network")._value.get()
    assert value == 1


@pytest.mark.asyncio
async def test_guest_network_info_rendered_when_object_present() -> None:
    collector = _collector()
    client = MagicMock()

    await collector._collect_network_feature_flags(
        client,
        "net-1",
        "Test Network",
        {"guest_network": {"name": "My Guests"}, "guest_network_enabled": True},
    )

    from eero_exporter.metrics import GUEST_NETWORK_INFO

    info = GUEST_NETWORK_INFO.labels(network_id="net-1")._value
    assert info["name"] == "My Guests"
    assert info["enabled"] == "true"


@pytest.mark.asyncio
async def test_all_feature_flags_absent_is_a_no_op() -> None:
    """No feature-flag fields present at all -- must not raise."""
    collector = _collector()
    client = MagicMock()

    await collector._collect_network_feature_flags(client, "net-1", "Test Network", {})
