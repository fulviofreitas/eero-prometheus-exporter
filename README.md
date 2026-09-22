<div align="center">

# 🌐 Eero Prometheus Exporter

**Keep an eye on your mesh network like never before**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PyPI](https://img.shields.io/pypi/v/eero-prometheus-exporter?style=for-the-badge&logo=pypi&logoColor=white)](https://pypi.org/project/eero-prometheus-exporter/)
[![License](https://img.shields.io/badge/license-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Prometheus](https://img.shields.io/badge/prometheus-ready-e6522c?style=for-the-badge&logo=prometheus&logoColor=white)](https://prometheus.io)
[![Docker](https://img.shields.io/badge/docker-ready-2496ed?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)

---

_A modern, async, strictly read-only Prometheus exporter for your eero mesh WiFi network._  
_Network health, every eero and radio, client devices, data usage, entitlements -- 197 metrics._

[Get Started](../../wiki/Installation) · [Metrics](../../wiki/Metrics) · [Docker](../../wiki/Docker) · [Documentation](../../wiki)

</div>

---

> ### ⚠️ Upgrading from 3.x? 4.0.0 is a breaking release
>
> - Requires **eero-api 8.x**. 3.x installs stopped working when eero-api 8.0.0 was published; 4.0.0 pins `>=8.0.2,<9` and builds images from the lock file.
> - **36 metrics were removed** (they never had an API source) and `eero_exporter_api_requests_total{status}` is now a closed enum -- see [Removed in 4.0.0](../../wiki/Metrics#removed-in-400).
> - The **session file is rewritten** to a new format on first use and 3.x cannot read it back. **Back it up first**; the config directory must be writable (containers: mount the directory read-write).
> - `--data-usage` became `--include-data-usage`; `--config` is kept as an alias of `--config-file`; `--include-diagnostics` is gone.
>
> Upgrade and rollback steps: [Installation → Upgrading from 3.x](../../wiki/Installation#upgrading-from-3x).

---

## 📸 Dashboard Preview

<div align="center">

![Grafana Dashboard](docs/images/grafana-dashboard.png)

*Eero Mesh Network Grafana Dashboard - network status, eero and radio health, devices, usage and entitlements*

</div>

---

## ✨ What You Get

| Feature | Description |
|---------|-------------|
| 📊 **197 metrics, tiered** | `core`, `extended` and `rf` on by default (29 API requests per cycle); `per-profile`, `per-device`, `per-eero` and `unverified` opt-in. Every metric documents its API source path and evidence level. |
| 🔒 **Strictly read-only** | Every data operation is a GET: the exporter never creates, changes or deletes anything on your network. The only POSTs are authentication -- `login`/`verify`, plus the SDK's own transparent session refresh. Enforced by a surface test against the real SDK and a write guard in the test suite. |
| 🌐 **Network & radios** | Health, ISP state, speed test, DNS/DHCP/WAN modes, 119 capability flags, per-band channel, width, TX power and utilisation on every eero. |
| 📱 **Devices & profiles** | Connection quality, PHY rates, MCS/NSS, packet statistics, data usage per device, eero and profile. |
| 💎 **eero Plus / Secure** | Entitlements, DNS policies, insights, WPA3 per band, permissions, subnets, notifications. |
| 🩺 **Observable errors** | `eero_exporter_api_requests_total{endpoint,status}` with a closed `status` enum: `premium_required`, `feature_unavailable` and `not_found` are expected states, not failures. |
| ⚙️ **Configure anywhere** | Every flag of every command has an `EERO_EXPORTER_*` environment variable; `serve`'s options also have YAML keys. Precedence CLI > env > YAML > default. |
| 🔐 **Browser login** | Optional `/auth` page (shared secret, CSRF, rate limit) to sign in without shell access -- handy for containers. |
| 🔎 **Read-only probe** | `eero-exporter probe` captures redacted API shapes for bug reports and new metrics. |
| 🐳 **Docker ready** | Non-root image built from `uv.lock`; `latest` only moves on releases. |

---

## 🚀 Quick Start

```bash
pip install eero-prometheus-exporter
eero-exporter login your-email@example.com   # identifier -> verification code
eero-exporter serve
```

Metrics live at **http://localhost:10052/metrics**. Configure with flags, `EERO_EXPORTER_*`
environment variables or `~/.config/eero-exporter/config.yml`:

```bash
EERO_EXPORTER_INTERVAL=120 EERO_EXPORTER_INCLUDE_PER_EERO=true eero-exporter serve
```

---

## 📚 Documentation

Full documentation in the **[Wiki](../../wiki)** — [Installation](../../wiki/Installation) · [Docker](../../wiki/Docker) · [CLI](../../wiki/CLI-Reference) · [Configuration](../../wiki/Configuration) · [Metrics](../../wiki/Metrics) · [Security](../../wiki/Security) · [Troubleshooting](../../wiki/Troubleshooting)

---

## 📄 License

[MIT](LICENSE) — Use it, fork it, build cool stuff 🎉

---

<div align="center">

## 📊 Repository Metrics

![Repository Metrics](./metrics.repository.svg)

</div>
