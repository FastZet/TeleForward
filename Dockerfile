
# ============================================================
# TeleForward - Production Dockerfile
# ============================================================

# ------------------------------------------------------------
# Stage 1: Build frontend
# ------------------------------------------------------------
FROM node:24-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./

RUN npm ci

COPY frontend/ ./

RUN npm run build


# ------------------------------------------------------------
# Stage 2: Prepare Python dependencies
# ------------------------------------------------------------
FROM python:3.12-slim AS backend-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN python -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt ./

RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt


# ------------------------------------------------------------
# Stage 3: Production runtime
# ------------------------------------------------------------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="TeleForward" \
      org.opencontainers.image.description="Self-hosted Telegram automation and forwarding platform" \
      org.opencontainers.image.vendor="TeleForward"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TELEFORWARD_ENV=production \
    TELEFORWARD_HOST=0.0.0.0 \
    TELEFORWARD_PORT=8000 \
    TELEFORWARD_DATA_DIR=/app/data \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Create a dedicated non-root application user.
RUN groupadd --system --gid 10001 teleforward \
    && useradd --system \
       --uid 10001 \
       --gid teleforward \
       --home-dir /app \
       --no-create-home \
       --shell /usr/sbin/nologin \
       teleforward

# Install runtime system dependencies.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       libffi8 \
    && rm -rf /var/lib/apt/lists/*

# Copy the prepared Python environment.
COPY --from=backend-builder /opt/venv /opt/venv

# Copy backend application.
COPY --chown=teleforward:teleforward backend/ /app/backend/

# Copy compiled frontend into the backend static directory.
COPY --from=frontend-builder \
     --chown=teleforward:teleforward \
     /frontend/dist/ \
     /app/backend/app/static/

# Prepare persistent application storage.
RUN mkdir -p /app/data \
    && chown -R teleforward:teleforward /app/data /app/backend

WORKDIR /app/backend

# Run as an unprivileged user.
USER teleforward

EXPOSE 8000

# Container health check.
HEALTHCHECK --interval=30s \
            --timeout=10s \
            --start-period=40s \
            --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)" || exit 1

# Start FastAPI.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
