"""HTTP server for exposing Prometheus metrics."""

import asyncio
import json
import logging
import signal
from http.server import HTTPServer, SimpleHTTPRequestHandler
from threading import Thread

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from . import __version__
from .collector import EeroCollector
from .config import ExporterConfig

_LOGGER = logging.getLogger(__name__)

# Global state for health checks
_health_state: dict[str, bool | int | str | None] = {
    "session_valid": False,
    "last_collection_success": False,
    "last_error": None,
    "collections_total": 0,
    "collections_failed": 0,
}


class MetricsHandler(SimpleHTTPRequestHandler):
    """HTTP handler for Prometheus metrics endpoint."""

    def log_message(self, format: str, *args: object) -> None:
        """Override to use our logger."""
        _LOGGER.debug(f"HTTP: {format % args}")

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

        html = f"""<!DOCTYPE html>
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
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


async def collection_loop(
    collector: EeroCollector,
    interval: int,
    stop_event: asyncio.Event,
) -> None:
    """Run the collection loop.

    Args:
        collector: The metrics collector
        interval: Collection interval in seconds
        stop_event: Event to signal shutdown
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
            _health_state["session_valid"] = success
            if success:
                _health_state["last_error"] = None
            else:
                collections_failed = _health_state["collections_failed"]
                if isinstance(collections_failed, int):
                    _health_state["collections_failed"] = collections_failed + 1
                _health_state["last_error"] = "Collection failed - check logs for details"
        except Exception as e:
            _health_state["last_collection_success"] = False
            _health_state["session_valid"] = False
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


def run_server(config: ExporterConfig) -> None:
    """Run the metrics server.

    Args:
        config: Exporter configuration
    """
    # Create collector
    collector = EeroCollector(
        include_devices=config.include_devices,
        include_profiles=config.include_profiles,
        timeout=config.timeout,
        cookie_file=str(config.session_file),
    )
    # Set collection interval for caching metrics
    collector._collection_interval = config.collection_interval

    # Create HTTP server
    server = HTTPServer((config.host, config.port), MetricsHandler)
    _LOGGER.info(f"HTTP server listening on {config.host}:{config.port}")

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
        await collection_loop(collector, config.collection_interval, stop_event)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _LOGGER.info("Keyboard interrupt received")
    finally:
        server.shutdown()
        _LOGGER.info("Server stopped")
