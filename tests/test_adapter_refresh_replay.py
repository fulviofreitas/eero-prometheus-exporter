"""Refresh-and-replay integration test (plan Sec7.1 / Q8).

Exercises the REAL eero-api 8.x ``EeroClient`` (not a mock of the
adapter's ``self._client``) through the adapter, mocking only the outermost
transport boundary -- ``aiohttp.ClientSession.request`` -- so the SDK's own
401-``error.session.refresh``-detection, single-flight refresh, and replay
logic in ``eero.api.base.BaseAPI._request`` all run for real.

Sequence exercised:
  1. Adapter calls ``get_network`` -> GET returns 401 with
     ``meta.error == "error.session.refresh"``.
  2. The SDK's refresh hook fires -> POST ``/login/refresh`` returns 200.
  3. The SDK replays the original GET -> 200 with the real payload.

Asserts the adapter's call returns the replayed payload and that exactly
one refresh POST occurred (no infinite loop, no double refresh).
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import aiohttp

from eero_exporter.eero_adapter import EeroClient


class _FakeContent:
    """Mimics ``aiohttp.StreamReader`` enough for ``_request``'s chunk loop."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def iter_chunked(self, _n: int):  # noqa: ANN201 - test double
        yield self._body


class _FakeResponse:
    """Mimics an aiohttp response used as ``async with session.request(...) as response``."""

    def __init__(self, status: int, json_body: dict[str, Any]) -> None:
        self.status = status
        self.headers: dict[str, str] = {}
        self.content = _FakeContent(json.dumps(json_body).encode("utf-8"))

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None


def _fake_request_sequence(
    responses: list[tuple[int, dict[str, Any]]],
) -> tuple[list[tuple[str, str]], Any]:
    """Build a ``ClientSession.request`` replacement that returns responses in order.

    Returns the (empty, filled-in-place) list of ``(method, url)`` tuples
    observed, and the callable to install as ``request``.
    """
    calls: list[tuple[str, str]] = []
    remaining = list(responses)

    def _request(method: str, url: str, **_kwargs: Any) -> _FakeResponse:
        calls.append((method, url))
        status, body = remaining.pop(0)
        return _FakeResponse(status, body)

    return calls, _request


async def test_refresh_and_replay_real_sdk(tmp_path: Path) -> None:
    """The adapter surfaces the replayed payload after exactly one transparent refresh."""
    adapter = EeroClient(cookie_file=str(tmp_path / "session.json"), use_keyring=False)

    async with adapter:
        assert adapter._client is not None
        await adapter._client.set_session_token("stale-token")  # noqa: S106 - test fixture only

        replayed_payload = {"meta": {"code": 200}, "data": {"name": "replayed-network"}}
        calls, fake_request = _fake_request_sequence(
            [
                (401, {"meta": {"code": 401, "error": "error.session.refresh"}}),
                (200, {"meta": {"code": 200}, "data": {"user_token": "irrelevant"}}),
                (200, replayed_payload),
            ]
        )

        with patch.object(aiohttp.ClientSession, "request", side_effect=fake_request):
            result = await adapter.get_network("net-1")

        assert result == {"name": "replayed-network"}

        refresh_calls = [call for call in calls if call[1].endswith("/login/refresh")]
        assert len(refresh_calls) == 1, f"expected exactly one refresh call, got {calls}"
        assert len(calls) == 3, f"expected GET, refresh POST, replayed GET; got {calls}"


async def test_terminal_401_surfaces_as_eero_auth_error_when_refresh_fails(tmp_path: Path) -> None:
    """When the refresh itself fails, the original 401 surfaces as EeroAuthError."""
    from eero_exporter.eero_adapter import EeroAuthError

    adapter = EeroClient(cookie_file=str(tmp_path / "session.json"), use_keyring=False)

    async with adapter:
        assert adapter._client is not None
        await adapter._client.set_session_token("stale-token")  # noqa: S106 - test fixture only

        calls, fake_request = _fake_request_sequence(
            [
                (401, {"meta": {"code": 401, "error": "error.session.refresh"}}),
                (401, {"meta": {"code": 401, "error": "error.session.expired"}}),
            ]
        )

        with patch.object(aiohttp.ClientSession, "request", side_effect=fake_request):
            import pytest

            with pytest.raises(EeroAuthError):
                await adapter.get_network("net-1")

        assert len(calls) == 2
