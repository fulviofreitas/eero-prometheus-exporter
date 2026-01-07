<div align="center">

# 🌐 Eero Prometheus Exporter

**Keep an eye on your mesh network like never before**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-22c55e?style=for-the-badge)](LICENSE)
[![Prometheus](https://img.shields.io/badge/prometheus-ready-e6522c?style=for-the-badge&logo=prometheus&logoColor=white)](https://prometheus.io)
[![Docker](https://img.shields.io/badge/docker-ready-2496ed?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)

---

_A modern, async Prometheus exporter for your eero mesh WiFi network._  
_Monitor network health, device connectivity, speed tests, and 50+ metrics with ease._

[Get Started](#-quick-start) · [View Metrics](#-available-metrics) · [Docker Setup](#-docker) · [Troubleshooting](#-troubleshooting)

</div>

---

## ✨ Why This Project?

Your eero mesh network is the backbone of your connected home. Shouldn't you be able to monitor it properly?

This exporter gives you **real-time insights** into your network's performance, device health, and connectivity—all exposed as Prometheus metrics ready for your favorite dashboards.

### What You Get

| Feature                   | Description                                                                 |
| ------------------------- | --------------------------------------------------------------------------- |
| 📊 **50+ Metrics**        | Network status, speed tests, device connectivity, signal strength, and more |
| ⚡ **Async Architecture** | Non-blocking I/O for efficient, lightweight collection                      |
| 🔐 **Secure Auth**        | Session-based authentication with secure local storage                      |
| 🐳 **Docker Ready**       | Multi-stage build with minimal image footprint                              |
| 🎨 **Beautiful CLI**      | Rich terminal output with colors and progress indicators                    |
| 📈 **Grafana Compatible** | Perfect for building stunning dashboards                                    |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10 or higher
- An eero account with at least one network

### Installation

```bash
# Clone the repository
git clone https://github.com/fulviofreitas/eero-prometheus-exporter.git
cd eero-prometheus-exporter

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install the package
pip install -e .
```

### Step 1: Authenticate

Before collecting metrics, link your eero account:

```bash
eero-exporter login your-email@example.com
```

Check your email or SMS for the verification code and enter it when prompted. That's it—you're in! 🎉

### Step 2: Start Collecting

```bash
# Fire up the metrics server
eero-exporter serve

# Or customize it
eero-exporter serve --port 9118 --interval 60
```

Your metrics are now live at **http://localhost:9118/metrics** 🚀

### Available Endpoints

| Endpoint   | Purpose                                             |
| ---------- | --------------------------------------------------- |
| `/metrics` | Prometheus metrics endpoint                         |
| `/health`  | Detailed health status (returns 503 when unhealthy) |
| `/ready`   | Readiness probe (always 200 if server is running)   |
| `/`        | Index page with links                               |

**Health endpoint example response:**

```json
{
  "status": "healthy",
  "session_valid": true,
  "last_collection_success": true,
  "collections_total": 42,
  "collections_failed": 0
}
```

---

## 🐳 Docker

### Quick Start with Docker Compose

**1. Authenticate locally first** (one-time setup):

```bash
pip install -e .
eero-exporter login your-email@example.com
# Enter your verification code
```

**2. Copy your session file:**

```bash
cp ~/.config/eero-exporter/session.json ./session.json
```

**3. Launch:**

```bash
docker-compose up -d
```

**4. Want the full monitoring stack?** Add Prometheus and Grafana:

```bash
docker-compose --profile monitoring up -d
```

### Building from Source

```bash
docker build -t eero-exporter .
docker run -p 9118:9118 \
  -v ./session.json:/home/eero/.config/eero-exporter/session.json:ro \
  eero-exporter
```

---

## 💻 CLI Reference

| Command                       | What It Does                         |
| ----------------------------- | ------------------------------------ |
| `eero-exporter login <email>` | 🔑 Link your eero account            |
| `eero-exporter logout`        | 🚪 Clear saved session               |
| `eero-exporter status`        | 📡 Check auth status & list networks |
| `eero-exporter validate`      | ✅ Validate session credentials      |
| `eero-exporter test`          | 🧪 Test metrics collection           |
| `eero-exporter serve`         | 🚀 Start the Prometheus server       |
| `eero-exporter version`       | ℹ️ Show version info                 |

### Validate Command

Test your credentials before deploying:

```bash
# Full output
eero-exporter validate

# Quiet mode (for scripts/CI)
eero-exporter validate -q && echo "Valid" || echo "Invalid"
```

**Exit codes:**

- `0` = Session is valid
- `1` = Session is invalid or expired
- `2` = No session file found

### Server Options

```bash
eero-exporter serve [OPTIONS]

Options:
  -p, --port INTEGER              Port to listen on [default: 9118]
  -h, --host TEXT                 Host to bind to [default: 0.0.0.0]
  -i, --interval INTEGER          Collection interval in seconds [default: 60]
  -s, --session-file PATH         Custom session file path
  -c, --config PATH               Custom config file path
  -l, --log-level TEXT            Log level (DEBUG, INFO, WARNING, ERROR)
  --include-devices/--no-devices  Include device metrics [default: enabled]
  --include-profiles/--no-profiles Include profile metrics [default: enabled]
```

---

## 📊 Available Metrics

<details>
<summary><strong>🌐 Network Metrics</strong></summary>

| Metric                       | Type  | Description                          |
| ---------------------------- | ----- | ------------------------------------ |
| `eero_network_status`        | Gauge | Network status (1=online, 0=offline) |
| `eero_network_clients_count` | Gauge | Total connected clients              |
| `eero_network_eeros_count`   | Gauge | Number of eero devices in mesh       |

</details>

<details>
<summary><strong>⚡ Speed Test Metrics</strong></summary>

| Metric                              | Type  | Description               |
| ----------------------------------- | ----- | ------------------------- |
| `eero_speed_upload_mbps`            | Gauge | Upload speed in Mbps      |
| `eero_speed_download_mbps`          | Gauge | Download speed in Mbps    |
| `eero_speed_test_timestamp_seconds` | Gauge | Last speed test timestamp |

</details>

<details>
<summary><strong>💚 Health Metrics</strong></summary>

| Metric               | Type  | Description                               |
| -------------------- | ----- | ----------------------------------------- |
| `eero_health_status` | Gauge | Health by source (internet, eero_network) |

</details>

<details>
<summary><strong>📶 Eero Device Metrics</strong></summary>

| Metric                              | Type  | Description                         |
| ----------------------------------- | ----- | ----------------------------------- |
| `eero_eero_status`                  | Gauge | Device status (1=online, 0=offline) |
| `eero_eero_is_gateway`              | Gauge | Whether device is the gateway       |
| `eero_eero_connected_clients_count` | Gauge | Connected clients per eero          |
| `eero_eero_mesh_quality_bars`       | Gauge | Mesh quality (0-5 bars)             |
| `eero_eero_uptime_seconds`          | Gauge | Device uptime in seconds            |
| `eero_eero_led_on`                  | Gauge | LED status (1=on, 0=off)            |
| `eero_eero_update_available`        | Gauge | Firmware update available           |
| `eero_eero_wired`                   | Gauge | Wired backhaul connection           |

</details>

<details>
<summary><strong>📱 Client Device Metrics</strong></summary>

| Metric                            | Type  | Description              |
| --------------------------------- | ----- | ------------------------ |
| `eero_device_connected`           | Gauge | Connection status        |
| `eero_device_wireless`            | Gauge | Wireless vs wired        |
| `eero_device_blocked`             | Gauge | Block status             |
| `eero_device_paused`              | Gauge | Pause status             |
| `eero_device_signal_strength_dbm` | Gauge | Signal strength in dBm   |
| `eero_device_connection_score`    | Gauge | Connection quality score |

</details>

<details>
<summary><strong>🔧 Exporter Metrics</strong></summary>

| Metric                                  | Type    | Description              |
| --------------------------------------- | ------- | ------------------------ |
| `eero_exporter_scrape_duration_seconds` | Gauge   | Collection duration      |
| `eero_exporter_scrape_success`          | Gauge   | Last scrape success      |
| `eero_exporter_scrape_errors_total`     | Counter | Total scrape errors      |
| `eero_exporter_api_requests_total`      | Counter | API requests by endpoint |

</details>

---

## ⚙️ Configuration

### Prometheus Setup

Add to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "eero"
    static_configs:
      - targets: ["localhost:9118"]
    scrape_interval: 60s
    scrape_timeout: 30s
```

### Config File (Optional)

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

---

## 📈 Example Queries

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

# Scrape success rate over the last hour
avg_over_time(eero_exporter_scrape_success[1h])
```

---

## 🔒 Security

| Aspect               | Implementation                         |
| -------------------- | -------------------------------------- |
| **Token Storage**    | Restricted file permissions (0600)     |
| **Default Location** | `~/.config/eero-exporter/session.json` |
| **Logging**          | Tokens are never logged in plain text  |
| **API Connection**   | HTTPS only                             |

---

## 🔧 Troubleshooting

### Authentication Problems?

```bash
# Validate your credentials
eero-exporter validate

# Check your session status
eero-exporter status

# Start fresh
eero-exporter logout
eero-exporter login your-email@example.com
```

### No Metrics Showing Up?

```bash
# Test collection with verbose output
eero-exporter test

# Run server with debug logging
eero-exporter serve --log-level DEBUG
```

### Health Endpoint Returns Unhealthy?

Check the `/health` endpoint for details:

```bash
curl http://localhost:9118/health | jq
```

Common issues:

- `session_valid: false` — Re-authenticate with `eero-exporter login`
- `last_collection_success: false` — Check logs for API errors

### Docker Container Keeps Restarting?

The container uses `/ready` for health checks (always returns 200 if server is running).
If using a custom health check, use `/ready` instead of `/health`:

```yaml
healthcheck:
  test:
    [
      "CMD",
      "python",
      "-c",
      "import urllib.request; urllib.request.urlopen('http://localhost:9118/ready')",
    ]
```

### Getting Rate Limited?

The eero API may throttle excessive requests. The exporter defaults to 60-second intervals to play nice. If you're still hitting limits, try increasing the interval.

---

## 🛠️ Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/
```

---

## 🙏 Acknowledgments & Credits

This project is a **complete revamp** inspired by and building upon the excellent work of:

- **[brmurphy/eero-exporter](https://github.com/brmurphy/eero-exporter)** — The original eero Prometheus exporter that started it all. Huge thanks to [@brmurphy](https://github.com/brmurphy) for pioneering this concept and the [343max/eero-client](https://github.com/343max/eero-client) library integration.

- **[acaranta/docker-eero-prometheus-exporter](https://github.com/acaranta/docker-eero-prometheus-exporter)** — Docker containerization approach that made deployment a breeze. Thanks to [@acaranta](https://github.com/acaranta) for the container-first thinking.

This revamp modernizes the codebase with:

- Full async/await architecture
- Type hints throughout
- Modern Python packaging (pyproject.toml)
- Rich CLI experience with Typer
- Extended metrics coverage
- Improved error handling and logging

Standing on the shoulders of giants 💪

---

## 📄 License

[Apache License 2.0](LICENSE) — Use it, modify it, share it.

---

<div align="center">

**Made with ❤️ for the home networking community**

_If this helps you, consider giving it a ⭐_

</div>
