# 🔧 Troubleshooting

Start with these three commands; they answer most questions without reading logs:

```bash
eero-exporter session-info     # file present? mode 0600? directory writable? schema 2?
eero-exporter validate         # one real API call; exit 0/1/2
eero-exporter test             # a full collection cycle with DEBUG logging
```

## Authentication

| Symptom | Meaning | Fix |
|---|---|---|
| `Not authenticated` on `serve` start | No session file at the configured path | `eero-exporter login <email-or-phone>` (mind `--session-file` / `EERO_EXPORTER_SESSION_FILE`) |
| `eero_up 0`, `scrape_errors_total{error_type="auth"}` rising, `/health` 503 with `session_valid: false` | The API rejected the token and the client could not refresh it. The client has deleted the session file. | Log in again. With `--auth-ui`, visit `/auth`. Under a supervisor, consider `--auth-failure-exit` (exit code 2) instead of retrying forever. |
| `Session file does not contain a JSON object` | The file is empty or a `{}` placeholder | Delete it and log in; placeholders are not valid records in 4.x |
| `Login failed` with a one-line reason | Identifier rejected by eero | Check the address / E.164 phone number |
| Error about saving credentials every cycle (`auth_storage`, "read-only file system", "permission denied") | The session **directory** is read-only or owned by another user; 4.0.0 needs to rewrite the record | Mount the directory read-write, or migrate the file once with `validate` on a writable machine and mount that `:ro` -- see [Docker](Docker#keeping-the-session-file-read-only) |

## API request status values

`eero_exporter_api_requests_total{endpoint,status}` classifies every call by the exception
class the client raised. Three values are **expected states**, not errors:

| `status` | What it means | Action |
|---|---|---|
| `premium_required` | The endpoint needs an eero Plus/Secure subscription | None; the family stays empty |
| `feature_unavailable` | The eero is offline or the feature does not exist on this hardware (e.g. nightlight on non-Beacon nodes) | None |
| `not_found` | The resource does not exist on this network (e.g. `multistaticip` on most meshes) | None |
| `access_denied` | Your account role lacks the permission (`eero_network_permission` shows what you can read) | Use an owner/admin account or disable the family |
| `rate_limited` | HTTP 429 or `error.rate.limit` | Raise `--interval`, disable optional tiers, check `eero_exporter_api_requests_last_cycle` |
| `transport` | DNS, connection or timeout error | Transient; `--get-retries` (default 1) already retries once |
| `validation` | The client rejected an argument or the API returned a 400 | Likely a malformed identifier -- please open an issue with `--log-level DEBUG` output |
| `auth` | Terminal 401 | See Authentication above |
| `error` | Any other API error (e.g. blocked client version) | Check the logs; the `error_code` is logged, the envelope is not |

Alert on `status!~"success|premium_required|feature_unavailable|not_found"`.

## A family has no samples

If a whole group of metrics is missing from `/metrics`, in this order:

1. **Its tier or family is off.** Disabled families are not registered at all (no `# HELP`
   line). Check the tier table in [Configuration](Configuration) and your flags / env vars /
   YAML.
2. **The feature is absent on your mesh.** Look at
   `eero_exporter_api_requests_total{endpoint="<family>"}` -- `premium_required`,
   `feature_unavailable` or `not_found` means the API has nothing to give.
3. **The payload was empty.** Families in the `unverified` tier log the top-level keys they
   saw at DEBUG (never values). Run `serve --log-level DEBUG --include-unverified` and share
   the key list in an issue.
4. **The metric was removed in 4.0.0.** See the appendix in [Metrics](Metrics#removed-in-400).

## Web login page (`/auth`)

| Response | Meaning |
|---|---|
| `404` | `--auth-ui` is not enabled |
| `403` | Wrong access token, wrong CSRF token, wrong verification code, an empty field, or a verification submitted after the pending login expired -- all deliberately indistinguishable. Reload the page for a fresh form and start again. |
| `429` with `Retry-After` | 5 failed attempts within 15 minutes; wait it out |
| `serve` exits 1 mentioning `--auth-ui-token` | Token missing or shorter than 16 characters |

## Container keeps restarting

Use `/ready` (always 200 while the server runs) for the container health check, and
`/health` (503 when unhealthy) for monitoring:

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:10052/ready')"]
```

## Rate limiting

The eero API allows roughly 100 requests per minute. The defaults use 29 per cycle at a
60 s interval. If `status="rate_limited"` appears after enabling `--include-per-eero`,
`--include-per-device`, `--include-per-profile` or `--include-unverified`, raise
`--interval` or turn the tier off again.

## Prometheus not scraping

1. `curl http://localhost:10052/metrics` works?
2. The Prometheus target uses the right host and port (10052 by default).
3. Check `http://<prometheus>:9090/targets` for the error text.

## Rolling back to 3.x

3.x cannot read a schema-2 session file. Stop 4.x, restore your pre-upgrade backup over the
session file (or plan a fresh login), then install `eero-prometheus-exporter==3.19.2` or
run the `3.19.2` image tag. Full recipe in [Installation](Installation#rollback).

## Still stuck

Run `eero-exporter probe --out ./probes` and attach the Markdown summary to your issue: it
contains response shapes and lengths only, never values, identifiers or tokens.
