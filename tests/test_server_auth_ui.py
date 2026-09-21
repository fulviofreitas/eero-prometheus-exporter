"""Tests for the opt-in `/auth` web authentication page.

The route-level tests spin up a real `ExporterHTTPServer` on port 0 in a
background thread and drive it with `http.client`, mirroring the rest of
the suite's "mock at the EeroClient boundary" convention: `EeroClient` is
patched at `eero_exporter.server.EeroClient`, the only place `AuthUiState`
constructs one.
"""

from __future__ import annotations

import http.client
import re
import time
from collections.abc import Iterator
from pathlib import Path
from threading import Thread
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

import eero_exporter.server as server_mod
from eero_exporter.cli import app, describe_options
from eero_exporter.config import AUTH_UI_MIN_TOKEN_LENGTH, ExporterConfig
from eero_exporter.eero_adapter import EeroAuthError
from eero_exporter.server import (
    AuthUiState,
    ExporterHTTPServer,
    MetricsHandler,
    _start_auth_ui_loop,
)

runner = CliRunner()

_TOKEN = "a" * 20


def _csrf_from_body(body: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', body)
    assert match, f"csrf field not found in body: {body!r}"
    return match.group(1)


def _has_code_field(body: str) -> bool:
    return 'name="code"' in body


class _AuthServer:
    """A running `ExporterHTTPServer` with (optionally) auth-ui enabled."""

    def __init__(self, enabled: bool = True, pending_ttl: int = 600) -> None:
        self.server = ExporterHTTPServer(("127.0.0.1", 0), MetricsHandler)
        self.auth_loop = None
        self.auth_thread = None
        self.state: AuthUiState | None = None
        if enabled:
            self.auth_loop, self.auth_thread = _start_auth_ui_loop()
            self.state = AuthUiState(
                token=_TOKEN,
                session_file=Path("/nonexistent/session.json"),
                pending_ttl=pending_ttl,
                loop=self.auth_loop,
            )
            self.server.auth_state = self.state
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def request(
        self, method: str, path: str, body: str | None = None
    ) -> tuple[int, dict[str, str], str]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            headers = {}
            if body is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read().decode("utf-8", errors="replace")
            return resp.status, dict(resp.getheaders()), data
        finally:
            conn.close()

    def shutdown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        if self.auth_loop is not None:
            self.auth_loop.call_soon_threadsafe(self.auth_loop.stop)
        if self.auth_thread is not None:
            self.auth_thread.join(timeout=5)


@pytest.fixture
def auth_server() -> Iterator[_AuthServer]:
    srv = _AuthServer(enabled=True)
    yield srv
    srv.shutdown()


@pytest.fixture
def disabled_server() -> Iterator[_AuthServer]:
    srv = _AuthServer(enabled=False)
    yield srv
    srv.shutdown()


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.login = AsyncMock(return_value=None)
    client.verify = AsyncMock(return_value=None)
    return client


# ---------------------------------------------------------------------------
# routes disabled
# ---------------------------------------------------------------------------


def test_routes_404_when_disabled(disabled_server: _AuthServer) -> None:
    status, _headers, _body = disabled_server.request("GET", "/auth")
    assert status == 404

    status, _headers, _body = disabled_server.request(
        "POST", "/auth/login", body="token=x&identifier=y&csrf=z"
    )
    assert status == 404


# ---------------------------------------------------------------------------
# GET /auth
# ---------------------------------------------------------------------------


def test_get_auth_renders_and_sets_security_headers(auth_server: _AuthServer) -> None:
    status, headers, body = auth_server.request("GET", "/auth")
    assert status == 200
    assert "identifier" in body
    assert headers["Content-Security-Policy"] == "default-src 'none'; style-src 'unsafe-inline'"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"
    assert headers["Referrer-Policy"] == "no-referrer"
    # The configured token itself is never rendered.
    assert _TOKEN not in body


def test_index_links_to_auth_only_when_enabled(
    auth_server: _AuthServer, disabled_server: _AuthServer
) -> None:
    _status, _headers, body = auth_server.request("GET", "/")
    assert '/auth"' in body

    _status, _headers, body = disabled_server.request("GET", "/")
    assert '/auth"' not in body


# ---------------------------------------------------------------------------
# token / csrf / rate limiting
# ---------------------------------------------------------------------------


def test_wrong_token_returns_403_denied_body(auth_server: _AuthServer) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    status, _headers, body = auth_server.request(
        "POST", "/auth/login", body=f"token=wrong&identifier=me@example.com&csrf={csrf}"
    )
    assert status == 403
    assert body == "Forbidden."


def test_csrf_missing_returns_403(auth_server: _AuthServer) -> None:
    status, _headers, body = auth_server.request(
        "POST", "/auth/login", body=f"token={_TOKEN}&identifier=me@example.com"
    )
    assert status == 403
    assert body == "Forbidden."


def test_sixth_failed_attempt_returns_429_with_retry_after(auth_server: _AuthServer) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    for _ in range(5):
        status, _headers, _body = auth_server.request(
            "POST", "/auth/login", body=f"token=wrong&identifier=x&csrf={csrf}"
        )
        assert status == 403

    status, headers, body = auth_server.request(
        "POST", "/auth/login", body=f"token=wrong&identifier=x&csrf={csrf}"
    )
    assert status == 429
    assert "Retry-After" in headers


def test_wrong_verification_code_gets_identical_response_to_wrong_token(
    auth_server: _AuthServer,
) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    with patch("eero_exporter.server.EeroClient", return_value=_mock_client()):
        status, _headers, _body = auth_server.request(
            "POST", "/auth/login", body=f"token={_TOKEN}&identifier=me@example.com&csrf={csrf}"
        )
    assert status == 303

    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)
    assert _has_code_field(body)

    mock_client: Any = auth_server.state._pending_client  # type: ignore[union-attr]
    mock_client.verify = AsyncMock(side_effect=EeroAuthError("bad code"))

    wrong_token_status, _headers, wrong_token_body = auth_server.request(
        "POST", "/auth/verify", body=f"token=wrong&code=000000&csrf={csrf}"
    )
    wrong_code_status, _headers, wrong_code_body = auth_server.request(
        "POST", "/auth/verify", body=f"token={_TOKEN}&code=000000&csrf={csrf}"
    )

    assert wrong_token_status == wrong_code_status == 403
    assert wrong_token_body == wrong_code_body == "Forbidden."


# ---------------------------------------------------------------------------
# login -> verify happy path
# ---------------------------------------------------------------------------


def test_login_happy_path_holds_pending_and_redirects(auth_server: _AuthServer) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    mock_client = _mock_client()
    with patch("eero_exporter.server.EeroClient", return_value=mock_client) as ctor:
        status, headers, _body = auth_server.request(
            "POST", "/auth/login", body=f"token={_TOKEN}&identifier=me@example.com&csrf={csrf}"
        )

    assert status == 303
    assert headers["Location"] == "/auth"
    ctor.assert_called_once()
    mock_client.login.assert_awaited_once_with("me@example.com")
    assert auth_server.state is not None
    assert auth_server.state.has_pending() is True

    _status, _headers, body = auth_server.request("GET", "/auth")
    assert _has_code_field(body)
    assert "me@example.com" not in body


def test_verify_happy_path_uses_same_client_and_never_leaks_secrets(
    auth_server: _AuthServer,
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

    status, headers, _body = auth_server.request(
        "POST", "/auth/verify", body=f"token={_TOKEN}&code=123456&csrf={csrf}"
    )
    assert status == 303
    assert headers["Location"] == "/auth"

    mock_client.verify.assert_awaited_once_with("123456")
    mock_client.__aexit__.assert_awaited()
    assert auth_server.state is not None
    assert auth_server.state.has_pending() is False

    _status, _headers, body = auth_server.request("GET", "/auth")
    assert "Session saved to" in body
    assert str(auth_server.state.session_file) in body
    assert "123456" not in body
    assert "me@example.com" not in body
    assert _TOKEN not in body


def test_verify_failure_keeps_pending(auth_server: _AuthServer) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    mock_client = _mock_client()
    mock_client.verify = AsyncMock(side_effect=EeroAuthError("bad code"))
    with patch("eero_exporter.server.EeroClient", return_value=mock_client):
        auth_server.request(
            "POST", "/auth/login", body=f"token={_TOKEN}&identifier=me@example.com&csrf={csrf}"
        )

    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    status, _headers, response_body = auth_server.request(
        "POST", "/auth/verify", body=f"token={_TOKEN}&code=000000&csrf={csrf}"
    )
    assert status == 403
    assert response_body == "Forbidden."
    assert auth_server.state is not None
    assert auth_server.state.has_pending() is True
    mock_client.__aexit__.assert_not_awaited()


def test_reset_closes_pending(auth_server: _AuthServer) -> None:
    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    mock_client = _mock_client()
    with patch("eero_exporter.server.EeroClient", return_value=mock_client):
        auth_server.request(
            "POST", "/auth/login", body=f"token={_TOKEN}&identifier=me@example.com&csrf={csrf}"
        )

    _status, _headers, body = auth_server.request("GET", "/auth")
    csrf = _csrf_from_body(body)

    status, headers, _body = auth_server.request(
        "POST", "/auth/reset", body=f"token={_TOKEN}&csrf={csrf}"
    )
    assert status == 303
    assert headers["Location"] == "/auth"
    assert auth_server.state is not None
    assert auth_server.state.has_pending() is False
    mock_client.__aexit__.assert_awaited()


# ---------------------------------------------------------------------------
# TTL expiry (unit-level, against AuthUiState directly)
# ---------------------------------------------------------------------------


def test_ttl_expiry_discards_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    loop, thread = _start_auth_ui_loop()
    try:
        state = AuthUiState(
            token=_TOKEN,
            session_file=Path("/nonexistent/session.json"),
            pending_ttl=10,
            loop=loop,
        )
        mock_client = _mock_client()
        with patch("eero_exporter.server.EeroClient", return_value=mock_client):
            state.start_login("me@example.com")

        assert state.has_pending() is True

        real_monotonic = time.monotonic()
        monkeypatch.setattr(server_mod.time, "monotonic", lambda: real_monotonic + 9999)

        assert state.has_pending() is False
        mock_client.__aexit__.assert_awaited()
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# config: masking + describe_options
# ---------------------------------------------------------------------------


def test_to_dict_masks_auth_ui_token() -> None:
    config = ExporterConfig(auth_ui=True, auth_ui_token="super-secret-value")
    data = config.to_dict()
    assert data["auth_ui_token"] == "***"
    assert "super-secret-value" not in str(data)


def test_to_dict_auth_ui_token_none_stays_none() -> None:
    config = ExporterConfig()
    assert config.to_dict()["auth_ui_token"] is None


def test_describe_options_lists_the_three_new_options() -> None:
    described = list(describe_options())
    flags = {row.flag for row in described if row.command == "serve"}
    assert "--auth-ui" in flags
    assert "--auth-ui-token" in flags
    assert "--auth-ui-pending-ttl" in flags


# ---------------------------------------------------------------------------
# serve: start-up validation + missing-session-file gate
# ---------------------------------------------------------------------------


@pytest.fixture
def session_file(tmp_path: Path) -> Path:
    path = tmp_path / "session.json"
    path.write_text("{}")
    return path


class TestServeAuthUiStartup:
    def test_auth_ui_without_token_refuses_to_start(self, session_file: Path) -> None:
        with patch("eero_exporter.cli.run_server") as mock_run_server:
            result = runner.invoke(
                app,
                ["serve", "--session-file", str(session_file), "--auth-ui"],
            )
        assert result.exit_code == 1
        mock_run_server.assert_not_called()

    def test_auth_ui_with_short_token_refuses_to_start(self, session_file: Path) -> None:
        with patch("eero_exporter.cli.run_server") as mock_run_server:
            result = runner.invoke(
                app,
                [
                    "serve",
                    "--session-file",
                    str(session_file),
                    "--auth-ui",
                    "--auth-ui-token",
                    "short",
                ],
            )
        assert result.exit_code == 1
        assert len("short") < AUTH_UI_MIN_TOKEN_LENGTH
        mock_run_server.assert_not_called()

    def test_auth_ui_starts_without_a_session_file(self, tmp_path: Path) -> None:
        missing_session = tmp_path / "no-such-session.json"
        captured: dict[str, Any] = {}

        def _fake_run_server(config: Any) -> None:
            captured["auth_ui"] = config.auth_ui

        with patch("eero_exporter.cli.run_server", side_effect=_fake_run_server):
            result = runner.invoke(
                app,
                [
                    "serve",
                    "--session-file",
                    str(missing_session),
                    "--auth-ui",
                    "--auth-ui-token",
                    _TOKEN,
                ],
            )

        assert result.exit_code == 0
        assert captured["auth_ui"] is True

    def test_missing_session_file_without_auth_ui_still_exits(self, tmp_path: Path) -> None:
        missing_session = tmp_path / "no-such-session.json"
        with patch("eero_exporter.cli.run_server") as mock_run_server:
            result = runner.invoke(app, ["serve", "--session-file", str(missing_session)])
        assert result.exit_code == 1
        mock_run_server.assert_not_called()
