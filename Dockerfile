# ============================================================================
# Stage 1: Build Frontend Static Assets (React + TypeScript + Vite)
# ============================================================================
FROM node:22-bookworm-slim AS frontend-builder
WORKDIR /build/frontend
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
COPY public ./public
RUN npm run build

# ============================================================================
# Stage 2: Build Rust Core Engine (Axum + Tokio + SQLx + Grammers MTProto)
# ============================================================================
FROM rust:1.83-slim-bookworm AS rust-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev libsqlite3-dev ca-certificates && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /build/backend
COPY Cargo.toml ./
COPY migrations ./migrations
COPY src-rust ./src-rust
RUN cargo build --release --locked || cargo build --release

# ============================================================================
# Stage 3: Minimal Non-Root Production Runtime Image (x86_64 & ARM64 compatible)
# ============================================================================
FROM debian:bookworm-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libssl3 libsqlite3-0 sqlite3 curl tini && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g 10001 teleroute && \
    useradd -u 10001 -g teleroute -m -d /app -s /usr/sbin/nologin teleroute && \
    mkdir -p /data /app/dist /app/migrations /app/recipes && \
    chown -R teleroute:teleroute /data /app

WORKDIR /app
COPY --from=rust-builder --chown=teleroute:teleroute /build/backend/target/release/teleroute /app/teleroute
COPY --from=frontend-builder --chown=teleroute:teleroute /build/frontend/dist /app/dist
COPY --chown=teleroute:teleroute migrations /app/migrations
COPY --chown=teleroute:teleroute recipes /app/recipes

USER 10001:10001
ENV PORT=3000 \
    HOST=0.0.0.0 \
    DATABASE_URL=sqlite:///data/teleroute.db?mode=rwc \
    SQLITE_PATH=/data/teleroute.db \
    STATIC_DIR=/app/dist \
    RUST_LOG=info,teleroute=info

EXPOSE 3000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3000/api/v1/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/teleroute"]
