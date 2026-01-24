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

ETHERNET_PORT_INFO = Info(
    f"{PREFIX}_ethernet_port",
    "Information about an Ethernet port",
    labelnames=["network_id", "eero_id", "port_number"],
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
# EERO HARDWARE METRICS
# =============================================================================

EERO_MEMORY_USAGE = Gauge(
    f"{PREFIX}_eero_memory_usage_percent",
    "Eero memory usage percentage",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_TEMPERATURE = Gauge(
    f"{PREFIX}_eero_temperature_celsius",
    "Eero temperature in Celsius",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_LED_BRIGHTNESS = Gauge(
    f"{PREFIX}_eero_led_brightness",
    "Eero LED brightness level (0-100)",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_LAST_REBOOT = Gauge(
    f"{PREFIX}_eero_last_reboot_timestamp_seconds",
    "Timestamp of last eero reboot (Unix epoch)",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_PROVIDES_WIFI = Gauge(
    f"{PREFIX}_eero_provides_wifi",
    "Whether the eero provides WiFi (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_BACKUP_CONNECTION = Gauge(
    f"{PREFIX}_eero_backup_connection",
    "Whether the eero is using backup connection (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location"],
)

# =============================================================================
# EERO ETHERNET PORT METRICS
# =============================================================================

ETHERNET_PORT_CARRIER = Gauge(
    f"{PREFIX}_ethernet_port_carrier",
    "Whether the Ethernet port has link (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location", "port_number", "port_name"],
)

ETHERNET_PORT_SPEED = Gauge(
    f"{PREFIX}_ethernet_port_speed_mbps",
    "Ethernet port negotiated speed in Mbps",
    labelnames=["network_id", "eero_id", "location", "port_number", "port_name"],
)

ETHERNET_PORT_IS_WAN = Gauge(
    f"{PREFIX}_ethernet_port_is_wan",
    "Whether the Ethernet port is used for WAN (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location", "port_number", "port_name"],
)

ETHERNET_PORT_POWER_SAVING = Gauge(
    f"{PREFIX}_ethernet_port_power_saving",
    "Whether power saving is enabled on the port (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location", "port_number", "port_name"],
)

EERO_WIRED_INTERNET = Gauge(
    f"{PREFIX}_eero_wired_internet",
    "Whether the eero has wired internet connection (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location"],
)

# =============================================================================
# EERO NIGHTLIGHT METRICS (Eero Beacon)
# =============================================================================

EERO_NIGHTLIGHT_ENABLED = Gauge(
    f"{PREFIX}_eero_nightlight_enabled",
    "Whether nightlight is enabled (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_NIGHTLIGHT_BRIGHTNESS = Gauge(
    f"{PREFIX}_eero_nightlight_brightness",
    "Nightlight brightness level (0-100)",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_NIGHTLIGHT_AMBIENT_ENABLED = Gauge(
    f"{PREFIX}_eero_nightlight_ambient_enabled",
    "Whether ambient light sensing is enabled (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_NIGHTLIGHT_SCHEDULE_ENABLED = Gauge(
    f"{PREFIX}_eero_nightlight_schedule_enabled",
    "Whether nightlight schedule is enabled (1=yes, 0=no)",
    labelnames=["network_id", "eero_id", "location"],
)

# =============================================================================
# CLIENT DEVICE METRICS
# =============================================================================

# Common device labels for consistency:
# - network_id: network identifier
# - device_id: unique device identifier
# - name: display name of device
# - mac: MAC address
# - manufacturer: device manufacturer (e.g., "Apple", "Samsung")
# - device_type: device category (e.g., "computer", "phone", "tv")
# - connection_type: "wired" or "wireless"
# - source_eero: location of the eero the device is connected to

DEVICE_CONNECTED = Gauge(
    f"{PREFIX}_device_connected",
    "Whether the device is connected (1=yes, 0=no)",
    labelnames=[
        "network_id",
        "device_id",
        "name",
        "mac",
        "manufacturer",
        "device_type",
        "connection_type",
        "source_eero",
    ],
)

DEVICE_WIRELESS = Gauge(
    f"{PREFIX}_device_wireless",
    "Whether the device is wireless (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name", "manufacturer", "device_type"],
)

DEVICE_BLOCKED = Gauge(
    f"{PREFIX}_device_blocked",
    "Whether the device is blocked (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name", "mac", "manufacturer"],
)

DEVICE_PAUSED = Gauge(
    f"{PREFIX}_device_paused",
    "Whether the device is paused (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name", "manufacturer", "device_type"],
)

DEVICE_IS_GUEST = Gauge(
    f"{PREFIX}_device_is_guest",
    "Whether the device is on guest network (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name", "manufacturer"],
)

DEVICE_SIGNAL_STRENGTH = Gauge(
    f"{PREFIX}_device_signal_strength_dbm",
    "Device signal strength in dBm",
    labelnames=[
        "network_id",
        "device_id",
        "name",
        "manufacturer",
        "band",
        "source_eero",
    ],
)

DEVICE_CONNECTION_SCORE = Gauge(
    f"{PREFIX}_device_connection_score",
    "Device connection quality score",
    labelnames=[
        "network_id",
        "device_id",
        "name",
        "manufacturer",
        "connection_type",
        "source_eero",
    ],
)

DEVICE_CONNECTION_SCORE_BARS = Gauge(
    f"{PREFIX}_device_connection_score_bars",
    "Device connection quality score in bars (0-5)",
    labelnames=[
        "network_id",
        "device_id",
        "name",
        "manufacturer",
        "connection_type",
        "source_eero",
    ],
)

# =============================================================================
# DEVICE WIRELESS METRICS
# =============================================================================

# Wireless metrics include band label ("2.4GHz", "5GHz", "6GHz") for filtering

DEVICE_FREQUENCY = Gauge(
    f"{PREFIX}_device_frequency_mhz",
    "Device WiFi frequency in MHz",
    labelnames=["network_id", "device_id", "name", "manufacturer", "band", "source_eero"],
)

DEVICE_CHANNEL = Gauge(
    f"{PREFIX}_device_channel",
    "Device WiFi channel number",
    labelnames=["network_id", "device_id", "name", "band", "source_eero"],
)

DEVICE_RX_BITRATE = Gauge(
    f"{PREFIX}_device_rx_bitrate_mbps",
    "Device receive bitrate in Mbps",
    labelnames=["network_id", "device_id", "name", "manufacturer", "band", "source_eero"],
)

DEVICE_SIGNAL_AVG = Gauge(
    f"{PREFIX}_device_signal_strength_avg_dbm",
    "Device average signal strength in dBm",
    labelnames=["network_id", "device_id", "name", "manufacturer", "band", "source_eero"],
)

DEVICE_RX_MCS = Gauge(
    f"{PREFIX}_device_rx_mcs",
    "Device receive MCS index",
    labelnames=["network_id", "device_id", "name", "band"],
)

DEVICE_RX_NSS = Gauge(
    f"{PREFIX}_device_rx_nss",
    "Device receive number of spatial streams",
    labelnames=["network_id", "device_id", "name", "band"],
)

DEVICE_RX_BANDWIDTH = Gauge(
    f"{PREFIX}_device_rx_bandwidth_mhz",
    "Device receive bandwidth in MHz",
    labelnames=["network_id", "device_id", "name", "band"],
)

DEVICE_TX_BITRATE = Gauge(
    f"{PREFIX}_device_tx_bitrate_mbps",
    "Device transmit bitrate in Mbps",
    labelnames=["network_id", "device_id", "name", "manufacturer", "band", "source_eero"],
)

DEVICE_TX_MCS = Gauge(
    f"{PREFIX}_device_tx_mcs",
    "Device transmit MCS index",
    labelnames=["network_id", "device_id", "name", "band"],
)

DEVICE_TX_NSS = Gauge(
    f"{PREFIX}_device_tx_nss",
    "Device transmit number of spatial streams",
    labelnames=["network_id", "device_id", "name", "band"],
)

DEVICE_TX_BANDWIDTH = Gauge(
    f"{PREFIX}_device_tx_bandwidth_mhz",
    "Device transmit bandwidth in MHz",
    labelnames=["network_id", "device_id", "name", "band"],
)

# =============================================================================
# DEVICE ADDITIONAL METRICS
# =============================================================================

DEVICE_PRIORITIZED = Gauge(
    f"{PREFIX}_device_prioritized",
    "Whether the device is prioritized for bandwidth (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name", "manufacturer", "device_type"],
)

DEVICE_PRIVATE = Gauge(
    f"{PREFIX}_device_private",
    "Whether the device is marked as private (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name", "manufacturer"],
)

DEVICE_CONNECTED_TO_GATEWAY = Gauge(
    f"{PREFIX}_device_connected_to_gateway",
    "Whether the device is connected directly to gateway (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name", "connection_type"],
)

DEVICE_DOWNLOAD_BYTES = Counter(
    f"{PREFIX}_device_download_bytes_total",
    "Total bytes downloaded by device",
    labelnames=["network_id", "device_id", "name", "manufacturer", "device_type"],
)

DEVICE_UPLOAD_BYTES = Counter(
    f"{PREFIX}_device_upload_bytes_total",
    "Total bytes uploaded by device",
    labelnames=["network_id", "device_id", "name", "manufacturer", "device_type"],
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
# NETWORK FEATURE FLAGS
# =============================================================================

NETWORK_WPA3_ENABLED = Gauge(
    f"{PREFIX}_network_wpa3_enabled",
    "Whether WPA3 is enabled (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

NETWORK_BAND_STEERING_ENABLED = Gauge(
    f"{PREFIX}_network_band_steering_enabled",
    "Whether band steering is enabled (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

NETWORK_SQM_ENABLED = Gauge(
    f"{PREFIX}_network_sqm_enabled",
    "Whether Smart Queue Management is enabled (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

NETWORK_UPNP_ENABLED = Gauge(
    f"{PREFIX}_network_upnp_enabled",
    "Whether UPnP is enabled (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

NETWORK_THREAD_ENABLED = Gauge(
    f"{PREFIX}_network_thread_enabled",
    "Whether Thread is enabled (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

NETWORK_IPV6_ENABLED = Gauge(
    f"{PREFIX}_network_ipv6_enabled",
    "Whether IPv6 is enabled (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

NETWORK_DNS_CACHING_ENABLED = Gauge(
    f"{PREFIX}_network_dns_caching_enabled",
    "Whether DNS caching is enabled (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

NETWORK_POWER_SAVING_ENABLED = Gauge(
    f"{PREFIX}_network_power_saving_enabled",
    "Whether power saving is enabled (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

NETWORK_GUEST_ENABLED = Gauge(
    f"{PREFIX}_network_guest_enabled",
    "Whether guest network is enabled (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

NETWORK_PREMIUM_ENABLED = Gauge(
    f"{PREFIX}_network_premium_enabled",
    "Whether Eero Plus/Secure subscription is active (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

NETWORK_BACKUP_INTERNET_ENABLED = Gauge(
    f"{PREFIX}_network_backup_internet_enabled",
    "Whether backup internet is enabled (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

# =============================================================================
# NETWORK TRANSFER METRICS
# =============================================================================

NETWORK_DOWNLOAD_BYTES = Counter(
    f"{PREFIX}_network_download_bytes_total",
    "Total bytes downloaded on the network",
    labelnames=["network_id"],
)

NETWORK_UPLOAD_BYTES = Counter(
    f"{PREFIX}_network_upload_bytes_total",
    "Total bytes uploaded on the network",
    labelnames=["network_id"],
)

# =============================================================================
# SQM (SMART QUEUE MANAGEMENT) METRICS
# =============================================================================

SQM_UPLOAD_BANDWIDTH = Gauge(
    f"{PREFIX}_sqm_upload_bandwidth_mbps",
    "SQM upload bandwidth limit in Mbps",
    labelnames=["network_id"],
)

SQM_DOWNLOAD_BANDWIDTH = Gauge(
    f"{PREFIX}_sqm_download_bandwidth_mbps",
    "SQM download bandwidth limit in Mbps",
    labelnames=["network_id"],
)

# =============================================================================
# BACKUP NETWORK METRICS (Eero Plus)
# =============================================================================

BACKUP_ENABLED = Gauge(
    f"{PREFIX}_backup_enabled",
    "Whether backup network is enabled (1=yes, 0=no)",
    labelnames=["network_id"],
)

BACKUP_ACTIVE = Gauge(
    f"{PREFIX}_backup_active",
    "Whether backup network is currently active (1=yes, 0=no)",
    labelnames=["network_id"],
)

BACKUP_CONNECTED = Gauge(
    f"{PREFIX}_backup_connected",
    "Whether backup connection is established (1=yes, 0=no)",
    labelnames=["network_id"],
)

BACKUP_DATA_USED = Counter(
    f"{PREFIX}_backup_data_used_bytes_total",
    "Total bytes used on backup connection",
    labelnames=["network_id"],
)

BACKUP_SIGNAL_STRENGTH = Gauge(
    f"{PREFIX}_backup_signal_strength",
    "Backup connection signal strength",
    labelnames=["network_id"],
)

# =============================================================================
# ACTIVITY METRICS (Eero Plus)
# =============================================================================

ACTIVITY_DOWNLOAD_BYTES = Gauge(
    f"{PREFIX}_activity_download_bytes",
    "Network activity download bytes (current period)",
    labelnames=["network_id"],
)

ACTIVITY_UPLOAD_BYTES = Gauge(
    f"{PREFIX}_activity_upload_bytes",
    "Network activity upload bytes (current period)",
    labelnames=["network_id"],
)

ACTIVITY_ACTIVE_CLIENTS = Gauge(
    f"{PREFIX}_activity_active_clients",
    "Number of active clients (Eero Plus)",
    labelnames=["network_id"],
)

ACTIVITY_CATEGORY_BYTES = Gauge(
    f"{PREFIX}_activity_category_bytes",
    "Activity bytes by category",
    labelnames=["network_id", "category"],
)

DEVICE_ACTIVITY_DOWNLOAD_BYTES = Gauge(
    f"{PREFIX}_device_activity_download_bytes",
    "Device activity download bytes (current period)",
    labelnames=["network_id", "device_id", "name", "manufacturer", "device_type"],
)

DEVICE_ACTIVITY_UPLOAD_BYTES = Gauge(
    f"{PREFIX}_device_activity_upload_bytes",
    "Device activity upload bytes (current period)",
    labelnames=["network_id", "device_id", "name", "manufacturer", "device_type"],
)

# =============================================================================
# THREAD METRICS
# =============================================================================

THREAD_DEVICE_COUNT = Gauge(
    f"{PREFIX}_thread_device_count",
    "Number of Thread devices on the network",
    labelnames=["network_id"],
)

THREAD_BORDER_ROUTER = Gauge(
    f"{PREFIX}_thread_border_router",
    "Number of Thread border routers",
    labelnames=["network_id"],
)

# =============================================================================
# GUEST NETWORK METRICS
# =============================================================================

GUEST_NETWORK_CONNECTED_CLIENTS = Gauge(
    f"{PREFIX}_guest_network_connected_clients",
    "Number of clients connected to guest network",
    labelnames=["network_id", "name"],
)

GUEST_NETWORK_INFO = Info(
    f"{PREFIX}_guest_network",
    "Guest network information",
    labelnames=["network_id"],
)

GUEST_NETWORK_ACCESS_DURATION_ENABLED = Gauge(
    f"{PREFIX}_guest_network_access_duration_enabled",
    "Whether time-limited guest access is enabled (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

# =============================================================================
# FIRMWARE/UPDATES METRICS
# =============================================================================

NETWORK_UPDATES_AVAILABLE = Gauge(
    f"{PREFIX}_network_updates_available",
    "Number of eeros with firmware updates available",
    labelnames=["network_id", "name"],
)

NETWORK_AUTO_UPDATE_ENABLED = Gauge(
    f"{PREFIX}_network_auto_update_enabled",
    "Whether auto-update is enabled (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

EERO_OS_VERSION_INFO = Info(
    f"{PREFIX}_eero_os_version",
    "Eero firmware version information",
    labelnames=["network_id", "eero_id", "location"],
)

# =============================================================================
# PORT FORWARDING METRICS
# =============================================================================

NETWORK_PORT_FORWARDS_COUNT = Gauge(
    f"{PREFIX}_network_port_forwards_count",
    "Total number of port forwarding rules",
    labelnames=["network_id", "name"],
)

PORT_FORWARD_INFO = Info(
    f"{PREFIX}_port_forward",
    "Port forward rule information",
    labelnames=["network_id", "forward_id"],
)

PORT_FORWARD_ENABLED = Gauge(
    f"{PREFIX}_port_forward_enabled",
    "Whether the port forward is enabled (1=yes, 0=no)",
    labelnames=["network_id", "forward_id", "port", "protocol"],
)

# =============================================================================
# BLACKLIST METRICS
# =============================================================================

NETWORK_BLACKLISTED_DEVICES_COUNT = Gauge(
    f"{PREFIX}_network_blacklisted_devices_count",
    "Number of blacklisted/blocked devices",
    labelnames=["network_id", "name"],
)

# =============================================================================
# DNS CONFIGURATION METRICS
# =============================================================================

NETWORK_CUSTOM_DNS_ENABLED = Gauge(
    f"{PREFIX}_network_custom_dns_enabled",
    "Whether custom DNS is configured (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

NETWORK_DNS_SERVER_COUNT = Gauge(
    f"{PREFIX}_network_dns_server_count",
    "Number of DNS servers configured",
    labelnames=["network_id", "name"],
)

DNS_CONFIG_INFO = Info(
    f"{PREFIX}_dns_config",
    "DNS configuration information",
    labelnames=["network_id"],
)

# =============================================================================
# DIAGNOSTICS METRICS
# =============================================================================

DIAGNOSTICS_INTERNET_LATENCY = Gauge(
    f"{PREFIX}_diagnostics_internet_latency_ms",
    "Internet latency in milliseconds",
    labelnames=["network_id"],
)

DIAGNOSTICS_DNS_LATENCY = Gauge(
    f"{PREFIX}_diagnostics_dns_latency_ms",
    "DNS resolution latency in milliseconds",
    labelnames=["network_id"],
)

DIAGNOSTICS_GATEWAY_LATENCY = Gauge(
    f"{PREFIX}_diagnostics_gateway_latency_ms",
    "Gateway response latency in milliseconds",
    labelnames=["network_id"],
)

DIAGNOSTICS_LAST_RUN_TIMESTAMP = Gauge(
    f"{PREFIX}_diagnostics_last_run_timestamp_seconds",
    "Timestamp of last diagnostic run (Unix epoch)",
    labelnames=["network_id"],
)

# =============================================================================
# ACCOUNT METRICS
# =============================================================================

ACCOUNT_NETWORKS_COUNT = Gauge(
    f"{PREFIX}_account_networks_count",
    "Total number of networks in account",
)

ACCOUNT_PREMIUM_EXPIRATION = Gauge(
    f"{PREFIX}_account_premium_expiration_timestamp_seconds",
    "Premium subscription expiration date (Unix epoch)",
    labelnames=["network_id"],
)

# =============================================================================
# DEVICE CONNECTION DETAILS METRICS
# =============================================================================

DEVICE_LAST_ACTIVE_TIMESTAMP = Gauge(
    f"{PREFIX}_device_last_active_timestamp_seconds",
    "Last time device was active (Unix epoch)",
    labelnames=["network_id", "device_id", "name", "manufacturer"],
)

DEVICE_FIRST_SEEN_TIMESTAMP = Gauge(
    f"{PREFIX}_device_first_seen_timestamp_seconds",
    "When device was first seen on network (Unix epoch)",
    labelnames=["network_id", "device_id", "name", "manufacturer"],
)

DEVICE_WIFI_GENERATION = Gauge(
    f"{PREFIX}_device_wifi_generation",
    "WiFi standard (4=WiFi 4, 5=WiFi 5, 6=WiFi 6, 7=WiFi 7)",
    labelnames=["network_id", "device_id", "name", "manufacturer"],
)

DEVICE_ADBLOCK_ENABLED = Gauge(
    f"{PREFIX}_device_adblock_enabled",
    "Whether ad blocking is enabled for device (1=yes, 0=no)",
    labelnames=["network_id", "device_id", "name", "manufacturer"],
)

# =============================================================================
# EERO SECURITY METRICS (Eero Plus)
# =============================================================================

SECURITY_THREATS_BLOCKED = Counter(
    f"{PREFIX}_security_threats_blocked_total",
    "Total threats blocked by Eero Secure",
    labelnames=["network_id"],
)

SECURITY_SCANS_BLOCKED = Counter(
    f"{PREFIX}_security_scans_blocked_total",
    "Network scans blocked",
    labelnames=["network_id"],
)

NETWORK_AD_BLOCK_ENABLED = Gauge(
    f"{PREFIX}_network_ad_block_enabled",
    "Whether ad blocking is enabled network-wide (1=yes, 0=no)",
    labelnames=["network_id", "name"],
)

# =============================================================================
# INSIGHTS METRICS
# =============================================================================

INSIGHTS_RECOMMENDATIONS_COUNT = Gauge(
    f"{PREFIX}_insights_recommendations_count",
    "Number of pending network recommendations",
    labelnames=["network_id"],
)

INSIGHTS_ISSUES_COUNT = Gauge(
    f"{PREFIX}_insights_issues_count",
    "Number of detected network issues",
    labelnames=["network_id"],
)

# =============================================================================
# DHCP RESERVATIONS METRICS
# =============================================================================

NETWORK_DHCP_RESERVATIONS_COUNT = Gauge(
    f"{PREFIX}_network_dhcp_reservations_count",
    "Number of DHCP reservations configured",
    labelnames=["network_id", "name"],
)

# =============================================================================
# EERO TRANSFER METRICS
# =============================================================================

EERO_RX_BYTES = Counter(
    f"{PREFIX}_eero_rx_bytes_total",
    "Total bytes received by eero device",
    labelnames=["network_id", "eero_id", "location"],
)

EERO_TX_BYTES = Counter(
    f"{PREFIX}_eero_tx_bytes_total",
    "Total bytes transmitted by eero device",
    labelnames=["network_id", "eero_id", "location"],
)

# =============================================================================
# EXPORTER METRICS
# =============================================================================

# Standard "up" metric following Prometheus exporter conventions
# See: https://prometheus.io/docs/instrumenting/writing_exporters/#failed-scrapes
EERO_UP = Gauge(
    f"{PREFIX}_up",
    "Whether the eero API is reachable and the last scrape was successful (1=up, 0=down)",
)

EXPORTER_SCRAPE_DURATION = Gauge(
    f"{PREFIX}_exporter_scrape_duration_seconds",
    "Time taken to collect metrics from eero API",
)

EXPORTER_SCRAPE_SUCCESS = Gauge(
    f"{PREFIX}_exporter_scrape_success",
    "Whether the last scrape was successful (1=yes, 0=no). Deprecated: use eero_up instead.",
)

EXPORTER_LAST_COLLECTION_TIMESTAMP = Gauge(
    f"{PREFIX}_exporter_last_collection_timestamp_seconds",
    "Unix timestamp of the last successful metrics collection. "
    "Metrics are cached between collections per Prometheus guidelines for expensive APIs.",
)

EXPORTER_COLLECTION_INTERVAL = Gauge(
    f"{PREFIX}_exporter_collection_interval_seconds",
    "Configured collection interval in seconds. Prometheus scrapes may receive cached data.",
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
