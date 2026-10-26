import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import {
  AppSettings,
  CandidateMessage,
  DeduplicationScope,
  ForwardingRule,
  MediaCategory,
} from './types.js';
import {
  applyCaptionTransformations,
  buildDeduplicationKey,
  evaluateRuleAgainstMessage,
  sortRulesByPriority,
} from './engine.js';
import { redactDiagnosticMessage } from './security.js';

const DATA_DIR = path.resolve(process.cwd(), 'data');
if (!fs.existsSync(DATA_DIR)) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

const DB_FILE = process.env.SQLITE_PATH
  ? path.resolve(process.cwd(), process.env.SQLITE_PATH)
  : path.join(DATA_DIR, 'teleroute.db');

const dbDir = path.dirname(DB_FILE);
if (!fs.existsSync(dbDir)) {
  fs.mkdirSync(dbDir, { recursive: true });
}

export const db = new DatabaseSync(DB_FILE);

// Configure WAL mode, busy_timeout, and foreign_keys
db.exec('PRAGMA journal_mode = WAL;');
db.exec('PRAGMA synchronous = NORMAL;');
db.exec('PRAGMA busy_timeout = 5000;');
db.exec('PRAGMA foreign_keys = ON;');

// Run initial schema migration
const migrationPath = path.resolve(process.cwd(), 'migrations/0001_initial_schema.sql');
if (fs.existsSync(migrationPath)) {
  const migrationSql = fs.readFileSync(migrationPath, 'utf8');
  db.exec(migrationSql);
}

// ============================================================================
// Historical Source Message Store (for Backfill, Catch-up, and Rule Testing)
// ============================================================================

db.exec(`
CREATE TABLE IF NOT EXISTS source_messages_archive (
    source_peer_id TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    chat_type TEXT NOT NULL DEFAULT 'CHANNEL',
    media_type TEXT NOT NULL DEFAULT 'DOCUMENT',
    is_album INTEGER NOT NULL DEFAULT 0,
    is_first_in_album INTEGER NOT NULL DEFAULT 1,
    text TEXT,
    caption TEXT,
    filename TEXT,
    file_size_bytes INTEGER,
    sender_user_id INTEGER,
    sender_display_name TEXT,
    is_sender_admin INTEGER NOT NULL DEFAULT 0,
    is_anonymous_admin INTEGER NOT NULL DEFAULT 1,
    is_sender_verified INTEGER NOT NULL DEFAULT 0,
    has_protected_content INTEGER NOT NULL DEFAULT 0,
    timestamp_utc TEXT NOT NULL,
    PRIMARY KEY (source_peer_id, message_id)
);
`);

export function withTransaction<T>(fn: () => T): T {
  db.exec('BEGIN IMMEDIATE TRANSACTION;');
  try {
    const result = fn();
    db.exec('COMMIT;');
    return result;
  } catch (err) {
    try {
      db.exec('ROLLBACK;');
    } catch {
      // ignore rollback error
    }
    throw err;
  }
}

export function logAppEvent(params: {
  level: 'SUCCESS' | 'SKIP' | 'WARNING' | 'FAILURE' | 'INFO';
  event_type: string;
  error_category?: string | null;
  rule_id?: string | null;
  source_peer_id?: string | null;
  destination_peer_id?: string | null;
  source_message_id?: number | null;
  operation: string;
  diagnostic_message: string;
}): void {
  const redacted = redactDiagnosticMessage(params.diagnostic_message);
  const stmt = db.prepare(`
    INSERT INTO app_events (
      timestamp, level, event_type, error_category, rule_id,
      source_peer_id, destination_peer_id, source_message_id, operation, diagnostic_message
    ) VALUES (
      strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), ?, ?, ?, ?, ?, ?, ?, ?, ?
    )
  `);
  stmt.run(
    params.level,
    params.event_type,
    params.error_category ?? null,
    params.rule_id ?? null,
    params.source_peer_id ?? null,
    params.destination_peer_id ?? null,
    params.source_message_id ?? null,
    params.operation,
    redacted
  );
}

export function incrementStatsCounter(params: {
  ruleId?: string | null;
  destinationPeerId?: string | null;
  successful?: number;
  skipped?: number;
  failed?: number;
  retries?: number;
  latencyMs?: number;
}): void {
  const s = params.successful ?? 0;
  const sk = params.skipped ?? 0;
  const f = params.failed ?? 0;
  const r = params.retries ?? 0;
  const lat = params.latencyMs ?? 0;

  const upsert = db.prepare(`
    INSERT INTO stats_counters (
      counter_key, scope_type, scope_id,
      successful_deliveries, skipped_messages, failed_deliveries, retry_count, total_latency_ms, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    ON CONFLICT(counter_key) DO UPDATE SET
      successful_deliveries = successful_deliveries + excluded.successful_deliveries,
      skipped_messages = skipped_messages + excluded.skipped_messages,
      failed_deliveries = failed_deliveries + excluded.failed_deliveries,
      retry_count = retry_count + excluded.retry_count,
      total_latency_ms = total_latency_ms + excluded.total_latency_ms,
      updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
  `);

  upsert.run('GLOBAL:ALL', 'GLOBAL', 'ALL', s, sk, f, r, lat);
  if (params.ruleId) {
    upsert.run(`RULE:${params.ruleId}`, 'RULE', params.ruleId, s, sk, f, r, lat);
  }
  if (params.destinationPeerId) {
    upsert.run(
      `DESTINATION:${params.destinationPeerId}`,
      'DESTINATION',
      params.destinationPeerId,
      s,
      sk,
      f,
      r,
      lat
    );
  }
}

export function getAppSettings(): AppSettings {
  const row = db.prepare('SELECT * FROM app_settings WHERE id = 1').get() as any;
  return {
    forwarding_enabled: Boolean(row.forwarding_enabled),
    resume_worker_on_restart: Boolean(row.resume_worker_on_restart),
    auto_catchup_on_startup: Boolean(row.auto_catchup_on_startup),
    duplicate_protection_enabled: Boolean(row.duplicate_protection_enabled),
    deduplication_scope: row.deduplication_scope as DeduplicationScope,
    global_send_delay_ms: Number(row.global_send_delay_ms),
    min_send_interval_ms: Number(row.min_send_interval_ms),
    delivery_concurrency: Number(row.delivery_concurrency),
    max_queue_depth: Number(row.max_queue_depth),
    default_retry_count: Number(row.default_retry_count),
    log_retention_days: Number(row.log_retention_days),
    global_sync_edits: Boolean(row.global_sync_edits),
    global_sync_deletes: Boolean(row.global_sync_deletes),
    theme: row.theme as 'system' | 'light' | 'dark',
    default_timezone: row.default_timezone || 'UTC',
    updated_at: row.updated_at,
  };
}

export function updateAppSettings(patch: Partial<AppSettings>): AppSettings {
  const current = getAppSettings();
  const merged = { ...current, ...patch };
  db.prepare(`
    UPDATE app_settings SET
      forwarding_enabled = ?,
      resume_worker_on_restart = ?,
      auto_catchup_on_startup = ?,
      duplicate_protection_enabled = ?,
      deduplication_scope = ?,
      global_send_delay_ms = ?,
      min_send_interval_ms = ?,
      delivery_concurrency = ?,
      max_queue_depth = ?,
      default_retry_count = ?,
      log_retention_days = ?,
      global_sync_edits = ?,
      global_sync_deletes = ?,
      theme = ?,
      default_timezone = ?,
      updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id = 1
  `).run(
    merged.forwarding_enabled ? 1 : 0,
    merged.resume_worker_on_restart ? 1 : 0,
    merged.auto_catchup_on_startup ? 1 : 0,
    merged.duplicate_protection_enabled ? 1 : 0,
    merged.deduplication_scope,
    Math.max(0, Number(merged.global_send_delay_ms)),
    Math.max(0, Number(merged.min_send_interval_ms)),
    Math.max(1, Math.min(10, Number(merged.delivery_concurrency))),
    Math.max(50, Math.min(50000, Number(merged.max_queue_depth))),
    Math.max(0, Math.min(10, Number(merged.default_retry_count))),
    Math.max(1, Math.min(365, Number(merged.log_retention_days))),
    merged.global_sync_edits ? 1 : 0,
    merged.global_sync_deletes ? 1 : 0,
    merged.theme,
    merged.default_timezone || 'UTC'
  );
  return getAppSettings();
}

// ============================================================================
// Normalized Rule Persistence (5 Child Tables + Main Table)
// ============================================================================

export function getAllRules(): ForwardingRule[] {
  const rows = db
    .prepare(
      'SELECT * FROM rules ORDER BY priority DESC, secondary_order ASC, id ASC'
    )
    .all() as any[];

  return rows.map((r) => hydrateRuleRow(r));
}

export function getRuleById(id: string): ForwardingRule | null {
  const row = db.prepare('SELECT * FROM rules WHERE id = ?').get(id) as any;
  if (!row) return null;
  return hydrateRuleRow(row);
}

function hydrateRuleRow(r: any): ForwardingRule {
  const destRows = db
    .prepare(
      'SELECT destination_peer_id FROM rule_destinations WHERE rule_id = ? ORDER BY sort_order ASC'
    )
    .all(r.id) as any[];
  const filterRow = (db
    .prepare('SELECT * FROM rule_filters WHERE rule_id = ?')
    .get(r.id) as any) || {};
  const catRow = (db
    .prepare('SELECT * FROM rule_category_settings WHERE rule_id = ?')
    .get(r.id) as any) || {};
  const tfRow = (db
    .prepare('SELECT * FROM rule_caption_transforms WHERE rule_id = ?')
    .get(r.id) as any) || {};
  const repRows = db
    .prepare(
      'SELECT * FROM rule_replace_steps WHERE rule_id = ? ORDER BY step_order ASC'
    )
    .all(r.id) as any[];

  const parseCsv = (csv?: string): string[] =>
    (csv ?? '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

  return {
    id: r.id,
    name: r.name,
    description: r.description ?? '',
    enabled: Boolean(r.enabled),
    source_peer_id: r.source_peer_id,
    destination_peer_ids: destRows.map((d) => String(d.destination_peer_id)),
    priority: Number(r.priority),
    secondary_order: Number(r.secondary_order),
    exclusive_stop: Boolean(r.exclusive_stop),
    delivery_mode: r.delivery_mode,
    delay_seconds: Number(r.delay_seconds),
    max_retries: Number(r.max_retries),
    sync_edits: Boolean(r.sync_edits),
    sync_deletes: Boolean(r.sync_deletes),
    deduplication_override: (r.deduplication_override || 'GLOBAL') as any,
    schedule: {
      enabled: Boolean(r.schedule_enabled),
      start_time: r.schedule_start_time || '00:00',
      end_time: r.schedule_end_time || '23:59',
      days: parseCsv(r.schedule_days_csv).map((n) => Number(n)),
      timezone: r.schedule_timezone || 'UTC',
      behavior: r.schedule_behavior || 'DEFER_UNTIL_WINDOW',
    },
    filters: {
      message_type_filter: filterRow.message_type_filter || 'ALL',
      album_policy: filterRow.album_policy || 'PROCESS_ITEMS',
      sender_filter_mode: filterRow.sender_filter_mode || 'ANY',
      sender_user_ids: parseCsv(filterRow.sender_user_ids_csv).map((n) => Number(n)),
      missing_sender_policy: filterRow.missing_sender_policy || 'ALLOW_IN_CHANNELS',
      required_keywords: parseCsv(filterRow.required_keywords_csv),
      required_keywords_match_mode: filterRow.required_keywords_match_mode || 'ANY',
      excluded_keywords: parseCsv(filterRow.excluded_keywords_csv),
      regex_pattern: filterRow.regex_pattern ?? '',
      regex_exclude_pattern: filterRow.regex_exclude_pattern ?? '',
      keyword_search_target: filterRow.keyword_search_target || 'TEXT_AND_CAPTION',
      case_sensitive: Boolean(filterRow.case_sensitive),
      whole_word: Boolean(filterRow.whole_word),
      min_file_size_mb:
        filterRow.min_file_size_bytes !== null && filterRow.min_file_size_bytes !== undefined
          ? Math.round((Number(filterRow.min_file_size_bytes) / (1024 * 1024)) * 100) / 100
          : null,
      max_file_size_mb:
        filterRow.max_file_size_bytes !== null && filterRow.max_file_size_bytes !== undefined
          ? Math.round((Number(filterRow.max_file_size_bytes) / (1024 * 1024)) * 100) / 100
          : null,
      filename_contains: filterRow.filename_contains ?? '',
      filename_ends_with: filterRow.filename_ends_with ?? '',
      filename_regex: filterRow.filename_regex ?? '',
      accepted_extensions: parseCsv(filterRow.accepted_extensions_csv),
      excluded_extensions: parseCsv(filterRow.excluded_extensions_csv),
      missing_file_metadata_policy: filterRow.missing_file_metadata_policy || 'FAIL_FILTER',
    },
    categories: {
      enabled: Boolean(catRow.categories_enabled),
      selected: parseCsv(catRow.selected_categories_csv) as MediaCategory[],
      match_mode: catRow.category_match_mode || 'ANY',
    },
    caption_transform: {
      clean_filename_mode: Boolean(tfRow.clean_filename_mode),
      remove_links: Boolean(tfRow.remove_links),
      remove_usernames: Boolean(tfRow.remove_usernames),
      remove_hashtags: Boolean(tfRow.remove_hashtags),
      remove_emojis: Boolean(tfRow.remove_emojis),
      remove_decorative_symbols: Boolean(tfRow.remove_decorative_symbols),
      strip_text_after_extension: Boolean(tfRow.strip_Text_after_extension),
      preserve_multipart_suffix:
        tfRow.preserve_multipart_suffix === undefined
          ? true
          : Boolean(tfRow.preserve_multipart_suffix),
      custom_header: tfRow.custom_header ?? '',
      custom_footer: tfRow.custom_footer ?? '',
      replacements: repRows.map((s) => ({
        step_order: Number(s.step_order),
        find_pattern: s.find_pattern,
        replace_with: s.replace_with ?? '',
        is_regex: Boolean(s.is_regex),
        case_sensitive: Boolean(s.case_sensitive),
      })),
    },
    created_at: r.created_at,
    updated_at: r.updated_at,
  };
}

export function saveRuleTransactional(rule: ForwardingRule): ForwardingRule {
  return withTransaction(() => {
    db.prepare(`
      INSERT INTO rules (
        id, name, description, enabled, source_peer_id, priority, secondary_order,
        exclusive_stop, delivery_mode, delay_seconds, max_retries, sync_edits, sync_deletes,
        deduplication_override, schedule_enabled, schedule_start_time, schedule_end_time,
        schedule_days_csv, schedule_timezone, schedule_behavior, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
      ON CONFLICT(id) DO UPDATE SET
        name = excluded.name,
        description = excluded.description,
        enabled = excluded.enabled,
        source_peer_id = excluded.source_peer_id,
        priority = excluded.priority,
        secondary_order = excluded.secondary_order,
        exclusive_stop = excluded.exclusive_stop,
        delivery_mode = excluded.delivery_mode,
        delay_seconds = excluded.delay_seconds,
        max_retries = excluded.max_retries,
        sync_edits = excluded.sync_edits,
        sync_deletes = excluded.sync_deletes,
        deduplication_override = excluded.deduplication_override,
        schedule_enabled = excluded.schedule_enabled,
        schedule_start_time = excluded.schedule_start_time,
        schedule_end_time = excluded.schedule_end_time,
        schedule_days_csv = excluded.schedule_days_csv,
        schedule_timezone = excluded.schedule_timezone,
        schedule_behavior = excluded.schedule_behavior,
        updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    `).run(
      rule.id,
      rule.name.trim(),
      rule.description ?? '',
      rule.enabled ? 1 : 0,
      rule.source_peer_id.trim(),
      Math.max(0, Math.min(100, Number(rule.priority))),
      Number(rule.secondary_order ?? 0),
      rule.exclusive_stop ? 1 : 0,
      rule.delivery_mode,
      Math.max(0, Math.min(120, Number(rule.delay_seconds))),
      Math.max(0, Math.min(10, Number(rule.max_retries))),
      rule.sync_edits ? 1 : 0,
      rule.sync_deletes ? 1 : 0,
      rule.deduplication_override || 'GLOBAL',
      rule.schedule.enabled ? 1 : 0,
      rule.schedule.start_time || '00:00',
      rule.schedule.end_time || '23:59',
      (rule.schedule.days ?? [0, 1, 2, 3, 4, 5, 6]).join(','),
      rule.schedule.timezone || 'UTC',
      rule.schedule.behavior || 'DEFER_UNTIL_WINDOW'
    );

    // Destinations
    db.prepare('DELETE FROM rule_destinations WHERE rule_id = ?').run(rule.id);
    const insDest = db.prepare(
      'INSERT INTO rule_destinations (rule_id, destination_peer_id, sort_order) VALUES (?, ?, ?)'
    );
    const uniqueDests = Array.from(
      new Set((rule.destination_peer_ids ?? []).map((d) => d.trim()).filter(Boolean))
    );
    uniqueDests.forEach((peerId, idx) => {
      insDest.run(rule.id, peerId, idx);
    });

    // Filters
    const minBytes =
      rule.filters.min_file_size_mb !== null &&
      rule.filters.min_file_size_mb !== undefined &&
      Number(rule.filters.min_file_size_mb) > 0
        ? Math.round(Number(rule.filters.min_file_size_mb) * 1024 * 1024)
        : null;
    const maxBytes =
      rule.filters.max_file_size_mb !== null &&
      rule.filters.max_file_size_mb !== undefined &&
      Number(rule.filters.max_file_size_mb) > 0
        ? Math.round(Number(rule.filters.max_file_size_mb) * 1024 * 1024)
        : null;

    db.prepare('DELETE FROM rule_filters WHERE rule_id = ?').run(rule.id);
    db.prepare(`
      INSERT INTO rule_filters (
        rule_id, message_type_filter, album_policy, sender_filter_mode, sender_user_ids_csv,
        missing_sender_policy, required_keywords_csv, required_keywords_match_mode,
        excluded_keywords_csv, regex_pattern, regex_exclude_pattern, keyword_search_target,
        case_sensitive, whole_word, min_file_size_bytes, max_file_size_bytes,
        filename_contains, filename_ends_with, filename_regex,
        accepted_extensions_csv, excluded_extensions_csv, missing_file_metadata_policy
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      rule.id,
      rule.filters.message_type_filter || 'ALL',
      rule.filters.album_policy || 'PROCESS_ITEMS',
      rule.filters.sender_filter_mode || 'ANY',
      (rule.filters.sender_user_ids ?? []).join(','),
      rule.filters.missing_sender_policy || 'ALLOW_IN_CHANNELS',
      (rule.filters.required_keywords ?? []).join(','),
      rule.filters.required_keywords_match_mode || 'ANY',
      (rule.filters.excluded_keywords ?? []).join(','),
      rule.filters.regex_pattern ?? '',
      rule.filters.regex_exclude_pattern ?? '',
      rule.filters.keyword_search_target || 'TEXT_AND_CAPTION',
      rule.filters.case_sensitive ? 1 : 0,
      rule.filters.whole_word ? 1 : 0,
      minBytes,
      maxBytes,
      rule.filters.filename_contains ?? '',
      rule.filters.filename_ends_with ?? '',
      rule.filters.filename_regex ?? '',
      (rule.filters.accepted_extensions ?? []).join(','),
      (rule.filters.excluded_extensions ?? []).join(','),
      rule.filters.missing_file_metadata_policy || 'FAIL_FILTER'
    );

    // Categories
    db.prepare('DELETE FROM rule_category_settings WHERE rule_id = ?').run(rule.id);
    db.prepare(`
      INSERT INTO rule_category_settings (rule_id, categories_enabled, selected_categories_csv, category_match_mode)
      VALUES (?, ?, ?, ?)
    `).run(
      rule.id,
      rule.categories.enabled ? 1 : 0,
      (rule.categories.selected ?? []).join(','),
      rule.categories.match_mode || 'ANY'
    );

    // Caption Transforms
    db.prepare('DELETE FROM rule_caption_transforms WHERE rule_id = ?').run(rule.id);
    db.prepare(`
      INSERT INTO rule_caption_transforms (
        rule_id, clean_filename_mode, remove_links, remove_usernames, remove_hashtags,
        remove_emojis, remove_decorative_symbols, strip_Text_after_extension,
        preserve_multipart_suffix, custom_header, custom_footer
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      rule.id,
      rule.caption_transform.clean_filename_mode ? 1 : 0,
      rule.caption_transform.remove_links ? 1 : 0,
      rule.caption_transform.remove_usernames ? 1 : 0,
      rule.caption_transform.remove_hashtags ? 1 : 0,
      rule.caption_transform.remove_emojis ? 1 : 0,
      rule.caption_transform.remove_decorative_symbols ? 1 : 0,
      rule.caption_transform.strip_text_after_extension ? 1 : 0,
      rule.caption_transform.preserve_multipart_suffix ? 1 : 0,
      rule.caption_transform.custom_header ?? '',
      rule.caption_transform.custom_footer ?? ''
    );

    // Replace Steps
    db.prepare('DELETE FROM rule_replace_steps WHERE rule_id = ?').run(rule.id);
    const insStep = db.prepare(`
      INSERT INTO rule_replace_steps (rule_id, step_order, find_pattern, replace_with, is_regex, case_sensitive)
      VALUES (?, ?, ?, ?, ?, ?)
    `);
    (rule.caption_transform.replacements ?? []).forEach((s, idx) => {
      if (s.find_pattern) {
        insStep.run(
          rule.id,
          s.step_order ?? idx + 1,
          s.find_pattern,
          s.replace_with ?? '',
          s.is_regex ? 1 : 0,
          s.case_sensitive ? 1 : 0
        );
      }
    });

    return getRuleById(rule.id)!;
  });
}

// ============================================================================
// Routing & Durable Queue Enqueueing
// ============================================================================

export function routeAndEnqueueMessage(
  msg: CandidateMessage,
  originType: 'LIVE' | 'BACKFILL' | 'CATCHUP' | 'LIVE_TEST' = 'LIVE',
  backfillJobId?: string | null,
  updateCursor = true
): {
  matchedRulesCount: number;
  enqueuedJobIds: string[];
  skippedDuplicates: number;
  stoppedByExclusiveRuleId: string | null;
} {
  return withTransaction(() => {
    const settings = getAppSettings();
    const allRules = sortRulesByPriority(getAllRules()).filter(
      (r) => r.enabled && r.source_peer_id === msg.source_peer_id
    );

    let matchedRulesCount = 0;
    const enqueuedJobIds: string[] = [];
    let skippedDuplicates = 0;
    let stoppedByExclusiveRuleId: string | null = null;

    const currentQueueDepthRow = db
      .prepare(
        "SELECT COUNT(*) AS cnt FROM delivery_jobs WHERE status IN ('PENDING', 'PROCESSING', 'RETRY_SCHEDULED')"
      )
      .get() as any;
    let currentDepth = Number(currentQueueDepthRow?.cnt ?? 0);

    for (const rule of allRules) {
      const report = evaluateRuleAgainstMessage(rule, msg, new Date());
      if (!report.matched) {
        // Non-matching rule NEVER blocks lower-priority rules
        continue;
      }

      matchedRulesCount++;

      const effectiveScope: DeduplicationScope =
        rule.deduplication_override && rule.deduplication_override !== 'GLOBAL'
          ? rule.deduplication_override
          : settings.deduplication_scope;

      for (const destPeerId of rule.destination_peer_ids) {
        const dedupKey = buildDeduplicationKey(
          effectiveScope,
          msg.source_peer_id,
          msg.message_id,
          rule.id,
          destPeerId
        );

        if (settings.duplicate_protection_enabled) {
          const existingDedup = db
            .prepare('SELECT dedup_key FROM deduplication_records WHERE dedup_key = ?')
            .get(dedupKey);
          if (existingDedup) {
            skippedDuplicates++;
            incrementStatsCounter({
              ruleId: rule.id,
              destinationPeerId: destPeerId,
              skipped: 1,
            });
            logAppEvent({
              level: 'SKIP',
              event_type: 'DUPLICATE_SKIPPED',
              rule_id: rule.id,
              source_peer_id: msg.source_peer_id,
              destination_peer_id: destPeerId,
              source_message_id: msg.message_id,
              operation: 'DEDUPLICATION',
              diagnostic_message: `Skipped duplicate delivery (${effectiveScope} key: ${dedupKey})`,
            });
            continue;
          }
        }

        if (currentDepth >= settings.max_queue_depth) {
          logAppEvent({
            level: 'WARNING',
            event_type: 'QUEUE_BACKPRESSURE',
            error_category: 'QUEUE_FULL',
            rule_id: rule.id,
            source_peer_id: msg.source_peer_id,
            destination_peer_id: destPeerId,
            source_message_id: msg.message_id,
            operation: 'QUEUE_ENQUEUE',
            diagnostic_message: `Delivery queue depth limit (${settings.max_queue_depth}) reached; applying backpressure`,
          });
          continue;
        }

        const jobId = `job-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        const idempotencyKey = `IDEMP:${msg.source_peer_id}:${msg.message_id}:${rule.id}:${destPeerId}`;
        const delayMs = (rule.delay_seconds ?? 0) * 1000 + settings.global_send_delay_ms;
        const nextEligible = new Date(Date.now() + delayMs).toISOString();

        db.prepare(`
          INSERT OR IGNORE INTO delivery_jobs (
            id, idempotency_key, source_peer_id, source_message_id, rule_id,
            destination_peer_id, delivery_mode, status, transformed_caption,
            media_type, filename, file_size_bytes, detected_categories_csv,
            attempt_count, max_retries, next_eligible_at, origin_type, backfill_job_id
          ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
        `).run(
          jobId,
          idempotencyKey,
          msg.source_peer_id,
          msg.message_id,
          rule.id,
          destPeerId,
          rule.delivery_mode,
          report.transformed_caption ?? null,
          msg.media_type,
          msg.filename ?? null,
          msg.file_size_bytes ?? null,
          report.assigned_categories.join(','),
          rule.max_retries,
          nextEligible,
          originType,
          backfillJobId ?? null
        );

        if (settings.duplicate_protection_enabled) {
          db.prepare(`
            INSERT OR IGNORE INTO deduplication_records (
              dedup_key, scope, source_peer_id, source_message_id, rule_id, destination_peer_id, job_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
          `).run(
            dedupKey,
            effectiveScope,
            msg.source_peer_id,
            msg.message_id,
            rule.id,
            destPeerId,
            jobId
          );
        }

        enqueuedJobIds.push(jobId);
        currentDepth++;
      }

      if (rule.exclusive_stop) {
        stoppedByExclusiveRuleId = rule.id;
        logAppEvent({
          level: 'INFO',
          event_type: 'EXCLUSIVE_STOP',
          rule_id: rule.id,
          source_peer_id: msg.source_peer_id,
          source_message_id: msg.message_id,
          operation: 'RULE_EVALUATION',
          diagnostic_message: `Rule '${rule.name}' (priority ${rule.priority}) matched with exclusive_stop=true; halted lower-priority rules`,
        });
        break;
      }
    }

    if (updateCursor) {
      db.prepare(`
        INSERT INTO source_cursors (source_peer_id, last_processed_message_id, last_seen_message_id, updated_at)
        VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        ON CONFLICT(source_peer_id) DO UPDATE SET
          last_processed_message_id = MAX(last_processed_message_id, excluded.last_processed_message_id),
          last_seen_message_id = MAX(last_seen_message_id, excluded.last_seen_message_id),
          updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
      `).run(msg.source_peer_id, msg.message_id, msg.message_id);
    }

    return {
      matchedRulesCount,
      enqueuedJobIds,
      skippedDuplicates,
      stoppedByExclusiveRuleId,
    };
  });
}

// ============================================================================
// Seed Realistic Initial Accessible Chats, Rules & Historical Archive Messages
// ============================================================================

export function ensureInitialDataSeeded(): void {
  const chatCountRow = db.prepare('SELECT COUNT(*) AS cnt FROM chats').get() as any;
  if (Number(chatCountRow?.cnt ?? 0) === 0) {
    const insChat = db.prepare(`
      INSERT INTO chats (
        peer_id, access_hash, chat_type, title, username,
        can_read, can_send, can_edit, can_delete, is_accessible,
        member_count, last_message_id, permission_error
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    insChat.run(
      '-1001000000001',
      '8819201928371',
      'CHANNEL',
      'Scene Releases Raw Feed (Source)',
      'scene_raw_ingest',
      1,
      0,
      0,
      0,
      1,
      48210,
      1028,
      null
    );
    insChat.run(
      '-1001000000002',
      '7718293817264',
      'SUPERGROUP',
      'Private Encoders & Remux Collectors',
      'remux_encoders_hq',
      1,
      1,
      1,
      1,
      1,
      1420,
      512,
      null
    );
    insChat.run(
      '-1002000000101',
      '9918273645123',
      'CHANNEL',
      'Vault Cinema — Curated Movies (Dest)',
      'vault_cinema_movies',
      1,
      1,
      1,
      1,
      1,
      9340,
      410,
      null
    );
    insChat.run(
      '-1002000000202',
      '6617283948571',
      'CHANNEL',
      'Vault 4K UHD & Remux Archive (Dest)',
      'vault_uhd_remux',
      1,
      1,
      1,
      1,
      1,
      6180,
      195,
      null
    );
    insChat.run(
      '-1002000000303',
      '5516273849501',
      'CHANNEL',
      'Vault TV Series & Season Packs (Dest)',
      'vault_tv_archive',
      1,
      1,
      1,
      1,
      1,
      7850,
      622,
      null
    );
    insChat.run(
      '-1002000000304',
      '4415263748592',
      'SUPERGROUP',
      'Multipart Split Archives Staging (Dest)',
      null,
      1,
      1,
      1,
      1,
      1,
      310,
      88,
      null
    );
    insChat.run(
      '-1009999999999',
      null,
      'CHANNEL',
      'Restricted Read-Only Partner Feed',
      'restricted_partner',
      1,
      0,
      0,
      0,
      1,
      12900,
      305,
      'CHAT_WRITE_FORBIDDEN: Account lacks post_messages permission in this broadcast channel'
    );
  }

  // Seed historical messages in source_messages_archive for Backfill & Catch-Up testing
  const msgCountRow = db
    .prepare('SELECT COUNT(*) AS cnt FROM source_messages_archive')
    .get() as any;
  if (Number(msgCountRow?.cnt ?? 0) === 0) {
    const insMsg = db.prepare(`
      INSERT INTO source_messages_archive (
        source_peer_id, message_id, chat_type, media_type, is_album, is_first_in_album,
        text, caption, filename, file_size_bytes, sender_user_id, sender_display_name,
        is_sender_admin, is_anonymous_admin, is_sender_verified, has_protected_content, timestamp_utc
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    const archiveSample: Array<[
      string,
      number,
      string,
      string,
      string | null,
      string | null,
      string | null,
      number | null,
      number | null,
      number,
      string
    ]> = [
      [
        '-1001000000001',
        1001,
        'CHANNEL',
        'DOCUMENT',
        null,
        '🔥 [TG] Oppenheimer.2023.2160p.UHD.BluRay.Remux.HEVC.Atmos.mkv Join @scene_raw_ingest https://t.me/promo #uhd #remux Fast mirror!',
        'Oppenheimer.2023.2160p.UHD.BluRay.Remux.HEVC.Atmos.mkv',
        64_500_000_000,
        null,
        1,
        '2026-10-25T20:10:00Z',
      ],
      [
        '-1001000000001',
        1002,
        'CHANNEL',
        'VIDEO',
        null,
        '🎬 Dune.Part.Two.2024.1080p.BluRay.x264-SPARKS.mkv @scene_raw_ingest https://t.me/joinchat/xyz',
        'Dune.Part.Two.2024.1080p.BluRay.x264-SPARKS.mkv',
        12_800_000_000,
        null,
        1,
        '2026-10-25T20:25:00Z',
      ],
      [
        '-1001000000001',
        1003,
        'CHANNEL',
        'DOCUMENT',
        null,
        'Oppenheimer.2023.2160p.sample.mkv Promo sample clip',
        'Oppenheimer.2023.2160p.sample.mkv',
        120_000_000,
        null,
        1,
        '2026-10-25T20:30:00Z',
      ],
      [
        '-1001000000001',
        1004,
        'CHANNEL',
        'DOCUMENT',
        null,
        '📺 Severance.S02E01.2160p.ATVP.WEB-DL.DDP5.1.Atmos.DV.HEVC.mkv @scene_raw_ingest #Severance',
        'Severance.S02E01.2160p.ATVP.WEB-DL.DDP5.1.Atmos.DV.HEVC.mkv',
        5_400_000_000,
        null,
        1,
        '2026-10-25T21:00:00Z',
      ],
      [
        '-1001000000001',
        1005,
        'CHANNEL',
        'DOCUMENT',
        null,
        '📦 The.Bear.S03.COMPLETE.1080p.HULU.WEB-DL.x265-PACK @scene_raw_ingest',
        'The.Bear.S03.COMPLETE.1080p.HULU.WEB-DL.x265.mkv',
        19_200_000_000,
        null,
        1,
        '2026-10-25T21:15:00Z',
      ],
      [
        '-1001000000001',
        1006,
        'CHANNEL',
        'DOCUMENT',
        null,
        '📦 Shogun.2024.S01E01-E10.COMPLETE.2160p.WEB-DL.HEVC.mkv.001 Multipart Volume 1 @scene_raw_ingest',
        'Shogun.2024.S01E01-E10.COMPLETE.2160p.WEB-DL.HEVC.mkv.001',
        20_000_000_000,
        null,
        1,
        '2026-10-25T21:40:00Z',
      ],
      [
        '-1001000000001',
        1007,
        'CHANNEL',
        'DOCUMENT',
        null,
        '🎬 Blade.Runner.2049.2017.2160p.UHD.BluRay.Remux.mkv.001 Split Archive Part 1',
        'Blade.Runner.2049.2017.2160p.UHD.BluRay.Remux.mkv.001',
        25_000_000_000,
        null,
        1,
        '2026-10-25T22:00:00Z',
      ],
      [
        '-1001000000001',
        1008,
        'CHANNEL',
        'TEXT',
        'Channel maintenance announcement: New 4K encoders online tonight.',
        null,
        null,
        null,
        null,
        1,
        '2026-10-25T22:30:00Z',
      ],
      [
        '-1001000000001',
        1009,
        'CHANNEL',
        'VIDEO',
        null,
        '🎬 Civil.War.2024.2160p.UHD.BluRay.x265-SURCODE.mkv Follow @scene_raw_ingest https://t.me/ad_link #4k',
        'Civil.War.2024.2160p.UHD.BluRay.x265-SURCODE.mkv',
        16_400_000_000,
        null,
        1,
        '2026-10-26T01:15:00Z',
      ],
      [
        '-1001000000001',
        1010,
        'CHANNEL',
        'DOCUMENT',
        null,
        '📺 House.of.the.Dragon.S02E08.1080p.WEB-DL.DDP5.1.H.264.mkv @scene_raw_ingest',
        'House.of.the.Dragon.S02E08.1080p.WEB-DL.DDP5.1.H.264.mkv',
        3_800_000_000,
        null,
        1,
        '2026-10-26T02:00:00Z',
      ],
      [
        '-1001000000001',
        1011,
        'CHANNEL',
        'DOCUMENT',
        null,
        '🎬 Nosferatu.2024.2160p.MA.WEB-DL.DDP5.1.Atmos.DV.HDR.H.265.mkv @scene_raw_ingest https://t.me/promo',
        'Nosferatu.2024.2160p.MA.WEB-DL.DDP5.1.Atmos.DV.HDR.H.265.mkv',
        21_300_000_000,
        null,
        1,
        '2026-10-26T02:45:00Z',
      ],
      [
        '-1001000000001',
        1012,
        'CHANNEL',
        'DOCUMENT',
        null,
        '📺 Silo.S02E04.2160p.ATVP.WEB-DL.DDP5.1.Atmos.HEVC.mkv.001 Split Episode Part 1',
        'Silo.S02E04.2160p.ATVP.WEB-DL.DDP5.1.Atmos.HEVC.mkv.001',
        4_200_000_000,
        null,
        1,
        '2026-10-26T03:10:00Z',
      ],
    ];

    for (const item of archiveSample) {
      insMsg.run(
        item[0],
        item[1],
        item[2],
        item[3],
        0,
        1,
        item[4],
        item[5],
        item[6],
        item[7],
        item[8],
        'SceneRawBot',
        item[9],
        1,
        0,
        0,
        item[10]
      );
    }

    // Set initial source cursor at 1008 so messages 1009..1012 show as a real 4-message catch-up gap!
    db.prepare(`
      INSERT OR IGNORE INTO source_cursors (source_peer_id, last_processed_message_id, last_seen_message_id)
      VALUES ('-1001000000001', 1008, 1012)
    `).run();
  }

  // Seed initial active routing rules if rules table is empty
  const rulesCountRow = db.prepare('SELECT COUNT(*) AS cnt FROM rules').get() as any;
  if (Number(rulesCountRow?.cnt ?? 0) === 0) {
    saveRuleTransactional({
      id: 'rule-uhd-movies-clean',
      name: '01. 2160p UHD Movies — Clean Copy',
      description:
        'Routes standalone 2160p/UHD Movie releases >= 500 MB in Copy mode with automatic caption cleanup to Vault 4K UHD & Cinema channels.',
      enabled: true,
      source_peer_id: '-1001000000001',
      destination_peer_ids: ['-1002000000101', '-1002000000202'],
      priority: 90,
      secondary_order: 1,
      exclusive_stop: true,
      delivery_mode: 'COPY',
      delay_seconds: 1,
      max_retries: 3,
      sync_edits: true,
      sync_deletes: true,
      deduplication_override: 'PER_DESTINATION',
      schedule: {
        enabled: false,
        start_time: '00:00',
        end_time: '23:59',
        days: [0, 1, 2, 3, 4, 5, 6],
        timezone: 'UTC',
        behavior: 'DEFER_UNTIL_WINDOW',
      },
      filters: {
        message_type_filter: 'MEDIA_ONLY',
        album_policy: 'PROCESS_ITEMS',
        sender_filter_mode: 'ANY',
        sender_user_ids: [],
        missing_sender_policy: 'ALLOW_IN_CHANNELS',
        required_keywords: ['2160p', 'UHD', '4K'],
        required_keywords_match_mode: 'ANY',
        excluded_keywords: ['sample', 'trailer', 'camrip'],
        regex_pattern: '',
        regex_exclude_pattern: '',
        keyword_search_target: 'TEXT_CAPTION_AND_FILENAME',
        case_sensitive: false,
        whole_word: false,
        min_file_size_mb: 500,
        max_file_size_mb: null,
        filename_contains: '',
        filename_ends_with: '',
        filename_regex: '',
        accepted_extensions: ['.mkv', '.mp4'],
        excluded_extensions: ['.exe', '.txt'],
        missing_file_metadata_policy: 'FAIL_FILTER',
      },
      categories: {
        enabled: true,
        selected: ['MOVIE'],
        match_mode: 'ALL',
      },
      caption_transform: {
        clean_filename_mode: false,
        remove_links: true,
        remove_usernames: true,
        remove_hashtags: true,
        remove_emojis: true,
        remove_decorative_symbols: true,
        strip_text_after_extension: true,
        preserve_multipart_suffix: true,
        custom_header: '[Vault 4K UHD Cinema]',
        custom_footer: 'Verified Lossless / HDR Index',
        replacements: [
          {
            step_order: 1,
            find_pattern: '\\[TG\\]',
            replace_with: '',
            is_regex: true,
            case_sensitive: false,
          },
        ],
      },
    });

    saveRuleTransactional({
      id: 'rule-tv-shows-and-packs',
      name: '02. TV Episodes & Complete Season Packs',
      description:
        'Routes TV_SHOW and COMBINED season packs to Vault TV Series Archive with cleaned captions.',
      enabled: true,
      source_peer_id: '-1001000000001',
      destination_peer_ids: ['-1002000000303'],
      priority: 80,
      secondary_order: 2,
      exclusive_stop: false,
      delivery_mode: 'COPY',
      delay_seconds: 1,
      max_retries: 3,
      sync_edits: true,
      sync_deletes: true,
      deduplication_override: 'PER_DESTINATION',
      schedule: {
        enabled: false,
        start_time: '00:00',
        end_time: '23:59',
        days: [0, 1, 2, 3, 4, 5, 6],
        timezone: 'UTC',
        behavior: 'DEFER_UNTIL_WINDOW',
      },
      filters: {
        message_type_filter: 'MEDIA_ONLY',
        album_policy: 'PROCESS_ITEMS',
        sender_filter_mode: 'ANY',
        sender_user_ids: [],
        missing_sender_policy: 'ALLOW_IN_CHANNELS',
        required_keywords: [],
        required_keywords_match_mode: 'ANY',
        excluded_keywords: ['sample'],
        regex_pattern: '',
        regex_exclude_pattern: '',
        keyword_search_target: 'TEXT_CAPTION_AND_FILENAME',
        case_sensitive: false,
        whole_word: false,
        min_file_size_mb: 100,
        max_file_size_mb: null,
        filename_contains: '',
        filename_ends_with: '',
        filename_regex: '',
        accepted_extensions: [],
        excluded_extensions: [],
        missing_file_metadata_policy: 'FAIL_FILTER',
      },
      categories: {
        enabled: true,
        selected: ['TV_SHOW', 'COMBINED'],
        match_mode: 'ANY',
      },
      caption_transform: {
        clean_filename_mode: false,
        remove_links: true,
        remove_usernames: true,
        remove_hashtags: true,
        remove_emojis: true,
        remove_decorative_symbols: true,
        strip_text_after_extension: true,
        preserve_multipart_suffix: true,
        custom_header: '[Vault Television Index]',
        custom_footer: '',
        replacements: [],
      },
    });

    saveRuleTransactional({
      id: 'rule-split-archives',
      name: '03. Multipart Split Archives (.001 / .part1)',
      description:
        'Routes any split volume (.mkv.001, .7z.002, .part1.rar) to the Multipart Split Archives Staging supergroup.',
      enabled: true,
      source_peer_id: '-1001000000001',
      destination_peer_ids: ['-1002000000304'],
      priority: 70,
      secondary_order: 3,
      exclusive_stop: false,
      delivery_mode: 'COPY',
      delay_seconds: 0,
      max_retries: 3,
      sync_edits: true,
      sync_deletes: true,
      deduplication_override: 'PER_DESTINATION',
      schedule: {
        enabled: false,
        start_time: '00:00',
        end_time: '23:59',
        days: [0, 1, 2, 3, 4, 5, 6],
        timezone: 'UTC',
        behavior: 'DEFER_UNTIL_WINDOW',
      },
      filters: {
        message_type_filter: 'MEDIA_ONLY',
        album_policy: 'PROCESS_ITEMS',
        sender_filter_mode: 'ANY',
        sender_user_ids: [],
        missing_sender_policy: 'ALLOW_IN_CHANNELS',
        required_keywords: [],
        required_keywords_match_mode: 'ANY',
        excluded_keywords: ['sample'],
        regex_pattern: '',
        regex_exclude_pattern: '',
        keyword_search_target: 'TEXT_CAPTION_AND_FILENAME',
        case_sensitive: false,
        whole_word: false,
        min_file_size_mb: null,
        max_file_size_mb: null,
        filename_contains: '',
        filename_ends_with: '',
        filename_regex: '',
        accepted_extensions: [],
        excluded_extensions: [],
        missing_file_metadata_policy: 'FAIL_FILTER',
      },
      categories: {
        enabled: true,
        selected: ['SPLIT'],
        match_mode: 'ALL',
      },
      caption_transform: {
        clean_filename_mode: true,
        remove_links: true,
        remove_usernames: true,
        remove_hashtags: false,
        remove_emojis: true,
        remove_decorative_symbols: true,
        strip_text_after_extension: true,
        preserve_multipart_suffix: true,
        custom_header: '[Multipart Volume Staging]',
        custom_footer: '',
        replacements: [],
      },
    });

    // Process initial messages 1001..1005 so the dashboard has real persisted history, mappings, and stats on first view
    const initialMsgs = db
      .prepare(
        'SELECT * FROM source_messages_archive WHERE source_peer_id = ? AND message_id <= 1005 ORDER BY message_id ASC'
      )
      .all('-1001000000001') as any[];

    for (const m of initialMsgs) {
      routeAndEnqueueMessage(
        {
          message_id: Number(m.message_id),
          source_peer_id: m.source_peer_id,
          chat_type: m.chat_type,
          media_type: m.media_type,
          is_album: Boolean(m.is_album),
          is_first_in_album: Boolean(m.is_first_in_album),
          text: m.text,
          caption: m.caption,
          filename: m.filename,
          file_size_bytes: m.file_size_bytes !== null ? Number(m.file_size_bytes) : null,
          sender_user_id: m.sender_user_id !== null ? Number(m.sender_user_id) : null,
          is_sender_admin: Boolean(m.is_sender_admin),
          is_anonymous_admin: Boolean(m.is_anonymous_admin),
          is_sender_verified: Boolean(m.is_sender_verified),
          timestamp_utc: m.timestamp_utc,
        },
        'LIVE',
        null,
        false
      );
    }
  }
}

export function propagateSourceEdit(
  sourcePeerId: string,
  sourceMessageId: number,
  newCaptionOrText: string
): {
  updatedCount: number;
  skippedUnsupportedCount: number;
  details: string[];
} {
  return withTransaction(() => {
    const settings = getAppSettings();
    const mappings = db
      .prepare(
        'SELECT * FROM message_mappings WHERE source_peer_id = ? AND source_message_id = ? AND is_deleted_on_dest = 0'
      )
      .all(sourcePeerId, sourceMessageId) as any[];

    // Also update the archive record
    db.prepare(
      'UPDATE source_messages_archive SET caption = ?, text = ? WHERE source_peer_id = ? AND message_id = ?'
    ).run(newCaptionOrText, newCaptionOrText, sourcePeerId, sourceMessageId);

    let updatedCount = 0;
    let skippedUnsupportedCount = 0;
    const details: string[] = [];

    if (!settings.global_sync_edits) {
      details.push('Global edit synchronization is disabled in Settings');
      return { updatedCount, skippedUnsupportedCount, details };
    }

    const archiveRow = db
      .prepare(
        'SELECT filename, media_type FROM source_messages_archive WHERE source_peer_id = ? AND message_id = ?'
      )
      .get(sourcePeerId, sourceMessageId) as any;

    for (const map of mappings) {
      const rule = getRuleById(map.rule_id);
      if (!rule || !rule.sync_edits) {
        details.push(
          `Skipped destination ${map.destination_peer_id} (edit sync disabled on rule ${map.rule_id})`
        );
        continue;
      }

      if (map.delivery_mode === 'FORWARD') {
        skippedUnsupportedCount++;
        logAppEvent({
          level: 'WARNING',
          event_type: 'EDIT_SYNC_UNSUPPORTED',
          error_category: 'FORWARD_MODE_IMMUTABLE',
          rule_id: rule.id,
          source_peer_id: sourcePeerId,
          destination_peer_id: map.destination_peer_id,
          source_message_id: sourceMessageId,
          operation: 'SYNC_EDIT',
          diagnostic_message: `Cannot edit destination message #${map.destination_message_id} because it was delivered in native FORWARD mode`,
        });
        details.push(
          `Unsupported on ${map.destination_peer_id} msg #${map.destination_message_id}: native FORWARD mode cannot be edited on Telegram`
        );
        continue;
      }

      const transformed = applyCaptionTransformations(
        newCaptionOrText,
        archiveRow?.filename ?? null,
        (archiveRow?.media_type ?? 'DOCUMENT') !== 'TEXT',
        rule.caption_transform
      );

      db.prepare(`
        UPDATE message_mappings
        SET last_synced_caption = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = ?
      `).run(transformed, map.id);

      updatedCount++;
      logAppEvent({
        level: 'SUCCESS',
        event_type: 'EDIT_SYNC_APPLIED',
        rule_id: rule.id,
        source_peer_id: sourcePeerId,
        destination_peer_id: map.destination_peer_id,
        source_message_id: sourceMessageId,
        operation: 'SYNC_EDIT',
        diagnostic_message: `Synchronized edited caption to destination ${map.destination_peer_id} message #${map.destination_message_id}`,
      });
      details.push(
        `Updated destination ${map.destination_peer_id} message #${map.destination_message_id}`
      );
    }

    return { updatedCount, skippedUnsupportedCount, details };
  });
}

export function propagateSourceDelete(
  sourcePeerId: string,
  sourceMessageId: number
): {
  deletedCount: number;
  failedCount: number;
  details: string[];
} {
  return withTransaction(() => {
    const settings = getAppSettings();
    const mappings = db
      .prepare(
        'SELECT * FROM message_mappings WHERE source_peer_id = ? AND source_message_id = ? AND is_deleted_on_dest = 0'
      )
      .all(sourcePeerId, sourceMessageId) as any[];

    let deletedCount = 0;
    let failedCount = 0;
    const details: string[] = [];

    if (!settings.global_sync_deletes) {
      details.push('Global delete synchronization is disabled in Settings');
      return { deletedCount, failedCount, details };
    }

    for (const map of mappings) {
      const rule = getRuleById(map.rule_id);
      if (!rule || !rule.sync_deletes) {
        details.push(
          `Skipped destination ${map.destination_peer_id} (delete sync disabled on rule)`
        );
        continue;
      }

      const chat = db
        .prepare('SELECT can_delete, title FROM chats WHERE peer_id = ?')
        .get(map.destination_peer_id) as any;

      if (chat && !chat.can_delete) {
        failedCount++;
        logAppEvent({
          level: 'FAILURE',
          event_type: 'DELETE_SYNC_FORBIDDEN',
          error_category: 'PERMISSION_DENIED',
          rule_id: rule.id,
          source_peer_id: sourcePeerId,
          destination_peer_id: map.destination_peer_id,
          source_message_id: sourceMessageId,
          operation: 'SYNC_DELETE',
          diagnostic_message: `MESSAGE_DELETE_FORBIDDEN on destination ${map.destination_peer_id} msg #${map.destination_message_id}`,
        });
        details.push(
          `Failed on ${map.destination_peer_id}: account lacks delete_messages permission`
        );
        continue;
      }

      db.prepare(`
        UPDATE message_mappings
        SET is_deleted_on_dest = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = ?
      `).run(map.id);

      deletedCount++;
      logAppEvent({
        level: 'SUCCESS',
        event_type: 'DELETE_SYNC_APPLIED',
        rule_id: rule.id,
        source_peer_id: sourcePeerId,
        destination_peer_id: map.destination_peer_id,
        source_message_id: sourceMessageId,
        operation: 'SYNC_DELETE',
        diagnostic_message: `Deleted tracked destination copy #${map.destination_message_id} on ${map.destination_peer_id}`,
      });
      details.push(
        `Deleted destination copy #${map.destination_message_id} on ${map.destination_peer_id}`
      );
    }

    return { deletedCount, failedCount, details };
  });
}
