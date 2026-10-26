//! Historical Backfill Engine (Bounded Batching, Dry-Run Preview, Resumable Cursor)

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum BackfillMode {
    AllAccessible,
    LastN,
    UnprocessedOnly,
    MessageIdRange,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum BackfillDirection {
    OldestFirst,
    NewestFirst,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum BackfillStatus {
    Pending,
    Running,
    Paused,
    Completed,
    Stopped,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackfillPreviewReport {
    pub source_peer_id: String,
    pub mode: BackfillMode,
    pub selected_range_label: String,
    pub examined_count: usize,
    pub matching_count: usize,
    pub expected_skipped_count: usize,
    pub destination_breakdown: BTreeMap<String, usize>,
    pub delivery_modes: Vec<String>,
    pub configuration_warnings: Vec<String>,
}

pub fn validate_backfill_parameters(
    mode: BackfillMode,
    last_n: Option<u32>,
    start_id: Option<i64>,
    end_id: Option<i64>,
) -> Result<(), String> {
    if mode == BackfillMode::LastN {
        let n = last_n.ok_or_else(|| "Last N mode requires a count between 50 and 5,000".to_string())?;
        if !(50..=5_000).contains(&n) {
            return Err("Last N count must be between 50 and 5,000".to_string());
        }
    }
    if mode == BackfillMode::MessageIdRange {
        if let (Some(s), Some(e)) = (start_id, end_id) {
            if s <= 0 || e <= 0 || s > e {
                return Err("Message ID range requires positive IDs with start_id <= end_id".to_string());
            }
        }
    }
    Ok(())
}
