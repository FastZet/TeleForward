-- ============================================================================
-- TeleRoute MTProto Core — Normalized Database Schema (Migration 0001)
-- Supports SQLite (WAL mode, foreign_keys = ON) & PostgreSQL compatible types
-- ============================================================================

PRAGMA foreign_keys = ON;

-- 1. Administrative Users & Web Sessions (No default credentials shipped)
CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    ip_address TEXT,
    user_agent TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires ON admin_sessions(expires_at);

-- 2. Application Global Settings
CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    forwarding_enabled INTEGER NOT NULL DEFAULT 1,
    resume_worker_on_restart INTEGER NOT NULL DEFAULT 1,
    auto_catchup_on_startup INTEGER NOT NULL DEFAULT 0,
    duplicate_protection_enabled INTEGER NOT NULL DEFAULT 1,
    deduplication_scope TEXT NOT NULL DEFAULT 'PER_DESTINATION' CHECK (deduplication_scope IN ('PER_RULE', 'PER_DESTINATION')),
    global_send_delay_ms INTEGER NOT NULL DEFAULT 500,
    min_send_interval_ms INTEGER NOT NULL DEFAULT 1000,
    delivery_concurrency INTEGER NOT NULL DEFAULT 2,
    max_queue_depth INTEGER NOT NULL DEFAULT 2000,
    default_retry_count INTEGER NOT NULL DEFAULT 3,
    log_retention_days INTEGER NOT NULL DEFAULT 30,
    global_sync_edits INTEGER NOT NULL DEFAULT 1,
    global_sync_deletes INTEGER NOT NULL DEFAULT 1,
    theme TEXT NOT NULL DEFAULT 'dark' CHECK (theme IN ('system', 'light', 'dark')),
    default_timezone TEXT NOT NULL DEFAULT 'UTC',
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT OR IGNORE INTO app_settings (id) VALUES (1);

-- 3. Telegram Account Metadata & Encrypted Session
CREATE TABLE IF NOT EXISTS telegram_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    api_id INTEGER,
    api_hash_encrypted TEXT,
    api_hash_iv TEXT,
    api_hash_tag TEXT,
    phone_number_masked TEXT,
    account_user_id TEXT,
    account_username TEXT,
    account_display_name TEXT,
    connection_state TEXT NOT NULL DEFAULT 'NOT_CONFIGURED' CHECK (
        connection_state IN (
            'NOT_CONFIGURED',
            'AWAITING_PHONE_NUMBER',
            'AWAITING_LOGIN_CODE',
            'AWAITING_TWO_STEP_PASSWORD',
            'CONNECTING',
            'CONNECTED',
            'RECONNECTING',
            'AUTHENTICATION_EXPIRED',
            'DISCONNECTED',
            'ERROR'
        )
    ),
    last_error TEXT,
    last_connected_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT OR IGNORE INTO telegram_account (id, connection_state) VALUES (1, 'NOT_CONFIGURED');

CREATE TABLE IF NOT EXISTS telegram_session_encrypted (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    ciphertext_b64 TEXT NOT NULL,
    nonce_b64 TEXT NOT NULL,
    auth_tag_b64 TEXT NOT NULL,
    key_fingerprint TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- 4. Accessible Telegram Chats (Stable Peer Identifiers)
CREATE TABLE IF NOT EXISTS chats (
    peer_id TEXT PRIMARY KEY,
    access_hash TEXT,
    chat_type TEXT NOT NULL CHECK (chat_type IN ('CHANNEL', 'SUPERGROUP', 'GROUP', 'PRIVATE')),
    title TEXT NOT NULL,
    username TEXT,
    can_read INTEGER NOT NULL DEFAULT 1,
    can_send INTEGER NOT NULL DEFAULT 1,
    can_edit INTEGER NOT NULL DEFAULT 1,
    can_delete INTEGER NOT NULL DEFAULT 1,
    is_accessible INTEGER NOT NULL DEFAULT 1,
    member_count INTEGER,
    last_message_id INTEGER,
    permission_error TEXT,
    last_synced_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_chats_type ON chats(chat_type);
CREATE INDEX IF NOT EXISTS idx_chats_title ON chats(title);

-- 5. Forwarding Rules (Core Table)
CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    source_peer_id TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 50 CHECK (priority >= 0 AND priority <= 100),
    secondary_order INTEGER NOT NULL DEFAULT 0,
    exclusive_stop INTEGER NOT NULL DEFAULT 0,
    delivery_mode TEXT NOT NULL DEFAULT 'COPY' CHECK (delivery_mode IN ('FORWARD', 'COPY')),
    delay_seconds INTEGER NOT NULL DEFAULT 0 CHECK (delay_seconds >= 0 AND delay_seconds <= 120),
    max_retries INTEGER NOT NULL DEFAULT 3 CHECK (max_retries >= 0 AND max_retries <= 10),
    sync_edits INTEGER NOT NULL DEFAULT 1,
    sync_deletes INTEGER NOT NULL DEFAULT 1,
    deduplication_override TEXT CHECK (deduplication_override IN ('GLOBAL', 'PER_RULE', 'PER_DESTINATION')),
    schedule_enabled INTEGER NOT NULL DEFAULT 0,
    schedule_start_time TEXT NOT NULL DEFAULT '00:00',
    schedule_end_time TEXT NOT NULL DEFAULT '23:59',
    schedule_days_csv TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
    schedule_timezone TEXT NOT NULL DEFAULT 'UTC',
    schedule_behavior TEXT NOT NULL DEFAULT 'DEFER_UNTIL_WINDOW' CHECK (schedule_behavior IN ('ONLY_ARRIVING_DURING_WINDOW', 'DEFER_UNTIL_WINDOW')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_rules_source_priority ON rules(source_peer_id, enabled, priority DESC, secondary_order ASC);

-- 6. Rule Destinations (Normalized 1-to-Many)
CREATE TABLE IF NOT EXISTS rule_destinations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
    destination_peer_id TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(rule_id, destination_peer_id)
);
CREATE INDEX IF NOT EXISTS idx_rule_destinations_rule ON rule_destinations(rule_id);
CREATE INDEX IF NOT EXISTS idx_rule_destinations_peer ON rule_destinations(destination_peer_id);

-- 7. Rule Filters (Normalized 1-to-1 per Rule)
CREATE TABLE IF NOT EXISTS rule_filters (
    rule_id TEXT PRIMARY KEY REFERENCES rules(id) ON DELETE CASCADE,
    message_type_filter TEXT NOT NULL DEFAULT 'ALL' CHECK (
        message_type_filter IN ('ALL', 'TEXT_ONLY', 'MEDIA_ONLY', 'PHOTO', 'VIDEO', 'DOCUMENT', 'AUDIO', 'VOICE')
    ),
    album_policy TEXT NOT NULL DEFAULT 'PROCESS_ITEMS' CHECK (album_policy IN ('PROCESS_ITEMS', 'FIRST_ITEM_ONLY', 'SKIP_ALBUMS')),
    sender_filter_mode TEXT NOT NULL DEFAULT 'ANY' CHECK (
        sender_filter_mode IN ('ANY', 'SPECIFIC_USER_IDS', 'ADMINS_ONLY', 'ANONYMOUS_ADMINS_ONLY', 'VERIFIED_USERS_ONLY')
    ),
    sender_user_ids_csv TEXT NOT NULL DEFAULT '',
    missing_sender_policy TEXT NOT NULL DEFAULT 'REJECT' CHECK (missing_sender_policy IN ('REJECT', 'ALLOW_IN_CHANNELS')),
    required_keywords_csv TEXT NOT NULL DEFAULT '',
    required_keywords_match_mode TEXT NOT NULL DEFAULT 'ANY' CHECK (required_keywords_match_mode IN ('ANY', 'ALL')),
    excluded_keywords_csv TEXT NOT NULL DEFAULT '',
    regex_pattern TEXT NOT NULL DEFAULT '',
    regex_exclude_pattern TEXT NOT NULL DEFAULT '',
    keyword_search_target TEXT NOT NULL DEFAULT 'TEXT_AND_CAPTION' CHECK (
        keyword_search_target IN ('TEXT_ONLY', 'CAPTION_ONLY', 'FILENAME_ONLY', 'TEXT_AND_CAPTION', 'TEXT_CAPTION_AND_FILENAME')
    ),
    case_sensitive INTEGER NOT NULL DEFAULT 0,
    whole_word INTEGER NOT NULL DEFAULT 0,
    min_file_size_bytes INTEGER,
    max_file_size_bytes INTEGER,
    filename_contains TEXT NOT NULL DEFAULT '',
    filename_ends_with TEXT NOT NULL DEFAULT '',
    filename_regex TEXT NOT NULL DEFAULT '',
    accepted_extensions_csv TEXT NOT NULL DEFAULT '',
    excluded_extensions_csv TEXT NOT NULL DEFAULT '',
    missing_file_metadata_policy TEXT NOT NULL DEFAULT 'FAIL_FILTER' CHECK (missing_file_metadata_policy IN ('FAIL_FILTER', 'PASS_IF_NON_FILE'))
);

-- 8. Rule Category Settings (Normalized 1-to-1 per Rule)
CREATE TABLE IF NOT EXISTS rule_category_settings (
    rule_id TEXT PRIMARY KEY REFERENCES rules(id) ON DELETE CASCADE,
    categories_enabled INTEGER NOT NULL DEFAULT 0,
    selected_categories_csv TEXT NOT NULL DEFAULT '',
    category_match_mode TEXT NOT NULL DEFAULT 'ANY' CHECK (category_match_mode IN ('ALL', 'ANY'))
);

-- 9. Rule Caption Transformations & Ordered Replacement Steps
CREATE TABLE IF NOT EXISTS rule_caption_transforms (
    rule_id TEXT PRIMARY KEY REFERENCES rules(id) ON DELETE CASCADE,
    clean_filename_mode INTEGER NOT NULL DEFAULT 0,
    remove_links INTEGER NOT NULL DEFAULT 0,
    remove_usernames INTEGER NOT NULL DEFAULT 0,
    remove_hashtags INTEGER NOT NULL DEFAULT 0,
    remove_emojis INTEGER NOT NULL DEFAULT 0,
    remove_decorative_symbols INTEGER NOT NULL DEFAULT 0,
    strip_Text_after_extension INTEGER NOT NULL DEFAULT 0,
    preserve_multipart_suffix INTEGER NOT NULL DEFAULT 1,
    custom_header TEXT NOT NULL DEFAULT '',
    custom_footer TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rule_replace_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL DEFAULT 0,
    find_pattern TEXT NOT NULL,
    replace_with TEXT NOT NULL DEFAULT '',
    is_regex INTEGER NOT NULL DEFAULT 0,
    case_sensitive INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_rule_replace_steps_rule ON rule_replace_steps(rule_id, step_order ASC);

-- 10. Durable Delivery Jobs & Delivery Attempts
CREATE TABLE IF NOT EXISTS delivery_jobs (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    source_peer_id TEXT NOT NULL,
    source_message_id INTEGER NOT NULL,
    rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
    destination_peer_id TEXT NOT NULL,
    delivery_mode TEXT NOT NULL CHECK (delivery_mode IN ('FORWARD', 'COPY')),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'SKIPPED', 'FAILED', 'RETRY_SCHEDULED', 'CANCELLED')
    ),
    transformed_caption TEXT,
    media_type TEXT NOT NULL DEFAULT 'TEXT',
    filename TEXT,
    file_size_bytes INTEGER,
    detected_categories_csv TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    next_eligible_at TEXT NOT NULL,
    last_error TEXT,
    error_category TEXT,
    destination_message_id INTEGER,
    origin_type TEXT NOT NULL DEFAULT 'LIVE' CHECK (origin_type IN ('LIVE', 'BACKFILL', 'CATCHUP', 'LIVE_TEST')),
    backfill_job_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_delivery_jobs_status_next ON delivery_jobs(status, next_eligible_at ASC);
CREATE INDEX IF NOT EXISTS idx_delivery_jobs_rule ON delivery_jobs(rule_id);
CREATE INDEX IF NOT EXISTS idx_delivery_jobs_dest ON delivery_jobs(destination_peer_id);
CREATE INDEX IF NOT EXISTS idx_delivery_jobs_source ON delivery_jobs(source_peer_id, source_message_id);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES delivery_jobs(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'TRANSIENT_ERROR', 'FLOOD_WAIT', 'PERMANENT_ERROR')),
    error_code TEXT,
    error_message TEXT,
    flood_wait_seconds INTEGER,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    attempted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_delivery_attempts_job ON delivery_attempts(job_id);

-- 11. Source-to-Destination Message Mappings (Edit/Delete Synchronization)
CREATE TABLE IF NOT EXISTS message_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_peer_id TEXT NOT NULL,
    source_message_id INTEGER NOT NULL,
    rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
    destination_peer_id TEXT NOT NULL,
    destination_message_id INTEGER NOT NULL,
    delivery_mode TEXT NOT NULL CHECK (delivery_mode IN ('FORWARD', 'COPY')),
    last_synced_caption TEXT,
    is_deleted_on_dest INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(source_peer_id, source_message_id, destination_peer_id, rule_id)
);
CREATE INDEX IF NOT EXISTS idx_message_mappings_source ON message_mappings(source_peer_id, source_message_id);

-- 12. Persistent Deduplication Records
CREATE TABLE IF NOT EXISTS deduplication_records (
    dedup_key TEXT PRIMARY KEY,
    scope TEXT NOT NULL CHECK (scope IN ('PER_RULE', 'PER_DESTINATION')),
    source_peer_id TEXT NOT NULL,
    source_message_id INTEGER NOT NULL,
    rule_id TEXT NOT NULL,
    destination_peer_id TEXT NOT NULL,
    job_id TEXT,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_dedup_source ON deduplication_records(source_peer_id, source_message_id);

-- 13. Source Processing Cursors (Missed-Message Catch-Up Tracking)
CREATE TABLE IF NOT EXISTS source_cursors (
    source_peer_id TEXT PRIMARY KEY,
    last_processed_message_id INTEGER NOT NULL DEFAULT 0,
    last_seen_message_id INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- 14. Historical Backfill Jobs
CREATE TABLE IF NOT EXISTS backfill_jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_peer_id TEXT NOT NULL,
    rule_id TEXT,
    mode TEXT NOT NULL CHECK (mode IN ('ALL_ACCESSIBLE', 'LAST_N', 'UNPROCESSED_ONLY', 'MESSAGE_ID_RANGE')),
    last_n_count INTEGER,
    start_message_id INTEGER,
    end_message_id INTEGER,
    direction TEXT NOT NULL DEFAULT 'OLDEST_FIRST' CHECK (direction IN ('OLDEST_FIRST', 'NEWEST_FIRST')),
    batch_size INTEGER NOT NULL DEFAULT 50,
    rate_limit_per_min INTEGER NOT NULL DEFAULT 30,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING', 'RUNNING', 'PAUSED', 'COMPLETED', 'STOPPED', 'FAILED')
    ),
    current_cursor_message_id INTEGER,
    total_estimated INTEGER NOT NULL DEFAULT 0,
    examined_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    forwarded_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_backfill_jobs_status ON backfill_jobs(status);

-- 15. Catch-Up Recovery Jobs
CREATE TABLE IF NOT EXISTS catchup_jobs (
    id TEXT PRIMARY KEY,
    source_peer_id TEXT NOT NULL,
    trigger_mode TEXT NOT NULL CHECK (trigger_mode IN ('AUTOMATIC_STARTUP', 'MANUAL')),
    from_message_id INTEGER NOT NULL,
    to_message_id INTEGER NOT NULL,
    current_cursor_message_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    estimated_gap INTEGER NOT NULL DEFAULT 0,
    processed_count INTEGER NOT NULL DEFAULT 0,
    enqueued_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT
);

-- 16. Application Operational Logs (Redacted, Indexed, Paginated)
CREATE TABLE IF NOT EXISTS app_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    level TEXT NOT NULL CHECK (level IN ('SUCCESS', 'SKIP', 'WARNING', 'FAILURE', 'INFO')),
    event_type TEXT NOT NULL,
    error_category TEXT,
    rule_id TEXT,
    source_peer_id TEXT,
    destination_peer_id TEXT,
    source_message_id INTEGER,
    operation TEXT NOT NULL,
    diagnostic_message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_events_timestamp ON app_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_app_events_level ON app_events(level);
CREATE INDEX IF NOT EXISTS idx_app_events_rule ON app_events(rule_id);
CREATE INDEX IF NOT EXISTS idx_app_events_source ON app_events(source_peer_id);

-- 17. Persistent Statistics Counters (Survive Log Cleanup)
CREATE TABLE IF NOT EXISTS stats_counters (
    counter_key TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('GLOBAL', 'RULE', 'DESTINATION')),
    scope_id TEXT NOT NULL,
    successful_deliveries INTEGER NOT NULL DEFAULT 0,
    skipped_messages INTEGER NOT NULL DEFAULT 0,
    failed_deliveries INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    total_latency_ms INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
INSERT OR IGNORE INTO stats_counters (counter_key, scope_type, scope_id) VALUES ('GLOBAL:ALL', 'GLOBAL', 'ALL');
