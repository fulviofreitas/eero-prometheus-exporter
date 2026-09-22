# 🐳 Docker

The image runs as the non-root user `eero` and keeps its session file in
`/home/eero/.config/eero-exporter/`. Since 4.0.0 that directory **must be writable**:
the eero-api client rewrites the credential record (see [Session file and schema 2](#session-file-and-schema-2)).

## Image

- Registry: `ghcr.io/fulviofreitas/eero-prometheus-exporter`
- Tags: `latest` and one tag per release version. `latest` moves **only when a release is
  published**, never on an ordinary merge. Pin a version tag or a digest if you want to
  control when a major upgrade arrives.
- Dependencies are installed from the repository's `uv.lock`, so an image always ships the
  exact `eero-api` version the release was tested with.

## Quick start with Docker Compose

The repository's `docker-compose.yml` mounts a named volume on the config directory:

```yaml
services:
  eero-exporter:
    image: ghcr.io/fulviofreitas/eero-prometheus-exporter:latest
    restart: unless-stopped
    ports:
      - "10052:10052"
    volumes:
      # Read-write: the client migrates and refreshes the session record in place
      - eero-config:/home/eero/.config/eero-exporter
    environment:
      - TZ=UTC
      # Any option can be set here, e.g. EERO_EXPORTER_INTERVAL=120

volumes:
  eero-config:
```

**1. Create the session inside the volume** (one-time). Either log in through the container:

```bash
docker compose run --rm eero-exporter login your-email@example.com
# enter the verification code when prompted
```

or copy a session you created elsewhere (the file is rewritten to schema 2 on first use):

```bash
docker compose run --rm --entrypoint sh eero-exporter -c \
  'cat > /home/eero/.config/eero-exporter/session.json && chmod 600 /home/eero/.config/eero-exporter/session.json' \
  < ~/.config/eero-exporter/session.json
```

**2. Start the exporter:**

```bash
docker compose up -d
docker compose exec eero-exporter eero-exporter session-info   # schema 2, mode 0600, dir writable
curl -s localhost:10052/health
```

**3. Optional full stack** (Prometheus + Grafana with the bundled dashboard):

```bash
docker compose --profile monitoring up -d
```

### Alternative: sign in from the browser

If you would rather not run commands in the container, enable the opt-in login page. Pass
the shared secret through the environment (not on the command line):

```yaml
    environment:
      - EERO_EXPORTER_AUTH_UI=true
      - EERO_EXPORTER_AUTH_UI_TOKEN=change-me-to-a-long-random-secret
```

`serve` then starts without a session file and `http://<host>:10052/auth` walks you through
the identifier-then-code login. Put it behind TLS or on a trusted network; see
[Security](Security#web-login-page-auth).

## Docker run

```bash
docker volume create eero-config

# one-time login into the volume
docker run --rm -it -v eero-config:/home/eero/.config/eero-exporter \
  ghcr.io/fulviofreitas/eero-prometheus-exporter:latest login your-email@example.com

# run
docker run -d --name eero-exporter -p 10052:10052 \
  -v eero-config:/home/eero/.config/eero-exporter \
  ghcr.io/fulviofreitas/eero-prometheus-exporter:latest
```

Re-authenticate later with `docker exec -it eero-exporter eero-exporter login you@example.com`
(or the `/auth` page).

### Bind-mounting a host directory instead of a volume

A bind mount works the same way, but the directory has to be writable by the container's
`eero` user. Find its UID with `docker run --rm --entrypoint id <image>` and `chown` the host
directory accordingly, or run the container with `--user "$(id -u):$(id -g)"` and a home
directory you own.

### Keeping the session file read-only

If your platform cannot give the container a writable mount, migrate the file **once** with
4.0.0 on any machine, then mount that migrated file `:ro`:

```bash
pip install 'eero-prometheus-exporter>=4'
eero-exporter validate --session-file ./session.json      # rewrites it to schema 2
eero-exporter session-info --session-file ./session.json  # confirms "Schema version: 2"
docker run -d -p 10052:10052 \
  -v ./session.json:/home/eero/.config/eero-exporter/session.json:ro \
  ghcr.io/fulviofreitas/eero-prometheus-exporter:latest
```

Collection works with a read-only file; the only cost is that any later save the client
attempts (a server-side token refresh) is logged as an error and lost, so you may have to
re-login sooner. There is no need for the old trick of creating an empty `{}` placeholder
file -- it is not a valid credential record and 4.0.0 treats it as "not authenticated".

## Session file and schema 2

eero-api 8.x stores the session as `{"session_id": "...", "schema_version": 2}` with mode
`0600`, written atomically (temporary file plus rename in the same directory). On first use
4.0.0 migrates a 3.x file to this format in place. Two consequences:

- The **directory** must be writable, not just the file.
- **3.x cannot read a schema-2 file.** It treats the token as expired and overwrites it with
  a null token. Back up the file before upgrading; see [Installation](Installation#upgrading-from-3x).

`eero-exporter session-info` prints the path, mode, owner match, directory writability,
schema version and whether a token is present -- never the token itself.

## Backup before upgrading

```bash
docker cp eero-exporter:/home/eero/.config/eero-exporter/session.json ./session.json.schema1.bak
chmod 600 ./session.json.schema1.bak
```

Keep the backup outside any repository. To roll back, stop the 4.x container, restore the
backup over the session file, and start the previous version tag.

## Health checks

The image's `HEALTHCHECK` (and the compose file) use `/ready`, which is 200 whenever the HTTP
server is up. Use `/health` for monitoring: it returns 503 while the session is invalid or
the last collection failed, which would otherwise make the container restart in a loop.

## Full observability stack on a server

For a server deployment with absolute paths (Prometheus and Grafana included), prepare a base
directory, put `prometheus.yml`, the Grafana provisioning files and `grafana/eero-dashboard.json`
from this repository in it, and use a compose file like the one below. Grafana provisions
the datasource and imports the dashboard on start.

```yaml
services:
  eero-exporter:
    image: ghcr.io/fulviofreitas/eero-prometheus-exporter:latest
    container_name: eero-exporter
    restart: unless-stopped
    ports:
      - "10052:10052"
    volumes:
      - /srv/eero/exporter-config:/home/eero/.config/eero-exporter   # writable, owned by the container user
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:10052/ready')"]
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
      - /srv/eero/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - /srv/eero/prometheus_data:/prometheus        # chown 65534:65534
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
      - /srv/eero/grafana_data:/var/lib/grafana      # chown 472:472
      - /srv/eero/grafana/provisioning:/etc/grafana/provisioning:ro
      - /srv/eero/grafana/eero-dashboard.json:/var/lib/grafana/dashboards/eero-dashboard.json:ro
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

`prometheus.yml` for the stack:

```yaml
global:
  scrape_interval: 60s

scrape_configs:
  - job_name: "eero"
    static_configs:
      - targets: ["eero-exporter:10052"]
```

### Common issues

| Issue | Solution |
|---|---|
| `auth_storage` / "could not save credentials" errors every cycle | The config directory is mounted read-only or owned by another user. Mount it read-write, or migrate the file first and accept the limitation. |
| Container starts, `eero_up 0`, `/health` says `session_valid: false` | Run `eero-exporter login` in the container (or use `/auth`); a terminal auth failure deletes the session file. |
| Prometheus won't start | `chown -R 65534:65534 <prometheus_data>` |
| Grafana permission denied | `chown -R 472:472 <grafana_data>` |
| Health check failing | Use `/ready` for the container health check, `/health` for monitoring. |
| Dashboard not showing | Verify `eero-dashboard.json` is mounted where the provisioning file expects it. |
