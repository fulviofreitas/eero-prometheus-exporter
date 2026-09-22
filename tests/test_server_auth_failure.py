"""Tests for `--auth-failure-exit` wiring in `server.collection_loop` (§2, D6).

The collector is mocked at its own boundary (`collector.collect()` /
`collector.last_error_kind`) per the repo's testing conventions -- no
`EeroClient` involved here.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from eero_exporter.server import AUTH_FAILURE_EXIT_CODE, _health_state, collection_loop


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


@pytest.mark.asyncio
async def test_non_auth_failure_keeps_the_session_marked_valid() -> None:
    """A transport or parser failure must not look like an expired session.

    `session_valid` previously tracked collection success, so any non-auth
    failure flipped it and `/health` told the operator to re-authenticate --
    with the auth page enabled, it also showed the sign-in hint -- for a
    problem that had nothing to do with their credentials.
    """
    _health_state["session_valid"] = True
    collector = _mock_collector(success=False, last_error_kind="network")
    stop_event = asyncio.Event()
    stop_event.set()

    await collection_loop(collector, interval=60, stop_event=stop_event)

    assert _health_state["session_valid"] is True
    assert _health_state["last_collection_success"] is False


@pytest.mark.asyncio
async def test_auth_failure_marks_the_session_invalid() -> None:
    _health_state["session_valid"] = True
    collector = _mock_collector(success=False, last_error_kind="auth")
    stop_event = asyncio.Event()
    stop_event.set()

    await collection_loop(collector, interval=60, stop_event=stop_event)

    assert _health_state["session_valid"] is False


@pytest.mark.asyncio
async def test_unexpected_exception_does_not_invalidate_the_session() -> None:
    """An exception escaping collect() is a bug, not a credential problem."""
    _health_state["session_valid"] = True
    collector = MagicMock()
    collector.collect = AsyncMock(side_effect=RuntimeError("parser blew up"))
    collector.last_error_kind = None
    stop_event = asyncio.Event()
    stop_event.set()

    await collection_loop(collector, interval=60, stop_event=stop_event)

    assert _health_state["session_valid"] is True
    assert _health_state["last_collection_success"] is False
