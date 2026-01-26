# 🐳 Docker

## Quick Start with Docker Compose

**1. Authenticate locally** (one-time setup):

```bash
# Install from PyPI
pip install eero-prometheus-exporter

# Login with your eero account (email or phone)
eero-exporter login your-email@example.com
# Or: eero-exporter login +15551234567
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

## Using Docker Run

```bash
# Run the exporter
docker run -d \
  -p 10052:10052 \
  -v ./session.json:/home/eero/.config/eero-exporter/session.json:ro \
  --name eero-exporter \
  ghcr.io/fulviofreitas/eero-prometheus-exporter:latest
```

## Building from Source

```bash
docker build -t eero-exporter .
docker run -p 10052:10052 \
  -v ./session.json:/home/eero/.config/eero-exporter/session.json:ro \
  eero-exporter
```

---

## 📦 Full Observability Stack

#### Exporter + Prometheus + Grafana

If you're deploying to a server with Portainer or Docker, follow these steps:

### 1. Run the Setup Script

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
      - targets: ['eero-exporter:10052']
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

# Download the Grafana dashboard
echo "Downloading Grafana dashboard..."
curl -fsSL -o "$BASE_DIR/grafana/eero-dashboard.json" \
  https://raw.githubusercontent.com/fulviofreitas/eero-prometheus-exporter/master/grafana/eero-dashboard.json
echo "Downloaded eero-dashboard.json"

echo ""
echo "Done! Directory structure:"
ls -la "$BASE_DIR"
ls -la "$BASE_DIR/grafana/"
echo ""
echo "Next steps:"
echo "1. Login locally: eero-exporter login your-email@example.com"
echo "2. Copy session: scp ~/.config/eero-exporter/session.json user@nas:$BASE_DIR/"
echo "3. Deploy the stack in Portainer"
```

Save as `setup-eero-exporter.sh`, make executable (`chmod +x setup-eero-exporter.sh`), and run with `sudo`.

### 2. Authenticate and Copy Session

On your local machine:

```bash
# Login with your eero account (email or phone)
eero-exporter login your-email@example.com
# Or: eero-exporter login +15551234567

# Validate it works
eero-exporter validate

# Copy to server
scp ~/.config/eero-exporter/session.json user@your-nas:/volume1/docker/eero/
```

### 3. Deploy the Stack

The setup script already downloaded the dashboard. Now deploy using Portainer or Docker Compose.

Use this compose file with absolute paths for server deployment. **Grafana will auto-configure the Prometheus datasource and import the dashboard on startup!**

```yaml
services:
  eero-exporter:
    image: ghcr.io/fulviofreitas/eero-prometheus-exporter:latest
    container_name: eero-exporter
    restart: unless-stopped
    ports:
      - "10052:10052"
    volumes:
      - /volume1/docker/eero/session.json:/home/eero/.config/eero-exporter/session.json:ro
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import urllib.request; urllib.request.urlopen('http://localhost:10052/ready')",
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

### Common Issues

| Issue                     | Solution                                                        |
| ------------------------- | --------------------------------------------------------------- |
| Prometheus won't start    | Run `chown -R 65534:65534 /volume1/docker/eero/prometheus_data` |
| Grafana permission denied | Run `chown -R 472:472 /volume1/docker/eero/grafana_data`        |
| Session invalid errors    | Re-run login locally and copy new `session.json` to server      |
| Health check failing      | Use `/ready` endpoint (always 200) instead of `/health`         |
| Dashboard not showing     | Verify `eero-dashboard.json` exists in the grafana folder       |
