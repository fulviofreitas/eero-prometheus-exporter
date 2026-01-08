# Eero Prometheus Exporter
# Multi-stage build for minimal image size

FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir build

# Copy source code
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Build wheel
RUN python -m build --wheel

# Final stage
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Eero Prometheus Exporter"
LABEL org.opencontainers.image.description="Prometheus metrics exporter for eero mesh WiFi networks"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /app

# Create non-root user
RUN groupadd -r eero && useradd -r -g eero eero

# Install git (required for pip to install eero-client from GitHub)
# Then install the wheel and clean up
COPY --from=builder /app/dist/*.whl ./
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    pip install --no-cache-dir *.whl && \
    rm *.whl && \
    apt-get purge -y git && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Create config directory with proper permissions
RUN mkdir -p /home/eero/.config/eero-exporter && \
    chown -R eero:eero /home/eero

# Switch to non-root user
USER eero

# Expose metrics port
EXPOSE 9118

# Health check - use /ready for container liveness (always 200 if server running)
# Use /health endpoint for detailed status monitoring
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9118/ready')" || exit 1

# Default command
ENTRYPOINT ["eero-exporter"]
CMD ["serve", "--host", "0.0.0.0", "--port", "9118"]



