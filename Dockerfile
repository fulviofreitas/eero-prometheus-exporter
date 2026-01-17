# syntax=docker/dockerfile:1.7
# Eero Prometheus Exporter
# Multi-stage build for minimal image size

FROM python:3.14-slim AS builder

WORKDIR /app

# Install build dependencies with cache mount
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install build

# Copy only files needed for build
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Build wheel
RUN python -m build --wheel

# Final stage
FROM python:3.14-slim

# OCI Image Labels - GitHub Container Registry supported labels
# https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#labelling-container-images
LABEL org.opencontainers.image.source="https://github.com/fulviofreitas/eero-prometheus-exporter" \
      org.opencontainers.image.description="Export Prometheus metrics from your eero mesh WiFi network. Monitor connected devices, network health, speed tests, and more." \
      org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /app

# Create non-root user
RUN groupadd -r eero && useradd -r -g eero eero

# Install dependencies with cache mounts for speed
# Git is required for pip to install eero-client from GitHub
COPY --from=builder /app/dist/*.whl ./
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=cache,target=/root/.cache/pip \
    apt-get update && \
    apt-get install -y --no-install-recommends git && \
    pip install *.whl && \
    rm *.whl && \
    apt-get purge -y git && \
    apt-get autoremove -y

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
