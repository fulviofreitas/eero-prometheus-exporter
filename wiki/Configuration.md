# ⚙️ Configuration

## Prometheus Setup

Add to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "eero"
    static_configs:
      - targets: ["localhost:9118"]
    scrape_interval: 60s
    scrape_timeout: 30s
```

## Config File (Optional)

Create `~/.config/eero-exporter/config.yml`:

```yaml
# Server
port: 9118
host: "0.0.0.0"

# Collection
collection_interval: 60
timeout: 30

# What to collect
include_devices: true
include_profiles: true
include_speed_test: false
speed_test_interval: 3600

# Logging
log_level: INFO
```

## Environment Variables

You can also configure the exporter using environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `EERO_EXPORTER_PORT` | Port to listen on | `9118` |
| `EERO_EXPORTER_HOST` | Host to bind to | `0.0.0.0` |
| `EERO_EXPORTER_INTERVAL` | Collection interval (seconds) | `60` |
| `EERO_EXPORTER_LOG_LEVEL` | Log level | `INFO` |
| `EERO_EXPORTER_SESSION_FILE` | Session file path | `~/.config/eero-exporter/session.json` |

## Example PromQL Queries

```promql
# Network online?
eero_network_status == 1

# Average mesh quality
avg(eero_eero_mesh_quality_bars)

# Devices with weak signal
eero_device_signal_strength_dbm < -70

# Eeros needing updates
eero_eero_update_available == 1
```

**👉 [View full metrics reference →](Metrics)**
