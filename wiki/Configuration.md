# ⚙️ Configuration

## Prometheus Setup

Add to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "eero"
    static_configs:
      - targets: ["localhost:10052"]
    scrape_interval: 60s
    scrape_timeout: 30s
```

## Config File (Optional)

Create `~/.config/eero-exporter/config.yml`:

```yaml
# Server
port: 10052
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
| `EERO_EXPORTER_PORT` | Port to listen on | `10052` |
| `EERO_EXPORTER_HOST` | Host to bind to | `0.0.0.0` |
| `EERO_EXPORTER_INTERVAL` | Collection interval (seconds) | `60` |
| `EERO_EXPORTER_LOG_LEVEL` | Log level | `INFO` |
| `EERO_EXPORTER_SESSION_FILE` | Session file path | `~/.config/eero-exporter/session.json` |

## Cardinality Considerations

For large networks with many devices, the exporter can generate significant metric cardinality.
Use these options to reduce storage requirements:

```bash
# Disable device metrics (significantly reduces cardinality)
eero-exporter serve --no-devices

# Disable profile metrics
eero-exporter serve --no-profiles
```

### Estimating Cardinality

| Network Size | Approx. Time Series |
|--------------|---------------------|
| Small (1-2 eeros, ~10 devices) | ~200 series |
| Medium (3-5 eeros, ~30 devices) | ~800 series |
| Large (6+ eeros, ~100 devices) | ~2500+ series |

### Tips for Large Networks

1. **Increase scrape interval** - Use 120s or higher for large networks
2. **Disable device metrics** - Use `--no-devices` if you only need network/eero metrics
3. **Use recording rules** - Pre-aggregate device metrics you need
4. **Adjust retention** - Consider shorter retention for high-cardinality metrics

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
