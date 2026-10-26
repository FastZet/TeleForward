//! Source-to-Destination Router with Priority Ordering, Exclusive-Stop, and Deduplication

use crate::filters::CandidateMessage;
use crate::rules::{evaluate_single_rule, sort_rules_by_priority, DeliveryMode, Rule};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum DeduplicationScope {
    PerRule,
    PerDestination,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlannedDeliveryJob {
    pub idempotency_key: String,
    pub dedup_key: String,
    pub dedup_scope: DeduplicationScope,
    pub source_peer_id: String,
    pub source_message_id: i64,
    pub rule_id: String,
    pub rule_name: String,
    pub destination_peer_id: String,
    pub delivery_mode: DeliveryMode,
    pub delay_seconds: u32,
    pub max_retries: u32,
    pub transformed_caption: Option<String>,
    pub deferred_by_schedule: bool,
    pub detected_categories: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoutingDecision {
    pub jobs_to_enqueue: Vec<PlannedDeliveryJob>,
    pub skipped_duplicates: Vec<String>,
    pub stopped_by_exclusive_rule_id: Option<String>,
}

pub fn build_deduplication_key(
    scope: DeduplicationScope,
    source_peer_id: &str,
    source_message_id: i64,
    rule_id: &str,
    destination_peer_id: &str,
) -> String {
    match scope {
        DeduplicationScope::PerRule => format!(
            "RULE:{}:{}:{}:{}",
            source_peer_id, source_message_id, rule_id, destination_peer_id
        ),
        DeduplicationScope::PerDestination => format!(
            "DEST:{}:{}:{}",
            source_peer_id, source_message_id, destination_peer_id
        ),
    }
}

pub fn route_candidate_message(
    rules: &[Rule],
    msg: &CandidateMessage,
    eval_time_utc: DateTime<Utc>,
    duplicate_protection_enabled: bool,
    global_scope: DeduplicationScope,
    existing_dedup_keys: &HashSet<String>,
) -> RoutingDecision {
    let mut ordered_rules = rules.to_vec();
    sort_rules_by_priority(&mut ordered_rules);

    let mut jobs_to_enqueue = Vec::new();
    let mut skipped_duplicates = Vec::new();
    let mut seen_in_batch = existing_dedup_keys.clone();
    let mut stopped_by_exclusive_rule_id = None;

    for rule in &ordered_rules {
        if !rule.enabled || rule.source_peer_id != msg.source_peer_id {
            continue;
        }

        let report = evaluate_single_rule(rule, msg, eval_time_utc);
        if !report.matched {
            // A rule that does not match MUST NEVER block lower-priority rules.
            continue;
        }

        for dest_peer_id in &rule.destination_peer_ids {
            let dedup_key = build_deduplication_key(
                global_scope,
                &msg.source_peer_id,
                msg.message_id,
                &rule.id,
                dest_peer_id,
            );
            let idempotency_key = format!(
                "IDEMP:{}:{}:{}:{}",
                msg.source_peer_id, msg.message_id, rule.id, dest_peer_id
            );

            if duplicate_protection_enabled && seen_in_batch.contains(&dedup_key) {
                skipped_duplicates.push(format!(
                    "Skipped duplicate delivery to {} via rule '{}' ({})",
                    dest_peer_id, rule.name, dedup_key
                ));
                continue;
            }

            seen_in_batch.insert(dedup_key.clone());
            jobs_to_enqueue.push(PlannedDeliveryJob {
                idempotency_key,
                dedup_key,
                dedup_scope: global_scope,
                source_peer_id: msg.source_peer_id.clone(),
                source_message_id: msg.message_id,
                rule_id: rule.id.clone(),
                rule_name: rule.name.clone(),
                destination_peer_id: dest_peer_id.clone(),
                delivery_mode: rule.delivery_mode,
                delay_seconds: rule.delay_seconds,
                max_retries: rule.max_retries,
                transformed_caption: report.transformed_caption.clone(),
                deferred_by_schedule: report.deferred_by_schedule,
                detected_categories: report
                    .assigned_categories
                    .iter()
                    .map(|c| c.as_str().to_string())
                    .collect(),
            });
        }

        if rule.exclusive_stop {
            stopped_by_exclusive_rule_id = Some(rule.id.clone());
            break;
        }
    }

    RoutingDecision {
        jobs_to_enqueue,
        skipped_duplicates,
        stopped_by_exclusive_rule_id,
    }
}
