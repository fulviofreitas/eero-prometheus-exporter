# 🛠️ Development

## Setup

```bash
# Clone the repository
git clone https://github.com/fulviofreitas/eero-prometheus-exporter.git
cd eero-prometheus-exporter

# Install with dev dependencies
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest
```

## Type Checking

```bash
mypy src/
```

## Linting

```bash
ruff check src/
```

## Code Style

This project uses:

- **Ruff** for linting and formatting
- **MyPy** for type checking
- **Pytest** for testing

## Prometheus Compliance

This exporter follows the [official Prometheus exporter guidelines](https://prometheus.io/docs/instrumenting/writing_exporters/):

### Standards Implemented

| Guideline | Implementation |
|-----------|----------------|
| **Port Allocation** | Port 10052 registered in [Prometheus wiki](https://github.com/prometheus/prometheus/wiki/Default-port-allocations) |
| **Up Metric** | `eero_up` gauge (1=success, 0=failure) for alerting |
| **Metric Naming** | `eero_` prefix, snake_case, base units documented |
| **Labels** | Minimal labels, no target label conflicts |
| **Help Strings** | Include units, source API fields, typical ranges |
| **Landing Page** | Version, status, links at `/` |
| **Caching** | Collection interval with timestamp metrics |
| **Health Endpoint** | `/health` for detailed status, `/ready` for probes |

### Key Metrics for Monitoring the Exporter

```promql
# Is the exporter working?
eero_up == 1

# How stale is the data?
time() - eero_exporter_last_collection_timestamp_seconds

# Scrape success rate
rate(eero_exporter_scrape_errors_total[5m])

# API call patterns
rate(eero_exporter_api_requests_total[5m])
```

### Alerting Examples

```yaml
groups:
  - name: eero-exporter
    rules:
      - alert: EeroExporterDown
        expr: eero_up == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Eero exporter is not scraping successfully"

      - alert: EeroDataStale
        expr: time() - eero_exporter_last_collection_timestamp_seconds > 300
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Eero metrics data is stale (>5min old)"
```

## Dependencies

This project uses the **[eero-api](https://pypi.org/project/eero-api/)** library for communicating with eero's cloud services. The eero-api library provides:

- 🚀 **Async-first** — Built on `aiohttp` for non-blocking operations
- 📦 **Type-safe** — Pydantic models with full type hints
- 🔒 **Secure** — System keyring integration for credential storage

Install from PyPI: `pip install eero-api` ([GitHub](https://github.com/fulviofreitas/eero-api))

## Acknowledgments & Credits

This project is a **complete revamp** inspired by and building upon the excellent work of:

- **[fulviofreitas/eero-api](https://github.com/fulviofreitas/eero-api)** — The modern, async Python client for the eero API that powers this exporter. Built on the foundation laid by [@343max](https://github.com/343max/eero-client).

- **[brmurphy/eero-exporter](https://github.com/brmurphy/eero-exporter)** — The original eero Prometheus exporter that started it all. Huge thanks to [@brmurphy](https://github.com/brmurphy) for pioneering this concept.

- **[acaranta/docker-eero-prometheus-exporter](https://github.com/acaranta/docker-eero-prometheus-exporter)** — Docker containerization approach that made deployment a breeze. Thanks to [@acaranta](https://github.com/acaranta) for the container-first thinking.

This revamp modernizes the codebase with:

- Async eero-api library integration
- Full async/await architecture
- Type hints throughout
- Modern Python packaging (pyproject.toml)
- Rich CLI experience with Typer
- Extended metrics coverage
- Improved error handling and logging

Standing on the shoulders of giants 💪
