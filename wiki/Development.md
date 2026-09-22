# 🛠️ Development

## Setup

```bash
git clone https://github.com/fulviofreitas/eero-prometheus-exporter.git
cd eero-prometheus-exporter
uv sync --frozen --extra dev          # or: pip install -e ".[dev]"
```

Gates run by CI (all must pass before a commit):

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest -q
uv run pytest --cov=eero_exporter --cov-report=term-missing
```

Commits follow Conventional Commits; semantic-release derives the version from them
(`feat!:` or a `BREAKING CHANGE:` footer cuts a major).

## Layout

```
src/eero_exporter/
├── cli.py            Typer commands; describe_options() walks the command tree
├── config.py         ExporterConfig, precedence (CLI > env > YAML > default), envvar_name()
├── eero_adapter.py   The only module that imports eero-api; read-only surface; error mapping
├── collector.py      EeroCollector: one cycle = one client, one network envelope, tiers
├── metrics.py        Registry: every metric declared with family/tier/source/evidence
├── probe.py          Read-only live API probe (write guard, budget, redaction)
└── server.py         /metrics, /health, /ready, / and the opt-in /auth page
scripts/
├── gen_metrics_doc.py   renders wiki/Metrics.md from the registry
├── gen_config_doc.py    renders the option tables in wiki/Configuration.md
└── probe_api.py         thin wrapper around `eero-exporter probe`
tests/fixtures/v8/       redacted API payloads (one per endpoint) used by the parser tests
```

## The SDK: eero-api 8.x

- `eero-api` is pinned to `>=8.0.1,<9`. Docker images install from `uv.lock`, so an image
  never resolves a newer SDK than the lock.
- **The SDK hands back raw envelopes, not Pydantic models.** (It does depend on Pydantic
  internally -- see `uv.lock` -- but no model instance reaches a caller.) Every call returns
  the raw `{"meta": ..., "data": ...}`
  envelope; the adapter extracts `data` and the collector parses dicts and lists defensively
  (`isinstance` before `.get`, nullable everywhere).
- `get_network()` is called once per cycle. The client caches that envelope and injects it as
  the parent for later network-scoped reads, and the collector reads dozens of settings
  (DNS, DHCP, updates, health, speed, capabilities, guest, premium) straight from it -- zero
  extra requests. Alias reads (`sqm`, `premium`, `updates`, `guest`) are gone.
- Data usage comes from `get_data_usage(start, end, cadence)` (time series) and
  `get_data_usage_breakdown()` (network, per-eero, per-device and per-profile totals in one
  GET).

### Error-class mapping

The adapter catches the SDK's `EeroException` base and maps **by class** to local exceptions;
the collector classifies **by class**, never by message text, and the API envelope never
reaches a message or a log line (it can carry account data).

| SDK exception | Local class | `status` label |
|---|---|---|
| `EeroAuthenticationException` | `EeroAuthError` (sibling of `EeroAPIError`, not a subclass) | `auth` -- aborts the network scrape |
| `EeroNotFoundException` | `EeroNotFoundError` | `not_found` (expected state) |
| `EeroAccessDeniedException` | `EeroAccessDeniedError` | `access_denied` |
| `EeroPremiumRequiredException` | `EeroPremiumRequiredError` | `premium_required` (expected state) |
| `EeroFeatureUnavailableException` | `EeroFeatureUnavailableError` | `feature_unavailable` (expected state) |
| `EeroRateLimitException` | `EeroRateLimitError` | `rate_limited` |
| `EeroValidationException` | `EeroValidationError` | `validation` |
| `EeroNetworkException`, `EeroTimeoutException` | `EeroTransportError` | `transport` |
| anything else (`EeroAPIException`, `EeroClientBlockedException`, ...) | `EeroAPIError` | `error` |

Every `EeroAPIError` carries `status_code`, `error_code` and `group`
(`eero.classify_error_code`). `collector._record_api_result()` is the single place the
`status` label is produced; `metrics.API_STATUS_VALUES` is the closed vocabulary and
`tests/test_collector_api_status.py` pins it.

## Registry and tiers

Every metric in `metrics.py` is declared through `_gauge` / `_counter` / `_info` with four
provenance fields:

```python
EERO_UPTIME_SECONDS = _gauge(
    f"{PREFIX}_eero_uptime_seconds",
    "Eero device uptime in seconds since last reboot.",
    ("network_id", "eero_id", "location"),
    family="eeros",
    source="eeros.data[].uptime.since_last_reboot_s",
    evidence="verified",          # verified | documented | inferred
    tier="core",                  # core | extended | rf | per_profile | per_device | per_eero | unverified
)
```

- Metrics are created **unregistered**; `register_metrics(config)` registers only the
  families whose tier / family flag is on, so `/metrics` never shows empty `# HELP` lines.
- `FAMILY_TIER` maps family -> tier; `describe_metrics()` returns the provenance records
  (the docs generator reads them); `REMOVED_IN_4_0_0` lists names that must never come back.
- `tests/test_metrics_registry.py` checks provenance completeness, tier gating, forbidden
  label names and that removed names are gone.

### Adding a metric

1. **Capture the shape first.** Run `eero-exporter probe` against a real mesh and read the
   key tree for the endpoint. Never guess keys.
2. Add or extend a fixture in `tests/fixtures/v8/` shaped like the real envelope (redacted
   values are fine; types and key names must match).
3. Declare the metric in `metrics.py` with `family`, `source`, `evidence` and `tier`. New
   families with a per-item cost go in an opt-in tier; unseen payloads go in `unverified`.
4. Parse it in `collector.py` through `_api_get()` / `_record_api_result()` so failures are
   classified and isolated per item.
5. Add a fixture-driven test in the matching `tests/test_collector_*.py`.
6. Regenerate the docs and commit them together with the code:
   ```bash
   uv run python scripts/gen_metrics_doc.py
   uv run python scripts/gen_config_doc.py    # only if a flag changed
   ```
   `tests/test_metrics_doc.py` fails when the wiki and the registry drift, and the
   generator refuses to run if a new family, tier or removed metric lacks a description.
7. Check the Grafana dashboard test (`tests/test_dashboard.py`) still passes.

## Read-only guarantee

- `tests/test_sdk_surface.py` imports the real `eero.EeroClient` and asserts every method the
  adapter calls exists with a compatible signature and none matches a write-name pattern.
- `tests/test_collector_readonly.py` runs a full cycle with every tier on under the probe's
  write guard (`BaseAPI.post/put/delete` replaced with functions that raise) and asserts the
  GET counts: 29 with the defaults, 58 on the fixture mesh with everything on.
- Any new adapter method must be a documented read in the eero-api API reference. Every data
  operation is a GET; the only POSTs are authentication -- `login` / `verify` (CLI and
  `/auth`), and the SDK's transparent session refresh, which it replays for the caller (see
  `tests/test_adapter_refresh_replay.py`).

## Probe workflow

```bash
uv run eero-exporter probe --dry-run                 # the step list
uv run eero-exporter probe --out /tmp/probes         # ~60 GETs, 1 req/s, on a copy of the session
```

The report is redacted (types, lengths, enums, timestamps -- never values), but **do not
commit it to the public repository**: it still describes one household's network layout.
Keep reports in a private location and derive fixtures from them by hand.

## Config surface

Every CLI option must have an `envvar` derived by `config.envvar_name()`; a test walks the
Typer tree and fails otherwise. New `ExporterConfig` fields need a flag, an env var, a YAML
key, a `to_dict()` entry and a `merge_overrides()` pass-through (CLI options default to
`None` so YAML values survive).

## Prometheus compliance

| Guideline | Implementation |
|---|---|
| Port allocation | 10052, registered in the Prometheus default-port wiki |
| Up metric | `eero_up` |
| Naming | `eero_` prefix, snake_case, base units in the name |
| Help strings | Units, source and typical ranges |
| Landing page | `/` |
| Caching | Background collection loop with `eero_exporter_last_collection_timestamp_seconds` |
| Health | `/health` (503 when unhealthy) and `/ready` (liveness) |

```yaml
groups:
  - name: eero-exporter
    rules:
      - alert: EeroExporterDown
        expr: eero_up == 0
        for: 5m
      - alert: EeroDataStale
        expr: time() - eero_exporter_last_collection_timestamp_seconds > 300
        for: 5m
      - alert: EeroApiFailures
        expr: sum(rate(eero_exporter_api_requests_total{status!~"success|premium_required|feature_unavailable|not_found"}[10m])) > 0
        for: 15m
```

## Acknowledgments

- [fulviofreitas/eero-api](https://github.com/fulviofreitas/eero-api) -- the async client
  this exporter is built on, itself descended from
  [@343max's eero-client](https://github.com/343max/eero-client).
- [brmurphy/eero-exporter](https://github.com/brmurphy/eero-exporter) -- the original eero
  Prometheus exporter.
- [acaranta/docker-eero-prometheus-exporter](https://github.com/acaranta/docker-eero-prometheus-exporter)
  -- the container-first approach.
