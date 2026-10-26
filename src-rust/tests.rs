//! Comprehensive Unit & Integration Tests for TeleRoute MTProto Core

use crate::classifier::{classify_media, evaluate_category_filter, CategoryMatchMode, MediaCategory};
use crate::filters::{
    check_file_filters, check_keyword_and_regex_filters, check_message_type, check_sender_filter,
    CandidateMessage, FilterConfig, KeywordSearchTarget, MatchMode, MessageMediaType,
    MessageTypeFilter, MissingFileMetadataPolicy, MissingSenderPolicy, SenderFilterMode,
};
use crate::queue::{compute_retry_transition, JobStatus};
use crate::router::{route_candidate_message, DeduplicationScope};
use crate::rules::{DeliveryMode, Rule};
use crate::scheduler::{is_within_schedule_window, ScheduleBehavior, ScheduleConfig};
use crate::security::{decrypt_session_bytes, encrypt_session_bytes, redact_diagnostic_message};
use crate::telegram::TelegramDeliveryError;
use crate::transform::{apply_caption_transformations, CaptionTransformConfig, ReplaceStep};
use chrono::{TimeZone, Utc};
use std::collections::HashSet;

#[test]
fn test_media_classifier_movies_tv_combined_and_split() {
    // Standalone Movie
    let m1 = classify_media(Some("Inception.2010.1080p.BluRay.x264.mkv"), None);
    assert_eq!(m1.categories, vec![MediaCategory::Movie]);

    // Standard TV Episode
    let tv1 = classify_media(Some("Severance.S01E05.2160p.WEB-DL.HEVC.mkv"), None);
    assert_eq!(tv1.categories, vec![MediaCategory::TvShow]);

    // Combined Season Pack
    let comb = classify_media(Some("The.Wire.S01.COMPLETE.1080p.BluRay.x265"), None);
    assert!(comb.categories.contains(&MediaCategory::Combined));
    assert!(comb.categories.contains(&MediaCategory::TvShow));

    // Combined + Split Archive
    let comb_split = classify_media(
        Some("Succession.S04E01-E10.2160p.BluRay.Remux.mkv.001"),
        None,
    );
    assert!(comb_split.categories.contains(&MediaCategory::TvShow));
    assert!(comb_split.categories.contains(&MediaCategory::Combined));
    assert!(comb_split.categories.contains(&MediaCategory::Split));

    // ALL vs ANY category evaluation
    assert!(evaluate_category_filter(
        &comb_split.categories,
        &[MediaCategory::TvShow, MediaCategory::Split],
        CategoryMatchMode::All
    ));
    assert!(!evaluate_category_filter(
        &tv1.categories,
        &[MediaCategory::TvShow, MediaCategory::Split],
        CategoryMatchMode::All
    ));
}

#[test]
fn test_caption_cleanup_and_ordered_replacements() {
    let cfg = CaptionTransformConfig {
        clean_filename_mode: false,
        remove_links: true,
        remove_usernames: true,
        remove_hashtags: true,
        remove_emojis: true,
        remove_decorative_symbols: true,
        strip_text_after_extension: true,
        preserve_multipart_suffix: true,
        custom_header: "[Archive]".to_string(),
        custom_footer: "Verified".to_string(),
        replacements: vec![
            ReplaceStep {
                step_order: 1,
                find_pattern: "x264".to_string(),
                replace_with: "H.264".to_string(),
                is_regex: false,
                case_sensitive: false,
            },
            ReplaceStep {
                step_order: 2,
                find_pattern: r"\[TG\]".to_string(),
                replace_with: "".to_string(),
                is_regex: true,
                case_sensitive: false,
            },
        ],
    };

    let raw = "🔥 [TG] Dune.Part.Two.2024.2160p.x264.mkv.001 Join @movie_channel https://t.me/spam #uhdPromo trailing promo";
    let res = apply_caption_transformations(Some(raw), Some("Dune.Part.Two.2024.2160p.x264.mkv.001"), true, &cfg).unwrap();
    assert_eq!(
        res,
        "[Archive]\nDune.Part.Two.2024.2160p.H.264.mkv.001\nVerified"
    );
}

#[test]
fn test_overnight_schedule_crossing_midnight() {
    let cfg = ScheduleConfig {
        enabled: true,
        start_time: "23:00".to_string(),
        end_time: "06:00".to_string(),
        days: vec![1], // Monday night -> Tuesday morning
        timezone: "UTC".to_string(),
        behavior: ScheduleBehavior::DeferUntilWindow,
    };

    // Monday 23:30 UTC -> inside window
    let mon_late = Utc.with_ymd_and_hms(2026, 10, 26, 23, 30, 0).unwrap();
    assert!(is_within_schedule_window(&cfg, mon_late).unwrap());

    // Tuesday 04:15 UTC -> inside Monday's overnight window
    let tue_early = Utc.with_ymd_and_hms(2026, 10, 27, 4, 15, 0).unwrap();
    assert!(is_within_schedule_window(&cfg, tue_early).unwrap());

    // Tuesday 14:00 UTC -> outside window
    let tue_afternoon = Utc.with_ymd_and_hms(2026, 10, 27, 14, 0, 0).unwrap();
    assert!(!is_within_schedule_window(&cfg, tue_afternoon).unwrap());
}

#[test]
fn test_priority_exclusive_stop_and_per_destination_dedup() {
    let base_filters = FilterConfig {
        message_type_filter: MessageTypeFilter::All,
        sender_filter_mode: SenderFilterMode::Any,
        sender_user_ids: vec![],
        missing_sender_policy: MissingSenderPolicy::AllowInChannels,
        required_keywords: vec![],
        required_keywords_match_mode: MatchMode::Any,
        excluded_keywords: vec![],
        regex_pattern: String::new(),
        regex_exclude_pattern: String::new(),
        keyword_search_target: KeywordSearchTarget::TextAndCaption,
        case_sensitive: false,
        whole_word: false,
        min_file_size_bytes: None,
        max_file_size_bytes: None,
        filename_contains: String::new(),
        filename_ends_with: String::new(),
        filename_regex: String::new(),
        accepted_extensions: vec![],
        excluded_extensions: vec![],
        missing_file_metadata_policy: MissingFileMetadataPolicy::PassIfNonFile,
    };

    let msg = CandidateMessage {
        message_id: 501,
        source_peer_id: "-100111".to_string(),
        chat_type: "CHANNEL".to_string(),
        media_type: MessageMediaType::Video,
        is_album: false,
        is_first_in_album: true,
        text: None,
        caption: Some("Interstellar.2014.2160p.BluRay.mkv".to_string()),
        filename: Some("Interstellar.2014.2160p.BluRay.mkv".to_string()),
        file_size_bytes: Some(1_500_000_000),
        sender_user_id: None,
        is_sender_admin: false,
        is_anonymous_admin: true,
        is_sender_verified: false,
        timestamp_utc: "2026-10-26T10:00:00Z".to_string(),
    };

    let rule_high_non_matching = Rule {
        id: "r-90".to_string(),
        name: "High Priority Non-Matching TV Rule".to_string(),
        description: String::new(),
        enabled: true,
        source_peer_id: "-100111".to_string(),
        destination_peer_ids: vec!["-100999".to_string()],
        priority: 90,
        secondary_order: 1,
        exclusive_stop: true, // Should NOT stop lower rules because it does not match!
        delivery_mode: DeliveryMode::Copy,
        delay_seconds: 0,
        max_retries: 3,
        sync_edits: true,
        sync_deletes: true,
        filters: base_filters.clone(),
        categories_enabled: true,
        selected_categories: vec![MediaCategory::TvShow],
        category_match_mode: CategoryMatchMode::All,
        schedule: ScheduleConfig {
            enabled: false,
            start_time: "00:00".to_string(),
            end_time: "23:59".to_string(),
            days: vec![0, 1, 2, 3, 4, 5, 6],
            timezone: "UTC".to_string(),
            behavior: ScheduleBehavior::DeferUntilWindow,
        },
        caption_transform: CaptionTransformConfig {
            clean_filename_mode: false,
            remove_links: false,
            remove_usernames: false,
            remove_hashtags: false,
            remove_emojis: false,
            remove_decorative_symbols: false,
            strip_text_after_extension: false,
            preserve_multipart_suffix: true,
            custom_header: String::new(),
            custom_footer: String::new(),
            replacements: vec![],
        },
    };

    let mut rule_mid_matching = rule_high_non_matching.clone();
    rule_mid_matching.id = "r-80".to_string();
    rule_mid_matching.name = "Movie Rule".to_string();
    rule_mid_matching.priority = 80;
    rule_mid_matching.selected_categories = vec![MediaCategory::Movie];
    rule_mid_matching.exclusive_stop = true;

    let mut rule_low = rule_mid_matching.clone();
    rule_low.id = "r-50".to_string();
    rule_low.priority = 50;
    rule_low.exclusive_stop = false;

    let decision = route_candidate_message(
        &[rule_low, rule_high_non_matching, rule_mid_matching],
        &msg,
        Utc::now(),
        true,
        DeduplicationScope::PerDestination,
        &HashSet::new(),
    );

    assert_eq!(decision.jobs_to_enqueue.len(), 1);
    assert_eq!(decision.jobs_to_enqueue[0].rule_id, "r-80");
    assert_eq!(
        decision.stopped_by_exclusive_rule_id.as_deref(),
        Some("r-80")
    );
}

#[test]
fn test_aes_session_encryption_and_flood_wait_retry() {
    let key = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    let raw_session = b"mtproto-dc2-auth-key-material";
    let enc = encrypt_session_bytes(raw_session, key).unwrap();
    let dec = decrypt_session_bytes(&enc, key).unwrap();
    assert_eq!(dec, raw_session);

    let redacted = redact_diagnostic_message("Failed login api_hash=secret123 phone_code=88412");
    assert!(!redacted.contains("secret123"));
    assert!(!redacted.contains("88412"));

    let now = Utc::now();
    let flood = TelegramDeliveryError::FloodWait {
        seconds: 45,
        message: "FLOOD_WAIT_45".to_string(),
    };
    let tr = compute_retry_transition(&flood, 1, 3, now);
    assert_eq!(tr.next_status, JobStatus::RetryScheduled);
    assert_eq!((tr.next_eligible_at - now).num_seconds(), 47);

    let perm = TelegramDeliveryError::PermanentPermission {
        message: "CHAT_WRITE_FORBIDDEN".to_string(),
    };
    let tr_perm = compute_retry_transition(&perm, 1, 5, now);
    assert_eq!(tr_perm.next_status, JobStatus::Failed);
}
