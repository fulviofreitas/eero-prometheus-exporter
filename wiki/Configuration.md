# ⚙️ Configuration

Every option can be set on the command line, through an `EERO_EXPORTER_*` environment
variable, or (for `serve`) in a YAML file. The tables in [Options by command](#options-by-command)
are generated from the CLI itself, so they are always complete.

## Precedence

```
CLI flag  >  environment variable  >  YAML config file  >  built-in default
```

A flag you do not pass never overrides the YAML file (4.0.0 fixed a 3.x bug where CLI
defaults clobbered YAML values). Boolean environment variables accept `true`/`false` and
`1`/`0`; list values such as `EERO_EXPORTER_DATA_USAGE_PERIODS` are comma-separated.

## Prometheus scrape config

Add to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "eero"
    static_configs:
      - targets: ["localhost:10052"]
    scrape_interval: 60s
    scrape_timeout: 30s
```

Metrics are collected in a background loop (every `--interval` seconds) and cached, so a
scrape returns in milliseconds and never triggers API calls of its own. Scraping more often
than the collection interval just returns the same values.

## Config file

The default path is `~/.config/eero-exporter/config.yml`; point `serve --config-file`
(alias `--config`) or `EERO_EXPORTER_CONFIG_FILE` elsewhere. Every YAML key below matches
the "YAML key" column of the `serve` table.

```yaml
# Server
port: 10052
host: "0.0.0.0"
metrics_path: "/metrics"
timeout: 30                 # HTTP server only; the API client has fixed timeouts

# Collection
collection_interval: 60
session_file: "~/.config/eero-exporter/session.json"
log_level: INFO

# Core families (all on by default)
include_devices: true
include_profiles: true
include_data_usage: true
include_premium: true
include_ethernet: true
include_port_forwards: true
include_reservations: true
include_blacklist: true
include_insights: true

# Tiers
include_extended: true
include_rf: true
include_per_profile: false
include_per_device: false
include_per_eero: false
include_unverified: false

# eero API client
get_retries: 1
send_legacy_cookie: true
accept_language: "en-US"
data_usage_periods: [day, week, month]
eeros_from_envelope: false

# Behaviour
auth_failure_exit: false
expose_public_ip: false

# Optional web login page (see Security)
auth_ui: false
# auth_ui_token: "a-long-random-secret-of-16-plus-chars"
auth_ui_pending_ttl: 600
```

`auth_ui_token` is masked when the configuration is dumped or logged.

## Collection tiers and their cost

The exporter groups its API reads into tiers so you can trade request volume and series
cardinality against coverage. Costs are GET requests per network per collection cycle on
the reference mesh (4 eeros, 137 devices, 10 profiles); the eero API allows roughly 100
requests per minute, so the defaults (29 per cycle at a 60 s interval) leave ample headroom.

| Tier | Flag | Default | Extra GETs / cycle | What it adds |
|---|---|---|---|---|
| core | per-family `--include-*` | on | about 16 | networks, network envelope, eeros, devices, profiles, data usage, insights, port forwards, reservations, blocked devices |
| extended | `--include-extended` | on | +12 | entitlements, WPA3 per band, fast transition, permissions, members, notifications, DNS content filter, subnets, profile insights |
| rf | `--include-rf` | on | +1 | channel utilisation per eero and band (one call for the whole mesh) |
| per-profile | `--include-per-profile` | off | +1 per profile | DNS policy applications per profile (eero Secure) |
| per-device | `--include-per-device` | off | +3 | device-level insights; series scale with device count |
| per-eero | `--include-per-eero` | off | +3 per eero | nightlight (Beacon), connections, OUI check |
| unverified | `--include-unverified` | off | +12 | families whose payload was empty or absent on the probed mesh; parsers are defensive |

With every tier on, the reference mesh costs 66 GETs per cycle. Watch
`eero_exporter_api_requests_last_cycle` and `eero_exporter_api_requests_total{status="rate_limited"}`
after enabling optional tiers on a large mesh, and raise `--interval` if needed. The full
metric list per tier is in [Metrics](Metrics).

## Option notes

| Option | Notes |
|---|---|
| `--get-retries` | Bounded retry count the eero-api client applies to a GET that fails with a transport error or a 5xx. Retries never apply to writes (the exporter issues none). Default 1. |
| `--send-legacy-cookie` | The client authenticates with the `X-User-Token` header; by default it also sends the legacy session cookie. Turn it off only if you know the API accepts header-only auth for your account. |
| `--accept-language` | Value of the `X-Accept-Language` header. Affects localised strings only. |
| `--data-usage-periods` | Which data-usage windows to fetch (`day`, `week`, `month`). Each window is one GET; drop windows you do not chart. |
| `--eeros-from-envelope` | Read the eero list embedded in the network envelope instead of the standalone `eeros` GET (saves one request per cycle; the standalone list is the documented shape, so this is off by default). |
| `--auth-failure-exit` | When a collection cycle ends with a terminal authentication failure (the API rejected the session and the client could not refresh it), log one error and exit with status 2 instead of retrying every cycle. Useful under systemd or Kubernetes where a supervisor can re-provision a session. A merely missing session file does not trigger it. |
| `--expose-public-ip` | Adds the `public_ip` label back onto `eero_network_info`. Off by default because the metrics endpoint is unauthenticated. |
| `--include-thread` | Accepted for compatibility; gates nothing in 4.0.0 (the Thread read is part of the `unverified` tier). |

### Web login page (`--auth-ui`)

`serve --auth-ui --auth-ui-token <secret>` enables a small `/auth` page on the exporter's
own port where you can complete the identifier-then-code login without shell access to the
host (handy for containers). Requirements and behaviour:

- `--auth-ui-token` must be at least 16 characters or `serve` refuses to start.
- **Pass the token through `EERO_EXPORTER_AUTH_UI_TOKEN` or the YAML file, not on the
  command line** -- argv is visible to every local user via `ps`.
- Put the page behind TLS (a reverse proxy) or restrict it to a trusted network; the token
  travels in the form body.
- `--auth-ui-pending-ttl` (default 600 s) bounds how long a started login waits for its code.
- With `--auth-ui` on, `serve` starts even when no session file exists yet; `/health`
  reports `"auth": "required"` until you sign in.

The threat model and protections (CSRF token, rate limiting, uniform 403 responses, security
headers) are described in [Security](Security).

## Options by command

Generated from the CLI by `scripts/gen_config_doc.py`; do not edit the block by hand.
Defaults shown for `serve` are the effective built-in defaults (the flag itself defaults to
"not provided" so YAML values survive).

<!-- BEGIN GENERATED: options -->

### `eero-exporter serve`

| Flag | Environment variable | YAML key | Default | Description |
|---|---|---|---|---|
| `--port` | `EERO_EXPORTER_PORT` | `port` | `10052` | Port to listen on (default: 10052, registered in Prometheus wiki) |
| `--host` | `EERO_EXPORTER_HOST` | `host` | `0.0.0.0` | Host to bind to |
| `--interval` | `EERO_EXPORTER_INTERVAL` | `collection_interval` | `60` | Collection interval in seconds |
| `--session-file` | `EERO_EXPORTER_SESSION_FILE` | `session_file` | `~/.config/eero-exporter/session.json` | Path to session file |
| `--config-file` | `EERO_EXPORTER_CONFIG_FILE` | - | `~/.config/eero-exporter/config.yml` | Path to config file (--config is kept as an alias) |
| `--log-level` | `EERO_EXPORTER_LOG_LEVEL` | `log_level` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `--include-devices` | `EERO_EXPORTER_INCLUDE_DEVICES` | `include_devices` | `true` | Include device metrics |
| `--include-profiles` | `EERO_EXPORTER_INCLUDE_PROFILES` | `include_profiles` | `true` | Include profile metrics |
| `--include-data-usage` | `EERO_EXPORTER_INCLUDE_DATA_USAGE` | `include_data_usage` | `true` | Include data usage metrics (adds ~9 API calls per network per scrape) |
| `--include-premium` | `EERO_EXPORTER_INCLUDE_PREMIUM` | `include_premium` | `true` | Include premium-feature metrics |
| `--include-ethernet` | `EERO_EXPORTER_INCLUDE_ETHERNET` | `include_ethernet` | `true` | Include ethernet port metrics |
| `--include-thread` | `EERO_EXPORTER_INCLUDE_THREAD` | `include_thread` | `true` | Include Thread network metrics |
| `--include-port-forwards` | `EERO_EXPORTER_INCLUDE_PORT_FORWARDS` | `include_port_forwards` | `true` | Include port-forward metrics |
| `--include-reservations` | `EERO_EXPORTER_INCLUDE_RESERVATIONS` | `include_reservations` | `true` | Include DHCP reservation metrics |
| `--include-blacklist` | `EERO_EXPORTER_INCLUDE_BLACKLIST` | `include_blacklist` | `true` | Include blacklist metrics |
| `--include-insights` | `EERO_EXPORTER_INCLUDE_INSIGHTS` | `include_insights` | `true` | Include insights metrics |
| `--include-extended` | `EERO_EXPORTER_INCLUDE_EXTENDED` | `include_extended` | `true` | Include the extended tier (entitlements, wpa3, permissions, ...) (§4.2) |
| `--include-rf` | `EERO_EXPORTER_INCLUDE_RF` | `include_rf` | `true` | Include the RF tier (channel utilisation per band) (§4.2) |
| `--include-per-profile` | `EERO_EXPORTER_INCLUDE_PER_PROFILE` | `include_per_profile` | `false` | Include the per-profile tier (off by default, extra GETs per profile) |
| `--include-per-device` | `EERO_EXPORTER_INCLUDE_PER_DEVICE` | `include_per_device` | `false` | Include the per-device tier (off by default, high cardinality) |
| `--include-per-eero` | `EERO_EXPORTER_INCLUDE_PER_EERO` | `include_per_eero` | `false` | Include the per-eero tier (nightlight, connections, ...) |
| `--include-unverified` | `EERO_EXPORTER_INCLUDE_UNVERIFIED` | `include_unverified` | `false` | Include unverified-shape families (off until a shape is captured) |
| `--get-retries` | `EERO_EXPORTER_GET_RETRIES` | `get_retries` | `1` | Bounded SDK GET retry count on transport/5xx errors (never writes) |
| `--send-legacy-cookie` | `EERO_EXPORTER_SEND_LEGACY_COOKIE` | `send_legacy_cookie` | `true` | Also send the legacy session cookie alongside X-User-Token |
| `--accept-language` | `EERO_EXPORTER_ACCEPT_LANGUAGE` | `accept_language` | `en-US` | Value sent as the X-Accept-Language header |
| `--data-usage-periods` | `EERO_EXPORTER_DATA_USAGE_PERIODS` | `data_usage_periods` | `day,week,month` | Comma-separated data-usage windows to collect (day,week,month) |
| `--eeros-from-envelope` | `EERO_EXPORTER_EEROS_FROM_ENVELOPE` | `eeros_from_envelope` | `false` | Read eeros from the cached network envelope instead of a separate GET |
| `--auth-failure-exit` | `EERO_EXPORTER_AUTH_FAILURE_EXIT` | `auth_failure_exit` | `false` | Exit non-zero on a terminal authentication failure instead of retrying forever |
| `--expose-public-ip` | `EERO_EXPORTER_EXPOSE_PUBLIC_IP` | `expose_public_ip` | `false` | Add public_ip back onto eero_network_info (off by default, D13) |
| `--auth-ui` | `EERO_EXPORTER_AUTH_UI` | `auth_ui` | `false` | Enable the opt-in /auth web login page. Put it behind TLS or a trusted network -- it accepts a shared secret over plain HTTP otherwise |
| `--auth-ui-token` | `EERO_EXPORTER_AUTH_UI_TOKEN` | `auth_ui_token` | - | Shared secret required by /auth (min 16 chars, never logged) |
| `--auth-ui-pending-ttl` | `EERO_EXPORTER_AUTH_UI_PENDING_TTL` | `auth_ui_pending_ttl` | `600` | Seconds a pending /auth login->verify flow stays valid before expiring |

### `eero-exporter login`

| Flag | Environment variable | YAML key | Default | Description |
|---|---|---|---|---|
| `--session-file` | `EERO_EXPORTER_SESSION_FILE` | - | `~/.config/eero-exporter/session.json` | Path to session file |

### `eero-exporter logout`

| Flag | Environment variable | YAML key | Default | Description |
|---|---|---|---|---|
| `--session-file` | `EERO_EXPORTER_SESSION_FILE` | - | `~/.config/eero-exporter/session.json` | Path to session file |

### `eero-exporter validate`

| Flag | Environment variable | YAML key | Default | Description |
|---|---|---|---|---|
| `--session-file` | `EERO_EXPORTER_SESSION_FILE` | - | `~/.config/eero-exporter/session.json` | Path to session file |
| `--quiet` | `EERO_EXPORTER_QUIET` | - | `false` | Only output errors, exit 0 if valid, 1 if invalid |

### `eero-exporter status`

| Flag | Environment variable | YAML key | Default | Description |
|---|---|---|---|---|
| `--session-file` | `EERO_EXPORTER_SESSION_FILE` | - | `~/.config/eero-exporter/session.json` | Path to session file |

### `eero-exporter test`

| Flag | Environment variable | YAML key | Default | Description |
|---|---|---|---|---|
| `--session-file` | `EERO_EXPORTER_SESSION_FILE` | - | `~/.config/eero-exporter/session.json` | Path to session file |

### `eero-exporter session-info`

| Flag | Environment variable | YAML key | Default | Description |
|---|---|---|---|---|
| `--session-file` | `EERO_EXPORTER_SESSION_FILE` | - | `~/.config/eero-exporter/session.json` | Path to session file |

### `eero-exporter probe`

| Flag | Environment variable | YAML key | Default | Description |
|---|---|---|---|---|
| `--session-file` | `EERO_EXPORTER_PROBE_SESSION_FILE` | - | `~/.config/eero-exporter/session.json` | Session file to copy for the run (the original is never written to) |
| `--out` | `EERO_EXPORTER_PROBE_OUT` | - | `probes` | Directory for the redacted JSON report and its Markdown summary |
| `--budget` | `EERO_EXPORTER_PROBE_BUDGET` | - | `80` | Maximum number of GET requests for the whole run |
| `--rate` | `EERO_EXPORTER_PROBE_RATE` | - | `1.0` | Maximum requests per second |
| `--only` | `EERO_EXPORTER_PROBE_ONLY` | - | - | Run a single step by label |
| `--dry-run` | `EERO_EXPORTER_PROBE_DRY_RUN` | - | `false` | List the planned steps and make no request |
| `--keep-copy` | `EERO_EXPORTER_PROBE_KEEP_COPY` | - | `false` | Keep the temporary session copy instead of deleting it at exit |
| `--log-level` | `EERO_EXPORTER_PROBE_LOG_LEVEL` | - | `INFO` | Logging level |

<!-- END GENERATED: options -->

## Cardinality

Device families dominate series count: roughly 25 series per client device with the
defaults, plus 3 per device if `--include-per-device` is on. Guidance for large meshes:

1. Raise `--interval` to 120 s or more.
2. Disable `--no-devices` if you only need network and eero metrics, or `--no-data-usage`
   to drop the per-device usage series.
3. Keep `--include-per-device` off unless you chart per-device insights.
4. Use recording rules to pre-aggregate the device series you alert on.

| Network size | Approximate series (defaults) |
|---|---|
| Small (1-2 eeros, ~10 devices) | ~600 |
| Medium (3-5 eeros, ~30 devices) | ~1,300 |
| Large (6+ eeros, ~100 devices) | ~3,500+ |

## Example PromQL

```promql
# Network online?
eero_network_status == 1

# API calls that did not succeed (expected states excluded)
sum by (endpoint, status) (
  rate(eero_exporter_api_requests_total{status!~"success|premium_required|feature_unavailable|not_found"}[5m])
)

# Devices with weak signal
eero_device_signal_strength_dbm < -70

# Eeros needing updates
eero_eero_update_available == 1
```

**[Full metrics reference](Metrics)**
