"""Configuration management for Eero Prometheus Exporter."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml  # type: ignore[import-untyped]

_LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "eero-exporter"
DEFAULT_SESSION_FILE = DEFAULT_CONFIG_PATH / "session.json"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_PATH / "config.yml"


# Default port for the exporter
# Port 10052 is registered in the Prometheus default port allocations wiki
# See: https://github.com/prometheus/prometheus/wiki/Default-port-allocations
DEFAULT_PORT = 10052


@dataclass
class ExporterConfig:
    """Configuration for the Eero Prometheus Exporter."""

    # Server settings
    port: int = DEFAULT_PORT
    host: str = "0.0.0.0"  # nosec B104 - intentional for Docker/container deployments
    metrics_path: str = "/metrics"

    # Collection settings
    collection_interval: int = 60  # seconds
    timeout: int = 30  # seconds

    # Session settings
    session_file: Path = field(default_factory=lambda: DEFAULT_SESSION_FILE)

    # Metrics settings
    include_devices: bool = True
    include_profiles: bool = True
    include_data_usage: bool = True
    include_speed_test: bool = False  # Off by default as it generates traffic
    speed_test_interval: int = 3600  # Run speed test every hour if enabled

    # Logging
    log_level: str = "INFO"

    @classmethod
    def from_file(cls, path: Path) -> "ExporterConfig":
        """Load configuration from a YAML file."""
        if not path.exists():
            _LOGGER.info(f"Config file not found at {path}, using defaults")
            return cls()

        try:
            with open(path) as f:
                data = yaml.safe_load(f)

            if data is None:
                return cls()

            # Convert session_file to Path if present
            if "session_file" in data:
                data["session_file"] = Path(data["session_file"])

            return cls(**data)
        except Exception as e:
            _LOGGER.warning(f"Error loading config from {path}: {e}, using defaults")
            return cls()

    def save(self, path: Path | None = None) -> None:
        """Save configuration to a YAML file."""
        save_path = path or DEFAULT_CONFIG_FILE
        save_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "port": self.port,
            "host": self.host,
            "metrics_path": self.metrics_path,
            "collection_interval": self.collection_interval,
            "timeout": self.timeout,
            "session_file": str(self.session_file),
            "include_devices": self.include_devices,
            "include_profiles": self.include_profiles,
            "include_data_usage": self.include_data_usage,
            "include_speed_test": self.include_speed_test,
            "speed_test_interval": self.speed_test_interval,
            "log_level": self.log_level,
        }

        with open(save_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        _LOGGER.info(f"Configuration saved to {save_path}")
