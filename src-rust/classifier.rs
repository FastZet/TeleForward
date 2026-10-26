//! Deterministic Offline Media Classifier (`MOVIE`, `TV_SHOW`, `COMBINED`, `SPLIT`)
//!
//! Inspects filename and caption text without external metadata APIs or AI vision.

use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::sync::LazyLock;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MediaCategory {
    Movie,
    TvShow,
    Combined,
    Split,
}

impl MediaCategory {
    pub fn as_str(&self) -> &'static str {
        match self {
            MediaCategory::Movie => "MOVIE",
            MediaCategory::TvShow => "TV_SHOW",
            MediaCategory::Combined => "COMBINED",
            MediaCategory::Split => "SPLIT",
        }
    }

    pub fn from_str(value: &str) -> Option<Self> {
        match value.trim().to_uppercase().as_str() {
            "MOVIE" => Some(MediaCategory::Movie),
            "TV_SHOW" => Some(MediaCategory::TvShow),
            "COMBINED" => Some(MediaCategory::Combined),
            "SPLIT" => Some(MediaCategory::Split),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CategoryMatchMode {
    All,
    Any,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClassificationResult {
    pub categories: Vec<MediaCategory>,
    pub reasons: Vec<String>,
}

static RE_TV_SINGLE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(?:^|[\s._\-\[\(])(?:S\d{1,2}\s*E\d{1,3}|\d{1,2}x\d{2,3}|Season\s*\d{1,2}\s*Episode\s*\d{1,3}|E\d{2,3}|EP\s*\d{1,4})(?:$|[\s._\-\]\)])").unwrap()
});

static RE_COMBINED_PACK: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(?:^|[\s._\-\[\(])(?:S\d{1,2}\s*E\d{1,3}\s*[-~]\s*(?:S\d{1,2}\s*)?E?\d{1,3}|S\d{1,2}\s*(?:COMPLETE|FULL|PACK)|COMPLETE\s+SEASON|SEASON\s+\d{1,2}\s*(?:-\s*\d{1,2}\s*)?(?:COMPLETE|PACK|FULL)|S\d{1,2}\s*-\s*S\d{1,2}|(?:^|[\s._\-])S\d{1,2}(?:$|[\s._\-])(?!E\d))(?:$|[\s._\-\]\)])").unwrap()
});

static RE_MULTI_EP_MARKERS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)S\d{1,2}E\d{1,3}(?:[._\-]?E\d{1,3})+").unwrap()
});

static RE_SPLIT_EXT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(?:\.(?:mkv|mp4|avi|ts|7z|zip|rar|tar)\.\d{3}$|\.part0*\d+\.rar$|\.r\d{2,3}$|(?:^|[\s._\-])(?:part|pt|cd|disc|disk|dvd)\s*0*\d{1,2}(?:$|[\s._\-]))").unwrap()
});

static RE_MOVIE_YEAR_QUALITY: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(?:^|[\s._\-\(\[])(19[2-9]\d|20[0-3]\d)(?:$|[\s._\-\)\]]).*(?:2160p|1080p|720p|480p|UHD|4K|BluRay|BDRip|BRRip|WEB-DL|WEBRip|HDRip|DVDRip|Remux|x264|x265|HEVC|H\.?264|H\.?265|AV1)").unwrap()
});

static RE_VIDEO_EXT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)\.(?:mkv|mp4|avi|mov|m4v|ts|iso)(?:\.\d{3})?$").unwrap()
});

pub fn classify_media(filename: Option<&str>, caption: Option<&str>) -> ClassificationResult {
    let fname = filename.unwrap_or("").trim();
    let cap = caption.unwrap_or("").trim();
    let combined_input = if fname.is_empty() {
        cap.to_string()
    } else if cap.is_empty() {
        fname.to_string()
    } else {
        format!("{} {}", fname, cap)
    };

    let mut categories = BTreeSet::new();
    let mut reasons = Vec::new();

    if combined_input.is_empty() {
        return ClassificationResult {
            categories: Vec::new(),
            reasons,
        };
    }

    // 1. Split-file detection (.mkv.001, .7z.002, .part1.rar, cd1, part2)
    if RE_SPLIT_EXT.is_match(fname) || RE_SPLIT_EXT.is_match(&combined_input) {
        categories.insert(MediaCategory::Split);
        reasons.push("Matched multipart/split archive or volume marker (.001 / partN / cdN)".to_string());
    }

    // 2. Combined-pack detection (Complete season, S01E01-E10, multi-episode markers)
    let is_combined = RE_COMBINED_PACK.is_match(&combined_input)
        || RE_MULTI_EP_MARKERS.is_match(&combined_input);
    if is_combined {
        categories.insert(MediaCategory::Combined);
        categories.insert(MediaCategory::TvShow);
        reasons.push("Matched combined season pack or episode range marker".to_string());
    }

    // 3. Television episode detection (S01E05, 1x05, Season 1 Episode 5)
    if RE_TV_SINGLE.is_match(&combined_input) {
        categories.insert(MediaCategory::TvShow);
        reasons.push("Matched episodic television marker (SxxExx / NxNN)".to_string());
    }

    // 4. Movie detection (Release year + quality/source tags or video container, without TV markers)
    let has_tv = categories.contains(&MediaCategory::TvShow) || categories.contains(&MediaCategory::Combined);
    if !has_tv {
        if RE_MOVIE_YEAR_QUALITY.is_match(&combined_input)
            || (RE_VIDEO_EXT.is_match(fname) && Regex::new(r"(?:^|[\s._\-\(\[])(19[2-9]\d|20[0-3]\d)(?:$|[\s._\-\)\]])").unwrap().is_match(&combined_input))
        {
            categories.insert(MediaCategory::Movie);
            reasons.push("Matched standalone movie release year and encoding/container signature".to_string());
        }
    }

    ClassificationResult {
        categories: categories.into_iter().collect(),
        reasons,
    }
}

pub fn evaluate_category_filter(
    detected: &[MediaCategory],
    selected: &[MediaCategory],
    mode: CategoryMatchMode,
) -> bool {
    if selected.is_empty() {
        return true;
    }
    match mode {
        CategoryMatchMode::All => selected.iter().all(|req| detected.contains(req)),
        CategoryMatchMode::Any => selected.iter().any(|req| detected.contains(req)),
    }
}
