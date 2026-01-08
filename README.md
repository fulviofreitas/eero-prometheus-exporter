<div align="center">

# 🌐 Eero Prometheus Exporter

**Keep an eye on your mesh network like never before**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-22c55e?style=for-the-badge)](LICENSE)
[![Prometheus](https://img.shields.io/badge/prometheus-ready-e6522c?style=for-the-badge&logo=prometheus&logoColor=white)](https://prometheus.io)
[![Docker](https://img.shields.io/badge/docker-ready-2496ed?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)

---

_A modern, async Prometheus exporter for your eero mesh WiFi network._  
_Monitor network health, device connectivity, speed tests, and 90+ metrics with ease._

[Get Started](#-quick-start) · [View Metrics](METRICS.md) · [Docker Setup](#-docker) · [Troubleshooting](#-troubleshooting)

</div>

---

## ✨ Why This Project?

Your eero mesh network is the backbone of your connected home. Shouldn't you be able to monitor it properly?

This exporter gives you **real-time insights** into your network's performance, device health, and connectivity—all exposed as Prometheus metrics ready for your favorite dashboards.

### What You Get

| Feature                    | Description                                                               |
| -------------------------- | ------------------------------------------------------------------------- |
| 📊 **90+ Metrics**         | Network, eero hardware, devices, Ethernet ports, Thread, Eero Plus & more |
| ⚡ **Async Architecture**  | Non-blocking I/O for efficient, lightweight collection                    |
| 🔗 **Async API Client**    | Powered by [eero-client](https://github.com/fulviofreitas/eero-client)    |
| 🔐 **Secure Auth**         | Session-based authentication with secure local storage                    |
| 🐳 **Docker Ready**        | Multi-stage build with minimal image footprint                            |
| 🎨 **Beautiful CLI**       | Rich terminal output with colors and progress indicators                  |
| 📈 **Grafana Compatible**  | Perfect for building stunning dashboards                                  |
| 💎 **Eero Plus Support**   | Activity tracking, backup network, and premium feature metrics            |

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

**1. Authenticate locally** (one-time setup):

```bash
# Clone and install
git clone https://github.com/fulviofreitas/eero-prometheus-exporter.git
cd eero-prometheus-exporter
pip install -e .

# Login with your eero account
eero-exporter login your-email@example.com
# Enter verification code when prompted
```

**2. Copy your session file:**

```bash
cp ~/.config/eero-exporter/session.json ./session.json
```

**3. Launch the exporter:**

```bash
docker-compose up -d
```

**4. Add the full monitoring stack** (optional):

```bash
docker-compose --profile monitoring up -d
```

### Using Docker Run

```bash
# Run the exporter
docker run -d \
  -p 9118:9118 \
  -v ./session.json:/home/eero/.config/eero-exporter/session.json:ro \
  --name eero-exporter \
  ghcr.io/fulviofreitas/eero-prometheus-exporter:latest
```

### Building from Source

```bash
docker build -t eero-exporter .
docker run -p 9118:9118 \
  -v ./session.json:/home/eero/.config/eero-exporter/session.json:ro \
  eero-exporter
```

<details>
<summary><strong>📦 Server Deployment Guide</strong></summary>

If you're deploying to a server with Portainer or Docker, follow these steps:

#### 1. Run the Setup Script

Create and run this setup script on your server to prepare the directory structure and fix permissions:

```bash
#!/bin/bash
# setup-eero-exporter.sh
# Run this on your server before deploying the stack

BASE_DIR="/volume1/docker/eero"

echo "Setting up eero-exporter directory structure..."

# Create directories
mkdir -p "$BASE_DIR"
mkdir -p "$BASE_DIR/prometheus_data"
mkdir -p "$BASE_DIR/grafana_data"
mkdir -p "$BASE_DIR/grafana/provisioning/datasources"
mkdir -p "$BASE_DIR/grafana/provisioning/dashboards"

# Fix Prometheus permissions (runs as nobody:nobody = 65534:65534)
chown -R 65534:65534 "$BASE_DIR/prometheus_data"

# Fix Grafana permissions (runs as grafana = 472:472)
chown -R 472:472 "$BASE_DIR/grafana_data"

# Create empty session.json (to be populated after login)
if [ ! -f "$BASE_DIR/session.json" ]; then
    echo '{}' > "$BASE_DIR/session.json"
    echo "Created empty session.json"
fi

# Create prometheus.yml config
if [ ! -f "$BASE_DIR/prometheus.yml" ]; then
    cat > "$BASE_DIR/prometheus.yml" << 'EOF'
global:
  scrape_interval: 60s
  evaluation_interval: 60s

scrape_configs:
  - job_name: 'eero'
    static_configs:
      - targets: ['eero-exporter:9118']
    metrics_path: /metrics

  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
EOF
    echo "Created prometheus.yml"
fi

# Create Grafana datasource provisioning (auto-configures Prometheus)
cat > "$BASE_DIR/grafana/provisioning/datasources/prometheus.yml" << 'EOF'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
    jsonData:
      timeInterval: "15s"
      httpMethod: POST
EOF
echo "Created Grafana datasource provisioning"

# Create Grafana dashboard provisioning
cat > "$BASE_DIR/grafana/provisioning/dashboards/dashboards.yml" << 'EOF'
apiVersion: 1
providers:
  - name: "Eero Dashboards"
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: /var/lib/grafana/dashboards
EOF
echo "Created Grafana dashboard provisioning"

echo ""
echo "Done! Directory structure:"
ls -la "$BASE_DIR"
echo ""
echo "Next steps:"
echo "1. Login locally: eero-exporter login your-email@example.com"
echo "2. Copy session: scp ~/.config/eero-exporter/session.json user@nas:$BASE_DIR/"
echo "3. Download dashboard: curl -o $BASE_DIR/grafana/eero-dashboard.json https://raw.githubusercontent.com/fulviofreitas/eero-prometheus-exporter/master/grafana/eero-dashboard.json"
echo "4. Deploy the stack in Portainer"
```

Save as `setup-eero-exporter.sh`, make executable (`chmod +x setup-eero-exporter.sh`), and run with `sudo`.

#### 2. Authenticate and Copy Session

On your local machine:

```bash
# Login with your eero account
eero-exporter login your-email@example.com

# Validate it works
eero-exporter validate

# Copy to server
scp ~/.config/eero-exporter/session.json user@your-nas:/volume1/docker/eero/
```

#### 3. Download the Dashboard

Download the pre-built Grafana dashboard to your server:

```bash
# On the server, or via SSH
curl -o /volume1/docker/eero/grafana/eero-dashboard.json \
  https://raw.githubusercontent.com/fulviofreitas/eero-prometheus-exporter/master/grafana/eero-dashboard.json
```

#### 4. Example Portainer Stack

Use this compose file with absolute paths for server deployment. **Grafana will auto-configure the Prometheus datasource and import the dashboard on startup!**

```yaml
version: "3.8"

services:
  eero-exporter:
    image: ghcr.io/fulviofreitas/eero-prometheus-exporter:latest
    container_name: eero-exporter
    restart: unless-stopped
    ports:
      - "9118:9118"
    volumes:
      - /volume1/docker/eero/session.json:/home/eero/.config/eero-exporter/session.json:ro
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import urllib.request; urllib.request.urlopen('http://localhost:9118/ready')",
        ]
      interval: 30s
      timeout: 10s
      retries: 3

  prometheus:
    image: prom/prometheus:latest
    container_name: eero-prometheus
    restart: unless-stopped
    ports:
      - "9090:9090"
    volumes:
      - /volume1/docker/eero/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - /volume1/docker/eero/prometheus_data:/prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"

  grafana:
    image: grafana/grafana:latest
    container_name: eero-grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      - /volume1/docker/eero/grafana_data:/var/lib/grafana
      # Auto-provisioning: datasource + dashboard
      - /volume1/docker/eero/grafana/provisioning:/etc/grafana/provisioning:ro
      - /volume1/docker/eero/grafana/eero-dashboard.json:/var/lib/grafana/dashboards/eero-dashboard.json:ro
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

> 💡 **Auto-provisioning**: When Grafana starts, it automatically:
>
> 1. Creates the Prometheus datasource pointing to `http://prometheus:9090`
> 2. Imports the Eero dashboard from the mounted JSON file
>
> No manual configuration needed—just deploy and open Grafana!

#### Common Issues

| Issue                     | Solution                                                        |
| ------------------------- | --------------------------------------------------------------- |
| Prometheus won't start    | Run `chown -R 65534:65534 /volume1/docker/eero/prometheus_data` |
| Grafana permission denied | Run `chown -R 472:472 /volume1/docker/eero/grafana_data`        |
| Session invalid errors    | Re-run login locally and copy new `session.json` to server      |
| Health check failing      | Use `/ready` endpoint (always 200) instead of `/health`         |
| Dashboard not showing     | Verify `eero-dashboard.json` exists in the grafana folder       |

</details>

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

The exporter provides **90+ metrics** across 15 categories:

| Category            | Metrics | Description                              |
| ------------------- | ------- | ---------------------------------------- |
| 🌐 Network          | 4       | Status, client count, eero count         |
| 🚦 Network Features | 11      | WPA3, SQM, UPnP, Thread, IPv6, etc.      |
| ⚡ Speed Test       | 3       | Upload, download, timestamp              |
| 💚 Health           | 1       | Internet and network health              |
| 📶 Eero Device      | 12      | Status, mesh quality, uptime, LED        |
| 🖥️ Eero Hardware    | 6       | Memory, temperature, LED, reboot         |
| 🔌 Ethernet Ports   | 6       | Port speed, carrier, WAN status          |
| 🌙 Nightlight       | 4       | Eero Beacon nightlight settings          |
| 📱 Client Device    | 11      | Connected, blocked, paused, prioritized  |
| 📡 Device Wireless  | 14      | Signal, bitrate, MCS, bandwidth, channel |
| 👥 Profiles         | 2       | Pause status, device count               |
| ⚙️ SQM              | 2       | Upload/download bandwidth limits         |
| 🧵 Thread           | 2       | IoT device count, border routers         |
| 💎 Eero Plus        | 11      | Backup network, activity tracking        |
| 🔧 Exporter         | 4       | Scrape duration, success, errors         |

**👉 [View Full Metrics Reference →](METRICS.md)**

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
# Network online?
eero_network_status == 1

# Average mesh quality
avg(eero_eero_mesh_quality_bars)

# Devices with weak signal
eero_device_signal_strength_dbm < -70

# Eeros needing updates
eero_eero_update_available == 1
```

**👉 [More example queries in METRICS.md →](METRICS.md#-example-promql-queries)**

---

## 🔒 Security

| Aspect               | Implementation                                                                   |
| -------------------- | -------------------------------------------------------------------------------- |
| **Token Storage**    | Restricted file permissions (0600)                                               |
| **Default Location** | `~/.config/eero-exporter/session.json`                                           |
| **Auth Library**     | Uses [eero-client](https://github.com/fulviofreitas/eero-client) for secure auth |
| **Logging**          | Tokens are never logged in plain text                                            |
| **API Connection**   | HTTPS only (TLS 1.2+)                                                            |

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

## 🔗 Dependencies

This project uses the **[eero-client](https://github.com/fulviofreitas/eero-client)** library for communicating with eero's cloud services. The eero-client provides:

- 🚀 **Async-first** — Built on `aiohttp` for non-blocking operations
- 📦 **Type-safe** — Pydantic models with full type hints
- 🔒 **Secure** — System keyring integration for credential storage

---

## 🙏 Acknowledgments & Credits

This project is a **complete revamp** inspired by and building upon the excellent work of:

- **[fulviofreitas/eero-client](https://github.com/fulviofreitas/eero-client)** — The modern, async Python client for the eero API that powers this exporter. Built on the foundation laid by [@343max](https://github.com/343max/eero-client).

- **[brmurphy/eero-exporter](https://github.com/brmurphy/eero-exporter)** — The original eero Prometheus exporter that started it all. Huge thanks to [@brmurphy](https://github.com/brmurphy) for pioneering this concept.

- **[acaranta/docker-eero-prometheus-exporter](https://github.com/acaranta/docker-eero-prometheus-exporter)** — Docker containerization approach that made deployment a breeze. Thanks to [@acaranta](https://github.com/acaranta) for the container-first thinking.

This revamp modernizes the codebase with:

- Async eero-client library integration
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
