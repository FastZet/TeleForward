//! Message-Type, Sender, Keyword, Safe Regex, and File Metadata Filters

use regex::RegexBuilder;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MessageMediaType {
    Text,
    Photo,
    Video,
    Document,
    Audio,
    Voice,
    Unsupported,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MessageTypeFilter {
    All,
    TextOnly,
    MediaOnly,
    Photo,
    Video,
    Document,
    Audio,
    Voice,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SenderFilterMode {
    Any,
    SpecificUserIds,
    AdminsOnly,
    AnonymousAdminsOnly,
    VerifiedUsersOnly,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MissingSenderPolicy {
    Reject,
    AllowInChannels,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum KeywordSearchTarget {
    TextOnly,
    CaptionOnly,
    FilenameOnly,
    TextAndCaption,
    TextCaptionAndFilename,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MatchMode {
    Any,
    All,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MissingFileMetadataPolicy {
    FailFilter,
    PassIfNonFile,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CandidateMessage {
    pub message_id: i64,
    pub source_peer_id: String,
    pub chat_type: String,
    pub media_type: MessageMediaType,
    pub is_album: bool,
    pub is_first_in_album: bool,
    pub text: Option<String>,
    pub caption: Option<String>,
    pub filename: Option<String>,
    pub file_size_bytes: Option<u64>,
    pub sender_user_id: Option<i64>,
    pub is_sender_admin: bool,
    pub is_anonymous_admin: bool,
    pub is_sender_verified: bool,
    pub timestamp_utc: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FilterConfig {
    pub message_type_filter: MessageTypeFilter,
    pub sender_filter_mode: SenderFilterMode,
    pub sender_user_ids: Vec<i64>,
    pub missing_sender_policy: MissingSenderPolicy,
    pub required_keywords: Vec<String>,
    pub required_keywords_match_mode: MatchMode,
    pub excluded_keywords: Vec<String>,
    pub regex_pattern: String,
    pub regex_exclude_pattern: String,
    pub keyword_search_target: KeywordSearchTarget,
    pub case_sensitive: bool,
    pub whole_word: bool,
    pub min_file_size_bytes: Option<u64>,
    pub max_file_size_bytes: Option<u64>,
    pub filename_contains: String,
    pub filename_ends_with: String,
    pub filename_regex: String,
    pub accepted_extensions: Vec<String>,
    pub excluded_extensions: Vec<String>,
    pub missing_file_metadata_policy: MissingFileMetadataPolicy,
}

pub const MAX_REGEX_PATTERN_LEN: usize = 512;
pub const MAX_SEARCHABLE_TEXT_LEN: usize = 16_384;

pub fn check_message_type(filter: MessageTypeFilter, actual: MessageMediaType) -> bool {
    if actual == MessageMediaType::Unsupported {
        return false;
    }
    match filter {
        MessageTypeFilter::All => true,
        MessageTypeFilter::TextOnly => actual == MessageMediaType::Text,
        MessageTypeFilter::MediaOnly => matches!(
            actual,
            MessageMediaType::Photo
                | MessageMediaType::Video
                | MessageMediaType::Document
                | MessageMediaType::Audio
                | MessageMediaType::Voice
        ),
        MessageTypeFilter::Photo => actual == MessageMediaType::Photo,
        MessageTypeFilter::Video => actual == MessageMediaType::Video,
        MessageTypeFilter::Document => actual == MessageMediaType::Document,
        MessageTypeFilter::Audio => actual == MessageMediaType::Audio,
        MessageTypeFilter::Voice => actual == MessageMediaType::Voice,
    }
}

pub fn check_sender_filter(cfg: &FilterConfig, msg: &CandidateMessage) -> Result<bool, String> {
    match cfg.sender_filter_mode {
        SenderFilterMode::Any => Ok(true),
        SenderFilterMode::SpecificUserIds => {
            if let Some(uid) = msg.sender_user_id {
                Ok(cfg.sender_user_ids.contains(&uid))
            } else if msg.chat_type.eq_ignore_ascii_case("CHANNEL")
                && cfg.missing_sender_policy == MissingSenderPolicy::AllowInChannels
            {
                Ok(true)
            } else {
                Ok(false)
            }
        }
        SenderFilterMode::AdminsOnly => Ok(msg.is_sender_admin),
        SenderFilterMode::AnonymousAdminsOnly => Ok(msg.is_anonymous_admin),
        SenderFilterMode::VerifiedUsersOnly => Ok(msg.is_sender_verified),
    }
}

pub fn extract_search_corpus(target: KeywordSearchTarget, msg: &CandidateMessage) -> String {
    let raw = match target {
        KeywordSearchTarget::TextOnly => msg.text.clone().unwrap_or_default(),
        KeywordSearchTarget::CaptionOnly => msg.caption.clone().unwrap_or_default(),
        KeywordSearchTarget::FilenameOnly => msg.filename.clone().unwrap_or_default(),
        KeywordSearchTarget::TextAndCaption => {
            format!(
                "{}\n{}",
                msg.text.as_deref().unwrap_or(""),
                msg.caption.as_deref().unwrap_or("")
            )
        }
        KeywordSearchTarget::TextCaptionAndFilename => {
            format!(
                "{}\n{}\n{}",
                msg.text.as_deref().unwrap_or(""),
                msg.caption.as_deref().unwrap_or(""),
                msg.filename.as_deref().unwrap_or("")
            )
        }
    };
    if raw.len() > MAX_SEARCHABLE_TEXT_LEN {
        raw[..MAX_SEARCHABLE_TEXT_LEN].to_string()
    } else {
        raw
    }
}

fn term_matches(corpus: &str, term: &str, case_sensitive: bool, whole_word: bool) -> bool {
    let trimmed = term.trim();
    if trimmed.is_empty() {
        return true;
    }
    if whole_word {
        let escaped = regex::escape(trimmed);
        let pat = format!(r"\b{}\b", escaped);
        if let Ok(re) = RegexBuilder::new(&pat)
            .case_insensitive(!case_sensitive)
            .size_limit(256 * 1024)
            .build()
        {
            return re.is_match(corpus);
        }
        false
    } else if case_sensitive {
        corpus.contains(trimmed)
    } else {
        corpus.to_lowercase().contains(&trimmed.to_lowercase())
    }
}

pub fn check_keyword_and_regex_filters(
    cfg: &FilterConfig,
    msg: &CandidateMessage,
) -> Result<(bool, Vec<String>, Vec<String>), String> {
    let corpus = extract_search_corpus(cfg.keyword_search_target, msg);
    let mut passed = Vec::new();
    let mut failed = Vec::new();

    // 1. Excluded keywords
    for kw in &cfg.excluded_keywords {
        if !kw.trim().is_empty() && term_matches(&corpus, kw, cfg.case_sensitive, cfg.whole_word) {
            failed.push(format!("Excluded keyword matched: '{}'", kw.trim()));
            return Ok((false, passed, failed));
        }
    }
    if !cfg.excluded_keywords.is_empty() {
        passed.push("No excluded keywords present".to_string());
    }

    // 2. Required keywords
    let active_req: Vec<&String> = cfg
        .required_keywords
        .iter()
        .filter(|s| !s.trim().is_empty())
        .collect();
    if !active_req.is_empty() {
        let matches = match cfg.required_keywords_match_mode {
            MatchMode::Any => active_req
                .iter()
                .any(|kw| term_matches(&corpus, kw, cfg.case_sensitive, cfg.whole_word)),
            MatchMode::All => active_req
                .iter()
                .all(|kw| term_matches(&corpus, kw, cfg.case_sensitive, cfg.whole_word)),
        };
        if matches {
            passed.push("Required keywords satisfied".to_string());
        } else {
            failed.push("Required keywords did not match".to_string());
            return Ok((false, passed, failed));
        }
    }

    // 3. Positive Regex
    if !cfg.regex_pattern.trim().is_empty() {
        if cfg.regex_pattern.len() > MAX_REGEX_PATTERN_LEN {
            return Err("Regular expression pattern exceeds maximum length limit".to_string());
        }
        let re = RegexBuilder::new(cfg.regex_pattern.trim())
            .case_insensitive(!cfg.case_sensitive)
            .size_limit(512 * 1024)
            .build()
            .map_err(|e| format!("Invalid regular expression: {}", e))?;
        if re.is_match(&corpus) {
            passed.push("Regex filter matched".to_string());
        } else {
            failed.push("Regex filter did not match".to_string());
            return Ok((false, passed, failed));
        }
    }

    // 4. Exclusion Regex
    if !cfg.regex_exclude_pattern.trim().is_empty() {
        if cfg.regex_exclude_pattern.len() > MAX_REGEX_PATTERN_LEN {
            return Err("Exclusion regex exceeds maximum length limit".to_string());
        }
        let re = RegexBuilder::new(cfg.regex_exclude_pattern.trim())
            .case_insensitive(!cfg.case_sensitive)
            .size_limit(512 * 1024)
            .build()
            .map_err(|e| format!("Invalid exclusion regular expression: {}", e))?;
        if re.is_match(&corpus) {
            failed.push("Exclusion regex matched".to_string());
            return Ok((false, passed, failed));
        }
        passed.push("Exclusion regex clear".to_string());
    }

    Ok((true, passed, failed))
}

pub fn check_file_filters(
    cfg: &FilterConfig,
    msg: &CandidateMessage,
) -> Result<(bool, Vec<String>, Vec<String>), String> {
    let mut passed = Vec::new();
    let mut failed = Vec::new();

    let has_size_rule = cfg.min_file_size_bytes.is_some() || cfg.max_file_size_bytes.is_some();
    let has_name_rule = !cfg.filename_contains.trim().is_empty()
        || !cfg.filename_ends_with.trim().is_empty()
        || !cfg.filename_regex.trim().is_empty()
        || !cfg.accepted_extensions.is_empty()
        || !cfg.excluded_extensions.is_empty();

    if !has_size_rule && !has_name_rule {
        return Ok((true, passed, failed));
    }

    if has_size_rule {
        match msg.file_size_bytes {
            None => {
                if cfg.missing_file_metadata_policy == MissingFileMetadataPolicy::FailFilter {
                    failed.push("Message lacks file size metadata (policy: FAIL_FILTER)".to_string());
                    return Ok((false, passed, failed));
                }
            }
            Some(sz) => {
                if let Some(min_b) = cfg.min_file_size_bytes {
                    if sz < min_b {
                        failed.push(format!("File size ({} B) is below minimum ({} B)", sz, min_b));
                        return Ok((false, passed, failed));
                    }
                    passed.push("Minimum file size passed".to_string());
                }
                if let Some(max_b) = cfg.max_file_size_bytes {
                    if sz > max_b {
                        failed.push(format!("File size ({} B) exceeds maximum ({} B)", sz, max_b));
                        return Ok((false, passed, failed));
                    }
                    passed.push("Maximum file size passed".to_string());
                }
            }
        }
    }

    if has_name_rule {
        match msg.filename.as_deref() {
            None | Some("") => {
                if cfg.missing_file_metadata_policy == MissingFileMetadataPolicy::FailFilter {
                    failed.push("Message lacks filename metadata (policy: FAIL_FILTER)".to_string());
                    return Ok((false, passed, failed));
                }
            }
            Some(fname) => {
                let fname_cmp = if cfg.case_sensitive {
                    fname.to_string()
                } else {
                    fname.to_lowercase()
                };

                if !cfg.filename_contains.trim().is_empty() {
                    let needle = if cfg.case_sensitive {
                        cfg.filename_contains.trim().to_string()
                    } else {
                        cfg.filename_contains.trim().to_lowercase()
                    };
                    if !fname_cmp.contains(&needle) {
                        failed.push(format!("Filename does not contain '{}'", cfg.filename_contains.trim()));
                        return Ok((false, passed, failed));
                    }
                    passed.push("Filename substring matched".to_string());
                }

                if !cfg.filename_ends_with.trim().is_empty() {
                    let suffix = if cfg.case_sensitive {
                        cfg.filename_ends_with.trim().to_string()
                    } else {
                        cfg.filename_ends_with.trim().to_lowercase()
                    };
                    if !fname_cmp.ends_with(&suffix) {
                        failed.push(format!("Filename does not end with '{}'", cfg.filename_ends_with.trim()));
                        return Ok((false, passed, failed));
                    }
                    passed.push("Filename suffix matched".to_string());
                }

                if !cfg.filename_regex.trim().is_empty() {
                    let re = RegexBuilder::new(cfg.filename_regex.trim())
                        .case_insensitive(!cfg.case_sensitive)
                        .size_limit(256 * 1024)
                        .build()
                        .map_err(|e| format!("Invalid filename regex: {}", e))?;
                    if !re.is_match(fname) {
                        failed.push("Filename regex did not match".to_string());
                        return Ok((false, passed, failed));
                    }
                    passed.push("Filename regex matched".to_string());
                }

                let fname_lower = fname.to_lowercase();
                if !cfg.excluded_extensions.is_empty() {
                    for ext in &cfg.excluded_extensions {
                        let norm = if ext.starts_with('.') {
                            ext.to_lowercase()
                        } else {
                            format!(".{}", ext.to_lowercase())
                        };
                        if fname_lower.ends_with(&norm) {
                            failed.push(format!("Excluded extension matched: {}", norm));
                            return Ok((false, passed, failed));
                        }
                    }
                    passed.push("No excluded extension matched".to_string());
                }

                if !cfg.accepted_extensions.is_empty() {
                    let ok = cfg.accepted_extensions.iter().any(|ext| {
                        let norm = if ext.starts_with('.') {
                            ext.to_lowercase()
                        } else {
                            format!(".{}", ext.to_lowercase())
                        };
                        fname_lower.ends_with(&norm)
                    });
                    if !ok {
                        failed.push("Filename did not match accepted extensions".to_string());
                        return Ok((false, passed, failed));
                    }
                    passed.push("Accepted extension matched".to_string());
                }
            }
        }
    }

    Ok((true, passed, failed))
}
