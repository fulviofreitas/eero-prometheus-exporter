# 💻 CLI Reference

## Commands

| Command | What It Does |
|---------|--------------|
| `eero-exporter login <email-or-phone>` | 🔑 Link your eero account |
| `eero-exporter logout` | 🚪 Clear saved session |
| `eero-exporter status` | 📡 Check auth status & list networks |
| `eero-exporter validate` | ✅ Validate session credentials |
| `eero-exporter test` | 🧪 Test metrics collection |
| `eero-exporter serve` | 🚀 Start the Prometheus server |
| `eero-exporter version` | ℹ️ Show version info |

## Validate Command

Test your credentials before deploying:

```bash
# Full output
eero-exporter validate

# Quiet mode (for scripts/CI)
eero-exporter validate -q && echo "Valid" || echo "Invalid"
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Session is valid |
| `1` | Session is invalid or expired |
| `2` | No session file found |

## Server Options

```bash
eero-exporter serve [OPTIONS]
```

### Available Options

| Option | Description | Default |
|--------|-------------|---------|
| `-p, --port INTEGER` | Port to listen on | `10052` |
| `-h, --host TEXT` | Host to bind to | `0.0.0.0` |
| `-i, --interval INTEGER` | Collection interval in seconds | `60` |
| `-s, --session-file PATH` | Custom session file path | `~/.config/eero-exporter/session.json` |
| `-c, --config PATH` | Custom config file path | `~/.config/eero-exporter/config.yml` |
| `-l, --log-level TEXT` | Log level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `--include-devices/--no-devices` | Include device metrics | Enabled |
| `--include-profiles/--no-profiles` | Include profile metrics | Enabled |

### Examples

```bash
# Start with default settings
eero-exporter serve

# Custom port and interval
eero-exporter serve --port 9200 --interval 120

# Debug logging
eero-exporter serve --log-level DEBUG

# Disable device metrics for faster collection
eero-exporter serve --no-devices
```
