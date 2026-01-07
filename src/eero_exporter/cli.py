"""CLI for Eero Prometheus Exporter."""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from . import __version__
from .api import EeroAPIError, EeroAuthError, EeroClient
from .collector import EeroCollector
from .config import DEFAULT_CONFIG_FILE, DEFAULT_SESSION_FILE, ExporterConfig, SessionData
from .server import run_server

app = typer.Typer(
    name="eero-exporter",
    help="Modern Prometheus exporter for eero mesh WiFi networks",
    add_completion=False,
)

console = Console()


def setup_logging(level: str = "INFO") -> None:
    """Setup logging with rich handler."""
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@app.command()
def login(
    identifier: str = typer.Argument(
        ...,
        help="Email address or phone number for your eero account",
    ),
    session_file: Optional[Path] = typer.Option(
        None,
        "--session-file",
        "-s",
        help="Path to session file",
    ),
) -> None:
    """Login to your eero account and save the session.
    
    This will send a verification code to your email or phone.
    """
    setup_logging()
    session_path = session_file or DEFAULT_SESSION_FILE

    async def _login() -> None:
        console.print(f"\n[bold blue]Eero Prometheus Exporter v{__version__}[/bold blue]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Sending verification code...", total=None)

            async with EeroClient() as client:
                try:
                    user_token = await client.login(identifier)
                    progress.remove_task(task)
                except EeroAuthError as e:
                    progress.remove_task(task)
                    console.print(f"[bold red]Login failed:[/bold red] {e}")
                    raise typer.Exit(1)

        console.print("[green]✓[/green] Verification code sent!")
        console.print(f"\nCheck your {'email' if '@' in identifier else 'phone'} for the code.\n")

        # Get verification code
        code = typer.prompt("Enter verification code")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Verifying code...", total=None)

            async with EeroClient(user_token=user_token) as client:
                client._user_token = user_token
                try:
                    session_data = await client.verify(code)
                    progress.remove_task(task)
                except EeroAuthError as e:
                    progress.remove_task(task)
                    console.print(f"[bold red]Verification failed:[/bold red] {e}")
                    raise typer.Exit(1)

        # Save session
        session = SessionData(
            user_token=session_data.get("user_token"),
            session_id=session_data.get("session_id"),
            preferred_network_id=session_data.get("preferred_network_id"),
            session_expiry=session_data.get("session_expiry"),
        )
        session.save(session_path)

        console.print("\n[green]✓[/green] Login successful!")
        console.print(f"[dim]Session saved to: {session_path}[/dim]\n")

    asyncio.run(_login())


@app.command()
def logout(
    session_file: Optional[Path] = typer.Option(
        None,
        "--session-file",
        "-s",
        help="Path to session file",
    ),
) -> None:
    """Clear the saved session."""
    setup_logging()
    session_path = session_file or DEFAULT_SESSION_FILE

    session = SessionData.from_file(session_path)
    session.clear(session_path)

    console.print("[green]✓[/green] Session cleared.")


@app.command()
def validate(
    session_file: Optional[Path] = typer.Option(
        None,
        "--session-file",
        "-s",
        help="Path to session file",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
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
                console.print(f"\nRun: [bold]eero-exporter login <email-or-phone>[/bold]")
            raise typer.Exit(2)

        session = SessionData.from_file(session_path)

        # Check if session has required fields
        if not session.is_valid:
            if not quiet:
                console.print("[bold red]✗[/bold red] Session file is empty or invalid")
                console.print(f"\nRun: [bold]eero-exporter login <email-or-phone>[/bold]")
            raise typer.Exit(1)

        if not quiet:
            console.print("[dim]Session file loaded, testing API...[/dim]")

        # Test API connectivity
        async with EeroClient(session_id=session.session_id) as client:
            try:
                networks = await client.get_networks()
                
                if not quiet:
                    console.print("[green]✓[/green] Session is valid!")
                    console.print(f"[green]✓[/green] Found {len(networks)} network(s)")
                    for net in networks:
                        name = net.get("name", "Unknown")
                        status = net.get("status", "unknown")
                        console.print(f"    • {name}: {status}")
                    console.print()
                
                # Success
                raise typer.Exit(0)
                
            except EeroAuthError as e:
                if not quiet:
                    console.print(f"[bold red]✗[/bold red] Session expired or invalid")
                    console.print(f"[dim]Error: {e}[/dim]")
                    console.print(f"\nRun: [bold]eero-exporter login <email-or-phone>[/bold]")
                raise typer.Exit(1)
            except EeroAPIError as e:
                if not quiet:
                    console.print(f"[bold red]✗[/bold red] API error: {e}")
                raise typer.Exit(1)

    asyncio.run(_validate())


@app.command()
def status(
    session_file: Optional[Path] = typer.Option(
        None,
        "--session-file",
        "-s",
        help="Path to session file",
    ),
) -> None:
    """Check authentication status and show network info."""
    setup_logging()
    session_path = session_file or DEFAULT_SESSION_FILE

    async def _status() -> None:
        console.print(f"\n[bold blue]Eero Prometheus Exporter v{__version__}[/bold blue]\n")

        session = SessionData.from_file(session_path)

        if not session.is_valid:
            console.print("[yellow]Not authenticated.[/yellow]")
            console.print(f"\nRun: [bold]eero-exporter login <email-or-phone>[/bold]")
            raise typer.Exit(1)

        console.print("[green]✓[/green] Authenticated\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Fetching network info...", total=None)

            async with EeroClient(session_id=session.session_id) as client:
                try:
                    networks = await client.get_networks()
                    progress.remove_task(task)
                except EeroAuthError:
                    progress.remove_task(task)
                    console.print("[bold red]Session expired. Please login again.[/bold red]")
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
            status = network.get("status", "unknown")
            url = network.get("url", "")
            network_id = url.rstrip("/").split("/")[-1] if url else "unknown"

            status_color = "green" if status in ("connected", "online") else "red"
            table.add_row(name, f"[{status_color}]{status}[/{status_color}]", network_id)

        console.print(table)
        console.print()

    asyncio.run(_status())


@app.command()
def test(
    session_file: Optional[Path] = typer.Option(
        None,
        "--session-file",
        "-s",
        help="Path to session file",
    ),
) -> None:
    """Test metrics collection without starting the server."""
    setup_logging("DEBUG")
    session_path = session_file or DEFAULT_SESSION_FILE

    async def _test() -> None:
        console.print(f"\n[bold blue]Eero Prometheus Exporter v{__version__}[/bold blue]\n")

        session = SessionData.from_file(session_path)

        if not session.is_valid:
            console.print("[yellow]Not authenticated.[/yellow]")
            console.print(f"\nRun: [bold]eero-exporter login <email-or-phone>[/bold]")
            raise typer.Exit(1)

        collector = EeroCollector(
            session=session,
            include_devices=True,
            include_profiles=True,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Collecting metrics...", total=None)
            success = await collector.collect()
            progress.remove_task(task)

        if success:
            console.print("[green]✓[/green] Metrics collection successful!")
            console.print("\n[dim]Run with --log-level DEBUG to see collected metrics.[/dim]")
        else:
            console.print("[bold red]✗[/bold red] Metrics collection failed.")
            raise typer.Exit(1)

    asyncio.run(_test())


@app.command()
def serve(
    port: int = typer.Option(
        9118,
        "--port",
        "-p",
        help="Port to listen on",
    ),
    host: str = typer.Option(
        "0.0.0.0",
        "--host",
        "-h",
        help="Host to bind to",
    ),
    interval: int = typer.Option(
        60,
        "--interval",
        "-i",
        help="Collection interval in seconds",
    ),
    session_file: Optional[Path] = typer.Option(
        None,
        "--session-file",
        "-s",
        help="Path to session file",
    ),
    config_file: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config file",
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        "-l",
        help="Log level (DEBUG, INFO, WARNING, ERROR)",
    ),
    include_devices: bool = typer.Option(
        True,
        "--include-devices/--no-devices",
        help="Include device metrics",
    ),
    include_profiles: bool = typer.Option(
        True,
        "--include-profiles/--no-profiles",
        help="Include profile metrics",
    ),
) -> None:
    """Start the Prometheus metrics server."""
    setup_logging(log_level.upper())

    # Load config
    if config_file and config_file.exists():
        config = ExporterConfig.from_file(config_file)
    else:
        config = ExporterConfig()

    # Override config with CLI options
    config.port = port
    config.host = host
    config.collection_interval = interval
    config.log_level = log_level
    config.include_devices = include_devices
    config.include_profiles = include_profiles

    if session_file:
        config.session_file = session_file

    # Load session
    session = SessionData.from_file(config.session_file)

    if not session.is_valid:
        console.print("[bold red]Not authenticated.[/bold red]")
        console.print(f"\nRun: [bold]eero-exporter login <email-or-phone>[/bold]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold blue]Eero Prometheus Exporter v{__version__}[/bold blue]\n\n"
        f"Listening on: [green]http://{host}:{port}/metrics[/green]\n"
        f"Collection interval: [cyan]{interval}s[/cyan]",
        title="Starting Exporter",
    ))

    # Run server
    run_server(config, session)


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"eero-prometheus-exporter [bold blue]v{__version__}[/bold blue]")


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()


