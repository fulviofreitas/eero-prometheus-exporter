"""Configuration management for Eero Prometheus Exporter."""

import json
import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

import yaml  # type: ignore[import-untyped]

_LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "eero-exporter"
DEFAULT_SESSION_FILE = DEFAULT_CONFIG_PATH / "session.json"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_PATH / "config.yml"


@dataclass
class ExporterConfig:
    """Configuration for the Eero Prometheus Exporter."""

    # Server settings
    port: int = 9118
    host: str = "0.0.0.0"
    metrics_path: str = "/metrics"

    # Collection settings
    collection_interval: int = 60  # seconds
    timeout: int = 30  # seconds

    # Session settings
    session_file: Path = field(default_factory=lambda: DEFAULT_SESSION_FILE)

    # Metrics settings
    include_devices: bool = True
    include_profiles: bool = True
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
            "include_speed_test": self.include_speed_test,
            "speed_test_interval": self.speed_test_interval,
            "log_level": self.log_level,
        }

        with open(save_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        _LOGGER.info(f"Configuration saved to {save_path}")


@dataclass
class SessionData:
    """Session data for eero authentication."""

    user_token: str | None = None
    session_id: str | None = None
    refresh_token: str | None = None
    user_id: str | None = None
    preferred_network_id: str | None = None
    session_expiry: str | None = None

    @property
    def is_valid(self) -> bool:
        """Check if the session is valid."""
        return bool(self.user_token and self.session_id)

    @classmethod
    def from_file(cls, path: Path) -> "SessionData":
        """Load session data from a JSON file."""
        if not path.exists():
            _LOGGER.debug(f"Session file not found at {path}")
            return cls()

        try:
            with open(path) as f:
                data = json.load(f)
            return cls(**data)
        except Exception as e:
            _LOGGER.warning(f"Error loading session from {path}: {e}")
            return cls()

    def save(self, path: Path) -> None:
        """Save session data to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "user_token": self.user_token,
            "session_id": self.session_id,
            "refresh_token": self.refresh_token,
            "user_id": self.user_id,
            "preferred_network_id": self.preferred_network_id,
            "session_expiry": self.session_expiry,
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        # Set restrictive permissions (owner read/write only)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        _LOGGER.info(f"Session saved to {path}")

    def clear(self, path: Path) -> None:
        """Clear session data and delete the file."""
        self.user_token = None
        self.session_id = None
        self.refresh_token = None
        self.user_id = None
        self.preferred_network_id = None
        self.session_expiry = None

        if path.exists():
            path.unlink()
            _LOGGER.info(f"Session file deleted: {path}")
