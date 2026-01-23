# 🔧 Troubleshooting

## Authentication Problems?

```bash
# Validate your credentials
eero-exporter validate

# Check your session status
eero-exporter status

# Start fresh
eero-exporter logout
eero-exporter login your-email@example.com
```

## No Metrics Showing Up?

```bash
# Test collection with verbose output
eero-exporter test

# Run server with debug logging
eero-exporter serve --log-level DEBUG
```

## Health Endpoint Returns Unhealthy?

Check the `/health` endpoint for details:

```bash
curl http://localhost:9118/health | jq
```

Common issues:

- `session_valid: false` — Re-authenticate with `eero-exporter login`
- `last_collection_success: false` — Check logs for API errors

## Docker Container Keeps Restarting?

The container uses `/ready` for health checks (always returns 200 if server is running).
If using a custom health check, use `/ready` instead of `/health`:

```yaml
healthcheck:
  test:
    [
      "CMD",
      "python",
      "-c",
      "import urllib.request; urllib.request.urlopen('http://localhost:9118/ready')",
    ]
```

## Getting Rate Limited?

The eero API may throttle excessive requests. The exporter defaults to 60-second intervals to play nice. If you're still hitting limits, try increasing the interval:

```bash
eero-exporter serve --interval 120
```

## Prometheus Not Scraping?

1. Check that the exporter is running: `curl http://localhost:9118/metrics`
2. Verify Prometheus configuration targets the correct host/port
3. Check Prometheus targets page for errors: `http://prometheus:9090/targets`

## Common Error Messages

| Error | Solution |
|-------|----------|
| `Session file not found` | Run `eero-exporter login your-email@example.com` |
| `Session expired` | Run `eero-exporter logout` then `eero-exporter login` |
| `Connection refused` | Check that the exporter is running and port is correct |
| `Permission denied` | Check file permissions on session.json (should be 600) |
| `Rate limited` | Increase collection interval with `--interval` |
