# 🔒 Security

## Overview

| Aspect | Implementation |
|--------|----------------|
| **Token Storage** | Restricted file permissions (0600) |
| **Default Location** | `~/.config/eero-exporter/session.json` |
| **Auth Library** | Uses [eero-api](https://github.com/fulviofreitas/eero-api) for secure auth |
| **Logging** | Tokens are never logged in plain text |
| **API Connection** | HTTPS only (TLS 1.2+) |

## Session File

The session file contains your authentication token. It is stored with restricted permissions:

```bash
# Check permissions
ls -la ~/.config/eero-exporter/session.json
# Should show: -rw------- (600)
```

## Best Practices

1. **Never share your session file** — It grants full access to your eero account
2. **Use read-only mounts in Docker** — Always mount with `:ro` flag
3. **Rotate credentials periodically** — Run `eero-exporter logout` and re-authenticate
4. **Monitor access logs** — Check the eero app for unusual activity

## Docker Security

When running in Docker, mount the session file as read-only:

```bash
docker run -d \
  -v ./session.json:/home/eero/.config/eero-exporter/session.json:ro \
  ghcr.io/fulviofreitas/eero-prometheus-exporter:latest
```

## Network Security

- The exporter only makes outbound HTTPS connections to eero's API
- No inbound connections are required except for Prometheus scraping
- Consider running behind a reverse proxy for additional security
