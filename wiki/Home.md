# 🌐 Eero Prometheus Exporter

A modern, async Prometheus exporter for your eero mesh WiFi network.

## 📚 Documentation

| Guide | Description |
|-------|-------------|
| [🚀 Installation](Installation) | Quick start, PyPI & source installation |
| [🐳 Docker](Docker) | Docker Compose, Docker Run, server deployment |
| [💻 CLI Reference](CLI-Reference) | Commands, options, and exit codes |
| [⚙️ Configuration](Configuration) | Prometheus setup and config file |
| [📊 Metrics](Metrics) | Full metrics reference (115+ metrics) |
| [🔒 Security](Security) | Authentication and security best practices |
| [🔧 Troubleshooting](Troubleshooting) | Common issues and solutions |
| [🛠️ Development](Development) | Contributing and local development |

## 📊 Grafana Dashboard

A pre-built Grafana dashboard is included with the project. See the [Docker guide](Docker) for automatic provisioning, or import manually:

```bash
# Download the dashboard JSON
curl -O https://raw.githubusercontent.com/fulviofreitas/eero-prometheus-exporter/master/grafana/eero-dashboard.json
```

Then import via Grafana UI: **Dashboards → Import → Upload JSON file**

## 🔗 Quick Links

- [GitHub Repository](https://github.com/fulviofreitas/eero-prometheus-exporter)
- [PyPI Package](https://pypi.org/project/eero-prometheus-exporter/)
- [Docker Image](https://ghcr.io/fulviofreitas/eero-prometheus-exporter)
- [Grafana Dashboard](https://github.com/fulviofreitas/eero-prometheus-exporter/blob/master/grafana/eero-dashboard.json)
- [eero-api SDK](https://github.com/fulviofreitas/eero-api)
