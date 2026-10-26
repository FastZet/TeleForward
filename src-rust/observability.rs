//! Observability: Redacted Event Logging, Persistent Statistics, and Health Diagnostics

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthReport {
    pub status: String,
    pub version: String,
    pub database_ready: bool,
    pub sqlite_journal_mode: String,
    pub telegram_state: String,
    pub worker_active: bool,
    pub pending_queue_jobs: i64,
    pub uptime_seconds: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AggregateStatsSummary {
    pub successful_deliveries: i64,
    pub skipped_messages: i64,
    pub failed_deliveries: i64,
    pub pending_queue_size: i64,
    pub retry_count: i64,
    pub avg_latency_ms: f64,
}
