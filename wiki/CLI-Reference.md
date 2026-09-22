# 💻 CLI Reference

```
eero-exporter [OPTIONS] COMMAND [ARGS]...
```

Every option of every command has an environment-variable equivalent, shown by `--help`
(`EERO_EXPORTER_<FLAG>`, or `EERO_EXPORTER_PROBE_<FLAG>` for `probe`). The complete
flag / env var / YAML key table is in [Configuration](Configuration#options-by-command).
`--session-file` (`-s`, `EERO_EXPORTER_SESSION_FILE`) is honoured by **every** command
that touches the session.

## Commands

| Command | What it does | Exit codes |
|---|---|---|
| `login <email-or-phone>` | Send a verification code, prompt for it, save the session (mode 0600) | 0 ok; 1 login or verification rejected / API error |
| `logout` | Delete the local session file (does not revoke the token server-side) | 0 |
| `validate [-q]` | Make one API call to prove the session works; for health checks and CI | 0 valid; 1 invalid, expired or API error; 2 no session file |
| `status` | Show authentication state and your networks | 0 ok; 1 not authenticated / API error |
| `test` | Run one full collection cycle with DEBUG logging, without serving | 0 ok; 1 collection failed |
| `session-info` | Print session-file diagnostics: path, mode, owner match, directory writability, credential schema version, token present (never the value) | 0 ok; 1 missing or unreadable |
| `serve` | Start the HTTP server and the background collection loop | 0 clean stop; 1 start-up refused; 2 terminal auth failure with `--auth-failure-exit` |
| `probe` | Read-only live API probe that writes a redacted shape report | 0 ok; 1 failure |
| `version` | Print the exporter version | 0 |

## `login`

```bash
eero-exporter login your-email@example.com
eero-exporter login +15551234567 --session-file /srv/eero/session.json
```

A rejected identifier or code exits 1 with a one-line reason; the API envelope is never
printed. The token is written with `X-User-Token` semantics in credential schema 2
(`{"session_id": ..., "schema_version": 2}`).

## `validate`

```bash
eero-exporter validate
eero-exporter validate -q && echo valid || echo invalid
```

`validate` also migrates a 3.x session file to schema 2 on first use, which makes it the
right tool for the "migrate locally, then mount read-only" container recipe.

## `session-info`

```
Session file: ~/.config/eero-exporter/session.json
Exists: True
Mode: -rw------- (0o600)
Owned by current user: True
Directory writable: True
Schema version: 2
Token present: True
```

`Schema version: 1 (legacy)` means the file has not been touched by 4.x yet.

## `serve`

```bash
eero-exporter serve [OPTIONS]
```

| Option | Description | Default |
|---|---|---|
| `-p, --port` | Port to listen on | `10052` |
| `-h, --host` | Bind address | `0.0.0.0` |
| `-i, --interval` | Collection interval, seconds | `60` |
| `-s, --session-file` | Session file path | `~/.config/eero-exporter/session.json` |
| `-c, --config-file` (alias `--config`) | YAML config file | `~/.config/eero-exporter/config.yml` |
| `-l, --log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
| `--include-devices/--no-devices` ... `--include-insights/--no-insights` | Core family toggles | on |
| `--include-data-usage/--no-data-usage` | Data-usage family (**renamed** from `--data-usage` in 3.x) | on |
| `--include-extended`, `--include-rf` | Default-on tiers | on |
| `--include-per-profile`, `--include-per-device`, `--include-per-eero`, `--include-unverified` | Opt-in tiers | off |
| `--get-retries` | Bounded GET retry on transport/5xx errors | `1` |
| `--send-legacy-cookie/--no-legacy-cookie` | Also send the legacy cookie alongside `X-User-Token` | on |
| `--accept-language` | `X-Accept-Language` header | `en-US` |
| `--data-usage-periods` | Comma-separated subset of `day,week,month` | all three |
| `--eeros-from-envelope/--no-eeros-from-envelope` | Read eeros from the cached network envelope (saves one GET) | off |
| `--auth-failure-exit/--no-auth-failure-exit` | Exit 2 on a terminal authentication failure instead of retrying | off |
| `--expose-public-ip/--no-expose-public-ip` | Add `public_ip` to `eero_network_info` | off |
| `--auth-ui/--no-auth-ui` | Enable the `/auth` browser login page | off |
| `--auth-ui-token` | Shared secret for `/auth`, at least 16 characters; **pass it via env var or YAML, not argv** | - |
| `--auth-ui-pending-ttl` | Seconds a started login waits for its code | `600` |

Removed in 4.0.0: `--include-diagnostics/--no-diagnostics` (nothing in the API backs it).

Start-up rules:

- Without `--auth-ui`, a missing session file is a hard stop (exit 1) with a hint to run
  `login`.
- With `--auth-ui`, `serve` starts anyway and `/health` reports `"auth": "required"` until
  you sign in; `--auth-ui` without a token of at least 16 characters exits 1.
- `--auth-failure-exit` fires only on a terminal 401 surfaced by the collector (exit 2),
  never on a merely missing file, so the two flags combine safely.

Examples:

```bash
eero-exporter serve --port 9200 --interval 120
eero-exporter serve --no-devices --no-data-usage            # small footprint
eero-exporter serve --include-per-eero --include-unverified   # everything on
EERO_EXPORTER_AUTH_UI=true EERO_EXPORTER_AUTH_UI_TOKEN=... eero-exporter serve --auth-ui
```

## `probe`

```bash
eero-exporter probe --out ./probes --budget 80 --rate 1.0
eero-exporter probe --dry-run          # list the steps, no request
eero-exporter probe --only network     # one step
```

`probe` walks a fixed allowlist of documented **read** endpoints against your live mesh and
writes `<date>-eero-api-<sdk version>.json` plus a Markdown summary. It exists so that new
metrics are designed from observed response shapes rather than guessed keys, and so you can
attach a report to a bug or feature request. Guarantees:

- **Strictly read-only.** The SDK's `post`/`put`/`delete` paths are replaced with functions
  that raise before any request is built, and both request dispatchers refuse non-GET verbs.
- **Your session file is never written to.** The probe works on a `0600` copy in a private
  temporary directory and deletes it afterwards (`--keep-copy` to keep it).
- **Bounded.** At most `--budget` GETs (default 80) at `--rate` requests per second (default
  1); it stops on the first rate-limit response or authentication failure.
- **Redacted output.** Booleans, numbers, timestamps and short values under an explicit enum
  allowlist survive; every other string becomes its length; keys on the never-export list keep
  only their type. No token, identifier, name, address, MAC, IP or SSID reaches the report.

Options: `--session-file` (`EERO_EXPORTER_PROBE_SESSION_FILE`), `--out`, `--budget`,
`--rate`, `--only`, `--dry-run`, `--keep-copy`, `--log-level`.

## Exit code summary

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Invalid or expired session, API error, refused start-up, failed collection |
| `2` | `validate`: no session file. `serve`: terminal authentication failure with `--auth-failure-exit` |
| `130` | Interrupted (Ctrl+C) |
