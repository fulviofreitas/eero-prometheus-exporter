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
