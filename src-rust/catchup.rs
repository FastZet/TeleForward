//! Missed-Message Catch-Up Subsystem (Cursor-Based Gap Detection & Recovery)

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceGapAssessment {
    pub source_peer_id: String,
    pub source_title: String,
    pub last_processed_message_id: i64,
    pub latest_available_message_id: i64,
    pub detected_gap: i64,
    pub recovery_eligible: bool,
}

pub fn compute_source_gap(
    source_peer_id: &str,
    source_title: &str,
    last_processed_id: i64,
    latest_available_id: i64,
) -> SourceGapAssessment {
    let gap = if last_processed_id > 0 && latest_available_id > last_processed_id {
        latest_available_id - last_processed_id
    } else {
        0
    };
    SourceGapAssessment {
        source_peer_id: source_peer_id.to_string(),
        source_title: source_title.to_string(),
        last_processed_message_id: last_processed_id,
        latest_available_message_id: latest_available_id,
        detected_gap: gap,
        recovery_eligible: gap > 0,
    }
}
