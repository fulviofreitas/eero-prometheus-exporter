# 📊 Eero Prometheus Exporter - Metrics Reference

**[← Back to README](README.md)**

---

The exporter provides **90+ metrics** across 15 categories. Click each section to expand.

## Table of Contents

- [Network Metrics](#-network-metrics)
- [Network Feature Flags](#-network-feature-flags)
- [Speed Test Metrics](#-speed-test-metrics)
- [Health Metrics](#-health-metrics)
- [Eero Device Metrics](#-eero-device-metrics)
- [Eero Hardware Metrics](#️-eero-hardware-metrics)
- [Ethernet Port Metrics](#-ethernet-port-metrics)
- [Nightlight Metrics](#-nightlight-metrics-eero-beacon)
- [Client Device Metrics](#-client-device-metrics)
- [Device Wireless Metrics](#-device-wireless-metrics)
- [Profile Metrics](#-profile-metrics)
- [SQM Metrics](#️-sqm-smart-queue-management-metrics)
- [Thread Metrics](#-thread-metrics-iot)
- [Eero Plus Metrics](#-eero-plus-metrics)
- [Exporter Metrics](#-exporter-metrics)

---

## 🌐 Network Metrics

| Metric                       | Type  | Description                          |
| ---------------------------- | ----- | ------------------------------------ |
| `eero_network_info`          | Info  | Network metadata (ISP, WAN type, IP) |
| `eero_network_status`        | Gauge | Network status (1=online, 0=offline) |
| `eero_network_clients_count` | Gauge | Total connected clients              |
| `eero_network_eeros_count`   | Gauge | Number of eero devices in mesh       |

---

## 🚦 Network Feature Flags

| Metric                                | Type  | Description                         |
| ------------------------------------- | ----- | ----------------------------------- |
| `eero_network_wpa3_enabled`           | Gauge | WPA3 enabled (1=yes, 0=no)          |
| `eero_network_band_steering_enabled`  | Gauge | Band steering enabled               |
| `eero_network_sqm_enabled`            | Gauge | Smart Queue Management enabled      |
| `eero_network_upnp_enabled`           | Gauge | UPnP enabled                        |
| `eero_network_thread_enabled`         | Gauge | Thread (IoT) enabled                |
| `eero_network_ipv6_enabled`           | Gauge | IPv6 enabled                        |
| `eero_network_dns_caching_enabled`    | Gauge | DNS caching enabled                 |
| `eero_network_power_saving_enabled`   | Gauge | Power saving mode enabled           |
| `eero_network_guest_enabled`          | Gauge | Guest network enabled               |
| `eero_network_premium_enabled`        | Gauge | Eero Plus/Secure active             |
| `eero_network_backup_internet_enabled`| Gauge | Backup internet enabled             |

---

## ⚡ Speed Test Metrics

| Metric                              | Type  | Description               |
| ----------------------------------- | ----- | ------------------------- |
| `eero_speed_upload_mbps`            | Gauge | Upload speed in Mbps      |
| `eero_speed_download_mbps`          | Gauge | Download speed in Mbps    |
| `eero_speed_test_timestamp_seconds` | Gauge | Last speed test timestamp |

---

## 💚 Health Metrics

| Metric               | Type  | Description                               |
| -------------------- | ----- | ----------------------------------------- |
| `eero_health_status` | Gauge | Health by source (internet, eero_network) |

---

## 📶 Eero Device Metrics

| Metric                                       | Type  | Description                            |
| -------------------------------------------- | ----- | -------------------------------------- |
| `eero_eero_info`                             | Info  | Device metadata (model, OS, MAC, IP)   |
| `eero_eero_status`                           | Gauge | Device status (1=online, 0=offline)    |
| `eero_eero_is_gateway`                       | Gauge | Whether device is the gateway          |
| `eero_eero_connected_clients_count`          | Gauge | Connected clients per eero             |
| `eero_eero_connected_wired_clients_count`    | Gauge | Wired clients per eero                 |
| `eero_eero_connected_wireless_clients_count` | Gauge | Wireless clients per eero              |
| `eero_eero_mesh_quality_bars`                | Gauge | Mesh quality (0-5 bars)                |
| `eero_eero_uptime_seconds`                   | Gauge | Device uptime in seconds               |
| `eero_eero_led_on`                           | Gauge | LED status (1=on, 0=off)               |
| `eero_eero_update_available`                 | Gauge | Firmware update available              |
| `eero_eero_heartbeat_ok`                     | Gauge | Heartbeat status                       |
| `eero_eero_wired`                            | Gauge | Wired backhaul connection              |

---

## 🖥️ Eero Hardware Metrics

| Metric                                   | Type  | Description                  |
| ---------------------------------------- | ----- | ---------------------------- |
| `eero_eero_memory_usage_percent`         | Gauge | Memory usage percentage      |
| `eero_eero_temperature_celsius`          | Gauge | Temperature in Celsius       |
| `eero_eero_led_brightness`               | Gauge | LED brightness level (0-100) |
| `eero_eero_last_reboot_timestamp_seconds`| Gauge | Last reboot timestamp        |
| `eero_eero_provides_wifi`                | Gauge | Device provides WiFi         |
| `eero_eero_backup_connection`            | Gauge | Using backup connection      |

---

## 🔌 Ethernet Port Metrics

| Metric                            | Type  | Description                     |
| --------------------------------- | ----- | ------------------------------- |
| `eero_ethernet_port_info`         | Info  | Port metadata                   |
| `eero_ethernet_port_carrier`      | Gauge | Port has link (1=yes, 0=no)     |
| `eero_ethernet_port_speed_mbps`   | Gauge | Negotiated speed in Mbps        |
| `eero_ethernet_port_is_wan`       | Gauge | Port used for WAN               |
| `eero_ethernet_port_power_saving` | Gauge | Power saving enabled            |
| `eero_eero_wired_internet`        | Gauge | Wired internet connection       |

---

## 🌙 Nightlight Metrics (Eero Beacon)

| Metric                                 | Type  | Description                  |
| -------------------------------------- | ----- | ---------------------------- |
| `eero_eero_nightlight_enabled`         | Gauge | Nightlight enabled           |
| `eero_eero_nightlight_brightness`      | Gauge | Brightness level (0-100)     |
| `eero_eero_nightlight_ambient_enabled` | Gauge | Ambient light sensing        |
| `eero_eero_nightlight_schedule_enabled`| Gauge | Schedule enabled             |

---

## 📱 Client Device Metrics

| Metric                            | Type    | Description                          |
| --------------------------------- | ------- | ------------------------------------ |
| `eero_device_info`                | Info    | Device metadata (manufacturer, type) |
| `eero_device_connected`           | Gauge   | Connection status                    |
| `eero_device_wireless`            | Gauge   | Wireless vs wired                    |
| `eero_device_blocked`             | Gauge   | Block status                         |
| `eero_device_paused`              | Gauge   | Pause status                         |
| `eero_device_is_guest`            | Gauge   | On guest network                     |
| `eero_device_prioritized`         | Gauge   | Bandwidth prioritized                |
| `eero_device_private`             | Gauge   | Marked as private                    |
| `eero_device_connected_to_gateway`| Gauge   | Connected directly to gateway        |
| `eero_device_download_bytes_total`| Counter | Total bytes downloaded               |
| `eero_device_upload_bytes_total`  | Counter | Total bytes uploaded                 |

---

## 📡 Device Wireless Metrics

Labels include `band` (2.4GHz, 5GHz, 6GHz) and `source_eero` (connected eero location).

| Metric                                | Type  | Description                  |
| ------------------------------------- | ----- | ---------------------------- |
| `eero_device_signal_strength_dbm`     | Gauge | Signal strength in dBm       |
| `eero_device_signal_strength_avg_dbm` | Gauge | Average signal strength      |
| `eero_device_connection_score`        | Gauge | Connection quality score     |
| `eero_device_connection_score_bars`   | Gauge | Quality score in bars (0-5)  |
| `eero_device_frequency_mhz`           | Gauge | WiFi frequency in MHz        |
| `eero_device_channel`                 | Gauge | WiFi channel number          |
| `eero_device_rx_bitrate_mbps`         | Gauge | Receive bitrate in Mbps      |
| `eero_device_tx_bitrate_mbps`         | Gauge | Transmit bitrate in Mbps     |
| `eero_device_rx_mcs`                  | Gauge | Receive MCS index            |
| `eero_device_tx_mcs`                  | Gauge | Transmit MCS index           |
| `eero_device_rx_nss`                  | Gauge | Receive spatial streams      |
| `eero_device_tx_nss`                  | Gauge | Transmit spatial streams     |
| `eero_device_rx_bandwidth_mhz`        | Gauge | Receive bandwidth in MHz     |
| `eero_device_tx_bandwidth_mhz`        | Gauge | Transmit bandwidth in MHz    |

---

## 👥 Profile Metrics

| Metric                       | Type  | Description               |
| ---------------------------- | ----- | ------------------------- |
| `eero_profile_paused`        | Gauge | Profile is paused         |
| `eero_profile_devices_count` | Gauge | Devices in profile        |

---

## ⚙️ SQM (Smart Queue Management) Metrics

| Metric                            | Type  | Description                |
| --------------------------------- | ----- | -------------------------- |
| `eero_sqm_upload_bandwidth_mbps`  | Gauge | SQM upload limit in Mbps   |
| `eero_sqm_download_bandwidth_mbps`| Gauge | SQM download limit in Mbps |

---

## 🧵 Thread Metrics (IoT)

| Metric                      | Type  | Description                |
| --------------------------- | ----- | -------------------------- |
| `eero_thread_device_count`  | Gauge | Thread devices on network  |
| `eero_thread_border_router` | Gauge | Thread border routers      |

---

## 💎 Eero Plus Metrics

These metrics require an active Eero Plus/Secure subscription.

### Backup Network

| Metric                             | Type    | Description               |
| ---------------------------------- | ------- | ------------------------- |
| `eero_backup_enabled`              | Gauge   | Backup network enabled    |
| `eero_backup_active`               | Gauge   | Currently using backup    |
| `eero_backup_connected`            | Gauge   | Backup connected          |
| `eero_backup_data_used_bytes_total`| Counter | Bytes used on backup      |
| `eero_backup_signal_strength`      | Gauge   | Backup signal strength    |

### Activity Tracking

| Metric                               | Type  | Description                    |
| ------------------------------------ | ----- | ------------------------------ |
| `eero_activity_download_bytes`       | Gauge | Network download (period)      |
| `eero_activity_upload_bytes`         | Gauge | Network upload (period)        |
| `eero_activity_active_clients`       | Gauge | Active client count            |
| `eero_activity_category_bytes`       | Gauge | Usage by category              |
| `eero_device_activity_download_bytes`| Gauge | Device download (period)       |
| `eero_device_activity_upload_bytes`  | Gauge | Device upload (period)         |

---

## 🔧 Exporter Metrics

| Metric                                  | Type    | Description              |
| --------------------------------------- | ------- | ------------------------ |
| `eero_exporter_scrape_duration_seconds` | Gauge   | Collection duration      |
| `eero_exporter_scrape_success`          | Gauge   | Last scrape success      |
| `eero_exporter_scrape_errors_total`     | Counter | Total scrape errors      |
| `eero_exporter_api_requests_total`      | Counter | API requests by endpoint |

---

## 📈 Example PromQL Queries

```promql
# Is the network online?
eero_network_status == 1

# Total devices across all networks
sum(eero_network_clients_count)

# Average mesh quality
avg(eero_eero_mesh_quality_bars)

# Find eeros needing updates
eero_eero_update_available == 1

# Devices with weak signal (below -70 dBm)
eero_device_signal_strength_dbm < -70

# High memory usage eeros
eero_eero_memory_usage_percent > 80

# Devices by WiFi band
count by (band) (eero_device_connected == 1)

# Top 10 devices by receive bitrate
topk(10, eero_device_rx_bitrate_mbps)

# Ethernet ports at gigabit speed
eero_ethernet_port_speed_mbps >= 1000

# Networks with WPA3 enabled
eero_network_wpa3_enabled == 1

# Scrape success rate over the last hour
avg_over_time(eero_exporter_scrape_success[1h])
```

---

**[← Back to README](README.md)**
