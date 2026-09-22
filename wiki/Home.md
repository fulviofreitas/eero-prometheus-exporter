# 🌐 Eero Prometheus Exporter

A modern, async, strictly read-only Prometheus exporter for your eero mesh WiFi network.

> **Upgrading from 3.x?** 4.0.0 is a breaking release (eero-api 8.x, removed metrics, new
> session-file format). Read [Installation - Upgrading from 3.x](Installation#upgrading-from-3x)
> and back up your session file first.

## 📚 Documentation

| Guide | Description |
|-------|-------------|
| [🚀 Installation](Installation) | Quick start, upgrade from 3.x, rollback |
| [🐳 Docker](Docker) | Compose, `docker run`, writable config mount, full monitoring stack |
| [💻 CLI Reference](CLI-Reference) | Every command, flag, exit code, the read-only probe |
| [⚙️ Configuration](Configuration) | Precedence, tiers and their cost, generated flag / env var / YAML table |
| [📊 Metrics](Metrics) | All 193 metrics with tier, evidence and source path; removed-in-4.0.0 appendix |
| [🔒 Security](Security) | Credential record, never-export list, read-only guarantee, `/auth` threat model |
| [🔧 Troubleshooting](Troubleshooting) | Status values, missing families, auth, rollback |
| [🛠️ Development](Development) | SDK notes, error mapping, registry design, adding a metric |

## 📊 Grafana Dashboard

A pre-built dashboard is included. See the [Docker guide](Docker) for automatic provisioning,
or import manually:

```bash
curl -O https://raw.githubusercontent.com/fulviofreitas/eero-prometheus-exporter/master/grafana/eero-dashboard.json
```

Then **Dashboards → Import → Upload JSON file** in Grafana.

## 🔗 Quick Links

- [GitHub Repository](https://github.com/fulviofreitas/eero-prometheus-exporter)
- [PyPI Package](https://pypi.org/project/eero-prometheus-exporter/)
- [Docker Image](https://ghcr.io/fulviofreitas/eero-prometheus-exporter)
- [Grafana Dashboard](https://github.com/fulviofreitas/eero-prometheus-exporter/blob/master/grafana/eero-dashboard.json)
- [eero-api SDK](https://github.com/fulviofreitas/eero-api)
