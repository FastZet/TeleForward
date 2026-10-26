//! Source Edit and Delete Synchronization Subsystem
//!
//! Propagates source edits (for Copy mode destinations) and deletions (for tracked
//! destination copies/forwards) while refusing to touch untracked messages.

use crate::rules::DeliveryMode;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrackedMessageMapping {
    pub source_peer_id: String,
    pub source_message_id: i64,
    pub rule_id: String,
    pub destination_peer_id: String,
    pub destination_message_id: i64,
    pub delivery_mode: DeliveryMode,
    pub sync_edits_enabled: bool,
    pub sync_deletes_enabled: bool,
    pub is_deleted_on_dest: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum EditSyncEligibility {
    Eligible,
    UnsupportedForwardMode,
    DisabledByPolicy,
    AlreadyDeleted,
}

pub fn check_edit_sync_eligibility(
    mapping: &TrackedMessageMapping,
    global_sync_edits: bool,
) -> EditSyncEligibility {
    if mapping.is_deleted_on_dest {
        return EditSyncEligibility::AlreadyDeleted;
    }
    if !global_sync_edits || !mapping.sync_edits_enabled {
        return EditSyncEligibility::DisabledByPolicy;
    }
    // Telegram does not allow editing native forwarded messages on a destination chat
    if mapping.delivery_mode == DeliveryMode::Forward {
        return EditSyncEligibility::UnsupportedForwardMode;
    }
    EditSyncEligibility::Eligible
}

pub fn check_delete_sync_eligibility(
    mapping: &TrackedMessageMapping,
    global_sync_deletes: bool,
) -> bool {
    !mapping.is_deleted_on_dest && global_sync_deletes && mapping.sync_deletes_enabled
}
