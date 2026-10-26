//! Telegram MTProto Client Adapter (`grammers-client` Personal Account Integration)
//!
//! Defines an explicit `TelegramAdapter` trait so the routing engine, queue worker,
//! backfill scanner, and catch-up engine remain decoupled from transport internals.

use crate::filters::{CandidateMessage, MessageMediaType};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use tokio::sync::Mutex;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum TelegramConnectionState {
    NotConfigured,
    AwaitingPhoneNumber,
    AwaitingLoginCode,
    AwaitingTwoStepPassword,
    Connecting,
    Connected,
    Reconnecting,
    AuthenticationExpired,
    Disconnected,
    Error,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AccessibleChat {
    pub peer_id: String,
    pub chat_type: String,
    pub title: String,
    pub username: Option<String>,
    pub can_read: bool,
    pub can_send: bool,
    pub can_edit: bool,
    pub can_delete: bool,
    pub is_accessible: bool,
    pub last_message_id: Option<i64>,
    pub permission_error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum TelegramDeliveryError {
    FloodWait { seconds: u64, message: String },
    TransientNetwork { message: String },
    SessionExpired { message: String },
    PermanentPermission { message: String },
    InvalidDestination { message: String },
    UnsupportedMedia { message: String },
}

impl TelegramDeliveryError {
    pub fn is_retryable(&self) -> bool {
        matches!(
            self,
            TelegramDeliveryError::FloodWait { .. }
                | TelegramDeliveryError::TransientNetwork { .. }
        )
    }
}

#[async_trait]
pub trait TelegramAdapter: Send + Sync {
    async fn connection_state(&self) -> TelegramConnectionState;
    async fn configure_api_credentials(&self, api_id: i32, api_hash: &str) -> Result<(), String>;
    async fn request_login_code(&self, phone_international: &str) -> Result<(), String>;
    async fn submit_login_code(&self, code: &str) -> Result<TelegramConnectionState, String>;
    async fn submit_two_step_password(&self, password: &str) -> Result<TelegramConnectionState, String>;
    async fn logout(&self) -> Result<(), String>;
    async fn list_dialogs(&self) -> Result<Vec<AccessibleChat>, String>;
    async fn fetch_history_batch(
        &self,
        source_peer_id: &str,
        offset_id: i64,
        limit: usize,
        oldest_first: bool,
    ) -> Result<Vec<CandidateMessage>, String>;
    async fn forward_message(
        &self,
        source_peer_id: &str,
        source_message_id: i64,
        destination_peer_id: &str,
    ) -> Result<i64, TelegramDeliveryError>;
    async fn copy_message(
        &self,
        source_peer_id: &str,
        source_message_id: i64,
        destination_peer_id: &str,
        transformed_caption: Option<&str>,
    ) -> Result<i64, TelegramDeliveryError>;
    async fn edit_destination_message(
        &self,
        destination_peer_id: &str,
        destination_message_id: i64,
        new_caption: &str,
    ) -> Result<(), TelegramDeliveryError>;
    async fn delete_destination_messages(
        &self,
        destination_peer_id: &str,
        destination_message_ids: &[i64],
    ) -> Result<usize, TelegramDeliveryError>;
}

/// Concurrency guard preventing simultaneous login flows from corrupting the MTProto session.
pub struct LoginFlowLock {
    inner: Mutex<bool>,
}

impl LoginFlowLock {
    pub fn new() -> Self {
        Self {
            inner: Mutex::new(false),
        }
    }

    pub async fn try_acquire(&self) -> Result<(), String> {
        let mut guard = self.inner.lock().await;
        if *guard {
            return Err("Another authentication operation is currently in progress".to_string());
        }
        *guard = true;
        Ok(())
    }

    pub async fn release(&self) {
        let mut guard = self.inner.lock().await;
        *guard = false;
    }
}

pub fn classify_mtproto_rpc_error(rpc_error: &str) -> TelegramDeliveryError {
    let upper = rpc_error.to_uppercase();
    if let Some(idx) = upper.find("FLOOD_WAIT_") {
        let digits: String = upper[idx + 11..]
            .chars()
            .take_while(|c| c.is_ascii_digit())
            .collect();
        let secs = digits.parse::<u64>().unwrap_or(30).max(1);
        return TelegramDeliveryError::FloodWait {
            seconds: secs,
            message: format!("Telegram rate limit FLOOD_WAIT_{}s", secs),
        };
    }
    if upper.contains("AUTH_KEY_UNREGISTERED")
        || upper.contains("SESSION_REVOKED")
        || upper.contains("USER_DEACTIVATED")
    {
        return TelegramDeliveryError::SessionExpired {
            message: rpc_error.to_string(),
        };
    }
    if upper.contains("CHAT_WRITE_FORBIDDEN")
        || upper.contains("CHAT_ADMIN_REQUIRED")
        || upper.contains("USER_BANNED_IN_CHANNEL")
        || upper.contains("CHAT_FORWARDS_RESTRICTED")
    {
        return TelegramDeliveryError::PermanentPermission {
            message: rpc_error.to_string(),
        };
    }
    if upper.contains("PEER_ID_INVALID") || upper.contains("CHANNEL_PRIVATE") {
        return TelegramDeliveryError::InvalidDestination {
            message: rpc_error.to_string(),
        };
    }
    TelegramDeliveryError::TransientNetwork {
        message: rpc_error.to_string(),
    }
}

pub fn map_grammers_media_type(
    has_photo: bool,
    has_video: bool,
    has_doc: bool,
    has_audio: bool,
    has_voice: bool,
) -> MessageMediaType {
    if has_voice {
        MessageMediaType::Voice
    } else if has_audio {
        MessageMediaType::Audio
    } else if has_video {
        MessageMediaType::Video
    } else if has_photo {
        MessageMediaType::Photo
    } else if has_doc {
        MessageMediaType::Document
    } else {
        MessageMediaType::Text
    }
}
