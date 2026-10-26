//! TeleRoute MTProto Core — Modular Monolith Library Root
//!
//! Organizes the platform into 15 explicit domain modules with trait boundaries
//! isolating the Telegram MTProto adapter from the routing, classification,
//! transformation, and persistence subsystems.

pub mod api;
pub mod backfill;
pub mod catchup;
pub mod classifier;
pub mod filters;
pub mod observability;
pub mod queue;
pub mod router;
pub mod rules;
pub mod scheduler;
pub mod security;
pub mod storage;
pub mod sync;
pub mod telegram;
pub mod transform;

#[cfg(test)]
mod tests;
