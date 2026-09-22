# 🚀 Installation

## Prerequisites

- Python 3.12 or newer
- An eero account with at least one network
- The `eero-api` SDK, **8.0.1 or newer, below 9** (installed automatically; 4.0.0 of the
  exporter does not work with eero-api 6.x/7.x and 3.x does not work with 8.x)

## Install from PyPI

```bash
pip install eero-prometheus-exporter
```

## Install from source

```bash
git clone https://github.com/fulviofreitas/eero-prometheus-exporter.git
cd eero-prometheus-exporter
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -e .
```

## Authenticate

The exporter uses eero's identifier-then-code login (no password):

```bash
eero-exporter login your-email@example.com     # or a phone number in E.164 form
```

Enter the code you receive by email or SMS. The session is stored in
`~/.config/eero-exporter/session.json` with mode `0600` (choose another path with
`--session-file` or `EERO_EXPORTER_SESSION_FILE`; every command honours it). Check it with:

```bash
eero-exporter session-info     # path, mode, schema version, token present -- never the token
eero-exporter validate         # makes one API call; exit 0 = valid
```

If you cannot type a code on the machine that runs the exporter (a container, for example),
use the opt-in browser login page instead -- see [Docker](Docker#alternative-sign-in-from-the-browser).

## Start collecting

```bash
eero-exporter serve
eero-exporter serve --port 10052 --interval 60 --log-level INFO
```

Metrics are at **http://localhost:10052/metrics**. With the defaults the exporter exposes
the `core`, `extended` and `rf` tiers -- about 178 of the 197 declared metrics -- using
29 API requests per network per cycle. See [Configuration](Configuration) for the optional
tiers and [Metrics](Metrics) for the full list.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `/metrics` | Prometheus exposition (cached from the background collection loop) |
| `/health` | JSON status; **503** while the session is invalid or the last collection failed |
| `/ready` | Liveness: 200 whenever the HTTP server is up |
| `/` | Index page |
| `/auth` | Browser login page, only when `--auth-ui` is enabled (404 otherwise) |

Only these paths exist, and only for `GET` (plus `POST` on the `/auth/*` routes).
Any other path is a 404 and any other method a 501; in particular the server does
not answer `HEAD`, so a probe that uses it must be pointed at `GET /ready`.

`/health` response:

```json
{
  "status": "healthy",
  "session_valid": true,
  "last_collection_success": true,
  "collections_total": 42,
  "collections_failed": 0
}
```

When unhealthy it adds `last_error`, and with `--auth-ui` on, `"auth": "required"` and a
hint to visit `/auth`.

## Upgrading from 3.x

4.0.0 is a breaking release. Read the release notes for the list of removed metrics and the
new `status` label values, then follow these steps for every deployment type.

### 1. Back up the session file

```bash
cp ~/.config/eero-exporter/session.json ~/session.json.schema1.bak
chmod 600 ~/session.json.schema1.bak
```

(`docker cp <container>:/home/eero/.config/eero-exporter/session.json ...` or `kubectl cp`
for containers.) 4.0.0 rewrites the file to credential schema 2 on first use and **3.x
cannot read a schema-2 file** -- it overwrites the token with null. Without this backup a
rollback needs a fresh login.

### 2. Make the session directory writable

The client saves the migrated record next to the original (temporary file plus rename), so
the **directory** must be writable by the user running the exporter. Read-only bind mounts
log an error every cycle; see [Docker](Docker#keeping-the-session-file-read-only) for the
migrate-first alternative.

### 3. Upgrade

| Setup | Steps |
|---|---|
| pip / venv | `pip install -U 'eero-prometheus-exporter>=4,<5'`, restart `serve` |
| Docker | pull the 4.x tag, switch the mount from the file to the directory (read-write) -- [Docker](Docker) |
| Compose | update `docker-compose.yml` as in the repository, `docker compose pull && docker compose up -d` |
| Kubernetes | new image tag; back the config directory with a writable volume (PVC or an `emptyDir` seeded by an init container from your Secret), set `fsGroup`/`runAsUser` to the image user; readiness on `/health`, liveness on `/ready` |
| systemd | `pip install -U`, make sure the service user owns `~/.config/eero-exporter`, `systemctl restart`; if you enable `--auth-failure-exit`, add `RestartPreventExitStatus=2` so a dead session does not restart-loop |

### 4. Verify

- `eero-exporter session-info` reports `Schema version: 2`
- `/health` returns 200 and `eero_up` is 1
- `eero_exporter_api_requests_total{status!="success"}` shows only `premium_required`,
  `feature_unavailable` or `not_found` for features your mesh lacks
- Update dashboards and alerts that reference removed metrics or `status="error"`

### Rollback

1. Stop the 4.x process or container.
2. Restore `session.json.schema1.bak` over the session file (mode 0600, owned by the
   service user) **before** starting the old version. No backup: plan an
   `eero-exporter login` right after.
3. Install the previous release: `pip install 'eero-prometheus-exporter==3.19.2'` (its own
   metadata caps eero-api below 7) or the `3.19.2` image tag.
4. Check `eero_up 1` and re-apply any dashboard changes.

## Next steps

- [Docker](Docker) -- containers, compose, the full monitoring stack
- [Configuration](Configuration) -- tiers, every flag, env var and YAML key
- [Metrics](Metrics) -- the 197 metrics with their source paths
- [Security](Security) -- what the exporter stores, sends and never exports

## Grafana dashboard

Import `grafana/eero-dashboard.json` from the repository, or use the compose `monitoring`
profile for automatic provisioning:

```bash
curl -O https://raw.githubusercontent.com/fulviofreitas/eero-prometheus-exporter/master/grafana/eero-dashboard.json
```
