//! Security Subsystem: Argon2id Password Hashing, AES-256-GCM Session Encryption, and Log Redaction

use aes_gcm::{
    aead::{Aead, KeyInit},
    Aes256Gcm, Nonce,
};
use argon2::{
    password_hash::{rand_core::OsRng, PasswordHash, PasswordHasher, PasswordVerifier, SaltString},
    Argon2,
};
use base64::{engine::general_purpose::STANDARD as B64, Engine};
use rand::RngCore;
use regex::Regex;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::sync::LazyLock;
use zeroize::Zeroize;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EncryptedPayload {
    pub ciphertext_b64: String,
    pub nonce_b64: String,
    pub key_fingerprint: String,
}

pub fn hash_admin_password(plain_password: &str) -> Result<(String, String), String> {
    if plain_password.len() < 10 {
        return Err("Administrator password must be at least 10 characters".to_string());
    }
    let salt = SaltString::generate(&mut OsRng);
    let argon2 = Argon2::default();
    let hash = argon2
        .hash_password(plain_password.as_bytes(), &salt)
        .map_err(|e| format!("Argon2 hashing failed: {}", e))?
        .to_string();
    Ok((hash, salt.to_string()))
}

pub fn verify_admin_password(plain_password: &str, stored_phc_hash: &str) -> bool {
    let Ok(parsed_hash) = PasswordHash::new(stored_phc_hash) else {
        return false;
    };
    Argon2::default()
        .verify_password(plain_password.as_bytes(), &parsed_hash)
        .is_ok()
}

pub fn derive_256bit_key(raw_secret: &str) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(raw_secret.as_bytes());
    let digest = hasher.finalize();
    let mut key = [0u8; 32];
    key.copy_from_slice(&digest);
    key
}

pub fn key_fingerprint(key: &[u8; 32]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"teleroute-key-fp:");
    hasher.update(key);
    let out = hasher.finalize();
    format!("{:x}", out)[..16].to_string()
}

pub fn encrypt_session_bytes(plaintext: &[u8], raw_key: &str) -> Result<EncryptedPayload, String> {
    let mut key = derive_256bit_key(raw_key);
    let fp = key_fingerprint(&key);
    let cipher = Aes256Gcm::new_from_slice(&key).map_err(|e| e.to_string())?;
    key.zeroize();

    let mut nonce_bytes = [0u8; 12];
    OsRng.fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);

    let ciphertext = cipher
        .encrypt(nonce, plaintext)
        .map_err(|_| "AES-256-GCM encryption failed".to_string())?;

    Ok(EncryptedPayload {
        ciphertext_b64: B64.encode(ciphertext),
        nonce_b64: B64.encode(nonce_bytes),
        key_fingerprint: fp,
    })
}

pub fn decrypt_session_bytes(payload: &EncryptedPayload, raw_key: &str) -> Result<Vec<u8>, String> {
    let mut key = derive_256bit_key(raw_key);
    let expected_fp = key_fingerprint(&key);
    if payload.key_fingerprint != expected_fp {
        key.zeroize();
        return Err("Session encryption key fingerprint mismatch".to_string());
    }
    let cipher = Aes256Gcm::new_from_slice(&key).map_err(|e| e.to_string())?;
    key.zeroize();

    let nonce_bytes = B64
        .decode(&payload.nonce_b64)
        .map_err(|_| "Malformed nonce base64".to_string())?;
    if nonce_bytes.len() != 12 {
        return Err("Invalid AES-GCM nonce length".to_string());
    }
    let ciphertext = B64
        .decode(&payload.ciphertext_b64)
        .map_err(|_| "Malformed ciphertext base64".to_string())?;

    cipher
        .decrypt(Nonce::from_slice(&nonce_bytes), ciphertext.as_ref())
        .map_err(|_| "Session decryption failed (corrupted data or wrong key)".to_string())
}

static RE_SENSITIVE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(api_hash|password|login_code|phone_code|session|secret|token)\s*[:=]\s*\S+").unwrap()
});

pub fn redact_diagnostic_message(input: &str) -> String {
    RE_SENSITIVE
        .replace_all(input, "$1=[REDACTED]")
        .to_string()
}
