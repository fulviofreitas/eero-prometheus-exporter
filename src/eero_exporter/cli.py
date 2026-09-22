"""CLI for Eero Prometheus Exporter."""

import asyncio
import json
import logging
import os
import stat
from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path
from typing import Any, NamedTuple

import click
import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from . import __version__
from .collector import EeroCollector
from .config import (
    AUTH_UI_MIN_TOKEN_LENGTH,
    DEFAULT_CONFIG_FILE,
    DEFAULT_PORT,
    DEFAULT_SESSION_FILE,
    ExporterConfig,
    envvar_name,
)
from .eero_adapter import (
    EeroAPIError,
    EeroAuthError,
    EeroClient,
    _extract_network_id,
    _parse_network_status,
)
from .metrics import register_metrics
from .probe import DEFAULT_BUDGET as DEFAULT_PROBE_BUDGET
from .probe import DEFAULT_OUT_DIR as DEFAULT_PROBE_OUT_DIR
from .probe import DEFAULT_RATE as DEFAULT_PROBE_RATE
from .probe import ProbeOptions, run_probe_cli
from .server import run_server

app = typer.Typer(
    name="eero-exporter",
    help="Modern Prometheus exporter for eero mesh WiFi networks",
    add_completion=False,
)

console = Console()
_LOGGER = logging.getLogger(__name__)

# Exit code used by `serve` when `--auth-failure-exit` is set and a
# collection cycle ends with a terminal authentication failure (§2, D6).
AUTH_FAILURE_EXIT_CODE = 2

_SESSION_FILE_HELP = "Path to session file"
_SESSION_FILE_ENVVAR = envvar_name("--session-file")


def _session_file_option() -> Any:
    """Build the shared ``--session-file``/``-s`` option used by every command."""
    return typer.Option(
        None,
        "--session-file",
        "-s",
        envvar=_SESSION_FILE_ENVVAR,
        show_envvar=True,
        help=_SESSION_FILE_HELP,
    )


def setup_logging(level: str = "INFO") -> None:
    """Setup logging with rich handler."""
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def _print_api_error(prefix: str, error: EeroAPIError) -> None:
    """Print a one-line, traceback-free summary of an :class:`EeroAPIError`.

    Never prints the upstream response envelope -- only the fields the
    local exception classes expose (``status_code``/``error_code``), plus
    the message the adapter already sanitised.

    Args:
        prefix: A short human label, e.g. ``"Login failed"``.
        error: The caught error.
    """
    detail = str(error)
    if error.status_code is not None:
        detail = f"{detail} (status={error.status_code})"
    if error.error_code is not None:
        detail = f"{detail} [{error.error_code}]"
    console.print(f"[bold red]{prefix}:[/bold red] {detail}")


async def _resolve_network_status(client: EeroClient, network: dict[str, Any]) -> str:
    """Resolve a network's status via the authoritative per-network detail endpoint.

    Mirrors the collector's approach (see ``collector.py:_collect_network_metrics``):
    the ``/networks`` list endpoint does not reliably carry a usable ``status``
    field, so the detail endpoint (``get_network``) is always queried. If the
    detail call fails, this falls back to whatever status (if any) was present
    on the list item, and finally to ``"unknown"`` if nothing is available.

    Args:
        client: An authenticated EeroClient.
        network: A network dict as returned by ``client.get_networks()``.

    Returns:
        The normalized status string.
    """
    network_id = _extract_network_id(network)
    if network_id:
        try:
            network_details = await client.get_network(network_id)
            return _parse_network_status(network_details.get("status"))
        except EeroAPIError as e:
            _LOGGER.debug(f"Failed to get network details for {network_id}: {e}")

    return _parse_network_status(network.get("status"))


@app.command()
def login(
    identifier: str = typer.Argument(
        ...,
        help="Email address or phone number for your eero account",
    ),
    session_file: Path | None = _session_file_option(),
) -> None:
    """Login to your eero account and save the session.

    This will send a verification code to your email or phone.
    """
    setup_logging()
    session_path = session_file or DEFAULT_SESSION_FILE

    async def _login() -> None:
        console.print(f"\n[bold blue]Eero Prometheus Exporter v{__version__}[/bold blue]\n")

        # Use a single client context for the entire login flow
        # (eero-api manages cookies internally)
        async with EeroClient(cookie_file=str(session_path)) as client:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Sending verification code...", total=None)

                try:
                    await client.login(identifier)
                    progress.remove_task(task)
                except EeroAuthError as e:
                    progress.remove_task(task)
                    console.print(f"[bold red]Login failed:[/bold red] {e}")
                    raise typer.Exit(1)
                except EeroAPIError as e:
                    progress.remove_task(task)
                    _print_api_error("Login failed", e)
                    raise typer.Exit(1)

            console.print("[green]✓[/green] Verification code sent!")
            console.print(
                f"\nCheck your {'email' if '@' in identifier else 'phone'} for the code.\n"
            )

            # Get verification code
            code = typer.prompt("Enter verification code")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Verifying code...", total=None)

                try:
                    await client.verify(code)
                    progress.remove_task(task)
                except EeroAuthError as e:
                    progress.remove_task(task)
                    console.print(f"[bold red]Verification failed:[/bold red] {e}")
                    raise typer.Exit(1)
                except EeroAPIError as e:
                    progress.remove_task(task)
                    _print_api_error("Verification failed", e)
                    raise typer.Exit(1)

        console.print("\n[green]✓[/green] Login successful!")
        console.print(f"[dim]Session saved to: {session_path}[/dim]\n")

    asyncio.run(_login())


@app.command()
def logout(
    session_file: Path | None = _session_file_option(),
) -> None:
    """Clear the saved session."""
    setup_logging()
    session_path = session_file or DEFAULT_SESSION_FILE

    if session_path.exists():
        session_path.unlink()
        console.print("[green]✓[/green] Session cleared.")
    else:
        console.print("[yellow]No session file found.[/yellow]")


@app.command()
def validate(
    session_file: Path | None = _session_file_option(),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        envvar=envvar_name("--quiet"),
        show_envvar=True,
        help="Only output errors, exit 0 if valid, 1 if invalid",
    ),
) -> None:
    """Validate session credentials by testing API connectivity.

    Useful for health checks and CI/CD pipelines.
    Exit codes: 0 = valid, 1 = invalid/expired, 2 = no session file
    """
    setup_logging("WARNING" if quiet else "INFO")
    session_path = session_file or DEFAULT_SESSION_FILE

    async def _validate() -> None:
        if not quiet:
            console.print(f"\n[bold blue]Eero Prometheus Exporter v{__version__}[/bold blue]\n")
            console.print(f"Validating session: [dim]{session_path}[/dim]\n")

        # Check if session file exists
        if not session_path.exists():
            if not quiet:
                console.print("[bold red]✗[/bold red] Session file not found")
                console.print("\nRun: [bold]eero-exporter login <email-or-phone>[/bold]")
            raise typer.Exit(2)

        if not quiet:
            console.print("[dim]Session file loaded, testing API...[/dim]")

        # Test API connectivity
        async with EeroClient(cookie_file=str(session_path)) as client:
            try:
                networks = await client.get_networks()

                if not quiet:
                    console.print("[green]✓[/green] Session is valid!")
                    console.print(f"[green]✓[/green] Found {len(networks)} network(s)")
                    for net in networks:
                        name = net.get("name", "Unknown")
                        status = await _resolve_network_status(client, net)
                        console.print(f"    • {name}: {status}")
                    console.print()

                # Success
                raise typer.Exit(0)

            except EeroAuthError as e:
                if not quiet:
                    console.print("[bold red]✗[/bold red] Session expired or invalid")
                    console.print(f"[dim]Error: {e}[/dim]")
                    console.print("\nRun: [bold]eero-exporter login <email-or-phone>[/bold]")
                raise typer.Exit(1)
            except EeroAPIError as e:
                if not quiet:
                    _print_api_error("API error", e)
                raise typer.Exit(1)

    asyncio.run(_validate())


@app.command()
def status(
    session_file: Path | None = _session_file_option(),
) -> None:
    """Check authentication status and show network info."""
    setup_logging()
    session_path = session_file or DEFAULT_SESSION_FILE

    async def _status() -> None:
        console.print(f"\n[bold blue]Eero Prometheus Exporter v{__version__}[/bold blue]\n")

        if not session_path.exists():
            console.print("[yellow]Not authenticated.[/yellow]")
            console.print("\nRun: [bold]eero-exporter login <email-or-phone>[/bold]")
            raise typer.Exit(1)

        console.print("[green]✓[/green] Authenticated\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Fetching network info...", total=None)

            async with EeroClient(cookie_file=str(session_path)) as client:
                try:
                    networks = await client.get_networks()
                    progress.remove_task(task)
                except EeroAuthError:
                    progress.remove_task(task)
                    console.print("[bold red]Session expired. Please login again.[/bold red]")
                    raise typer.Exit(1)
                except EeroAPIError as e:
                    progress.remove_task(task)
                    _print_api_error("API error", e)
                    raise typer.Exit(1)

                if not networks:
                    console.print("[yellow]No networks found.[/yellow]")
                    return

                table = Table(title="Your Networks")
                table.add_column("Name", style="cyan")
                table.add_column("Status", style="green")
                table.add_column("Network ID", style="dim")

                for network in networks:
                    name = network.get("name", "Unknown")
                    net_status = await _resolve_network_status(client, network)
                    url = network.get("url", "")
                    network_id = str(url).rstrip("/").split("/")[-1] if url else "unknown"

                    status_color = "green" if net_status in ("connected", "online") else "red"
                    table.add_row(
                        name, f"[{status_color}]{net_status}[/{status_color}]", network_id
                    )

        console.print(table)
        console.print()

    asyncio.run(_status())


@app.command()
def test(
    session_file: Path | None = _session_file_option(),
) -> None:
    """Test metrics collection without starting the server."""
    setup_logging("DEBUG")
    session_path = session_file or DEFAULT_SESSION_FILE

    async def _test() -> None:
        console.print(f"\n[bold blue]Eero Prometheus Exporter v{__version__}[/bold blue]\n")

        if not session_path.exists():
            console.print("[yellow]Not authenticated.[/yellow]")
            console.print("\nRun: [bold]eero-exporter login <email-or-phone>[/bold]")
            raise typer.Exit(1)

        test_config = ExporterConfig(include_devices=True, include_profiles=True)
        register_metrics(test_config)
        collector = EeroCollector(session_file=str(session_path), config=test_config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Collecting metrics...", total=None)
            try:
                success = await collector.collect()
            except EeroAPIError as e:
                progress.remove_task(task)
                _print_api_error("Metrics collection failed", e)
                raise typer.Exit(1)
            progress.remove_task(task)

        if success:
            console.print("[green]✓[/green] Metrics collection successful!")
            console.print("\n[dim]Run with --log-level DEBUG to see collected metrics.[/dim]")
        else:
            console.print("[bold red]✗[/bold red] Metrics collection failed.")
            raise typer.Exit(1)

    asyncio.run(_test())


@app.command(name="session-info")
def session_info(
    session_file: Path | None = _session_file_option(),
) -> None:
    """Show session-file diagnostics without ever printing the token.

    Prints: path, existence, permission mode bits, whether the file is
    owned by the current user, whether its parent directory is writable,
    the credential ``schema_version`` (``"1 (legacy)"`` when the record
    predates the schema-version marker), and whether a token is present
    (``True``/``False`` only -- never the value).
    """
    setup_logging()
    session_path = session_file or DEFAULT_SESSION_FILE

    console.print(f"\n[bold blue]Eero Prometheus Exporter v{__version__}[/bold blue]\n")
    console.print(f"Session file: [dim]{session_path}[/dim]")

    # `Path.exists()` is not uniformly safe: on Python 3.12/3.13 it re-raises
    # any OSError it does not consider "missing file" (a directory the user
    # cannot traverse, for example), while 3.14 returns False. Stat once,
    # inside the handler, and derive existence from the result.
    try:
        st = session_path.stat()
    except FileNotFoundError:
        console.print("Exists: False")
        console.print("\nRun: [bold]eero-exporter login <email-or-phone>[/bold]")
        raise typer.Exit(1)
    except OSError as e:
        console.print(f"[bold red]Could not stat session file:[/bold red] {e}")
        raise typer.Exit(1)

    console.print("Exists: True")
    mode = stat.filemode(st.st_mode)
    console.print(f"Mode: {mode} ({oct(st.st_mode & 0o777)})")
    console.print(f"Owned by current user: {st.st_uid == os.getuid()}")

    parent_writable = os.access(session_path.parent, os.W_OK)
    console.print(f"Directory writable: {parent_writable}")

    try:
        with open(session_path) as f:
            record = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        console.print(f"[bold red]Could not read session file as JSON:[/bold red] {e}")
        raise typer.Exit(1)

    if not isinstance(record, dict):
        console.print("[bold red]Session file does not contain a JSON object[/bold red]")
        raise typer.Exit(1)

    schema_version = record.get("schema_version")
    schema_display = schema_version if schema_version is not None else "1 (legacy)"
    console.print(f"Schema version: {schema_display}")

    has_token = bool(record.get("session_id") or record.get("user_token"))
    console.print(f"Token present: {has_token}")
    console.print()


@app.command()
def serve(
    port: int | None = typer.Option(
        None,
        "--port",
        "-p",
        envvar=envvar_name("--port"),
        show_envvar=True,
        help=f"Port to listen on (default: {DEFAULT_PORT}, registered in Prometheus wiki)",
    ),
    host: str | None = typer.Option(
        None,
        "--host",
        "-h",
        envvar=envvar_name("--host"),
        show_envvar=True,
        help="Host to bind to",
    ),
    interval: int | None = typer.Option(
        None,
        "--interval",
        "-i",
        envvar=envvar_name("--interval"),
        show_envvar=True,
        help="Collection interval in seconds",
    ),
    session_file: Path | None = _session_file_option(),
    config_file: Path | None = typer.Option(
        None,
        "--config-file",
        "--config",
        "-c",
        envvar=envvar_name("--config-file"),
        show_envvar=True,
        help="Path to config file (--config is kept as an alias)",
    ),
    log_level: str | None = typer.Option(
        None,
        "--log-level",
        "-l",
        envvar=envvar_name("--log-level"),
        show_envvar=True,
        help="Log level (DEBUG, INFO, WARNING, ERROR)",
    ),
    include_devices: bool | None = typer.Option(
        None,
        "--include-devices/--no-devices",
        envvar=envvar_name("--include-devices"),
        show_envvar=True,
        help="Include device metrics",
    ),
    include_profiles: bool | None = typer.Option(
        None,
        "--include-profiles/--no-profiles",
        envvar=envvar_name("--include-profiles"),
        show_envvar=True,
        help="Include profile metrics",
    ),
    include_data_usage: bool | None = typer.Option(
        None,
        "--include-data-usage/--no-data-usage",
        envvar=envvar_name("--include-data-usage"),
        show_envvar=True,
        help="Include data usage metrics (adds ~9 API calls per network per scrape)",
    ),
    include_premium: bool | None = typer.Option(
        None,
        "--include-premium/--no-premium",
        envvar=envvar_name("--include-premium"),
        show_envvar=True,
        help="Include premium-feature metrics",
    ),
    include_ethernet: bool | None = typer.Option(
        None,
        "--include-ethernet/--no-ethernet",
        envvar=envvar_name("--include-ethernet"),
        show_envvar=True,
        help="Include ethernet port metrics",
    ),
    include_thread: bool | None = typer.Option(
        None,
        "--include-thread/--no-thread",
        envvar=envvar_name("--include-thread"),
        show_envvar=True,
        help="Include Thread network metrics",
    ),
    include_port_forwards: bool | None = typer.Option(
        None,
        "--include-port-forwards/--no-port-forwards",
        envvar=envvar_name("--include-port-forwards"),
        show_envvar=True,
        help="Include port-forward metrics",
    ),
    include_reservations: bool | None = typer.Option(
        None,
        "--include-reservations/--no-reservations",
        envvar=envvar_name("--include-reservations"),
        show_envvar=True,
        help="Include DHCP reservation metrics",
    ),
    include_blacklist: bool | None = typer.Option(
        None,
        "--include-blacklist/--no-blacklist",
        envvar=envvar_name("--include-blacklist"),
        show_envvar=True,
        help="Include blacklist metrics",
    ),
    include_insights: bool | None = typer.Option(
        None,
        "--include-insights/--no-insights",
        envvar=envvar_name("--include-insights"),
        show_envvar=True,
        help="Include insights metrics",
    ),
    include_extended: bool | None = typer.Option(
        None,
        "--include-extended/--no-extended",
        envvar=envvar_name("--include-extended"),
        show_envvar=True,
        help="Include the extended tier (entitlements, wpa3, permissions, ...) (§4.2)",
    ),
    include_rf: bool | None = typer.Option(
        None,
        "--include-rf/--no-rf",
        envvar=envvar_name("--include-rf"),
        show_envvar=True,
        help="Include the RF tier (channel utilisation per band) (§4.2)",
    ),
    include_per_profile: bool | None = typer.Option(
        None,
        "--include-per-profile/--no-per-profile",
        envvar=envvar_name("--include-per-profile"),
        show_envvar=True,
        help="Include the per-profile tier (off by default, extra GETs per profile)",
    ),
    include_per_device: bool | None = typer.Option(
        None,
        "--include-per-device/--no-per-device",
        envvar=envvar_name("--include-per-device"),
        show_envvar=True,
        help="Include the per-device tier (off by default, high cardinality)",
    ),
    include_per_eero: bool | None = typer.Option(
        None,
        "--include-per-eero/--no-per-eero",
        envvar=envvar_name("--include-per-eero"),
        show_envvar=True,
        help="Include the per-eero tier (nightlight, connections, ...)",
    ),
    include_unverified: bool | None = typer.Option(
        None,
        "--include-unverified/--no-unverified",
        envvar=envvar_name("--include-unverified"),
        show_envvar=True,
        help="Include unverified-shape families (off until a shape is captured)",
    ),
    get_retries: int | None = typer.Option(
        None,
        "--get-retries",
        envvar=envvar_name("--get-retries"),
        show_envvar=True,
        help="Bounded SDK GET retry count on transport/5xx errors (never writes)",
    ),
    send_legacy_cookie: bool | None = typer.Option(
        None,
        "--send-legacy-cookie/--no-legacy-cookie",
        envvar=envvar_name("--send-legacy-cookie"),
        show_envvar=True,
        help="Also send the legacy session cookie alongside X-User-Token",
    ),
    accept_language: str | None = typer.Option(
        None,
        "--accept-language",
        envvar=envvar_name("--accept-language"),
        show_envvar=True,
        help="Value sent as the X-Accept-Language header",
    ),
    data_usage_periods: str | None = typer.Option(
        None,
        "--data-usage-periods",
        envvar=envvar_name("--data-usage-periods"),
        show_envvar=True,
        help="Comma-separated data-usage windows to collect (day,week,month)",
    ),
    eeros_from_envelope: bool | None = typer.Option(
        None,
        "--eeros-from-envelope/--no-eeros-from-envelope",
        envvar=envvar_name("--eeros-from-envelope"),
        show_envvar=True,
        help="Read eeros from the cached network envelope instead of a separate GET",
    ),
    auth_failure_exit: bool | None = typer.Option(
        None,
        "--auth-failure-exit/--no-auth-failure-exit",
        envvar=envvar_name("--auth-failure-exit"),
        show_envvar=True,
        help="Exit non-zero on a terminal authentication failure instead of retrying forever",
    ),
    expose_public_ip: bool | None = typer.Option(
        None,
        "--expose-public-ip/--no-expose-public-ip",
        envvar=envvar_name("--expose-public-ip"),
        show_envvar=True,
        help="Add public_ip back onto eero_network_info (off by default, D13)",
    ),
    auth_ui: bool | None = typer.Option(
        None,
        "--auth-ui/--no-auth-ui",
        envvar=envvar_name("--auth-ui"),
        show_envvar=True,
        help=(
            "Enable the opt-in /auth web login page. Put it behind TLS or a "
            "trusted network -- it accepts a shared secret over plain HTTP otherwise"
        ),
    ),
    auth_ui_token: str | None = typer.Option(
        None,
        "--auth-ui-token",
        envvar=envvar_name("--auth-ui-token"),
        show_envvar=True,
        help=(
            f"Shared secret required by /auth (min {AUTH_UI_MIN_TOKEN_LENGTH} chars, never logged)"
        ),
    ),
    auth_ui_pending_ttl: int | None = typer.Option(
        None,
        "--auth-ui-pending-ttl",
        envvar=envvar_name("--auth-ui-pending-ttl"),
        show_envvar=True,
        help="Seconds a pending /auth login->verify flow stays valid before expiring",
    ),
) -> None:
    """Start the Prometheus metrics server."""
    # Load YAML first (lowest precedence above the dataclass default),
    # then apply only the CLI/env values that were actually provided
    # (non-None) -- this is the CLI > env > YAML > default fix (D6).
    resolved_config_file = config_file or DEFAULT_CONFIG_FILE
    if resolved_config_file.exists():
        config = ExporterConfig.from_file(resolved_config_file)
    else:
        config = ExporterConfig()

    config = config.merge_overrides(
        port=port,
        host=host,
        collection_interval=interval,
        session_file=session_file,
        log_level=log_level,
        include_devices=include_devices,
        include_profiles=include_profiles,
        include_data_usage=include_data_usage,
        include_premium=include_premium,
        include_ethernet=include_ethernet,
        include_thread=include_thread,
        include_port_forwards=include_port_forwards,
        include_reservations=include_reservations,
        include_blacklist=include_blacklist,
        include_insights=include_insights,
        include_extended=include_extended,
        include_rf=include_rf,
        include_per_profile=include_per_profile,
        include_per_device=include_per_device,
        include_per_eero=include_per_eero,
        include_unverified=include_unverified,
        get_retries=get_retries,
        send_legacy_cookie=send_legacy_cookie,
        accept_language=accept_language,
        data_usage_periods=data_usage_periods,
        eeros_from_envelope=eeros_from_envelope,
        auth_failure_exit=auth_failure_exit,
        expose_public_ip=expose_public_ip,
        auth_ui=auth_ui,
        auth_ui_token=auth_ui_token,
        auth_ui_pending_ttl=auth_ui_pending_ttl,
    )

    setup_logging(config.log_level.upper())

    # `--auth-ui` requires a shared secret of a minimum length -- refuse to
    # start rather than serve a login page with no meaningful protection.
    if config.auth_ui and (
        not config.auth_ui_token or len(config.auth_ui_token) < AUTH_UI_MIN_TOKEN_LENGTH
    ):
        console.print(
            f"[bold red]--auth-ui requires --auth-ui-token "
            f"of at least {AUTH_UI_MIN_TOKEN_LENGTH} characters.[/bold red]"
        )
        raise typer.Exit(1)

    # Check session file exists. When `--auth-ui` is enabled, the exporter
    # starts anyway: the collector keeps recording auth failures and the
    # session can be created later via the /auth page. Without `--auth-ui`,
    # behaviour is unchanged: a missing session file is a hard stop. Note:
    # if `--auth-failure-exit` is also set, it does not fire on a merely
    # *missing* session file -- only on a terminal auth failure surfaced by
    # the collector -- so the two flags can be combined safely.
    if not config.session_file.exists():
        if not config.auth_ui:
            console.print("[bold red]Not authenticated.[/bold red]")
            console.print("\nRun: [bold]eero-exporter login <email-or-phone>[/bold]")
            raise typer.Exit(1)
        console.print(
            "[yellow]Not authenticated yet.[/yellow] "
            f"Visit [green]http://{config.host}:{config.port}/auth[/green] to sign in."
        )

    console.print(
        Panel.fit(
            f"[bold blue]Eero Prometheus Exporter v{__version__}[/bold blue]\n\n"
            f"Listening on: [green]http://{config.host}:{config.port}/metrics[/green]\n"
            f"Collection interval: [cyan]{config.collection_interval}s[/cyan]",
            title="Starting Exporter",
        )
    )

    # Run server
    try:
        run_server(config)
    except SystemExit as e:
        raise typer.Exit(e.code if isinstance(e.code, int) else 1)


@app.command()
def probe(
    session_file: Path = typer.Option(
        DEFAULT_SESSION_FILE,
        "--session-file",
        "-s",
        envvar="EERO_EXPORTER_PROBE_SESSION_FILE",
        help="Session file to copy for the run (the original is never written to)",
    ),
    out: Path = typer.Option(
        DEFAULT_PROBE_OUT_DIR,
        "--out",
        "-o",
        envvar="EERO_EXPORTER_PROBE_OUT",
        help="Directory for the redacted JSON report and its Markdown summary",
    ),
    budget: int = typer.Option(
        DEFAULT_PROBE_BUDGET,
        "--budget",
        "-b",
        envvar="EERO_EXPORTER_PROBE_BUDGET",
        help="Maximum number of GET requests for the whole run",
    ),
    rate: float = typer.Option(
        DEFAULT_PROBE_RATE,
        "--rate",
        "-r",
        envvar="EERO_EXPORTER_PROBE_RATE",
        help="Maximum requests per second",
    ),
    only: str | None = typer.Option(
        None,
        "--only",
        envvar="EERO_EXPORTER_PROBE_ONLY",
        help="Run a single step by label",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        envvar="EERO_EXPORTER_PROBE_DRY_RUN",
        help="List the planned steps and make no request",
    ),
    keep_copy: bool = typer.Option(
        False,
        "--keep-copy",
        envvar="EERO_EXPORTER_PROBE_KEEP_COPY",
        help="Keep the temporary session copy instead of deleting it at exit",
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        "-l",
        envvar="EERO_EXPORTER_PROBE_LOG_LEVEL",
        help="Logging level",
    ),
) -> None:
    """Run the strictly read-only live API probe and write a redacted report.

    The probe issues GET requests only: every non-GET path in the SDK is
    patched to raise before a request is built. It works on a 0600 copy of the
    session file, caps and paces its requests, and writes a key tree with
    lengths instead of values, so no secret or identifier reaches the report.
    """
    setup_logging(log_level)
    exit_code = run_probe_cli(
        ProbeOptions(
            session_file=session_file,
            out_dir=out,
            budget=budget,
            rate=rate,
            only=only,
            dry_run=dry_run,
            keep_copy=keep_copy,
        )
    )
    raise typer.Exit(exit_code)


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"eero-prometheus-exporter [bold blue]v{__version__}[/bold blue]")


class OptionDescription(NamedTuple):
    """One row of the CLI option -> env var -> YAML key catalogue (§4.3.9)."""

    command: str
    flag: str
    env_var: str
    yaml_key: str | None
    default: Any
    help: str | None


def describe_options() -> Iterator[OptionDescription]:
    """Yield every CLI option of every command, for docs generation.

    Walks the real Typer command tree (the same one Click executes), so
    this can never drift from what ``--help`` actually shows. A docs agent
    can use this to regenerate ``wiki/Configuration.md``.

    Yields:
        One :class:`OptionDescription` per ``click.Option`` (arguments, and
        the bare ``--help`` flag, are skipped).
    """
    yaml_keys = {f.name for f in fields(ExporterConfig)}
    click_app = typer.main.get_command(app)
    assert isinstance(click_app, click.Group)

    for command_name, command in sorted(click_app.commands.items()):
        for param in command.params:
            if not isinstance(param, typer.core.TyperOption):
                continue
            if param.name == "help":
                continue

            long_opt = _primary_long_opt(param)
            env_var = param.envvar if isinstance(param.envvar, str) else envvar_name(long_opt)
            yaml_key = param.name if param.name in yaml_keys else None

            yield OptionDescription(
                command=command_name,
                flag=long_opt,
                env_var=env_var,
                yaml_key=yaml_key,
                default=param.default,
                help=param.help,
            )


def _primary_long_opt(param: Any) -> str:
    """Return a click parameter's primary long-form flag (e.g. ``"--host"``).

    For boolean ``--flag/--no-flag`` pairs, this is the affirmative side
    (``param.opts``), never the negative (``param.secondary_opts``).

    Args:
        param: A ``click.Option``.

    Returns:
        The first long-form (``--``-prefixed) flag string declared on the
        option.
    """
    for opt in param.opts:
        if opt.startswith("--"):
            return str(opt)
    # Options declared with only a short form (shouldn't happen here, but
    # fall back rather than raise).
    return str(param.opts[0])


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
