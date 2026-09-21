"""Configuration management for Eero Prometheus Exporter."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

_LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "eero-exporter"
DEFAULT_SESSION_FILE = DEFAULT_CONFIG_PATH / "session.json"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_PATH / "config.yml"


# Default port for the exporter
# Port 10052 is registered in the Prometheus default port allocations wiki
# See: https://github.com/prometheus/prometheus/wiki/Default-port-allocations
DEFAULT_PORT = 10052

# The eero-api v8 `get_data_usage`/`get_devices_data_usage` family accepts
# exactly these cadence windows for the exporter's use case.
VALID_DATA_USAGE_PERIODS: tuple[str, ...] = ("day", "week", "month")

# Every EERO_EXPORTER_* environment variable shares this prefix (D6/D15).
ENV_PREFIX = "EERO_EXPORTER_"

# Minimum length required for `--auth-ui-token` when `--auth-ui` is enabled.
# Enforced by `cli.serve` at start-up, not here, so a malformed YAML/env
# value still round-trips through `ExporterConfig` for inspection.
AUTH_UI_MIN_TOKEN_LENGTH = 16

# Default TTL (seconds) a pending /auth login->verify flow stays alive
# before being discarded.
DEFAULT_AUTH_UI_PENDING_TTL = 600


def envvar_name(flag: str) -> str:
    """Derive the ``EERO_EXPORTER_*`` environment-variable name for a CLI flag.

    This is the single implementation of the D15 naming rule ("upper snake
    case of the long flag") so option definitions and the tests that verify
    them can never drift apart.

    Args:
        flag: A long-form CLI flag, e.g. ``"--session-file"``.

    Returns:
        The derived environment-variable name, e.g.
        ``"EERO_EXPORTER_SESSION_FILE"``.
    """
    return ENV_PREFIX + flag.lstrip("-").upper().replace("-", "_")


def parse_data_usage_periods(value: str | list[str]) -> list[str]:
    """Parse and validate a data-usage-periods value.

    Accepts either an already-parsed list (as loaded from YAML) or a
    comma-separated string (as passed on the CLI or via the environment
    variable), and validates every entry against :data:`VALID_DATA_USAGE_PERIODS`.

    Args:
        value: A list of periods, or a comma-separated string such as
            ``"day,week,month"``.

    Returns:
        The validated list of periods, order preserved, duplicates kept as
        given.

    Raises:
        ValueError: If the value is empty, or contains an entry outside
            :data:`VALID_DATA_USAGE_PERIODS`.
    """
    periods = value if isinstance(value, list) else [p.strip() for p in value.split(",")]
    periods = [p for p in periods if p]

    if not periods:
        raise ValueError("data_usage_periods must not be empty")

    invalid = sorted({p for p in periods if p not in VALID_DATA_USAGE_PERIODS})
    if invalid:
        raise ValueError(
            f"Invalid data_usage_periods {invalid!r}; must be one of {VALID_DATA_USAGE_PERIODS}"
        )

    return periods


@dataclass
class ExporterConfig:
    """Configuration for the Eero Prometheus Exporter.

    Every field here that is also a CLI option follows the precedence
    CLI > env var > YAML file > this dataclass default (D6/D15). CLI
    options default to ``None`` sentinels so :meth:`merge_overrides` can
    tell "not provided" apart from "explicitly set to the default value".
    """

    # Server settings
    port: int = DEFAULT_PORT
    host: str = "0.0.0.0"  # nosec B104 - intentional for Docker/container deployments
    metrics_path: str = "/metrics"

    # Collection settings
    collection_interval: int = 60  # seconds

    # HTTP-server-only setting. Historically also passed to the collector /
    # SDK client, but v8's `BaseEeroClient` has no such kwarg (timeout is
    # fixed at 30s total / 10s read) -- it never had any effect there. Kept
    # here purely for a future HTTP-server-side use; no longer threaded
    # through to the collector or adapter.
    timeout: int = 30  # seconds

    # Session settings
    session_file: Path = field(default_factory=lambda: DEFAULT_SESSION_FILE)

    # Per-family metrics toggles (core tier, all default on)
    include_devices: bool = True
    include_profiles: bool = True
    include_data_usage: bool = True
    include_premium: bool = True
    include_ethernet: bool = True
    include_thread: bool = True
    include_port_forwards: bool = True
    include_reservations: bool = True
    include_blacklist: bool = True
    include_diagnostics: bool = True
    include_insights: bool = True

    include_speed_test: bool = False  # Off by default as it generates traffic
    speed_test_interval: int = 3600  # Run speed test every hour if enabled

    # Collection tiers (§4.2). The collector wires these in a later commit;
    # they are defined and parsed here so config/CLI/env/YAML round-trip
    # cleanly ahead of that work.
    include_extended: bool = True
    include_rf: bool = True
    include_per_profile: bool = False
    include_per_device: bool = False
    include_per_eero: bool = False
    include_unverified: bool = False

    # eero-api v8 SDK client options (§2, §4.3), passed through the
    # collector to the adapter's `EeroClient` constructor.
    get_retries: int = 1
    send_legacy_cookie: bool = True
    accept_language: str = "en-US"

    # Data-usage / optimisation flags
    data_usage_periods: list[str] = field(default_factory=lambda: list(VALID_DATA_USAGE_PERIODS))
    eeros_from_envelope: bool = False

    # Auth behaviour
    auth_failure_exit: bool = False

    # Opt-in web authentication page (§/auth). `auth_ui_token` is the shared
    # secret required to use the page; it is never echoed by `to_dict()` or
    # logged. See `cli.serve` for the start-up validation (min length) and
    # `server.py` for the route implementation.
    auth_ui: bool = False
    auth_ui_token: str | None = None
    auth_ui_pending_ttl: int = DEFAULT_AUTH_UI_PENDING_TTL

    # Privacy-sensitive opt-in (D13)
    expose_public_ip: bool = False

    # Logging
    log_level: str = "INFO"

    @classmethod
    def from_file(cls, path: Path) -> ExporterConfig:
        """Load configuration from a YAML file.

        Args:
            path: Path to a YAML config file. If it does not exist, the
                defaults are returned.

        Returns:
            The loaded (or default) configuration. Malformed files are
            logged and fall back to the defaults rather than raising.
        """
        if not path.exists():
            _LOGGER.info(f"Config file not found at {path}, using defaults")
            return cls()

        try:
            with open(path) as f:
                data = yaml.safe_load(f)

            if data is None:
                return cls()

            return cls(**_coerce_yaml_fields(data))
        except Exception as e:
            _LOGGER.warning(f"Error loading config from {path}: {e}, using defaults")
            return cls()

    def merge_overrides(self, **overrides: Any) -> ExporterConfig:
        """Return a new config with non-``None`` overrides applied.

        Implements the CLI > env > YAML > default precedence: callers pass
        every CLI/env-resolved value (Typer/Click already resolved env vars
        against ``None`` sentinels), and only the ones that are not
        ``None`` override whatever this config already holds (typically
        loaded from YAML, or the dataclass defaults).

        Args:
            **overrides: Field name -> value. Unknown field names are
                rejected; ``None`` values are treated as "not provided" and
                skipped. ``data_usage_periods`` may be passed as a
                comma-separated string.

        Returns:
            A new :class:`ExporterConfig` with the overrides applied.

        Raises:
            TypeError: If a keyword does not name a real field.
        """
        valid_names = {f.name for f in fields(self)}
        applied: dict[str, Any] = {}

        for key, value in overrides.items():
            if key not in valid_names:
                raise TypeError(f"ExporterConfig has no field {key!r}")
            if value is None:
                continue
            if key == "data_usage_periods":
                value = parse_data_usage_periods(value)
            elif key == "session_file" and not isinstance(value, Path):
                value = Path(value)
            applied[key] = value

        return replace(self, **applied)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this configuration to a plain, YAML-friendly dict.

        Returns:
            A dict with every field, ``Path`` and list values converted to
            YAML-safe types.
        """
        return {
            "port": self.port,
            "host": self.host,
            "metrics_path": self.metrics_path,
            "collection_interval": self.collection_interval,
            "timeout": self.timeout,
            "session_file": str(self.session_file),
            "include_devices": self.include_devices,
            "include_profiles": self.include_profiles,
            "include_data_usage": self.include_data_usage,
            "include_premium": self.include_premium,
            "include_ethernet": self.include_ethernet,
            "include_thread": self.include_thread,
            "include_port_forwards": self.include_port_forwards,
            "include_reservations": self.include_reservations,
            "include_blacklist": self.include_blacklist,
            "include_diagnostics": self.include_diagnostics,
            "include_insights": self.include_insights,
            "include_speed_test": self.include_speed_test,
            "speed_test_interval": self.speed_test_interval,
            "include_extended": self.include_extended,
            "include_rf": self.include_rf,
            "include_per_profile": self.include_per_profile,
            "include_per_device": self.include_per_device,
            "include_per_eero": self.include_per_eero,
            "include_unverified": self.include_unverified,
            "get_retries": self.get_retries,
            "send_legacy_cookie": self.send_legacy_cookie,
            "accept_language": self.accept_language,
            "data_usage_periods": list(self.data_usage_periods),
            "eeros_from_envelope": self.eeros_from_envelope,
            "auth_failure_exit": self.auth_failure_exit,
            "auth_ui": self.auth_ui,
            "auth_ui_token": "***" if self.auth_ui_token else None,
            "auth_ui_pending_ttl": self.auth_ui_pending_ttl,
            "expose_public_ip": self.expose_public_ip,
            "log_level": self.log_level,
        }

    def save(self, path: Path | None = None) -> None:
        """Save configuration to a YAML file.

        Args:
            path: Destination path. Defaults to :data:`DEFAULT_CONFIG_FILE`.
        """
        save_path = path or DEFAULT_CONFIG_FILE
        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False)

        _LOGGER.info(f"Configuration saved to {save_path}")


def _coerce_yaml_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce raw YAML values into the types :class:`ExporterConfig` expects.

    Args:
        data: The raw ``yaml.safe_load`` result.

    Returns:
        A shallow copy of ``data`` with ``session_file`` coerced to
        ``Path`` and ``data_usage_periods`` validated, when present.
    """
    coerced = dict(data)
    if "session_file" in coerced:
        coerced["session_file"] = Path(coerced["session_file"])
    if "data_usage_periods" in coerced:
        coerced["data_usage_periods"] = parse_data_usage_periods(coerced["data_usage_periods"])
    return coerced
