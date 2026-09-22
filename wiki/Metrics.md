# Metrics Reference

<!-- GENERATED FILE: do not edit by hand. Regenerate with `uv run python scripts/gen_metrics_doc.py`; tests/test_metrics_doc.py fails when this page and src/eero_exporter/metrics.py drift. -->

The exporter declares **193 metrics** in 29 resource families. Every metric is read from the eero cloud API with GET requests only; the exporter never changes anything on your network.

Each table lists the metric name, its Prometheus type, labels, the collection tier that has to be enabled for it to be exposed, the evidence level for its source, and the API path it is read from. Metrics whose family is disabled do not appear on `/metrics` at all (no empty `# HELP` lines).

**Evidence levels**

| Level | Meaning |
|---|---|
| `verified` | The path was observed on a live mesh by the read-only probe and parses as declared. |
| `documented` | The path is named in the eero-api SDK or its wiki but was empty or absent on the probed mesh. |
| `inferred` | Kept from a pre-4.0.0 metric whose exact path was not re-verified by the probe; parsed defensively. |

## Collection tiers

Families are grouped into tiers. A tier is enabled with one `serve` flag (or its `EERO_EXPORTER_*` environment variable / YAML key -- see [Configuration](Configuration)). GET counts are per network per collection cycle on the reference mesh (4 eeros, 137 devices, 10 profiles): **29 with the defaults**, **66 with every tier on**. The eero API allows roughly 100 requests per minute.

| Tier | Enable with | Default | Metrics | Cost per cycle |
|---|---|---|---:|---|
| `core` | per-family `--include-*` flags | on | 143 | about 16 GETs: account + networks (2), network envelope, eeros, devices, profiles, data usage (one per period + one breakdown), insights (3), port forwards, reservations, blacklist |
| `extended` | `--include-extended` | on | 20 | +12 GETs, fixed cost: entitlements, WPA3 per band, fast transition, permissions, members, notification settings, unread flag, DNS content filter, subnets, profile insights (3) |
| `rf` | `--include-rf` | on | 11 | +1 GET: a single unparameterised channel-utilisation call covering every eero and band |
| `per_profile` | `--include-per-profile` | off | 1 | +1 GET per profile (DNS policy applications, needs eero Secure) |
| `per_device` | `--include-per-device` | off | 1 | +3 GETs (list-level device insights, one per insight type); high series cardinality on large meshes |
| `per_eero` | `--include-per-eero` | off | 3 | +3 GETs per eero: nightlight (Beacon only), connections, OUI check |
| `unverified` | `--include-unverified` | off | 14 | +12 GETs: families whose payload was empty or absent on the probed mesh; parsers are defensive and log the observed keys at DEBUG |

Core families with their own flag: `blacklist` (`--include-blacklist`), `data_usage` (`--include-data-usage`), `devices` (`--include-devices`), `ethernet` (`--include-ethernet`), `insights` (`--include-insights`), `port_forwards` (`--include-port-forwards`), `profiles` (`--include-profiles`), `reservations` (`--include-reservations`). Every other core family is always on.

Flags that gate reads inside other families rather than a family of their own: `--include-premium`, `--include-thread` (`--no-premium` skips the premium sub-collector and the eero Secure DNS content-filter read; `--include-thread` is accepted for compatibility but gates nothing in 4.0.0 -- the Thread read lives in the `unverified` tier).

## Table of contents

- [Exporter self-observability](#exporter-self-observability) (7)
- [Account](#account) (2)
- [Network identity, health and speed test](#network-identity-health-and-speed-test) (8)
- [Network settings and feature flags](#network-settings-and-feature-flags) (31)
- [Network capabilities](#network-capabilities) (1)
- [Guest network](#guest-network) (2)
- [Eero nodes](#eero-nodes) (29)
- [Eero radios (per band)](#eero-radios-per-band) (5)
- [Ethernet ports](#ethernet-ports) (6)
- [Client devices](#client-devices) (31)
- [Profiles](#profiles) (6)
- [Data usage](#data-usage) (7)
- [Insights (eero Secure)](#insights-eero-secure) (3)
- [Port forwards](#port-forwards) (3)
- [DHCP reservations](#dhcp-reservations) (1)
- [Blocked devices](#blocked-devices) (1)
- [Entitlements and subscription](#entitlements-and-subscription) (4)
- [Wireless security](#wireless-security) (2)
- [Account permissions](#account-permissions) (2)
- [Network members](#network-members) (1)
- [Notification settings](#notification-settings) (2)
- [DNS policy (eero Secure)](#dns-policy-eero-secure) (2)
- [Subnets](#subnets) (6)
- [Profile insights](#profile-insights) (1)
- [RF channel utilisation](#rf-channel-utilisation) (11)
- [Per-profile reads](#per-profile-reads) (1)
- [Device insights](#device-insights) (1)
- [Per-eero reads](#per-eero-reads) (3)
- [Unverified-shape families](#unverified-shape-families) (14)
- [`eero_exporter_api_requests_total{status}` values](#api-request-status-values)
- [PromQL examples](#promql-examples)
- [Removed in 4.0.0](#removed-in-400)

## Exporter self-observability

Family `exporter` -- tier `core`, always on.

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_exporter_api_requests_last_cycle` | gauge | - | `core` | `verified` | `derived: EeroCollector._api_requests_this_cycle` |
| `eero_exporter_api_requests_total` | counter | `endpoint`, `status` | `core` | `verified` | `derived: _record_api_result()` |
| `eero_exporter_collection_interval_seconds` | gauge | - | `core` | `verified` | `derived: ExporterConfig.collection_interval` |
| `eero_exporter_last_collection_timestamp_seconds` | gauge | - | `core` | `verified` | `derived: collect() wall-clock time` |
| `eero_exporter_scrape_duration_seconds` | gauge | - | `core` | `verified` | `derived: collect() wall-clock duration` |
| `eero_exporter_scrape_errors_total` | counter | `error_type` | `core` | `verified` | `derived: collect() exception classification` |
| `eero_up` | gauge | - | `core` | `verified` | `derived: collect() outcome` |

## Account

Family `account` -- tier `core`, always on.

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_account_networks_count` | gauge | - | `core` | `verified` | `account.data.networks.count` |
| `eero_account_premium_next_renewal_timestamp_seconds` | gauge | `network_id` | `core` | `verified` | `network.data.premium_details.next_billing_event_date` |

## Network identity, health and speed test

Family `network` -- tier `core`, always on.

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_health_status` | gauge | `network_id`, `source` | `core` | `verified` | `network.data.health.{internet,eero_network}.status` |
| `eero_network` | info | `network_id` | `core` | `verified` | `network.data (name, status, geo_ip.isp, ip_settings.public_ip, wan_type, gateway_ip)` |
| `eero_network_clients_count` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.clients.count` |
| `eero_network_eeros_count` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.eeros.count` |
| `eero_network_status` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.status` |
| `eero_speed_download_mbps` | gauge | `network_id` | `core` | `verified` | `network.data.speed.down.value` |
| `eero_speed_test_timestamp_seconds` | gauge | `network_id` | `core` | `verified` | `network.data.speed.date` |
| `eero_speed_upload_mbps` | gauge | `network_id` | `core` | `verified` | `network.data.speed.up.value` |

## Network settings and feature flags

Family `network_features` -- tier `core`, always on.

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_dns_config` | info | `network_id` | `core` | `verified` | `network.data.dns.mode` |
| `eero_network_ad_block_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.premium_dns.dns_policies.ad_block` |
| `eero_network_backup_internet_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.backup_internet_enabled` |
| `eero_network_band_steering_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.band_steering` |
| `eero_network_connection_mode` | info | `network_id` | `core` | `verified` | `network.data.connection.mode (upper-cased)` |
| `eero_network_custom_dns_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `derived: network.data.dns.mode == 'custom'` |
| `eero_network_ddns_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.ddns.enabled` |
| `eero_network_dhcp_mode` | info | `network_id` | `core` | `verified` | `network.data.dhcp.mode` |
| `eero_network_dns_caching_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.dns.caching` |
| `eero_network_dns_mode` | info | `network_id`, `family` | `core` | `verified` | `network.data.dns.mode (ipv4); network.data.ipv6.name_servers.mode (ipv6, if observed)` |
| `eero_network_dns_parent_server_count` | gauge | `network_id`, `name` | `core` | `verified` | `len(network.data.dns.parent.ips)` |
| `eero_network_dns_server_count` | gauge | `network_id`, `name` | `core` | `verified` | `len(network.data.dns.custom.ips)` |
| `eero_network_double_nat_detected` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.ip_settings.double_nat` |
| `eero_network_guest_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.guest_network.enabled` |
| `eero_network_ipv6_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.ipv6_upstream` |
| `eero_network_isp_up` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.health.internet.isp_up` |
| `eero_network_last_reboot_timestamp_seconds` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.last_reboot` |
| `eero_network_malware_block_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.premium_dns.dns_policies.block_malware` |
| `eero_network_mlo_mode` | info | `network_id` | `core` | `verified` | `network.data.mlo_mode` |
| `eero_network_power_saving_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.power_saving` |
| `eero_network_premium_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.{premium_status,premium_details}` |
| `eero_network_sqm_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.sqm` |
| `eero_network_thread_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.thread` |
| `eero_network_timezone` | info | `network_id` | `core` | `verified` | `network.data.timezone.value` |
| `eero_network_update_available` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.updates.has_update` |
| `eero_network_update_target` | info | `network_id` | `core` | `verified` | `network.data.updates.target_firmware` |
| `eero_network_updates_available` | gauge | `network_id`, `name` | `core` | `verified` | `eeros.data[].update_available (count)` |
| `eero_network_upnp_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.upnp` |
| `eero_network_wan_type` | info | `network_id` | `core` | `verified` | `network.data.wan_type` |
| `eero_network_wireless_mode` | info | `network_id` | `core` | `verified` | `network.data.wireless_mode` |
| `eero_network_wpa3_enabled` | gauge | `network_id`, `name` | `core` | `verified` | `network.data.wpa3` |

## Network capabilities

Family `network_capabilities` -- tier `core`, always on.

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_network_capability` | gauge | `network_id`, `capability` | `core` | `verified` | `network.data.capabilities.<name>.capable` |

## Guest network

Family `guest` -- tier `core`, always on.

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_guest_network` | info | `network_id` | `core` | `verified` | `network.data.guest_network` |
| `eero_guest_network_connected_clients` | gauge | `network_id`, `name` | `core` | `verified` | `derived: count(devices.data[] where connected and is_guest)` |

## Eero nodes

Family `eeros` -- tier `core`, always on.

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_eero` | info | `network_id`, `eero_id` | `core` | `verified` | `eeros.data[] (location, model, model_number, os_version, serial, mac_address, ip_address)` |
| `eero_eero_band_supported` | gauge | `network_id`, `eero_id`, `location`, `band` | `core` | `verified` | `eeros.data[].bands[]` |
| `eero_eero_connected_clients_count` | gauge | `network_id`, `eero_id`, `location`, `model` | `core` | `verified` | `eeros.data[].connected_clients_count` |
| `eero_eero_connected_wired_clients_count` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].connected_wired_clients_count` |
| `eero_eero_connected_wireless_clients_count` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].connected_wireless_clients_count` |
| `eero_eero_connection_type` | info | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].connection_type (upper-cased on this resource)` |
| `eero_eero_heartbeat_ok` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].heartbeat_ok` |
| `eero_eero_is_gateway` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].gateway` |
| `eero_eero_is_primary` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].is_primary_node` |
| `eero_eero_joined_timestamp_seconds` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].joined` |
| `eero_eero_last_heartbeat_timestamp_seconds` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].last_heartbeat` |
| `eero_eero_last_reboot_timestamp_seconds` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].last_reboot` |
| `eero_eero_led_brightness` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].led_brightness` |
| `eero_eero_led_on` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].led_on` |
| `eero_eero_mesh_quality_bars` | gauge | `network_id`, `eero_id`, `location`, `model` | `core` | `verified` | `eeros.data[].mesh_quality_bars` |
| `eero_eero_nightlight_brightness` | gauge | `network_id`, `eero_id`, `location` | `core` | `inferred` | `eeros.data[].nightlight.brightness` |
| `eero_eero_nightlight_enabled` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].nightlight.enabled` |
| `eero_eero_nightlight_schedule_enabled` | gauge | `network_id`, `eero_id`, `location` | `core` | `inferred` | `eeros.data[].nightlight.schedule.enabled` |
| `eero_eero_os_version` | info | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].os_version` |
| `eero_eero_power_saving_active` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].power_saving.schedule.active` |
| `eero_eero_power_source` | info | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].power_info.power_source` |
| `eero_eero_provides_wifi` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].provides_wifi` |
| `eero_eero_radio_count` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `len(eeros.data[].bssids_with_bands)` |
| `eero_eero_status` | gauge | `network_id`, `eero_id`, `location`, `model` | `core` | `verified` | `eeros.data[].status` |
| `eero_eero_update_available` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].update_available` |
| `eero_eero_uptime_seconds` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].uptime.since_last_reboot_s` |
| `eero_eero_using_wan` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].using_wan` |
| `eero_eero_wired` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].wired` |
| `eero_eero_wired_internet` | gauge | `network_id`, `eero_id`, `location` | `core` | `verified` | `eeros.data[].ethernet_status.wiredInternet` |

## Eero radios (per band)

Family `radio` -- tier `core`, always on.

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_eero_radio_channel` | gauge | `network_id`, `eero_id`, `location`, `band` | `core` | `verified` | `eeros.data[].radio_channel_stats[band].channel` |
| `eero_eero_radio_channel_utilization_percent` | gauge | `network_id`, `eero_id`, `location`, `band` | `core` | `verified` | `eeros.data[].radio_channel_stats[band].channel_utilization` |
| `eero_eero_radio_channel_width_mhz` | gauge | `network_id`, `eero_id`, `location`, `band` | `core` | `verified` | `eeros.data[].radio_channel_stats[band].channel_width` |
| `eero_eero_radio_client_count` | gauge | `network_id`, `eero_id`, `location`, `band` | `core` | `verified` | `eeros.data[].radio_channel_stats[band].client_count` |
| `eero_eero_radio_tx_power_dbm` | gauge | `network_id`, `eero_id`, `location`, `band` | `core` | `verified` | `eeros.data[].radio_channel_stats[band].tx_power` |

## Ethernet ports

Family `ethernet` -- tier `core`, toggled by `--include-ethernet` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_ethernet_port` | info | `network_id`, `eero_id`, `port_number` | `core` | `verified` | `eeros.data[].ethernet_status.statuses[].port_name` |
| `eero_ethernet_port_carrier` | gauge | `network_id`, `eero_id`, `location`, `port_number`, `port_name` | `core` | `verified` | `eeros.data[].ethernet_status.statuses[].hasCarrier` |
| `eero_ethernet_port_is_lte` | gauge | `network_id`, `eero_id`, `location`, `port_number`, `port_name` | `core` | `verified` | `eeros.data[].ethernet_status.statuses[].isLte` |
| `eero_ethernet_port_is_wan` | gauge | `network_id`, `eero_id`, `location`, `port_number`, `port_name` | `core` | `verified` | `eeros.data[].ethernet_status.statuses[].isWanPort` |
| `eero_ethernet_port_neighbor` | info | `network_id`, `eero_id`, `port_number` | `core` | `verified` | `eeros.data[].ethernet_status.statuses[].neighbor.{type,metadata.port}` |
| `eero_ethernet_port_speed_mbps` | gauge | `network_id`, `eero_id`, `location`, `port_number`, `port_name` | `core` | `verified` | `eeros.data[].ethernet_status.statuses[].speed (enum P10\|P100\|P1000\|P10000)` |

## Client devices

Family `devices` -- tier `core`, toggled by `--include-devices` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_device` | info | `network_id`, `device_id`, `mac` | `core` | `verified` | `devices.data[] (nickname/hostname/display_name, manufacturer, ip, device_type, connection_type)` |
| `eero_device_blocked` | gauge | `network_id`, `device_id`, `name`, `mac`, `manufacturer` | `core` | `verified` | `devices.data[].blacklisted` |
| `eero_device_channel` | gauge | `network_id`, `device_id`, `name`, `band`, `source_eero` | `core` | `verified` | `devices.data[].channel (top-level; falls back to connectivity.channel)` |
| `eero_device_connected` | gauge | `network_id`, `device_id`, `name`, `mac`, `manufacturer`, `device_type`, `connection_type`, `source_eero` | `core` | `verified` | `devices.data[].connected` |
| `eero_device_connected_to_gateway` | gauge | `network_id`, `device_id`, `name`, `connection_type` | `core` | `verified` | `devices.data[].source.is_gateway` |
| `eero_device_connection_score` | gauge | `network_id`, `device_id`, `name`, `manufacturer`, `connection_type`, `source_eero` | `core` | `verified` | `devices.data[].connectivity.score` |
| `eero_device_connection_score_bars` | gauge | `network_id`, `device_id`, `name`, `manufacturer`, `connection_type`, `source_eero` | `core` | `verified` | `devices.data[].connectivity.score_bars` |
| `eero_device_first_seen_timestamp_seconds` | gauge | `network_id`, `device_id`, `name`, `manufacturer` | `core` | `verified` | `devices.data[].first_active \| first_seen` |
| `eero_device_frequency_mhz` | gauge | `network_id`, `device_id`, `name`, `manufacturer`, `band`, `source_eero` | `core` | `verified` | `devices.data[].connectivity.frequency` |
| `eero_device_is_guest` | gauge | `network_id`, `device_id`, `name`, `manufacturer` | `core` | `verified` | `devices.data[].is_guest` |
| `eero_device_last_active_timestamp_seconds` | gauge | `network_id`, `device_id`, `name`, `manufacturer` | `core` | `verified` | `devices.data[].last_active` |
| `eero_device_packet_stats_rx_drop_ppm` | gauge | `network_id`, `device_id` | `core` | `verified` | `devices.data[].connectivity.packet_stats.rx_drop_ppm` |
| `eero_device_packet_stats_rx_drops` | gauge | `network_id`, `device_id` | `core` | `verified` | `devices.data[].connectivity.packet_stats.rx_drops` |
| `eero_device_packet_stats_rx_packets` | gauge | `network_id`, `device_id` | `core` | `verified` | `devices.data[].connectivity.packet_stats.rx_packets` |
| `eero_device_packet_stats_total_packets` | gauge | `network_id`, `device_id` | `core` | `verified` | `devices.data[].connectivity.packet_stats.total_packets` |
| `eero_device_packet_stats_tx_fail_ppm` | gauge | `network_id`, `device_id` | `core` | `verified` | `devices.data[].connectivity.packet_stats.tx_fail_ppm` |
| `eero_device_packet_stats_tx_packets` | gauge | `network_id`, `device_id` | `core` | `verified` | `devices.data[].connectivity.packet_stats.tx_packets` |
| `eero_device_packet_stats_tx_retransmit_ppm` | gauge | `network_id`, `device_id` | `core` | `verified` | `devices.data[].connectivity.packet_stats.tx_retransmit_ppm` |
| `eero_device_packet_stats_tx_retries` | gauge | `network_id`, `device_id` | `core` | `verified` | `devices.data[].connectivity.packet_stats.tx_retries` |
| `eero_device_paused` | gauge | `network_id`, `device_id`, `name`, `manufacturer`, `device_type` | `core` | `verified` | `devices.data[].paused` |
| `eero_device_private` | gauge | `network_id`, `device_id`, `name`, `manufacturer` | `core` | `verified` | `devices.data[].is_private` |
| `eero_device_rx_bitrate_mbps` | gauge | `network_id`, `device_id`, `name`, `manufacturer`, `band`, `source_eero` | `core` | `verified` | `devices.data[].connectivity.rx_rate_info.rate_bps / 1e6 (primary) \| connectivity.rx_bitrate (string fallback)` |
| `eero_device_rx_mcs` | gauge | `network_id`, `device_id`, `name`, `band` | `core` | `verified` | `devices.data[].connectivity.rx_rate_info.mcs` |
| `eero_device_rx_nss` | gauge | `network_id`, `device_id`, `name`, `band` | `core` | `verified` | `devices.data[].connectivity.rx_rate_info.nss` |
| `eero_device_signal_strength_dbm` | gauge | `network_id`, `device_id`, `name`, `manufacturer`, `band`, `source_eero` | `core` | `verified` | `devices.data[].connectivity.signal` |
| `eero_device_subnet_kind` | info | `network_id`, `device_id` | `core` | `verified` | `devices.data[].subnet_kind` |
| `eero_device_tx_bitrate_mbps` | gauge | `network_id`, `device_id`, `name`, `manufacturer`, `band`, `source_eero` | `core` | `verified` | `devices.data[].connectivity.tx_rate_info.rate_bps / 1e6` |
| `eero_device_tx_mcs` | gauge | `network_id`, `device_id`, `name`, `band` | `core` | `verified` | `devices.data[].connectivity.tx_rate_info.mcs` |
| `eero_device_tx_nss` | gauge | `network_id`, `device_id`, `name`, `band` | `core` | `verified` | `devices.data[].connectivity.tx_rate_info.nss` |
| `eero_device_wifi_generation` | gauge | `network_id`, `device_id`, `name`, `manufacturer` | `core` | `inferred` | `derived: devices.data[].connectivity.{frequency,rx_rate_info.mode}` |
| `eero_device_wireless` | gauge | `network_id`, `device_id`, `name`, `manufacturer`, `device_type` | `core` | `verified` | `devices.data[].wireless` |

## Profiles

Family `profiles` -- tier `core`, toggled by `--include-profiles` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_profile_blocked_applications_count` | gauge | `network_id`, `profile_id`, `name` | `core` | `verified` | `len(profiles.data[].premium_dns.blocked_applications)` |
| `eero_profile_connected_devices_count` | gauge | `network_id`, `profile_id`, `name` | `core` | `verified` | `sum(profiles.data[].devices[].connected)` |
| `eero_profile_content_filters_set` | gauge | `network_id`, `profile_id`, `name` | `core` | `verified` | `profiles.data[].unified_content_filters.is_content_filters_set` |
| `eero_profile_devices_count` | gauge | `network_id`, `profile_id`, `name` | `core` | `verified` | `len(profiles.data[].devices)` |
| `eero_profile_paused` | gauge | `network_id`, `profile_id`, `name` | `core` | `verified` | `profiles.data[].paused` |
| `eero_profile_schedules_count` | gauge | `network_id`, `profile_id`, `name` | `core` | `verified` | `len(profiles.data[].schedule)` |

## Data usage

Family `data_usage` -- tier `core`, toggled by `--include-data-usage` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_data_usage_download_bytes` | gauge | `network_id` | `core` | `verified` | `get_data_usage().data.series[type=download].sum` |
| `eero_data_usage_upload_bytes` | gauge | `network_id` | `core` | `verified` | `get_data_usage().data.series[type=upload].sum` |
| `eero_device_data_usage_bytes` | gauge | `network_id`, `device_id`, `name`, `period`, `cadence`, `direction` | `core` | `verified` | `get_data_usage_breakdown().data.devices[].{upload,download}` |
| `eero_device_data_usage_download_bytes` | gauge | `network_id`, `device_id`, `name`, `manufacturer`, `device_type` | `core` | `verified` | `get_data_usage_breakdown().data.devices[].download` |
| `eero_device_data_usage_upload_bytes` | gauge | `network_id`, `device_id`, `name`, `manufacturer`, `device_type` | `core` | `verified` | `get_data_usage_breakdown().data.devices[].upload` |
| `eero_eero_data_usage_bytes` | gauge | `network_id`, `eero_id`, `location`, `period`, `cadence`, `direction` | `core` | `verified` | `get_data_usage_breakdown().data.eeros[].{upload,download}` |
| `eero_network_data_usage_bytes` | gauge | `network_id`, `period`, `cadence`, `direction` | `core` | `verified` | `get_data_usage().data.series[].sum, keyed by .type` |

## Insights (eero Secure)

Family `insights` -- tier `core`, toggled by `--include-insights` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_insights_adblock_total` | gauge | `network_id`, `category` | `core` | `verified` | `get_insights(insight_type=adblock).data.series[].sum` |
| `eero_insights_blocked_total` | gauge | `network_id`, `category` | `core` | `verified` | `get_insights(insight_type=blocked).data.series[].sum` |
| `eero_insights_inspected_total` | gauge | `network_id`, `category` | `core` | `verified` | `get_insights(insight_type=inspected).data.series[].sum` |

## Port forwards

Family `port_forwards` -- tier `core`, toggled by `--include-port-forwards` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_network_port_forwards_count` | gauge | `network_id`, `name` | `core` | `verified` | `len(get_forwards())` |
| `eero_port_forward` | info | `network_id`, `forward_id` | `core` | `inferred` | `get_forwards()[] (client_port, gateway_port, protocol, description; falls back to legacy port/external_port/internal_port/nickname). routing.data.forwards.data was empty (len 0) on the probed mesh -- the remapped keys are unverified.` |
| `eero_port_forward_enabled` | gauge | `network_id`, `forward_id`, `gateway_port`, `protocol` | `core` | `inferred` | `get_forwards()[].enabled` |

## DHCP reservations

Family `reservations` -- tier `core`, toggled by `--include-reservations` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_network_dhcp_reservations_count` | gauge | `network_id`, `name` | `core` | `verified` | `len(get_reservations())` |

## Blocked devices

Family `blacklist` -- tier `core`, toggled by `--include-blacklist` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_network_blacklisted_devices_count` | gauge | `network_id`, `name` | `core` | `verified` | `len(get_blacklist())` |

## Entitlements and subscription

Family `entitlements` -- tier `extended`, enabled with `--include-extended` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_account_entitlement_created_timestamp_seconds` | gauge | `network_id` | `extended` | `verified` | `get_entitlement_features().data.entitlements[].created_at` |
| `eero_account_entitlement_product_info` | gauge | `network_id`, `type` | `extended` | `verified` | `get_entitlement_features().data.entitlements[].product.type` |
| `eero_account_entitlement_state` | gauge | `network_id`, `state` | `extended` | `verified` | `get_entitlement_features().data.entitlements[].state` |
| `eero_network_feature_entitled` | gauge | `network_id`, `feature` | `extended` | `verified` | `get_entitlement_features().data.features.<name>.capability.capable` |

## Wireless security

Family `security` -- tier `extended`, enabled with `--include-extended` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_network_fast_transition_enabled` | gauge | `network_id` | `extended` | `verified` | `get_fast_transition().data.fast_transition` |
| `eero_network_wpa3_band_mode` | gauge | `network_id`, `band`, `mode` | `extended` | `verified` | `get_wpa3_per_band().data.{band_2_4_ghz,band_5_ghz,band_6_ghz}` |

## Account permissions

Family `permissions` -- tier `extended`, enabled with `--include-extended` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_network_permission` | gauge | `network_id`, `capability` | `extended` | `verified` | `get_permissions().data.permissions[<dotted key>].read` |
| `eero_network_role` | info | `network_id` | `extended` | `verified` | `get_permissions().data.role` |

## Network members

Family `members` -- tier `extended`, enabled with `--include-extended` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_network_members_count` | gauge | `network_id` | `extended` | `verified` | `len(get_members().data.members)` |

## Notification settings

Family `notifications` -- tier `extended`, enabled with `--include-extended` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_network_notification_enabled` | gauge | `network_id`, `event` | `extended` | `verified` | `get_notification_settings().data[<dotted key>]` |
| `eero_network_notifications_unread` | gauge | `network_id` | `extended` | `verified` | `has_unread_notifications().data.has_unread` |

## DNS policy (eero Secure)

Family `dns_policy` -- tier `extended`, enabled with `--include-extended` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_dns_policy_allowed_domains_count` | gauge | `network_id` | `extended` | `verified` | `len(get_advanced_content_filter().data.allowed_list)` |
| `eero_dns_policy_blocked_domains_count` | gauge | `network_id` | `extended` | `verified` | `len(get_advanced_content_filter().data.blocked_list)` |

## Subnets

Family `subnets` -- tier `extended`, enabled with `--include-extended` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_subnet_enabled` | gauge | `network_id`, `subnet_kind`, `subnet_type` | `extended` | `verified` | `get_subnets_config().data[].enabled` |
| `eero_subnet_igmp_snooping_enabled` | gauge | `network_id`, `subnet_kind`, `subnet_type` | `extended` | `verified` | `get_subnets_config().data[].igmp_snooping_enable` |
| `eero_subnet_lan_access` | gauge | `network_id`, `subnet_kind`, `subnet_type` | `extended` | `verified` | `get_subnets_config().data[].lan_access` |
| `eero_subnet_nat_port_randomization` | gauge | `network_id`, `subnet_kind`, `subnet_type` | `extended` | `verified` | `get_subnets_config().data[].nat_port_randomization` |
| `eero_subnet_open_network` | gauge | `network_id`, `subnet_kind`, `subnet_type` | `extended` | `verified` | `get_subnets_config().data[].open_network` |
| `eero_subnet_wan_access` | gauge | `network_id`, `subnet_kind`, `subnet_type` | `extended` | `verified` | `get_subnets_config().data[].wan_access` |

## Profile insights

Family `profile_insights` -- tier `extended`, enabled with `--include-extended` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_profile_insights_total` | gauge | `network_id`, `profile_id`, `type` | `extended` | `verified` | `get_profiles_insights().data.insights[].sum (id from .insights_url)` |

## RF channel utilisation

Family `rf` -- tier `rf`, enabled with `--include-rf` (default on).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_channel_acs_events_total` | gauge | `network_id`, `eero_id`, `band` | `rf` | `verified` | `get_channel_utilization().data.utilization[].len(acs_events)` |
| `eero_channel_busy_last` | gauge | `network_id`, `eero_id`, `band` | `rf` | `verified` | `get_channel_utilization().data.utilization[].time_series_data[-1].busy` |
| `eero_channel_busy_minutes` | gauge | `network_id`, `eero_id`, `band` | `rf` | `verified` | `get_channel_utilization().data.utilization[].minutes_over_busy_threshold` |
| `eero_channel_info` | info | `network_id`, `eero_id`, `band` | `rf` | `verified` | `get_channel_utilization().data.utilization[].{channel,center_channel,channel_bandwidth,frequency}` |
| `eero_channel_noise_last` | gauge | `network_id`, `eero_id`, `band` | `rf` | `verified` | `get_channel_utilization().data.utilization[].time_series_data[-1].noise` |
| `eero_channel_rx_other_last` | gauge | `network_id`, `eero_id`, `band` | `rf` | `verified` | `get_channel_utilization().data.utilization[].time_series_data[-1].rx_other` |
| `eero_channel_rx_tx_last` | gauge | `network_id`, `eero_id`, `band` | `rf` | `verified` | `get_channel_utilization().data.utilization[].time_series_data[-1].rx_tx` |
| `eero_channel_utilization_avg_percent` | gauge | `network_id`, `eero_id`, `band` | `rf` | `verified` | `get_channel_utilization().data.utilization[].average_utilization` |
| `eero_channel_utilization_max_percent` | gauge | `network_id`, `eero_id`, `band` | `rf` | `verified` | `get_channel_utilization().data.utilization[].max_utilization` |
| `eero_channel_utilization_p99_percent` | gauge | `network_id`, `eero_id`, `band` | `rf` | `verified` | `get_channel_utilization().data.utilization[].p99_utilization` |
| `eero_eero_role_info` | info | `network_id`, `eero_id` | `rf` | `verified` | `get_channel_utilization().data.eeros[].role` |

## Per-profile reads

Family `per_profile` -- tier `per_profile`, enabled with `--include-per-profile` (default off).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_profile_dns_policy_applications_count` | gauge | `network_id`, `profile_id` | `per_profile` | `verified` | `get_dns_policy_applications().data (list length)` |

## Device insights

Family `device_insights` -- tier `per_device`, enabled with `--include-per-device` (default off).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_device_insights_total` | gauge | `network_id`, `device_id`, `type` | `per_device` | `verified` | `get_devices_insights().data.insights[].sum (id from .insights_url)` |

## Per-eero reads

Family `per_eero` -- tier `per_eero`, enabled with `--include-per-eero` (default off).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_eero_connections_count` | gauge | `network_id`, `eero_id` | `per_eero` | `verified` | `get_connections().data.len(wireless_devices)` |
| `eero_eero_ouicheck_can_add` | gauge | `network_id`, `eero_id` | `per_eero` | `verified` | `get_ouicheck().data.can_add` |
| `eero_eero_ouicheck_must_update` | gauge | `network_id`, `eero_id` | `per_eero` | `documented` | `get_ouicheck().data.must_update` |

## Unverified-shape families

Family `unverified` -- tier `unverified`, enabled with `--include-unverified` (default off).

| Metric | Type | Labels | Tier | Evidence | Source |
|---|---|---|---|---|---|
| `eero_backup_access_point_connectivity_info` | info | `network_id`, `index`, `status` | `unverified` | `documented` | `list_backup_access_points().data[].connectivity.status` |
| `eero_backup_access_point_enabled` | gauge | `network_id`, `index` | `unverified` | `documented` | `list_backup_access_points().data[].enabled` |
| `eero_backup_access_points_count` | gauge | `network_id` | `unverified` | `documented` | `list_backup_access_points().data (list length)` |
| `eero_cellular_backup_outages_count` | gauge | `network_id` | `unverified` | `verified` | `get_cellular_backup_events().data.outages (list length)` |
| `eero_cellular_backup_usage_items_count` | gauge | `network_id` | `unverified` | `verified` | `get_cellular_backup_usage().data.backup_usage_items (list length)` |
| `eero_network_ac_compat` | gauge | `network_id` | `unverified` | `verified` | `get_ac_compat().data.enabled` |
| `eero_network_multistaticip_enabled` | gauge | `network_id` | `unverified` | `verified` | `get_multistaticip().data.enabled (404 -> 0)` |
| `eero_network_power_saving_schedules_count` | gauge | `network_id` | `unverified` | `verified` | `get_power_saving_schedules().data.schedules (list length)` |
| `eero_network_routing_devices_count` | gauge | `network_id` | `unverified` | `documented` | `get_routing().data.devices.data (list length)` |
| `eero_network_routing_forwards_count` | gauge | `network_id` | `unverified` | `documented` | `get_routing().data.forwards.data (list length)` |
| `eero_network_routing_pinholes_count` | gauge | `network_id` | `unverified` | `documented` | `get_routing().data.pinholes.data (list length)` |
| `eero_network_routing_reservations_count` | gauge | `network_id` | `unverified` | `documented` | `get_routing().data.reservations.data (list length)` |
| `eero_network_scan_conflicting_ssid` | gauge | `network_id` | `unverified` | `verified` | `get_network_scan().data.conflicting_ssid` |
| `eero_speed_tests_total` | gauge | `network_id` | `unverified` | `verified` | `get_speed_tests(limit=...).data (list length)` |

## API request status values

`eero_exporter_api_requests_total{endpoint,status}` uses a closed `status` vocabulary derived from the exception class the adapter raised -- never from message text, and never the raw API `error_code`. Sum failures with `status!="success"`; the three expected states below are not failures.

| `status` | Meaning |
|---|---|
| `access_denied` | HTTP 403 -- the account role lacks the permission (see `eero_network_permission`). |
| `auth` | HTTP 401 that the SDK could not refresh. The network scrape is aborted, `eero_up` drops to 0 and the session file is deleted by the SDK; run `eero-exporter login` again. |
| `error` | A generic API error not mapped to a more specific class (for example a blocked client version, or an unrecognised domain error). |
| `feature_unavailable` | The eero is offline or the feature does not exist on this hardware (for example nightlight on a non-Beacon node). An expected state. |
| `not_found` | HTTP 404 -- the resource or feature does not exist on this network. An expected state (for example `multistaticip` on most meshes), not an error. |
| `premium_required` | The endpoint needs an eero Plus/Secure subscription. An expected state. |
| `rate_limited` | HTTP 429 or `error.rate.limit`. Increase `--interval` or disable optional tiers. |
| `success` | The request completed and its payload was parsed. |
| `transport` | DNS failure, connection error or timeout. Transient; the bounded `--get-retries` applies. |
| `validation` | The SDK rejected an argument before sending, or the API returned a 400 form error. Usually a malformed identifier -- please report it. |

`eero_exporter_scrape_errors_total{error_type}` counts whole-cycle failures with `error_type` in `auth`, `api`, `network`, `rate_limit` or `unknown`.

## PromQL examples

```promql
# Is the exporter collecting successfully?
eero_up == 1

# API calls that did not succeed, by endpoint and status (5m rate)
sum by (endpoint, status) (rate(eero_exporter_api_requests_total{status!="success"}[5m]))

# Expected non-success states you can ignore on most meshes
eero_exporter_api_requests_total{status=~"premium_required|feature_unavailable|not_found"}

# Requests issued per collection cycle (watch the ~100 req/min API limit)
eero_exporter_api_requests_last_cycle

# Eeros with a firmware update pending
eero_eero_update_available == 1

# Devices with a weak signal
eero_device_signal_strength_dbm < -70

# Busiest radios in the mesh (per eero and band)
topk(5, eero_eero_radio_channel_utilization_percent)

# Daily download per device, top 10
topk(10, eero_device_data_usage_bytes{period="day", direction="download"})

# Which eero Secure features is the network entitled to?
eero_network_feature_entitled == 1
```

## Removed in 4.0.0

These 36 metric names no longer exist. Each had no source in the eero API (most never produced a sample) or was renamed. Update dashboards and alerts that reference them.

| Removed metric | Replacement | Reason |
|---|---|---|
| `eero_account_premium_expiration_timestamp_seconds` | `eero_account_premium_next_renewal_timestamp_seconds` | Renamed: the field is the next billing/renewal date, not an expiry. |
| `eero_backup_active` | - | The backup endpoints were removed from the SDK and never returned data. |
| `eero_backup_connected` | `eero_backup_access_point_connectivity_info (unverified tier)` | The backup endpoints were removed from the SDK and never returned data. |
| `eero_backup_data_used_bytes_total` | `eero_cellular_backup_usage_items_count (unverified tier)` | The backup endpoints were removed from the SDK and never returned data. |
| `eero_backup_enabled` | `eero_network_backup_internet_enabled` | The backup endpoints were removed from the SDK and never returned data. |
| `eero_backup_signal_strength` | - | The backup endpoints were removed from the SDK and never returned data. |
| `eero_data_usage_active_clients` | `eero_network_clients_count` | `get_data_usage` has no `totals` object; the value never populated. |
| `eero_device_adblock_enabled` | `eero_network_ad_block_enabled` | Ad blocking is a network-level setting; no per-device field exists. |
| `eero_device_download_bytes_total` | `eero_device_data_usage_bytes` | Transfer statistics are inaccessible (403/404); use the data-usage family. |
| `eero_device_prioritized` | - | The API has no `prioritized` field. |
| `eero_device_rx_bandwidth_mhz` | - | No such field on the device resource. |
| `eero_device_signal_strength_avg_dbm` | - | `connectivity.signal_avg` is null on every device. |
| `eero_device_tx_bandwidth_mhz` | - | No such field on the device resource. |
| `eero_device_upload_bytes_total` | `eero_device_data_usage_bytes` | Transfer statistics are inaccessible (403/404); use the data-usage family. |
| `eero_diagnostics_dns_latency_ms` | - | `get_diagnostics` returns `{status}` only; results need a write-triggered run. |
| `eero_diagnostics_gateway_latency_ms` | - | `get_diagnostics` returns `{status}` only; results need a write-triggered run. |
| `eero_diagnostics_internet_latency_ms` | - | `get_diagnostics` returns `{status}` only; results need a write-triggered run. |
| `eero_diagnostics_last_run_timestamp_seconds` | - | `get_diagnostics` returns `{status}` only; results need a write-triggered run. |
| `eero_eero_backup_connection` | - | No such field on the eero resource. |
| `eero_eero_memory_usage_percent` | - | No such field on the eero resource. |
| `eero_eero_nightlight_ambient_enabled` | - | `ambient_light_enabled` is a pre-v8 key that no longer exists. |
| `eero_eero_rx_bytes_total` | `eero_eero_data_usage_bytes` | Transfer statistics are inaccessible (403/404); use the data-usage family. |
| `eero_eero_temperature_celsius` | - | No such field on the eero resource. |
| `eero_eero_tx_bytes_total` | `eero_eero_data_usage_bytes` | Transfer statistics are inaccessible (403/404); use the data-usage family. |
| `eero_ethernet_port_power_saving` | - | Never populated by the 3.x parser and dropped with the Ethernet family rewrite. |
| `eero_exporter_scrape_success` | `eero_up` | Deprecated since 3.x; `eero_up` and `eero_exporter_scrape_errors_total` cover it. |
| `eero_guest_network_access_duration_enabled` | - | The guest network object has only `enabled`, `name` and `password`. |
| `eero_network_auto_update_enabled` | `eero_network_update_available` | No `auto_update` field; the updates object carries `has_update`. |
| `eero_network_download_bytes_total` | `eero_network_data_usage_bytes` | Transfer statistics are inaccessible (403/404); use the data-usage family. |
| `eero_network_upload_bytes_total` | `eero_network_data_usage_bytes` | Transfer statistics are inaccessible (403/404); use the data-usage family. |
| `eero_security_scans_blocked_total` | `eero_insights_blocked_total` | Never populated; insights cover blocked threats by category. |
| `eero_security_threats_blocked_total` | `eero_insights_blocked_total` | Never populated; insights cover blocked threats by category. |
| `eero_sqm_download_bandwidth_mbps` | `eero_network_sqm_enabled` | SQM is a single boolean in the API. |
| `eero_sqm_upload_bandwidth_mbps` | `eero_network_sqm_enabled` | SQM is a single boolean in the API. |
| `eero_thread_border_router` | `eero_network_thread_enabled` | `get_thread` carries no border-router field. |
| `eero_thread_device_count` | `eero_network_thread_enabled` | `get_thread` carries no device count (mostly key material). |

Also removed: the `original_speed` and `derated_reason` fields of `eero_ethernet_port_info` (always null), the `endpoint` values `backup`, `backup_status`, `premium` and `sqm` on `eero_exporter_api_requests_total` (those reads were folded into the network envelope), and the `status="error"` catch-all semantics -- see the status table above.
