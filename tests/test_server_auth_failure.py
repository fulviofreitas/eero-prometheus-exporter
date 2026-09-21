"""Tests for `--auth-failure-exit` wiring in `server.collection_loop` (§2, D6).

The collector is mocked at its own boundary (`collector.collect()` /
`collector.last_error_kind`) per the repo's testing conventions -- no
`EeroClient` involved here.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from eero_exporter.server import AUTH_FAILURE_EXIT_CODE, collection_loop


def _mock_collector(success: bool, last_error_kind: str | None) -> MagicMock:
    collector = MagicMock()
    collector.collect = AsyncMock(return_value=success)
    collector.last_error_kind = last_error_kind
    return collector


@pytest.mark.asyncio
async def test_auth_failure_exit_true_raises_system_exit_on_terminal_auth_failure() -> None:
    collector = _mock_collector(success=False, last_error_kind="auth")
    stop_event = asyncio.Event()

    with pytest.raises(SystemExit) as exc_info:
        await collection_loop(collector, interval=60, stop_event=stop_event, auth_failure_exit=True)

    assert exc_info.value.code == AUTH_FAILURE_EXIT_CODE


@pytest.mark.asyncio
async def test_auth_failure_exit_false_keeps_looping(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = _mock_collector(success=False, last_error_kind="auth")
    stop_event = asyncio.Event()
    stop_event.set()  # loop body still runs the initial collection once

    # Should not raise: auth_failure_exit defaults to False.
    await collection_loop(collector, interval=60, stop_event=stop_event)
    collector.collect.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_failure_exit_true_but_non_auth_failure_keeps_looping() -> None:
    collector = _mock_collector(success=False, last_error_kind=None)
    stop_event = asyncio.Event()
    stop_event.set()

    # A non-auth failure never triggers the exit, even with the flag on.
    await collection_loop(collector, interval=60, stop_event=stop_event, auth_failure_exit=True)
    collector.collect.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_failure_exit_true_but_success_keeps_looping() -> None:
    collector = _mock_collector(success=True, last_error_kind=None)
    stop_event = asyncio.Event()
    stop_event.set()

    await collection_loop(collector, interval=60, stop_event=stop_event, auth_failure_exit=True)
    collector.collect.assert_awaited_once()
