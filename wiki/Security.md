# 🔒 Security

## Summary

| Aspect | Implementation |
|---|---|
| API access | Read-only by default. Every request the collector makes is a GET; the only POSTs the exporter ever issues are `login`/`verify` (CLI or the opt-in `/auth` page) and, with `--wan-burst` opted in, one burst-reporter request per network per cycle (see [Non-read opt-ins](#non-read-opt-ins)). |
| Transport | HTTPS only, enforced by the eero-api client |
| Authentication | Session token sent as the `X-User-Token` header (plus the legacy cookie while `--send-legacy-cookie` is on) |
| Credential storage | `~/.config/eero-exporter/session.json`, mode `0600`, written atomically |
| Logging | Tokens, identifiers, verification codes and API envelopes are never logged at any level |
| Metrics endpoint | Unauthenticated by design; keep it on a trusted network |

## Credential record

eero-api 8.x stores the session as a small JSON record:

```json
{"session_id": "<token>", "schema_version": 2}
```

- Written with `0600` permissions via a temporary file in the same directory followed by an
  atomic rename, so a crash never leaves a half-written record and the directory must be
  writable.
- A 3.x (schema 1) file is migrated in place on first use; the exporter itself never parses
  the token, it only checks that the file exists.
- When the API answers a terminal 401 (a token the client could not refresh), the client
  **deletes the file**. `serve` keeps recording the failure (`eero_up 0`,
  `eero_exporter_scrape_errors_total{error_type="auth"}`), exits with status 2 if
  `--auth-failure-exit` is set, and refuses to start on the next restart until you log in
  again. `logout` deletes the file locally without contacting the API.
- `session-info` is the supported way to inspect the file: it prints mode, owner, schema
  version and *whether* a token is present, never the value.

## What the exporter never exports

Regardless of tier or flag, these values never reach `/metrics`, the logs or the probe report:

- Wi-Fi, guest, subnet and backup-access-point passwords or PSKs
- The DDNS subdomain
- Public IP (unless you opt in with `--expose-public-ip`), gateway/WAN IPs, DHCP ranges,
  IPv6 prefixes and address lists, DNS resolver addresses
- Member and account names, e-mail addresses, phone numbers
- BSSIDs, LLDP chassis/port identifiers, neighbouring SSIDs from network scans
- Free-text fields (notification bodies, failure reasons, support contacts)
- Any `url`, `serial`, `uuid` or `etag`

The registry test rejects a metric that declares a label named `ip`, `public_ip`, `password`,
`ssid`, `email`, `phone`, `bssid`, `subdomain`, `serial`, `url` or `mac_address`. Device
metrics do carry the device MAC (`mac`) and a display name as labels, as in 3.x; disable the
device family with `--no-devices` if that is not acceptable in your environment.

## Read-only guarantee and how it is tested

With the defaults the exporter cannot change anything on your network. Three layers enforce
that:

1. **Adapter surface.** `eero_adapter.py` wraps read methods of the SDK. The unit test
   `tests/test_sdk_surface.py` imports the real `eero.EeroClient` and checks every method the
   adapter calls exists with a compatible signature and is on the read allow-list
   (`get_`/`list_`/`has_`, plus `login`/`verify`) in `tests/readonly_names.py`. The single
   sanctioned exception, `create_burst_reporter`, must appear exactly once, inside
   `request_wan_burst`.
2. **Write guard.** `tests/test_collector_readonly.py` runs a full collection cycle with every
   tier enabled while the SDK's `post`/`put`/`delete` methods are patched to raise. The same
   guard is installed by `eero-exporter probe` for real runs, which never includes a burst.
3. **Classification by class.** API failures are mapped by exception class and `error_code`,
   never by matching message text, and the raw response envelope (which can contain account
   data) is never copied into an exception message or a log line.

## Non-read opt-ins

`--wan-burst` (`EERO_EXPORTER_WAN_BURST=true`, `wan_burst: true` in YAML; **off by default**) is
the only setting that makes the collector issue a non-authentication POST. It asks the eero
cloud for a "burst reporter": the cloud then refreshes each device's live `usage` for a few
seconds, which the exporter reads back about 12 s later and sums into
`eero_network_wan_download_mbps` / `eero_network_wan_upload_mbps`. The request has an empty
body, runs no speed test and changes no setting. It was verified live on 2026-10-20 against
eero-api 8.4.1 (usage refreshed within 12 s on 103 of 116 connected devices, no node rebooted).

Safeguards built into the collector:

- at most one burst per network per collection cycle, and never within 60 s of the previous one
  (the API's own limit); the window is consumed even when the request fails, so nothing is ever
  retried inside it;
- bridge-mode networks are skipped;
- after three consecutive definitive failures (permission, feature-unavailable, validation) the
  family disables itself for the rest of the process and `eero_exporter_wan_burst_enabled` drops
  to 0; transport and rate-limit errors do not trip it;
- when no fresh sample exists the gauges are absent, never 0, and
  `eero_network_wan_burst_sample_timestamp_seconds` dates the sample that is there.

Leave the flag off if a strictly GET-only exporter matters more to you than the two gauges.

## Web login page (`/auth`)

The page is **off by default**. When enabled with `serve --auth-ui --auth-ui-token <secret>`
it lets you run the identifier-then-code login from a browser and writes the same session
file the collector reads. Threat model and controls:

| Control | Detail |
|---|---|
| Opt-in | Every `/auth*` route is a 404 unless `--auth-ui` is set |
| Access token | Required on every POST, at least 16 characters, compared in constant time (`hmac.compare_digest`); `serve` refuses to start otherwise |
| Token handling | Provide it through `EERO_EXPORTER_AUTH_UI_TOKEN` or the YAML key `auth_ui_token`, not on the command line (argv is visible to local users); it is masked in config dumps and never logged |
| CSRF | A per-process CSRF token is embedded in the form and checked on every POST |
| No oracle | A wrong access token, a wrong CSRF token, a wrong verification code, a missing identifier or code, and a verify with no pending flow all return the identical 403 and all count as a failed attempt, so none can be used to probe the others |
| Rate limit | 5 failed attempts (token, CSRF, code or a malformed submission) per 15 minutes trip a 429 with `Retry-After`; a successful step resets the window |
| Malformed input | The token and CSRF fields are compared as bytes, so a non-ASCII or invalid byte is denied like any wrong value instead of raising inside the handler |
| Single pending flow | One login at a time, discarded after `--auth-ui-pending-ttl` seconds (default 600) or via the reset button |
| Response headers | `Content-Security-Policy: default-src 'none'`, `X-Frame-Options: DENY`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer` |
| Logging | Only "login started", "verify ok" and "verify failed (<class>)" -- never the identifier, code or tokens |
| Rendering | The page shows whether a session exists and its schema version; never the token or identifier |

**The token and the verification code travel in plain HTTP form bodies.** Terminate TLS in
front of the exporter (a reverse proxy) or restrict the port to a trusted network before
enabling the page, and disable it again once you have a session if you do not need it.

## Probe report redaction

`eero-exporter probe` writes a key tree, not values: booleans, numbers and timestamps are
kept, short strings survive only under an explicit enum-key allowlist, every other string is
replaced by its length, and never-export keys are reduced to their type. A unit test plants
every never-export key and secret-shaped value in a synthetic response and asserts none
survives serialisation. The probe runs on a `0600` copy of the session file in a private
temporary directory; the original is only read.

## Best practices

1. Never share the session file; it grants access to your eero account.
2. Mount the config **directory** read-write in containers (4.0.0 needs to rewrite the
   record). If you must mount the file read-only, migrate it first with `validate`.
3. Rotate by running `eero-exporter logout` and logging in again.
4. Keep `/metrics` on a private network or behind an authenticating reverse proxy; it lists
   your devices by name and MAC.
5. Leave `--expose-public-ip` off unless the endpoint is private.
