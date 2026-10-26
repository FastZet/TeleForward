//! Durable Delivery Queue State Machine, Pacing, Flood-Wait Deferral, and Retry Backoff

use crate::telegram::TelegramDeliveryError;
use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum JobStatus {
    Pending,
    Processing,
    Completed,
    Skipped,
    Failed,
    RetryScheduled,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RetryTransition {
    pub next_status: JobStatus,
    pub next_eligible_at: DateTime<Utc>,
    pub error_category: String,
    pub diagnostic: String,
}

/// Computes bounded exponential backoff with deterministic jitter or FloodWait deferral.
/// Permanent errors (invalid destination, missing permissions, unsupported media) fail immediately.
pub fn compute_retry_transition(
    err: &TelegramDeliveryError,
    attempt_count: u32,
    max_retries: u32,
    now: DateTime<Utc>,
) -> RetryTransition {
    match err {
        TelegramDeliveryError::FloodWait { seconds, message } => {
            if attempt_count > max_retries {
                return RetryTransition {
                    next_status: JobStatus::Failed,
                    next_eligible_at: now,
                    error_category: "FLOOD_WAIT_EXHAUSTED".to_string(),
                    diagnostic: format!("Exceeded max retries ({}) after {}", max_retries, message),
                };
            }
            // Respect Telegram's exact FLOOD_WAIT interval + 2s safety buffer
            let wait_secs = (*seconds as i64).saturating_add(2);
            RetryTransition {
                next_status: JobStatus::RetryScheduled,
                next_eligible_at: now + Duration::seconds(wait_secs),
                error_category: "FLOOD_WAIT".to_string(),
                diagnostic: format!(
                    "Deferred by {}s due to Telegram FLOOD_WAIT (attempt {}/{})",
                    wait_secs, attempt_count, max_retries
                ),
            }
        }
        TelegramDeliveryError::TransientNetwork { message } => {
            if attempt_count > max_retries {
                return RetryTransition {
                    next_status: JobStatus::Failed,
                    next_eligible_at: now,
                    error_category: "TRANSIENT_EXHAUSTED".to_string(),
                    diagnostic: format!("Retries exhausted ({}): {}", max_retries, message),
                };
            }
            // Bounded exponential backoff: 2^attempt * 3s, capped at 300s
            let exp = 2_i64.saturating_pow(attempt_count.min(6));
            let backoff_secs = (exp * 3).min(300);
            RetryTransition {
                next_status: JobStatus::RetryScheduled,
                next_eligible_at: now + Duration::seconds(backoff_secs),
                error_category: "TRANSIENT_NETWORK".to_string(),
                diagnostic: format!(
                    "Scheduled retry {}/{} in {}s: {}",
                    attempt_count, max_retries, backoff_secs, message
                ),
            }
        }
        TelegramDeliveryError::SessionExpired { message } => RetryTransition {
            next_status: JobStatus::Failed,
            next_eligible_at: now,
            error_category: "SESSION_EXPIRED".to_string(),
            diagnostic: format!("Non-retryable session error: {}", message),
        },
        TelegramDeliveryError::PermanentPermission { message } => RetryTransition {
            next_status: JobStatus::Failed,
            next_eligible_at: now,
            error_category: "PERMISSION_DENIED".to_string(),
            diagnostic: format!("Permanent permission error (not retrying): {}", message),
        },
        TelegramDeliveryError::InvalidDestination { message } => RetryTransition {
            next_status: JobStatus::Failed,
            next_eligible_at: now,
            error_category: "INVALID_DESTINATION".to_string(),
            diagnostic: format!("Permanent invalid destination (not retrying): {}", message),
        },
        TelegramDeliveryError::UnsupportedMedia { message } => RetryTransition {
            next_status: JobStatus::Failed,
            next_eligible_at: now,
            error_category: "UNSUPPORTED_MEDIA".to_string(),
            diagnostic: format!("Unsupported media operation (not retrying): {}", message),
        },
    }
}
