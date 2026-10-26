export type MediaCategory = 'MOVIE' | 'TV_SHOW' | 'COMBINED' | 'SPLIT';
export type CategoryMatchMode = 'ALL' | 'ANY';

export type MessageMediaType =
  | 'TEXT'
  | 'PHOTO'
  | 'VIDEO'
  | 'DOCUMENT'
  | 'AUDIO'
  | 'VOICE'
  | 'UNSUPPORTED';

export type MessageTypeFilter =
  | 'ALL'
  | 'TEXT_ONLY'
  | 'MEDIA_ONLY'
  | 'PHOTO'
  | 'VIDEO'
  | 'DOCUMENT'
  | 'AUDIO'
  | 'VOICE';

export type AlbumPolicy = 'PROCESS_ITEMS' | 'FIRST_ITEM_ONLY' | 'SKIP_ALBUMS';

export type SenderFilterMode =
  | 'ANY'
  | 'SPECIFIC_USER_IDS'
  | 'ADMINS_ONLY'
  | 'ANONYMOUS_ADMINS_ONLY'
  | 'VERIFIED_USERS_ONLY';

export type MissingSenderPolicy = 'REJECT' | 'ALLOW_IN_CHANNELS';

export type KeywordSearchTarget =
  | 'TEXT_ONLY'
  | 'CAPTION_ONLY'
  | 'FILENAME_ONLY'
  | 'TEXT_AND_CAPTION'
  | 'TEXT_CAPTION_AND_FILENAME';

export type MatchMode = 'ANY' | 'ALL';
export type MissingFileMetadataPolicy = 'FAIL_FILTER' | 'PASS_IF_NON_FILE';
export type DeliveryMode = 'FORWARD' | 'COPY';
export type DeduplicationScope = 'PER_RULE' | 'PER_DESTINATION';
export type ScheduleBehavior = 'ONLY_ARRIVING_DURING_WINDOW' | 'DEFER_UNTIL_WINDOW';

export type TelegramConnectionState =
  | 'NOT_CONFIGURED'
  | 'AWAITING_PHONE_NUMBER'
  | 'AWAITING_LOGIN_CODE'
  | 'AWAITING_TWO_STEP_PASSWORD'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'RECONNECTING'
  | 'AUTHENTICATION_EXPIRED'
  | 'DISCONNECTED'
  | 'ERROR';

export interface ReplaceStep {
  step_order: number;
  find_pattern: string;
  replace_with: string;
  is_regex: boolean;
  case_sensitive: boolean;
}

export interface CaptionTransformConfig {
  clean_filename_mode: boolean;
  remove_links: boolean;
  remove_usernames: boolean;
  remove_hashtags: boolean;
  remove_emojis: boolean;
  remove_decorative_symbols: boolean;
  strip_text_after_extension: boolean;
  preserve_multipart_suffix: boolean;
  custom_header: string;
  custom_footer: string;
  replacements: ReplaceStep[];
}

export interface RuleFilterConfig {
  message_type_filter: MessageTypeFilter;
  album_policy: AlbumPolicy;
  sender_filter_mode: SenderFilterMode;
  sender_user_ids: number[];
  missing_sender_policy: MissingSenderPolicy;
  required_keywords: string[];
  required_keywords_match_mode: MatchMode;
  excluded_keywords: string[];
  regex_pattern: string;
  regex_exclude_pattern: string;
  keyword_search_target: KeywordSearchTarget;
  case_sensitive: boolean;
  whole_word: boolean;
  min_file_size_mb: number | null;
  max_file_size_mb: number | null;
  filename_contains: string;
  filename_ends_with: string;
  filename_regex: string;
  accepted_extensions: string[];
  excluded_extensions: string[];
  missing_file_metadata_policy: MissingFileMetadataPolicy;
}

export interface RuleScheduleConfig {
  enabled: boolean;
  start_time: string;
  end_time: string;
  days: number[];
  timezone: string;
  behavior: ScheduleBehavior;
}

export interface RuleCategoryConfig {
  enabled: boolean;
  selected: MediaCategory[];
  match_mode: CategoryMatchMode;
}

export interface ForwardingRule {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  source_peer_id: string;
  destination_peer_ids: string[];
  priority: number;
  secondary_order: number;
  exclusive_stop: boolean;
  delivery_mode: DeliveryMode;
  delay_seconds: number;
  max_retries: number;
  sync_edits: boolean;
  sync_deletes: boolean;
  deduplication_override: 'GLOBAL' | 'PER_RULE' | 'PER_DESTINATION';
  schedule: RuleScheduleConfig;
  filters: RuleFilterConfig;
  categories: RuleCategoryConfig;
  caption_transform: CaptionTransformConfig;
  created_at?: string;
  updated_at?: string;
}

export interface CandidateMessage {
  message_id: number;
  source_peer_id: string;
  chat_type: 'CHANNEL' | 'SUPERGROUP' | 'GROUP' | 'PRIVATE';
  media_type: MessageMediaType;
  is_album: boolean;
  is_first_in_album: boolean;
  text: string | null;
  caption: string | null;
  filename: string | null;
  file_size_bytes: number | null;
  sender_user_id: number | null;
  sender_display_name?: string | null;
  is_sender_admin: boolean;
  is_anonymous_admin: boolean;
  is_sender_verified: boolean;
  has_protected_content?: boolean;
  timestamp_utc: string;
}

export interface RuleEvaluationReport {
  rule_id: string;
  rule_name: string;
  priority: number;
  matched: boolean;
  passed_conditions: string[];
  failed_conditions: string[];
  assigned_categories: MediaCategory[];
  classification_reasons: string[];
  target_destinations: string[];
  exclusive_stop_triggered: boolean;
  deferred_by_schedule: boolean;
  next_window_estimate?: string;
  transformed_caption: string | null;
}

export interface AppSettings {
  forwarding_enabled: boolean;
  resume_worker_on_restart: boolean;
  auto_catchup_on_startup: boolean;
  duplicate_protection_enabled: boolean;
  deduplication_scope: DeduplicationScope;
  global_send_delay_ms: number;
  min_send_interval_ms: number;
  delivery_concurrency: number;
  max_queue_depth: number;
  default_retry_count: number;
  log_retention_days: number;
  global_sync_edits: boolean;
  global_sync_deletes: boolean;
  theme: 'system' | 'light' | 'dark';
  default_timezone: string;
  updated_at?: string;
}
