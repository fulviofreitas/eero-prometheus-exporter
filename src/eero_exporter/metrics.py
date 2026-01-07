"""Prometheus metrics definitions for Eero Exporter."""

from prometheus_client import Counter, Gauge, Info

# Metric prefix
PREFIX = "eero"

# =============================================================================
# INFO METRICS - Static information about the eero network
# =============================================================================

NETWORK_INFO = Info(
    f"{PREFIX}_network",
    "Information about the eero network",
    labelnames=["network_id"],
)

EERO_INFO = Info(
    f"{PREFIX}_eero",
    "Information about an eero device",
    labelnames=["network_id", "eero_id", "serial"],
)

DEVICE_INFO = Info(
    f"{PREFIX}_device",
    "Information about a connected device",
    labelnames=["network_id", "device_id", "mac"],
)

# =============================================================================
# NETWORK METRICS
# =============================================================================

NETWORK_STATUS = Gauge(
    f"{PREFIX}_network_status",
    "Network status (1=online, 0=offline)",
    labelnames=["network_id", "name"],
)

NETWORK_CLIENTS_COUNT = Gauge(
    f"{PREFIX}_network_clients_count",
    "Total number of clients on the network",
    labelnames=["network_id", "name"],
)

NETWORK_EEROS_COUNT = Gauge(
    f"{PREFIX}_network_eeros_count",
    "Number of eero devices in the network",
    labelnames=["network_id", "name"],
)

# =============================================================================
# SPEED TEST METRICS
# =============================================================================

SPEED_UPLOAD_MBPS = Gauge(
    f"{PREFIX}_speed_upload_mbps",
    "Latest speed test upload result in Mbps",
    labelnames=["network_id"],
)

SPEED_DOWNLOAD_MBPS = Gauge(
    f"{PREFIX}_speed_download_mbps",
    "Latest speed test download result in Mbps",
    labelnames=["network_id"],
)

SPEED_TEST_TIMESTAMP = Gauge(
    f"{PREFIX}_speed_test_timestamp_seconds",
    "Timestamp of the last speed test (Unix epoch)",
    labelnames=["network_id"],
)

# =============================================================================
# HEALTH METRICS
# =============================================================================

HEALTH_STATUS = Gauge(
    f"{PREFIX}_health_status",
    "Health status of network components (1=healthy, 0=unhealthy)",
    labelnames=["network_id", "source"],
)

# =============================================================================
# EERO DEVICE METRICS
# =============================================================================

EERO_STATUS = Gauge(
    f"{PREFIX}_eero_status",
    "Eero device status (1=online, 0=offline)",
    labelnames=["network_id", "eero_id", "location", "model"],
)

EERO_IS_GATEWAY = Gauge(
    f"{PREFIX}_eero_is_gateway",
    "Whether the eero is the gateway (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_CONNECTED_CLIENTS = Gauge(
    f"{PREFIX}_eero_connected_clients_count",
    "Number of clients connected to this eero",
    labelnames=["network_id", "eero_id", "location", "model"],
)

EERO_CONNECTED_WIRED_CLIENTS = Gauge(
    f"{PREFIX}_eero_connected_wired_clients_count",
    "Number of wired clients connected to this eero",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_CONNECTED_WIRELESS_CLIENTS = Gauge(
    f"{PREFIX}_eero_connected_wireless_clients_count",
    "Number of wireless clients connected to this eero",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_MESH_QUALITY = Gauge(
    f"{PREFIX}_eero_mesh_quality_bars",
    "Mesh quality indicator (0-5 bars)",
    labelnames=["network_id", "eero_id", "location", "model"],
)

EERO_UPTIME_SECONDS = Gauge(
    f"{PREFIX}_eero_uptime_seconds",
    "Eero device uptime in seconds",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_LED_ON = Gauge(
    f"{PREFIX}_eero_led_on",
    "Whether the eero LED is on (1=on, 0=off)",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_UPDATE_AVAILABLE = Gauge(
    f"{PREFIX}_eero_update_available",
    "Whether an update is available (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_HEARTBEAT_OK = Gauge(
    f"{PREFIX}_eero_heartbeat_ok",
    "Whether the eero heartbeat is OK (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_WIRED = Gauge(
    f"{PREFIX}_eero_wired",
    "Whether the eero is wired (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location"],
)

# =============================================================================
# CLIENT DEVICE METRICS
# =============================================================================

DEVICE_CONNECTED = Gauge(
    f"{PREFIX}_device_connected",
    "Whether the device is connected (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name", "mac"],
)

DEVICE_WIRELESS = Gauge(
    f"{PREFIX}_device_wireless",
    "Whether the device is wireless (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name"],
)

DEVICE_BLOCKED = Gauge(
    f"{PREFIX}_device_blocked",
    "Whether the device is blocked (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name", "mac"],
)

DEVICE_PAUSED = Gauge(
    f"{PREFIX}_device_paused",
    "Whether the device is paused (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name"],
)

DEVICE_IS_GUEST = Gauge(
    f"{PREFIX}_device_is_guest",
    "Whether the device is on guest network (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name"],
)

DEVICE_SIGNAL_STRENGTH = Gauge(
    f"{PREFIX}_device_signal_strength_dbm",
    "Device signal strength in dBm",
    labelnames=["network_id", "device_id", "name"],
)

DEVICE_CONNECTION_SCORE = Gauge(
    f"{PREFIX}_device_connection_score",
    "Device connection quality score",
    labelnames=["network_id", "device_id", "name"],
)

DEVICE_CONNECTION_SCORE_BARS = Gauge(
    f"{PREFIX}_device_connection_score_bars",
    "Device connection quality score in bars (0-5)",
    labelnames=["network_id", "device_id", "name"],
)

# =============================================================================
# PROFILE METRICS
# =============================================================================

PROFILE_PAUSED = Gauge(
    f"{PREFIX}_profile_paused",
    "Whether the profile is paused (1=yes, 0=no)",
    labelnames=["network_id", "profile_id", "name"],
)

PROFILE_DEVICES_COUNT = Gauge(
    f"{PREFIX}_profile_devices_count",
    "Number of devices in the profile",
    labelnames=["network_id", "profile_id", "name"],
)

# =============================================================================
# EXPORTER METRICS
# =============================================================================

EXPORTER_SCRAPE_DURATION = Gauge(
    f"{PREFIX}_exporter_scrape_duration_seconds",
    "Time taken to collect metrics from eero API",
)

EXPORTER_SCRAPE_SUCCESS = Gauge(
    f"{PREFIX}_exporter_scrape_success",
    "Whether the last scrape was successful (1=yes, 0=no)",
)

EXPORTER_SCRAPE_ERRORS = Counter(
    f"{PREFIX}_exporter_scrape_errors_total",
    "Total number of scrape errors",
    labelnames=["error_type"],
)

EXPORTER_API_REQUESTS = Counter(
    f"{PREFIX}_exporter_api_requests_total",
    "Total number of API requests made",
    labelnames=["endpoint", "status"],
)


def reset_all_metrics() -> None:
    """Reset all metrics to their default state.
    
    This is useful when re-scraping to avoid stale data.
    """
    # Note: Info metrics cannot be reset, they are idempotent
    # Gauges need to be cleared per label set, which we handle in the collector
    pass


