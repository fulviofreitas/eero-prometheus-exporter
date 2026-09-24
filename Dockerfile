# syntax=docker/dockerfile:1.27
# Eero Prometheus Exporter
# Multi-stage build for minimal image size
# Uses uv.lock to ensure reproducible builds with pinned versions

FROM python:3.14-slim AS builder

WORKDIR /app

# Install build dependencies with cache mount
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install build==1.6.1 uv==0.12.18

# Copy only files needed for build
COPY pyproject.toml README.md uv.lock ./
COPY src/ ./src/

# Build wheel, then export frozen requirements from uv.lock
RUN python -m build --wheel && \
    uv export --frozen --no-dev --no-emit-project -o requirements.txt

# Final stage
FROM python:3.14-slim

# OCI Image Labels - GitHub Container Registry supported labels
# https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#labelling-container-images
LABEL org.opencontainers.image.source="https://github.com/fulviofreitas/eero-prometheus-exporter" \
      org.opencontainers.image.description="Export Prometheus metrics from your eero mesh WiFi network. Monitor connected devices, network health, speed tests, and more." \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Create non-root user
RUN groupadd -r eero && useradd -r -g eero eero

# Install uv (fast Python package installer)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

# Copy frozen requirements and wheel from builder
COPY --from=builder /app/requirements.txt ./
COPY --from=builder /app/dist/*.whl ./

# Install dependencies from frozen lock, then the application wheel
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt && \
    uv pip install --system --no-deps ./*.whl && \
    rm ./*.whl requirements.txt

# Create config directory with proper permissions
RUN mkdir -p /home/eero/.config/eero-exporter && \
    chown -R eero:eero /home/eero

# Switch to non-root user
USER eero

# Expose metrics port
EXPOSE 10052

# Health check - use /ready for container liveness (always 200 if server running)
# Use /health endpoint for detailed status monitoring
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:10052/ready')" || exit 1

# Default command
ENTRYPOINT ["eero-exporter"]
CMD ["serve", "--host", "0.0.0.0", "--port", "10052"]
