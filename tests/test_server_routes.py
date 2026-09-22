"""Route-level coverage for MetricsHandler: /health states, /ready, /, /metrics, 404.

Spins up a real `ExporterHTTPServer` on port 0 (no auth-ui), mirroring the
harness in `test_server_auth_ui.py`, and drives it with `http.client`.
`_health_state` is a module-level dict; tests save/restore it around each
mutation so they don't leak state to other tests in the suite.
"""

from __future__ import annotations

import http.client
import json
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Thread
from typing import Any

import pytest

import eero_exporter.server as server_mod
from eero_exporter.server import ExporterHTTPServer, MetricsHandler


class _BasicServer:
    def __init__(self) -> None:
        self.server = ExporterHTTPServer(("127.0.0.1", 0), MetricsHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def request(self, method: str, path: str) -> tuple[int, dict[str, str], str]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            data = resp.read().decode("utf-8", errors="replace")
            return resp.status, dict(resp.getheaders()), data
        finally:
            conn.close()

    def shutdown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)


@pytest.fixture
def basic_server() -> Iterator[_BasicServer]:
    srv = _BasicServer()
    yield srv
    srv.shutdown()


@contextmanager
def _health_state_override(**overrides: Any) -> Iterator[None]:
    """Temporarily overlay `_health_state` fields, restoring the originals after."""
    original = dict(server_mod._health_state)
    server_mod._health_state.update(overrides)
    try:
        yield
    finally:
        server_mod._health_state.clear()
        server_mod._health_state.update(original)


# ---------------------------------------------------------------------------
# /ready -- always 200 while the server is running
# ---------------------------------------------------------------------------


def test_ready_always_200(basic_server: _BasicServer) -> None:
    status, headers, body = basic_server.request("GET", "/ready")
    assert status == 200
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"status": "ready"}


def test_readyz_alias(basic_server: _BasicServer) -> None:
    status, _headers, _body = basic_server.request("GET", "/readyz")
    assert status == 200


# ---------------------------------------------------------------------------
# /health -- healthy / unhealthy / auth-required states
# ---------------------------------------------------------------------------


def test_health_healthy_returns_200(basic_server: _BasicServer) -> None:
    with _health_state_override(session_valid=True, last_collection_success=True, last_error=None):
        status, _headers, body = basic_server.request("GET", "/health")
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "healthy"
    assert "auth" not in payload


def test_health_unhealthy_returns_503_with_last_error(basic_server: _BasicServer) -> None:
    with _health_state_override(
        session_valid=False,
        last_collection_success=False,
        last_error="Collection failed - check logs for details",
        auth_ui_enabled=False,
    ):
        status, _headers, body = basic_server.request("GET", "/health")
    assert status == 503
    payload = json.loads(body)
    assert payload["status"] == "unhealthy"
    assert payload["last_error"] == "Collection failed - check logs for details"
    assert "auth" not in payload


def test_health_auth_required_hint_when_auth_ui_enabled(basic_server: _BasicServer) -> None:
    with _health_state_override(
        session_valid=False,
        last_collection_success=False,
        auth_ui_enabled=True,
    ):
        status, _headers, body = basic_server.request("GET", "/health")
    assert status == 503
    payload = json.loads(body)
    assert payload["auth"] == "required"
    assert payload["hint"] == "Visit /auth to sign in"


def test_health_no_auth_hint_when_session_valid_but_collection_failing(
    basic_server: _BasicServer,
) -> None:
    """auth hint only appears when session_valid is False, even if unhealthy."""
    with _health_state_override(
        session_valid=True,
        last_collection_success=False,
        auth_ui_enabled=True,
    ):
        status, _headers, body = basic_server.request("GET", "/health")
    assert status == 503
    payload = json.loads(body)
    assert "auth" not in payload
    assert "hint" not in payload


def test_healthz_alias(basic_server: _BasicServer) -> None:
    with _health_state_override(session_valid=True, last_collection_success=True):
        status, _headers, _body = basic_server.request("GET", "/healthz")
    assert status == 200


# ---------------------------------------------------------------------------
# / -- index page
# ---------------------------------------------------------------------------


def test_index_shows_healthy_status(basic_server: _BasicServer) -> None:
    with _health_state_override(session_valid=True, last_collection_success=True):
        status, headers, body = basic_server.request("GET", "/")
    assert status == 200
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert "Healthy" in body


def test_index_shows_unhealthy_status(basic_server: _BasicServer) -> None:
    with _health_state_override(session_valid=False, last_collection_success=False):
        status, _headers, body = basic_server.request("GET", "/")
    assert status == 200
    assert "Unhealthy" in body
    assert "Invalid" in body


# ---------------------------------------------------------------------------
# /metrics -- content type
# ---------------------------------------------------------------------------


def test_metrics_content_type_and_200(basic_server: _BasicServer) -> None:
    status, headers, _body = basic_server.request("GET", "/metrics")
    assert status == 200
    assert "text/plain" in headers["Content-Type"]


def test_metrics_with_query_string_still_served(basic_server: _BasicServer) -> None:
    status, _headers, _body = basic_server.request("GET", "/metrics?foo=bar")
    assert status == 200


# ---------------------------------------------------------------------------
# 404s
# ---------------------------------------------------------------------------


def test_unknown_get_path_404(basic_server: _BasicServer) -> None:
    status, _headers, _body = basic_server.request("GET", "/no-such-route")
    assert status == 404


def test_auth_get_404_when_auth_ui_disabled(basic_server: _BasicServer) -> None:
    status, _headers, _body = basic_server.request("GET", "/auth")
    assert status == 404


def test_post_to_any_route_404_when_auth_ui_disabled(basic_server: _BasicServer) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", basic_server.port, timeout=5)
    try:
        conn.request("POST", "/auth/login", body="a=b")
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 404
    finally:
        conn.close()
