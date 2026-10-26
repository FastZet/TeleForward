//! Deterministic Caption Transformation Pipeline (Copy Mode)

use regex::{Regex, RegexBuilder};
use serde::{Deserialize, Serialize};
use std::sync::LazyLock;

pub const TELEGRAM_MAX_CAPTION_CHARS: usize = 1024;
pub const TELEGRAM_MAX_TEXT_CHARS: usize = 4096;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReplaceStep {
    pub step_order: i32,
    pub find_pattern: String,
    pub replace_with: String,
    pub is_regex: bool,
    pub case_sensitive: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptionTransformConfig {
    pub clean_filename_mode: bool,
    pub remove_links: bool,
    pub remove_usernames: bool,
    pub remove_hashtags: bool,
    pub remove_emojis: bool,
    pub remove_decorative_symbols: bool,
    pub strip_text_after_extension: bool,
    pub preserve_multipart_suffix: bool,
    pub custom_header: String,
    pub custom_footer: String,
    pub replacements: Vec<ReplaceStep>,
}

static RE_LINKS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(?:https?://|t\.me/|telegram\.me/|www\.)\S+").unwrap()
});

static RE_USERNAMES: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?:^|\s)@[A-Za-z0-9_]{3,32}\b").unwrap()
});

static RE_HASHTAGS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?:^|\s)#[A-Za-z0-9_]+\b").unwrap()
});

static RE_DECORATIVE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"[★☆✦✧❖⚡🔥💥🎬📺💎👑🔔📢✅❌⭕➖➗➕💲🔗]+").unwrap()
});

static RE_STRIP_AFTER_EXT_MULTIPART: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?is)^(.*?\.(?:mkv|mp4|avi|mov|ts|iso|7z|rar|zip)(?:\.\d{3}|\.part\d+\.rar)?)\b.*$").unwrap()
});

static RE_STRIP_AFTER_EXT_PLAIN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?is)^(.*?\.(?:mkv|mp4|avi|mov|ts|iso|7z|rar|zip))\b.*$").unwrap()
});

pub fn apply_caption_transformations(
    original_caption: Option<&str>,
    filename: Option<&str>,
    is_media: bool,
    cfg: &CaptionTransformConfig,
) -> Result<String, String> {
    // Step 1: Extract base string (or clean filename mode)
    let mut text = if cfg.clean_filename_mode {
        if let Some(fname) = filename.filter(|s| !s.trim().is_empty()) {
            fname.trim().to_string()
        } else {
            original_caption.unwrap_or("").to_string()
        }
    } else {
        original_caption.unwrap_or("").to_string()
    };

    // Step 2: Strip trailing promotional text after filename extension (preserving .001 if configured)
    if cfg.strip_text_after_extension {
        let re = if cfg.preserve_multipart_suffix {
            &*RE_STRIP_AFTER_EXT_MULTIPART
        } else {
            &*RE_STRIP_AFTER_EXT_PLAIN
        };
        if let Some(caps) = re.captures(&text) {
            if let Some(matched) = caps.get(1) {
                text = matched.as_str().to_string();
            }
        }
    }

    // Step 3: Optional cleanup operations in deterministic order
    if cfg.remove_links {
        text = RE_LINKS.replace_all(&text, "").to_string();
    }
    if cfg.remove_usernames {
        text = RE_USERNAMES.replace_all(&text, " ").to_string();
    }
    if cfg.remove_hashtags {
        text = RE_HASHTAGS.replace_all(&text, " ").to_string();
    }
    if cfg.remove_decorative_symbols {
        text = RE_DECORATIVE.replace_all(&text, "").to_string();
    }
    if cfg.remove_emojis {
        text = text
            .chars()
            .filter(|&c| {
                let u = c as u32;
                !(0x1F300..=0x1FAFF).contains(&u) && !(0x2600..=0x27BF).contains(&u)
            })
            .collect();
    }

    // Step 4: Custom find-and-replace steps in configured step_order
    let mut ordered = cfg.replacements.clone();
    ordered.sort_by_key(|s| s.step_order);
    for step in &ordered {
        if step.find_pattern.is_empty() {
            continue;
        }
        if step.is_regex {
            let re = RegexBuilder::new(&step.find_pattern)
                .case_insensitive(!step.case_sensitive)
                .size_limit(256 * 1024)
                .build()
                .map_err(|e| format!("Invalid replacement regex '{}': {}", step.find_pattern, e))?;
            text = re.replace_all(&text, step.replace_with.as_str()).to_string();
        } else if step.case_sensitive {
            text = text.replace(&step.find_pattern, &step.replace_with);
        } else {
            let escaped = regex::escape(&step.find_pattern);
            let re = RegexBuilder::new(&escaped)
                .case_insensitive(true)
                .build()
                .map_err(|e| e.to_string())?;
            text = re.replace_all(&text, step.replace_with.as_str()).to_string();
        }
    }

    // Collapse redundant horizontal whitespace while keeping intentional line breaks
    text = text
        .lines()
        .map(|line| line.split_whitespace().collect::<Vec<_>>().join(" "))
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string();

    // Step 5: Prepend custom header and append custom footer
    let mut parts = Vec::new();
    if !cfg.custom_header.trim().is_empty() {
        parts.push(cfg.custom_header.trim().to_string());
    }
    if !text.is_empty() {
        parts.push(text);
    }
    if !cfg.custom_footer.trim().is_empty() {
        parts.push(cfg.custom_footer.trim().to_string());
    }

    let mut final_caption = parts.join("\n");

    // Step 6: Validate against Telegram message/caption length constraints
    let max_len = if is_media {
        TELEGRAM_MAX_CAPTION_CHARS
    } else {
        TELEGRAM_MAX_TEXT_CHARS
    };
    if final_caption.chars().count() > max_len {
        final_caption = final_caption.chars().take(max_len).collect();
    }

    Ok(final_caption)
}
