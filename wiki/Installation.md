# 🚀 Installation

## Prerequisites

- Python 3.12 or higher
- An eero account with at least one network

## Install from PyPI (Recommended)

```bash
pip install eero-prometheus-exporter
```

## Install from Source

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

## Authentication

Before collecting metrics, link your eero account using email or phone number:

```bash
# Using email
eero-exporter login your-email@example.com

# Using phone number
eero-exporter login +15551234567
```

Check your email or SMS for the verification code and enter it when prompted. That's it—you're in! 🎉

## Start Collecting Metrics

```bash
# Fire up the metrics server
eero-exporter serve

# Or customize it
eero-exporter serve --port 10052 --interval 60
```

Your metrics are now live at **http://localhost:10052/metrics** 🚀

## Available Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/metrics` | Prometheus metrics endpoint |
| `/health` | Detailed health status (returns 503 when unhealthy) |
| `/ready` | Readiness probe (always 200 if server is running) |
| `/` | Index page with links |

### Health Endpoint Response

```json
{
  "status": "healthy",
  "session_valid": true,
  "last_collection_success": true,
  "collections_total": 42,
  "collections_failed": 0
}
```

## Next Steps

- [🐳 Docker Setup](Docker) — Run with Docker Compose
- [⚙️ Configuration](Configuration) — Configure Prometheus scraping
- [📊 Metrics Reference](Metrics) — Explore all 90+ metrics
