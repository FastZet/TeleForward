//! Rule Models, Priority Ordering, Exclusive-Stop Logic, and Dry-Run Testing

use crate::classifier::{classify_media, evaluate_category_filter, CategoryMatchMode, MediaCategory};
use crate::filters::{
    check_file_filters, check_keyword_and_regex_filters, check_message_type, check_sender_filter,
    CandidateMessage, FilterConfig, MessageMediaType,
};
use crate::scheduler::{is_within_schedule_window, ScheduleBehavior, ScheduleConfig};
use crate::transform::{apply_caption_transformations, CaptionTransformConfig};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum DeliveryMode {
    Forward,
    Copy,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Rule {
    pub id: String,
    pub name: String,
    pub description: String,
    pub enabled: bool,
    pub source_peer_id: String,
    pub destination_peer_ids: Vec<String>,
    pub priority: i32,
    pub secondary_order: i32,
    pub exclusive_stop: bool,
    pub delivery_mode: DeliveryMode,
    pub delay_seconds: u32,
    pub max_retries: u32,
    pub sync_edits: bool,
    pub sync_deletes: bool,
    pub filters: FilterConfig,
    pub categories_enabled: bool,
    pub selected_categories: Vec<MediaCategory>,
    pub category_match_mode: CategoryMatchMode,
    pub schedule: ScheduleConfig,
    pub caption_transform: CaptionTransformConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuleEvaluationReport {
    pub rule_id: String,
    pub rule_name: String,
    pub matched: bool,
    pub passed_conditions: Vec<String>,
    pub failed_conditions: Vec<String>,
    pub assigned_categories: Vec<MediaCategory>,
    pub target_destinations: Vec<String>,
    pub exclusive_stop_triggered: bool,
    pub deferred_by_schedule: bool,
    pub transformed_caption: Option<String>,
}

/// Sorts rules in descending priority order, with deterministic secondary ordering
/// (`secondary_order ASC`, then `id ASC`).
pub fn sort_rules_by_priority(rules: &mut [Rule]) {
    rules.sort_by(|a, b| {
        b.priority
            .cmp(&a.priority)
            .then_with(|| a.secondary_order.cmp(&b.secondary_order))
            .then_with(|| a.id.cmp(&b.id))
    });
}

pub fn evaluate_single_rule(
    rule: &Rule,
    msg: &CandidateMessage,
    eval_time_utc: DateTime<Utc>,
) -> RuleEvaluationReport {
    let mut passed = Vec::new();
    let mut failed = Vec::new();

    let classification = classify_media(msg.filename.as_deref(), msg.caption.as_deref());

    if !rule.enabled {
        failed.push("Rule is disabled".to_string());
        return RuleEvaluationReport {
            rule_id: rule.id.clone(),
            rule_name: rule.name.clone(),
            matched: false,
            passed_conditions: passed,
            failed_conditions: failed,
            assigned_categories: classification.categories,
            target_destinations: Vec::new(),
            exclusive_stop_triggered: false,
            deferred_by_schedule: false,
            transformed_caption: None,
        };
    }

    if rule.source_peer_id != msg.source_peer_id {
        failed.push(format!(
            "Source peer mismatch (expected {}, got {})",
            rule.source_peer_id, msg.source_peer_id
        ));
        return RuleEvaluationReport {
            rule_id: rule.id.clone(),
            rule_name: rule.name.clone(),
            matched: false,
            passed_conditions: passed,
            failed_conditions: failed,
            assigned_categories: classification.categories,
            target_destinations: Vec::new(),
            exclusive_stop_triggered: false,
            deferred_by_schedule: false,
            transformed_caption: None,
        };
    }
    passed.push("Source chat matched".to_string());

    // 1. Message type filter
    if !check_message_type(rule.filters.message_type_filter, msg.media_type) {
        failed.push(format!(
            "Message type {:?} rejected by filter {:?}",
            msg.media_type, rule.filters.message_type_filter
        ));
    } else {
        passed.push(format!("Message type {:?} accepted", msg.media_type));
    }

    // 2. Sender filter
    match check_sender_filter(&rule.filters, msg) {
        Ok(true) => passed.push("Sender filter passed".to_string()),
        Ok(false) => failed.push("Sender filter rejected sender".to_string()),
        Err(e) => failed.push(e),
    }

    // 3. Keyword & Regex filter
    match check_keyword_and_regex_filters(&rule.filters, msg) {
        Ok((ok, p, f)) => {
            passed.extend(p);
            if !ok {
                failed.extend(f);
            }
        }
        Err(e) => failed.push(e),
    }

    // 4. File filters
    match check_file_filters(&rule.filters, msg) {
        Ok((ok, p, f)) => {
            passed.extend(p);
            if !ok {
                failed.extend(f);
            }
        }
        Err(e) => failed.push(e),
    }

    // 5. Automatic media category filter
    if rule.categories_enabled && !rule.selected_categories.is_empty() {
        if evaluate_category_filter(
            &classification.categories,
            &rule.selected_categories,
            rule.category_match_mode,
        ) {
            passed.push(format!(
                "Category filter {:?} matched {:?}",
                rule.category_match_mode, classification.categories
            ));
        } else {
            failed.push(format!(
                "Category filter {:?} failed (required {:?}, detected {:?})",
                rule.category_match_mode, rule.selected_categories, classification.categories
            ));
        }
    }

    // 6. Schedule filter
    let mut deferred_by_schedule = false;
    if rule.schedule.enabled {
        match is_within_schedule_window(&rule.schedule, eval_time_utc) {
            Ok(true) => passed.push("Within active schedule window".to_string()),
            Ok(false) => {
                if rule.schedule.behavior == ScheduleBehavior::OnlyArrivingDuringWindow {
                    failed.push("Message arrived outside schedule window (mode: ONLY_ARRIVING_DURING_WINDOW)".to_string());
                } else {
                    deferred_by_schedule = true;
                    passed.push("Matched; delivery deferred until next schedule window".to_string());
                }
            }
            Err(e) => failed.push(e),
        }
    }

    let matched = failed.is_empty();
    let is_media = msg.media_type != MessageMediaType::Text;
    let base_text = if is_media {
        msg.caption.as_deref()
    } else {
        msg.text.as_deref()
    };

    let transformed_caption = if matched && rule.delivery_mode == DeliveryMode::Copy {
        apply_caption_transformations(
            base_text,
            msg.filename.as_deref(),
            is_media,
            &rule.caption_transform,
        )
        .ok()
    } else {
        base_text.map(|s| s.to_string())
    };

    RuleEvaluationReport {
        rule_id: rule.id.clone(),
        rule_name: rule.name.clone(),
        matched,
        passed_conditions: passed,
        failed_conditions: failed,
        assigned_categories: classification.categories,
        target_destinations: if matched {
            rule.destination_peer_ids.clone()
        } else {
            Vec::new()
        },
        exclusive_stop_triggered: matched && rule.exclusive_stop,
        deferred_by_schedule,
        transformed_caption,
    }
}
