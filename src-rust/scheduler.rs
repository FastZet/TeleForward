//! Time-Window Evaluation (IANA Timezones & Midnight-Crossing Windows)

use chrono::{DateTime, Datelike, NaiveTime, Timelike, Utc};
use chrono_tz::Tz;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ScheduleBehavior {
    OnlyArrivingDuringWindow,
    DeferUntilWindow,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScheduleConfig {
    pub enabled: bool,
    pub start_time: String, // "HH:MM"
    pub end_time: String,   // "HH:MM"
    pub days: Vec<u32>,     // 0 = Sunday .. 6 = Saturday
    pub timezone: String,   // e.g. "UTC", "America/New_York", "Europe/Berlin"
    pub behavior: ScheduleBehavior,
}

pub fn is_within_schedule_window(
    cfg: &ScheduleConfig,
    timestamp_utc: DateTime<Utc>,
) -> Result<bool, String> {
    if !cfg.enabled {
        return Ok(true);
    }

    let tz: Tz = cfg
        .timezone
        .parse()
        .map_err(|_| format!("Unrecognized IANA timezone: {}", cfg.timezone))?;

    let local_dt = timestamp_utc.with_timezone(&tz);
    let start = NaiveTime::parse_from_str(&cfg.start_time, "%H:%M")
        .map_err(|_| format!("Invalid start_time format: {}", cfg.start_time))?;
    let end = NaiveTime::parse_from_str(&cfg.end_time, "%H:%M")
        .map_err(|_| format!("Invalid end_time format: {}", cfg.end_time))?;

    let current_time = NaiveTime::from_hms_opt(local_dt.hour(), local_dt.minute(), 0)
        .unwrap_or(start);
    let current_day = local_dt.weekday().num_days_from_sunday(); // 0..=6

    if start <= end {
        // Same-day window (e.g., 09:00 to 18:00)
        Ok(cfg.days.contains(&current_day) && current_time >= start && current_time <= end)
    } else {
        // Overnight window crossing midnight (e.g., 23:00 to 06:00)
        if current_time >= start {
            Ok(cfg.days.contains(&current_day))
        } else if current_time <= end {
            let prev_day = if current_day == 0 { 6 } else { current_day - 1 };
            Ok(cfg.days.contains(&prev_day))
        } else {
            Ok(false)
        }
    }
}
