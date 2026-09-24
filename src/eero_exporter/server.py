"""HTTP server for exposing Prometheus metrics."""

import asyncio
import hmac
import html
import json
import logging
import secrets
import signal
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from . import __version__
from .collector import EeroCollector
from .config import ExporterConfig
from .eero_adapter import (
    EeroAPIError,
    EeroAuthError,
    EeroClient,
    EeroRateLimitError,
    EeroValidationError,
)
from .metrics import register_metrics

_LOGGER = logging.getLogger(__name__)

# §/auth rate limiting: at most this many failed token/CSRF/verification-code
# attempts are tolerated within `_AUTH_UI_RATE_LIMIT_WINDOW_SECONDS`, per
# process, before further attempts get a 429 (D-authui §5).
_AUTH_UI_RATE_LIMIT_MAX_FAILURES = 5
_AUTH_UI_RATE_LIMIT_WINDOW_SECONDS = 15 * 60

# The exact body returned for every one of: wrong `--auth-ui-token`, wrong
# CSRF token, or a wrong verification code. These three failure modes are
# made indistinguishable from each other (same status, same body) so an
# attacker probing the endpoint cannot use response differences as an
# oracle for guessing the token (D-authui §5).
_AUTH_UI_DENIED_BODY = b"Forbidden."

# Exit code raised when `--auth-failure-exit` is set and a collection cycle
# ends with a terminal authentication failure (§2, D6). Mirrors
# `cli.AUTH_FAILURE_EXIT_CODE`; duplicated here (rather than imported) to
# avoid a server -> cli import edge.
AUTH_FAILURE_EXIT_CODE = 2

# Global state for health checks
_health_state: dict[str, bool | int | str | None] = {
    "session_valid": False,
    "last_collection_success": False,
    "last_error": None,
    "collections_total": 0,
    "collections_failed": 0,
    "auth_ui_enabled": False,
}


class AuthUiPendingRequiredError(Exception):
    """Raised when /auth/verify is posted with no pending login flow."""


class AuthUiState:
    """Per-process state for the opt-in `/auth` web login page.

    Holds the single in-flight adapter login/verify client (there is at
    most one pending flow per process at a time), the process-local CSRF
    secret, and a failed-attempt window for rate limiting. Every adapter
    call is dispatched onto ``loop`` (a long-lived background asyncio event
    loop, distinct from the collection loop) via
    ``asyncio.run_coroutine_threadsafe`` so the pending client's aiohttp
    session -- which is bound to the loop it was created on -- stays valid
    across the separate HTTP requests that make up the login -> verify
    flow. All mutable state is guarded by a single lock since the HTTP
    server thread is the only caller.
    """

    def __init__(
        self,
        token: str,
        session_file: Path,
        pending_ttl: int,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Initialize the auth-ui state.

        Args:
            token: The configured `--auth-ui-token` shared secret.
            session_file: The same session file path the collector uses.
            pending_ttl: Seconds a pending login->verify flow stays valid.
            loop: The background event loop adapter calls run on.
        """
        self.token = token
        self.session_file = session_file
        self.pending_ttl = pending_ttl
        self.loop = loop
        self.csrf_token = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self._pending_client: EeroClient | None = None
        self._pending_expiry: float | None = None
        self._failures: list[float] = []
        self._message: str | None = None

    def _run_coro(self, coro: Any) -> Any:
        """Run a coroutine on the background loop and block for its result."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=30)

    def _close_pending_locked(self) -> None:
        client = self._pending_client
        self._pending_client = None
        self._pending_expiry = None
        if client is not None:
            try:
                self._run_coro(client.__aexit__(None, None, None))
            except Exception:  # noqa: BLE001 - best-effort cleanup only  # nosec B110
                pass

    def _expire_pending_locked(self) -> None:
        if (
            self._pending_client is not None
            and self._pending_expiry is not None
            and time.monotonic() >= self._pending_expiry
        ):
            self._close_pending_locked()

    def has_pending(self) -> bool:
        """Report whether a login->verify flow is currently pending."""
        with self._lock:
            self._expire_pending_locked()
            return self._pending_client is not None

    def start_login(self, identifier: str) -> None:
        """Open a new adapter client and start the login flow.

        Any previously pending client is discarded first. On failure the
        newly opened client is closed and the exception re-raised; no
        pending state is left behind.

        Args:
            identifier: Email address or phone number.
        """

        async def _do() -> EeroClient:
            client = EeroClient(cookie_file=str(self.session_file))
            await client.__aenter__()
            try:
                await client.login(identifier)
            except BaseException:
                await client.__aexit__(None, None, None)
                raise
            return client

        client = self._run_coro(_do())
        with self._lock:
            self._close_pending_locked()
            self._pending_client = client
            self._pending_expiry = time.monotonic() + self.pending_ttl

    def verify(self, code: str) -> None:
        """Complete the pending login flow with a verification code.

        On success, the pending client is closed and cleared. On failure,
        the pending client is left in place so the caller can retry the
        code (the flow is only discarded by :meth:`reset` or TTL expiry).

        Args:
            code: The verification code delivered out of band.

        Raises:
            AuthUiPendingRequiredError: If no login flow is pending.
            EeroAuthError: On a wrong/expired verification code.
            EeroAPIError: On any other adapter-level failure.
        """
        with self._lock:
            self._expire_pending_locked()
            client = self._pending_client
        if client is None:
            raise AuthUiPendingRequiredError("No pending verification")

        self._run_coro(client.verify(code))

        with self._lock:
            if self._pending_client is client:
                self._pending_client = None
                self._pending_expiry = None
        self._run_coro(client.__aexit__(None, None, None))

    def reset(self) -> None:
        """Discard any pending login flow, closing its client."""
        with self._lock:
            self._close_pending_locked()

    def is_rate_limited(self) -> tuple[bool, float]:
        """Check whether the failed-attempt window is exhausted.

        Returns:
            A ``(limited, retry_after_seconds)`` tuple. ``retry_after_seconds``
            is ``0.0`` when not limited.
        """
        now = time.monotonic()
        with self._lock:
            self._failures = [
                t for t in self._failures if now - t < _AUTH_UI_RATE_LIMIT_WINDOW_SECONDS
            ]
            if len(self._failures) >= _AUTH_UI_RATE_LIMIT_MAX_FAILURES:
                retry_after = _AUTH_UI_RATE_LIMIT_WINDOW_SECONDS - (now - self._failures[0])
                return True, max(retry_after, 1.0)
            return False, 0.0

    def record_failure(self) -> None:
        """Record one failed token/CSRF/code attempt."""
        with self._lock:
            self._failures.append(time.monotonic())

    def reset_failures(self) -> None:
        """Clear the failed-attempt window (called on any successful step)."""
        with self._lock:
            self._failures.clear()

    def set_message(self, message: str) -> None:
        """Stash a one-shot flash message for the next `/auth` render."""
        with self._lock:
            self._message = message

    def pop_message(self) -> str | None:
        """Return and clear the pending one-shot flash message, if any."""
        with self._lock:
            message = self._message
            self._message = None
            return message


def _session_summary(session_file: Path) -> dict[str, Any]:
    """Summarise a session file without ever reading its token value.

    Mirrors `cli.session_info`'s existence/schema-version checks (kept as a
    small local duplicate rather than a shared import, since this is the
    only piece the `/auth` page needs).

    Args:
        session_file: Path to the session file the collector uses.

    Returns:
        A dict with ``exists`` (bool) and ``schema_version`` (``str | int |
        None``).
    """
    if not session_file.exists():
        return {"exists": False, "schema_version": None}
    try:
        with open(session_file) as f:
            record = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"exists": True, "schema_version": None}
    if not isinstance(record, dict):
        return {"exists": True, "schema_version": None}
    schema_version = record.get("schema_version")
    return {
        "exists": True,
        "schema_version": schema_version if schema_version is not None else "1 (legacy)",
    }


def _render_auth_html(
    csrf_token: str,
    pending: bool,
    session: dict[str, Any],
    message: str | None,
) -> bytes:
    """Render the `/auth` HTML page.

    Plain forms only, no JavaScript. Never renders the configured token,
    an identifier, or a verification code.

    Args:
        csrf_token: The process-local CSRF secret to embed as a hidden field.
        pending: Whether a login flow is currently pending (shows the code
            form instead of the identifier form).
        session: The result of :func:`_session_summary`.
        message: An optional one-line status/error message to display.

    Returns:
        The UTF-8 encoded HTML document.
    """
    csrf_safe = html.escape(csrf_token, quote=True)
    message_html = f'<p class="msg">{html.escape(message)}</p>' if message else ""
    session_line = (
        f"present (schema {html.escape(str(session['schema_version']))})"
        if session["exists"]
        else "absent"
    )

    if pending:
        form_html = f"""
        <form method="post" action="/auth/verify">
            <label>Access token<br><input type="password" name="token" required></label><br>
            <label>Verification code<br><input type="text" name="code" required></label><br>
            <input type="hidden" name="csrf" value="{csrf_safe}">
            <button type="submit">Verify</button>
        </form>
        <form method="post" action="/auth/reset">
            <label>Access token<br><input type="password" name="token" required></label><br>
            <input type="hidden" name="csrf" value="{csrf_safe}">
            <button type="submit">Start over</button>
        </form>
        """
    else:
        form_html = f"""
        <form method="post" action="/auth/login">
            <label>Access token<br><input type="password" name="token" required></label><br>
            <label>Email or phone<br><input type="text" name="identifier" required></label><br>
            <input type="hidden" name="csrf" value="{csrf_safe}">
            <button type="submit">Send code</button>
        </form>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Eero Exporter - Authenticate</title>
    <meta name="robots" content="noindex, nofollow">
    <style>
        body {{ font-family: sans-serif; max-width: 480px; margin: 40px auto; }}
        label {{ display: block; margin-top: 12px; }}
        input {{ width: 100%; padding: 6px; box-sizing: border-box; }}
        button {{ margin-top: 16px; padding: 8px 16px; }}
        .msg {{ padding: 8px; background: #eee; }}
        .warn {{ color: #a00; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>Eero Exporter</h1>
    <p class="warn">Serve this page only over TLS or a trusted network.</p>
    <p>Session file: {session_line}</p>
    {message_html}
    {form_html}
</body>
</html>
""".encode()


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler for the exporter's fixed set of endpoints.

    Deliberately built on `BaseHTTPRequestHandler`, not
    `SimpleHTTPRequestHandler`: the latter's inherited `do_HEAD`/`send_head`
    serve files from the process working directory, which would let an
    unauthenticated client enumerate files (existence, size, mtime) next to
    the exporter. Only the routes matched in `do_GET`/`do_POST` exist.
    """

    def log_message(self, format: str, *args: object) -> None:
        """Override to use our logger."""
        _LOGGER.debug(f"HTTP: {format % args}")

    def _auth_state(self) -> "AuthUiState | None":
        """Return the server's `AuthUiState`, or `None` when auth-ui is off."""
        state = getattr(self.server, "auth_state", None)
        return state if isinstance(state, AuthUiState) else None

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == "/metrics" or self.path.startswith("/metrics?"):
            self._serve_metrics()
        elif self.path == "/health" or self.path == "/healthz":
            self._serve_health()
        elif self.path == "/ready" or self.path == "/readyz":
            self._serve_ready()
        elif self.path == "/":
            self._serve_index()
        elif self.path == "/auth" and self._auth_state() is not None:
            self._serve_auth_page()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        """Handle POST requests -- only the /auth/* routes, when enabled."""
        state = self._auth_state()
        if state is None:
            self.send_error(404)
            return
        if self.path == "/auth/login":
            self._handle_auth_login(state)
        elif self.path == "/auth/verify":
            self._handle_auth_verify(state)
        elif self.path == "/auth/reset":
            self._handle_auth_reset(state)
        else:
            self.send_error(404)

    def _serve_metrics(self) -> None:
        """Serve Prometheus metrics."""
        try:
            output = generate_latest(REGISTRY)
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(output)))
            self.end_headers()
            self.wfile.write(output)
        except Exception as e:
            _LOGGER.error(f"Error generating metrics: {e}")
            self.send_error(500)

    def _serve_ready(self) -> None:
        """Serve readiness check - always 200 if server is running.

        Use this for container health checks (Docker/Kubernetes liveness probes).
        """
        response = b'{"status": "ready"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def _serve_health(self) -> None:
        """Serve health check endpoint with detailed status.

        Use this for monitoring the actual health of the exporter.
        Returns 503 if session is invalid or collections are failing.
        """
        is_healthy = _health_state["session_valid"] and _health_state["last_collection_success"]

        response_data = {
            "status": "healthy" if is_healthy else "unhealthy",
            "session_valid": _health_state["session_valid"],
            "last_collection_success": _health_state["last_collection_success"],
            "collections_total": _health_state["collections_total"],
            "collections_failed": _health_state["collections_failed"],
        }

        if _health_state["last_error"]:
            response_data["last_error"] = _health_state["last_error"]

        if (
            not is_healthy
            and _health_state["auth_ui_enabled"]
            and not _health_state["session_valid"]
        ):
            response_data["auth"] = "required"
            response_data["hint"] = "Visit /auth to sign in"

        response = json.dumps(response_data).encode()

        # Return 200 for healthy, 503 for unhealthy
        status_code = 200 if is_healthy else 503
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def _serve_index(self) -> None:
        """Serve index page with links.

        Per Prometheus guidelines, provide a simple HTML page with exporter
        name, version, and links to /metrics.
        """
        # Determine status indicators
        is_healthy = _health_state["session_valid"] and _health_state["last_collection_success"]
        status_color = "#00d4aa" if is_healthy else "#ff6b6b"
        status_text = "Healthy" if is_healthy else "Unhealthy"
        session_status = "Valid" if _health_state["session_valid"] else "Invalid"
        collections = _health_state["collections_total"]
        auth_link = (
            '<li><a href="/auth">Authentication</a> - Sign in with a verification code</li>'
            if self._auth_state() is not None
            else ""
        )

        page_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Eero Prometheus Exporter</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            max-width: 650px;
            margin: 50px auto;
            padding: 20px;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            min-height: 100vh;
        }}
        h1 {{
            color: #00d4aa;
            border-bottom: 2px solid #00d4aa;
            padding-bottom: 10px;
        }}
        a {{
            color: #00d4aa;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .version {{
            color: #888;
            font-size: 0.9em;
        }}
        .status {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 4px;
            background: {status_color}22;
            color: {status_color};
            border: 1px solid {status_color};
            font-weight: 500;
        }}
        .links {{
            background: rgba(255,255,255,0.1);
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
        }}
        .links li {{
            margin: 10px 0;
        }}
        .info-table {{
            margin-top: 20px;
            width: 100%;
        }}
        .info-table td {{
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        .info-table td:first-child {{
            color: #888;
            width: 40%;
        }}
        .footer {{
            margin-top: 40px;
            color: #888;
            font-size: 0.9em;
        }}
        code {{
            background: rgba(0,212,170,0.1);
            padding: 8px 12px;
            border-radius: 4px;
            display: block;
            margin-top: 8px;
        }}
    </style>
</head>
<body>
    <h1>Eero Prometheus Exporter <span class="version">v{__version__}</span></h1>
    <p>Prometheus metrics exporter for eero mesh WiFi networks.</p>
    <p><span class="status">{status_text}</span></p>

    <div class="links">
        <ul>
            <li><a href="/metrics">Metrics</a> - Prometheus metrics endpoint</li>
            <li><a href="/health">Health</a> - Health check with detailed status</li>
            <li><a href="/ready">Ready</a> - Readiness probe (for k8s/docker)</li>
            {auth_link}
        </ul>
    </div>

    <table class="info-table">
        <tr><td>Session</td><td>{session_status}</td></tr>
        <tr><td>Collections</td><td>{collections}</td></tr>
        <tr><td>Port</td><td>10052 (registered in Prometheus wiki)</td></tr>
    </table>

    <div class="footer">
        <p>Add this target to your Prometheus configuration:</p>
        <code>- targets: ['localhost:10052']</code>
        <p style="margin-top: 20px;">
            <a href="https://github.com/fulviofreitas/eero-prometheus-exporter">GitHub</a> ·
            <a href="https://github.com/fulviofreitas/eero-prometheus-exporter/wiki">Documentation</a>
        </p>
    </div>
</body>
</html>
""".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page_html)))
        self.end_headers()
        self.wfile.write(page_html)

    # =========================================================================
    # /auth -- opt-in web authentication page
    # =========================================================================

    def _auth_security_headers(self) -> None:
        """Send the fixed security headers shared by every /auth* response."""
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")

    def _read_form(self) -> dict[str, str]:
        """Read and parse an `application/x-www-form-urlencoded` POST body.

        Returns:
            A flat dict of the first value per key. Empty when the body is
            missing, empty, or larger than the fixed 8 KiB cap (these forms
            never legitimately need more).
        """
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            return {}
        if length <= 0 or length > 8192:
            return {}
        body = self.rfile.read(length)
        parsed = urllib.parse.parse_qs(
            body.decode("utf-8", errors="replace"), keep_blank_values=True
        )
        return {key: values[0] for key, values in parsed.items()}

    def _auth_token_and_csrf_ok(self, state: "AuthUiState", form: dict[str, str]) -> bool:
        """Constant-time check of the submitted token and CSRF field.

        Both operands are encoded to bytes first: `hmac.compare_digest`
        raises `TypeError` on `str` arguments containing non-ASCII
        characters, and `_read_form` decodes the body with
        `errors="replace"`, so any invalid byte in the submitted token
        would otherwise crash the handler before any authorization check.
        """
        token_ok = hmac.compare_digest(
            form.get("token", "").encode("utf-8"), state.token.encode("utf-8")
        )
        csrf_ok = hmac.compare_digest(
            form.get("csrf", "").encode("utf-8"), state.csrf_token.encode("utf-8")
        )
        return token_ok and csrf_ok

    def _send_auth_denied(self, state: "AuthUiState") -> None:
        """Send the fixed 403 used for a wrong token, wrong CSRF, or wrong code.

        Deliberately identical in status and body across all three cases --
        see the module-level `_AUTH_UI_DENIED_BODY` docstring comment.
        """
        state.record_failure()
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(_AUTH_UI_DENIED_BODY)))
        self._auth_security_headers()
        self.end_headers()
        self.wfile.write(_AUTH_UI_DENIED_BODY)

    def _send_auth_rate_limited(self, retry_after: float) -> None:
        """Send 429 with a `Retry-After` header."""
        body = b"Too Many Requests."
        self.send_response(429)
        self.send_header("Retry-After", str(int(retry_after) + 1))
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._auth_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _redirect_to_auth(self) -> None:
        """Send a 303 redirect back to `/auth` (used after every POST)."""
        self.send_response(303)
        self.send_header("Location", "/auth")
        self._auth_security_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_auth_page(self, status: int = 200, message: str | None = None) -> None:
        """Render the `/auth` page.

        Args:
            status: HTTP status to send (200 for a normal GET, or a 4xx
                passed through by a failed POST handler that re-renders
                the page in place instead of redirecting).
            message: An explicit message to show. When `None`, a pending
                one-shot flash message (e.g. "session saved to ...") is
                popped and shown instead, if any.
        """
        state = self._auth_state()
        assert state is not None  # callers only reach here when enabled
        if message is None:
            message = state.pop_message()
        session = _session_summary(state.session_file)
        body = _render_auth_html(state.csrf_token, state.has_pending(), session, message)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._auth_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _handle_auth_login(self, state: "AuthUiState") -> None:
        """Handle `POST /auth/login` (token, identifier, csrf).

        Never logs the identifier. On success, logs only
        "auth ui: login started".
        """
        limited, retry_after = state.is_rate_limited()
        if limited:
            self._send_auth_rate_limited(retry_after)
            return

        form = self._read_form()
        identifier = form.get("identifier", "")
        # A missing identifier is denied exactly like a wrong token or CSRF:
        # a distinguishable response here would be a free oracle telling an
        # attacker that a guessed access token is correct, without ever
        # sending a verification code. The form marks the field `required`,
        # so a browser never submits this case.
        if not self._auth_token_and_csrf_ok(state, form) or not identifier:
            self._send_auth_denied(state)
            return

        try:
            state.start_login(identifier)
        except EeroAuthError as e:
            self._serve_auth_page(status=400, message=f"Login failed ({type(e).__name__}).")
            return
        except (EeroValidationError, EeroRateLimitError, EeroAPIError) as e:
            self._serve_auth_page(status=400, message=f"Login failed ({type(e).__name__}).")
            return

        _LOGGER.info("auth ui: login started")
        state.reset_failures()
        self._redirect_to_auth()

    def _handle_auth_verify(self, state: "AuthUiState") -> None:
        """Handle `POST /auth/verify` (token, code, csrf).

        A wrong code gets the exact same 403 as a wrong token/CSRF (see
        `_send_auth_denied`) and counts toward the same rate limit. Logs
        only "auth ui: verify ok" or "auth ui: verify failed (<class>)".
        """
        limited, retry_after = state.is_rate_limited()
        if limited:
            self._send_auth_rate_limited(retry_after)
            return

        form = self._read_form()
        code = form.get("code", "")
        # Wrong token, wrong CSRF, missing code and "no pending flow" all
        # produce the identical 403 and all count toward the rate limit, so
        # none of them can be used to test a guessed access token.
        if not self._auth_token_and_csrf_ok(state, form) or not state.has_pending() or not code:
            self._send_auth_denied(state)
            return

        try:
            state.verify(code)
        except EeroAuthError as e:
            _LOGGER.info(f"auth ui: verify failed ({type(e).__name__})")
            self._send_auth_denied(state)
            return
        except (EeroValidationError, EeroRateLimitError, EeroAPIError) as e:
            _LOGGER.info(f"auth ui: verify failed ({type(e).__name__})")
            self._serve_auth_page(status=400, message=f"Verification failed ({type(e).__name__}).")
            return

        _LOGGER.info("auth ui: verify ok")
        state.reset_failures()
        state.set_message(f"Session saved to {state.session_file}")
        self._redirect_to_auth()

    def _handle_auth_reset(self, state: "AuthUiState") -> None:
        """Handle `POST /auth/reset` (token, csrf): discard any pending flow."""
        limited, retry_after = state.is_rate_limited()
        if limited:
            self._send_auth_rate_limited(retry_after)
            return

        form = self._read_form()
        if not self._auth_token_and_csrf_ok(state, form):
            self._send_auth_denied(state)
            return

        state.reset()
        state.reset_failures()
        self._redirect_to_auth()


async def collection_loop(
    collector: EeroCollector,
    interval: int,
    stop_event: asyncio.Event,
    auth_failure_exit: bool = False,
) -> None:
    """Run the collection loop.

    Args:
        collector: The metrics collector
        interval: Collection interval in seconds
        stop_event: Event to signal shutdown
        auth_failure_exit: When True, a collection cycle that ends in a
            terminal authentication failure (``collector.last_error_kind ==
            "auth"``) logs one ERROR with a re-login hint and raises
            ``SystemExit(AUTH_FAILURE_EXIT_CODE)`` instead of letting the
            loop keep retrying forever (§2, D6). Default off.
    """
    _LOGGER.info(f"Starting collection loop (interval: {interval}s)")

    async def do_collection() -> None:
        """Perform collection and update health state."""
        collections_total = _health_state["collections_total"]
        if isinstance(collections_total, int):
            _health_state["collections_total"] = collections_total + 1
        try:
            success = await collector.collect()
            _health_state["last_collection_success"] = success
            # Only an authentication failure invalidates the session. A
            # transport error or a parser bug must not flip `session_valid`,
            # or /health tells the operator to re-authenticate (and, with the
            # auth page on, shows the sign-in hint) for a problem that has
            # nothing to do with their credentials.
            if success:
                _health_state["session_valid"] = True
            elif collector.last_error_kind == "auth":
                _health_state["session_valid"] = False
            if success:
                _health_state["last_error"] = None
            else:
                collections_failed = _health_state["collections_failed"]
                if isinstance(collections_failed, int):
                    _health_state["collections_failed"] = collections_failed + 1
                _health_state["last_error"] = "Collection failed - check logs for details"

                if auth_failure_exit and collector.last_error_kind == "auth":
                    _LOGGER.error(
                        "Terminal authentication failure and --auth-failure-exit is set; "
                        "exiting. Run: eero-exporter login <email-or-phone>"
                    )
                    raise SystemExit(AUTH_FAILURE_EXIT_CODE)
        except SystemExit:
            raise
        except Exception as e:
            # Log before recording: the failure path above tells operators to
            # "check logs for details", and an unexpected exception here (a
            # parser bug, an SDK exception the adapter does not map) would
            # otherwise appear only in the /health JSON, with its type lost.
            _LOGGER.exception("Collection cycle raised %s", type(e).__name__)
            _health_state["last_collection_success"] = False
            # An exception escaping collect() is a bug, not a credential
            # problem, so it leaves `session_valid` alone for the same reason
            # as the failure branch above.
            collections_failed = _health_state["collections_failed"]
            if isinstance(collections_failed, int):
                _health_state["collections_failed"] = collections_failed + 1
            _health_state["last_error"] = str(e)

    # Initial collection
    await do_collection()

    while not stop_event.is_set():
        try:
            # Wait for interval or stop event
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=interval,
            )
        except TimeoutError:
            # Interval elapsed, collect metrics
            await do_collection()

    _LOGGER.info("Collection loop stopped")


class ExporterHTTPServer(HTTPServer):
    """`HTTPServer` with an optional `auth_state` slot for `MetricsHandler`.

    Kept as a real attribute (rather than a module global) so `AuthUiState`
    is scoped to one server instance -- relevant for tests that spin up
    more than one server in the same process.
    """

    auth_state: AuthUiState | None = None


def _start_auth_ui_loop() -> tuple[asyncio.AbstractEventLoop, Thread]:
    """Start a dedicated, long-lived background asyncio event loop.

    The `/auth` page's pending adapter client is bound to whichever loop it
    was created on (its aiohttp session is loop-bound); every login/verify
    call for that client must therefore run on the same loop across
    separate HTTP requests. A one-off `asyncio.run()` per request would
    bind the client to a loop that is immediately closed, so this loop
    starts once, kept alive with `run_forever()`, and every adapter call is
    dispatched onto it with `asyncio.run_coroutine_threadsafe`.

    Returns:
        The running loop and the daemon thread it runs on.
    """
    loop = asyncio.new_event_loop()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = Thread(target=_run, name="auth-ui-loop", daemon=True)
    thread.start()
    return loop, thread


def run_server(config: ExporterConfig) -> None:
    """Run the metrics server.

    Args:
        config: Exporter configuration
    """
    # Create collector. `timeout` is intentionally NOT passed through: it is
    # an HTTP-server-only setting (the v8 SDK client has no such kwarg).
    # Every include_*/tier flag and every SDK client option is read straight
    # off `config` by the collector's own __init__ (commit 3, §1). Tier
    # flags with no consuming family yet (include_extended/rf/per_profile/
    # per_device/per_eero/unverified) are stored as attributes for a later
    # commit.
    collector = EeroCollector(session_file=str(config.session_file), config=config)

    # Register every metric family enabled by `config`'s tier/include_* flags
    # into the default registry `/metrics` renders (commit 4, §3). Safe to
    # call again on repeated `run_server` invocations in the same process
    # (e.g. tests) -- already-registered metrics are skipped.
    register_metrics(config)

    # Create HTTP server
    server = ExporterHTTPServer((config.host, config.port), MetricsHandler)
    _LOGGER.info(f"HTTP server listening on {config.host}:{config.port}")

    _health_state["auth_ui_enabled"] = config.auth_ui

    auth_ui_loop: asyncio.AbstractEventLoop | None = None
    auth_ui_thread: Thread | None = None
    if config.auth_ui and config.auth_ui_token:
        auth_ui_loop, auth_ui_thread = _start_auth_ui_loop()
        server.auth_state = AuthUiState(
            token=config.auth_ui_token,
            session_file=config.session_file,
            pending_ttl=config.auth_ui_pending_ttl,
            loop=auth_ui_loop,
        )
        _LOGGER.info("HTTP server: /auth login page enabled")

    # Create stop event for graceful shutdown
    stop_event = asyncio.Event()
    loop: asyncio.AbstractEventLoop | None = None

    def signal_handler(signum: int, frame: object) -> None:
        """Handle shutdown signals."""
        _LOGGER.info(f"Received signal {signum}, shutting down...")
        if loop:
            loop.call_soon_threadsafe(stop_event.set)
        server.shutdown()

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start HTTP server in a thread
    server_thread = Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    # Run collection loop in the main thread's event loop
    async def main() -> None:
        nonlocal loop
        loop = asyncio.get_running_loop()
        await collection_loop(
            collector,
            config.collection_interval,
            stop_event,
            auth_failure_exit=config.auth_failure_exit,
        )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _LOGGER.info("Keyboard interrupt received")
    finally:
        server.shutdown()
        if server.auth_state is not None:
            server.auth_state.reset()
        if auth_ui_loop is not None and auth_ui_thread is not None:
            auth_ui_loop.call_soon_threadsafe(auth_ui_loop.stop)
            auth_ui_thread.join(timeout=5)
        _LOGGER.info("Server stopped")
