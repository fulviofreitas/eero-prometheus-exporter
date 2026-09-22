"""Edge-case coverage for the /auth UI: session-file summary parsing,
adapter-error branches on login/verify, rate limiting on verify/reset,
verify-with-no-pending-flow, and collection_loop's generic exception path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eero_exporter.eero_adapter import (
    EeroAPIError,
    EeroAuthError,
    EeroRateLimitError,
    EeroValidationError,
)
from eero_exporter.server import (
    AuthUiState,
    _session_summary,
    _start_auth_ui_loop,
    collection_loop,
)
from tests.test_server_auth_ui import _AuthServer, _csrf_from_body, _mock_client  # noqa: F401

_TOKEN = "a" * 20


# ---------------------------------------------------------------------------
# _session_summary
# ---------------------------------------------------------------------------


def test_session_summary_missing_file() -> None:
    result = _session_summary(Path("/nonexistent/session.json"))
    assert result == {"exists": False, "schema_version": None}


def test_session_summary_unreadable_json(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text("not valid json {{{")
    result = _session_summary(path)
    assert result == {"exists": True, "schema_version": None}


def test_session_summary_not_a_dict(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text("[1, 2, 3]")
    result = _session_summary(path)
    assert result == {"exists": True, "schema_version": None}


def test_session_summary_legacy_schema_missing_version(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text('{"token": "x"}')
    result = _session_summary(path)
    assert result == {"exists": True, "schema_version": "1 (legacy)"}


def test_session_summary_explicit_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text('{"schema_version": 2, "token": "x"}')
    result = _session_summary(path)
    assert result == {"exists": True, "schema_version": 2}


def test_session_summary_permission_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "session.json"
    path.write_text("{}")

    def _raise_oserror(*_a: object, **_k: object) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr("builtins.open", _raise_oserror)
    result = _session_summary(path)
    assert result == {"exists": True, "schema_version": None}


# ---------------------------------------------------------------------------
# /auth/login and /auth/verify: adapter error-class branches
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_server():  # type: ignore[no-untyped-def]
    srv = _AuthServer(enabled=True)
    yield srv
    srv.shutdown()


def test_login_missing_identifier_reprompts_with_400(auth_server: _AuthServer) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    status, _headers, body = auth_server.request(
        "POST", "/auth/login", body=f"token={_TOKEN}&identifier=&csrf={csrf}"
    )
    assert status == 400
    assert "email address or phone number is required" in body.lower()


@pytest.mark.parametrize(
    "exc",
    [
        EeroAuthError("bad identifier"),
        EeroValidationError("bad identifier"),
        EeroRateLimitError("rate limited"),
        EeroAPIError("boom"),
    ],
)
def test_login_adapter_error_reprompts_with_400(auth_server: _AuthServer, exc: Exception) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    mock_client = _mock_client()
    mock_client.login = AsyncMock(side_effect=exc)
    with patch("eero_exporter.server.EeroClient", return_value=mock_client):
        status, _headers, body = auth_server.request(
            "POST", "/auth/login", body=f"token={_TOKEN}&identifier=me@example.com&csrf={csrf}"
        )
    assert status == 400
    assert "login failed" in body.lower()
    assert type(exc).__name__ in body


def test_verify_no_pending_flow_reprompts_with_400(auth_server: _AuthServer) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    status, _headers, body = auth_server.request(
        "POST", "/auth/verify", body=f"token={_TOKEN}&code=123456&csrf={csrf}"
    )
    assert status == 400
    assert "no pending verification" in body.lower()


@pytest.mark.parametrize(
    "exc",
    [
        EeroValidationError("bad code"),
        EeroRateLimitError("rate limited"),
        EeroAPIError("boom"),
    ],
)
def test_verify_non_auth_adapter_error_reprompts_with_400(
    auth_server: _AuthServer, exc: Exception
) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    mock_client = _mock_client()
    with patch("eero_exporter.server.EeroClient", return_value=mock_client):
        auth_server.request(
            "POST", "/auth/login", body=f"token={_TOKEN}&identifier=me@example.com&csrf={csrf}"
        )

    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    mock_client.verify = AsyncMock(side_effect=exc)
    status, _headers, body = auth_server.request(
        "POST", "/auth/verify", body=f"token={_TOKEN}&code=000000&csrf={csrf}"
    )
    assert status == 400
    assert "verification failed" in body.lower()
    assert type(exc).__name__ in body


def test_verify_rate_limited_returns_429(auth_server: _AuthServer) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    for _ in range(5):
        status, _headers, _body = auth_server.request(
            "POST", "/auth/verify", body=f"token=wrong&code=0&csrf={csrf}"
        )
        assert status == 403

    status, headers, _body = auth_server.request(
        "POST", "/auth/verify", body=f"token=wrong&code=0&csrf={csrf}"
    )
    assert status == 429
    assert "Retry-After" in headers


def test_reset_rate_limited_returns_429(auth_server: _AuthServer) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    for _ in range(5):
        status, _headers, _body = auth_server.request(
            "POST", "/auth/reset", body=f"token=wrong&csrf={csrf}"
        )
        assert status == 403

    status, headers, _body = auth_server.request(
        "POST", "/auth/reset", body=f"token=wrong&csrf={csrf}"
    )
    assert status == 429
    assert "Retry-After" in headers


def test_reset_wrong_token_returns_403(auth_server: _AuthServer) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    status, _headers, body = auth_server.request(
        "POST", "/auth/reset", body=f"token=wrong&csrf={csrf}"
    )
    assert status == 403
    assert body == "Forbidden."


# ---------------------------------------------------------------------------
# AuthUiState.start_login: SDK client cleanup on login failure
# ---------------------------------------------------------------------------


def test_start_login_failure_closes_the_client_it_opened() -> None:
    loop, thread = _start_auth_ui_loop()
    try:
        state = AuthUiState(
            token=_TOKEN,
            session_file=Path("/nonexistent/session.json"),
            pending_ttl=600,
            loop=loop,
        )
        mock_client = _mock_client()
        mock_client.login = AsyncMock(side_effect=EeroAuthError("rejected"))
        with patch("eero_exporter.server.EeroClient", return_value=mock_client):
            with pytest.raises(EeroAuthError):
                state.start_login("me@example.test")

        mock_client.__aexit__.assert_awaited()
        assert state.has_pending() is False
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


def test_close_pending_locked_swallows_aexit_failure() -> None:
    """A failing __aexit__ during pending-client cleanup is swallowed, not raised."""
    loop, thread = _start_auth_ui_loop()
    try:
        state = AuthUiState(
            token=_TOKEN,
            session_file=Path("/nonexistent/session.json"),
            pending_ttl=600,
            loop=loop,
        )
        mock_client = _mock_client()
        with patch("eero_exporter.server.EeroClient", return_value=mock_client):
            state.start_login("me@example.test")

        mock_client.__aexit__ = AsyncMock(side_effect=RuntimeError("cleanup boom"))
        # Starting a second login discards the first pending client via
        # _close_pending_locked -- must not raise even though __aexit__ fails.
        mock_client_2 = _mock_client()
        with patch("eero_exporter.server.EeroClient", return_value=mock_client_2):
            state.start_login("someone-else@example.test")

        assert state.has_pending() is True
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# collection_loop: unexpected (non-SystemExit) exception during collect()
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AuthUiState.verify: direct guard against a missing pending flow
# ---------------------------------------------------------------------------


def test_verify_raises_pending_required_when_nothing_pending() -> None:
    from eero_exporter.server import AuthUiPendingRequiredError

    loop, thread = _start_auth_ui_loop()
    try:
        state = AuthUiState(
            token=_TOKEN,
            session_file=Path("/nonexistent/session.json"),
            pending_ttl=600,
            loop=loop,
        )
        with pytest.raises(AuthUiPendingRequiredError):
            state.verify("123456")
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# do_POST: unmatched path under an enabled auth-ui still 404s
# ---------------------------------------------------------------------------


def test_post_unmatched_auth_path_404s_when_enabled(auth_server: _AuthServer) -> None:
    status, _headers, _body = auth_server.request("POST", "/auth/no-such-action", body="a=b")
    assert status == 404


# ---------------------------------------------------------------------------
# _read_form: malformed Content-Length and oversized body
# ---------------------------------------------------------------------------


def test_read_form_zero_content_length_yields_empty_form(auth_server: _AuthServer) -> None:
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", auth_server.port, timeout=5)
    try:
        conn.request("POST", "/auth/reset", body=b"")
        resp = conn.getresponse()
        body = resp.read().decode()
    finally:
        conn.close()
    # Empty form -> token/csrf both missing -> denied, not a 500.
    assert resp.status == 403
    assert body == "Forbidden."


def test_read_form_invalid_content_length_header_yields_empty_form(
    auth_server: _AuthServer,
) -> None:
    import socket

    sock = socket.create_connection(("127.0.0.1", auth_server.port), timeout=5)
    try:
        request = (
            "POST /auth/reset HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{auth_server.port}\r\n"
            "Content-Length: not-a-number\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        sock.sendall(request.encode())
        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
    finally:
        sock.close()
    assert b"403" in response.split(b"\r\n", 1)[0]


def test_read_form_oversized_body_yields_empty_form(auth_server: _AuthServer) -> None:
    import http.client

    oversized = b"token=" + b"a" * 9000
    conn = http.client.HTTPConnection("127.0.0.1", auth_server.port, timeout=5)
    try:
        conn.request("POST", "/auth/reset", body=oversized)
        resp = conn.getresponse()
        body = resp.read().decode()
    finally:
        conn.close()
    assert resp.status == 403
    assert body == "Forbidden."


async def test_collection_loop_handles_unexpected_exception_from_collector() -> None:
    collector = MagicMock()
    collector.collect = AsyncMock(side_effect=RuntimeError("boom"))
    stop_event = asyncio.Event()
    stop_event.set()

    # Must not raise -- the generic except Exception branch records the
    # error into _health_state instead of propagating.
    await collection_loop(collector, interval=60, stop_event=stop_event)
    collector.collect.assert_awaited_once()

    import eero_exporter.server as server_mod

    assert server_mod._health_state["last_collection_success"] is False
    assert server_mod._health_state["last_error"] == "boom"


async def test_collection_loop_collects_again_after_interval_elapses() -> None:
    """The while-loop body (post-initial-collection) fires on a short interval."""
    collector = MagicMock()
    collector.collect = AsyncMock(return_value=True)
    stop_event = asyncio.Event()

    async def _stop_soon() -> None:
        await asyncio.sleep(0.05)
        stop_event.set()

    stopper = asyncio.ensure_future(_stop_soon())
    try:
        await collection_loop(collector, interval=0, stop_event=stop_event)
    finally:
        await stopper

    # Initial collection plus at least one loop-body collection.
    assert collector.collect.await_count >= 2


# ---------------------------------------------------------------------------
# _serve_metrics: exception path -> 500
# ---------------------------------------------------------------------------


def test_serve_metrics_error_returns_500(basic_server_for_metrics_error) -> None:  # noqa: ANN001
    status, _headers, _body = basic_server_for_metrics_error.request("GET", "/metrics")
    assert status == 500


@pytest.fixture
def basic_server_for_metrics_error():  # type: ignore[no-untyped-def]
    from tests.test_server_routes import _BasicServer

    srv = _BasicServer()
    with patch("eero_exporter.server.generate_latest", side_effect=RuntimeError("boom")):
        yield srv
    srv.shutdown()
