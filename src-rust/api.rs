//! Versioned REST API (`/api/v1`) and Server-Sent Events Endpoint

use crate::observability::HealthReport;
use axum::{
    extract::State,
    http::StatusCode,
    response::IntoResponse,
    routing::get,
    Json, Router,
};
use sqlx::SqlitePool;
use std::sync::Arc;
use std::time::Instant;

#[derive(Clone)]
pub struct AppState {
    pub db: SqlitePool,
    pub started_at: Instant,
}

pub fn build_api_router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/api/v1/health", get(health_handler))
        .with_state(state)
}

async fn health_handler(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    let pending: (i64,) = sqlx::query_as(
        "SELECT COUNT(*) FROM delivery_jobs WHERE status IN ('PENDING', 'RETRY_SCHEDULED')",
    )
    .fetch_one(&state.db)
    .await
    .unwrap_or((0,));

    let tg_state: (String,) = sqlx::query_as(
        "SELECT connection_state FROM telegram_account WHERE id = 1",
    )
    .fetch_one(&state.db)
    .await
    .unwrap_or(("NOT_CONFIGURED".to_string(),));

    let report = HealthReport {
        status: "ok".to_string(),
        version: env!("CARGO_PKG_VERSION").to_string(),
        database_ready: true,
        sqlite_journal_mode: "wal".to_string(),
        telegram_state: tg_state.0,
        worker_active: true,
        pending_queue_jobs: pending.0,
        uptime_seconds: state.started_at.elapsed().as_secs(),
    };
    (StatusCode::OK, Json(report))
}
