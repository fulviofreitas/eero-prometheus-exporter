"""Tests for the collector's pass-through of SDK client options (§4.3.4)
and the `last_error_kind` attribute consumed by `--auth-failure-exit` (§2).

Mocked at the adapter boundary (`eero_exporter.collector.EeroClient`), per
the repo's testing conventions.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eero_exporter.collector import EeroCollector
from eero_exporter.eero_adapter import EeroAuthError


def _mock_client(networks: list[dict[str, object]] | None = None) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get_networks = AsyncMock(return_value=networks or [])
    return client


@pytest.mark.asyncio
async def test_collect_passes_client_options_through_to_eero_client() -> None:
    collector = EeroCollector(
        cookie_file="/tmp/session.json",  # nosec B108 - test fixture path
        send_legacy_cookie=False,
        accept_language="fr-FR",
        get_retries=3,
    )
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client) as mock_ctor:
        await collector.collect()

    mock_ctor.assert_called_once_with(
        cookie_file="/tmp/session.json",  # nosec B108
        send_legacy_cookie=False,
        accept_language="fr-FR",
        get_retries=3,
    )


@pytest.mark.asyncio
async def test_collect_defaults_match_config_defaults() -> None:
    collector = EeroCollector(cookie_file="/tmp/session.json")  # nosec B108
    mock_client = _mock_client()

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client) as mock_ctor:
        await collector.collect()

    _, kwargs = mock_ctor.call_args
    assert kwargs["send_legacy_cookie"] is True
    assert kwargs["accept_language"] == "en-US"
    assert kwargs["get_retries"] == 1


@pytest.mark.asyncio
async def test_last_error_kind_set_to_auth_on_auth_error() -> None:
    collector = EeroCollector(cookie_file="/tmp/session.json")  # nosec B108
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get_networks = AsyncMock(side_effect=EeroAuthError("expired"))

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        success = await collector.collect()

    assert success is False
    assert collector.last_error_kind == "auth"


@pytest.mark.asyncio
async def test_last_error_kind_reset_to_none_on_success() -> None:
    collector = EeroCollector(cookie_file="/tmp/session.json")  # nosec B108
    collector.last_error_kind = "auth"  # simulate a prior failed cycle
    mock_client = _mock_client(networks=[])

    with patch("eero_exporter.collector.EeroClient", return_value=mock_client):
        await collector.collect()

    assert collector.last_error_kind is None
