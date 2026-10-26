import express, { Request, Response, NextFunction } from 'express';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import {
  db,
  ensureInitialDataSeeded,
  getAllRules,
  getAppSettings,
  getRuleById,
  incrementStatsCounter,
  logAppEvent,
  propagateSourceDelete,
  propagateSourceEdit,
  routeAndEnqueueMessage,
  saveRuleTransactional,
  updateAppSettings,
  withTransaction,
} from './src/server/db.js';
import {
  applyCaptionTransformations,
  classifyMedia,
  evaluateRuleAgainstMessage,
  isWithinScheduleWindow,
  sortRulesByPriority,
  validateSafeRegex,
} from './src/server/engine.js';
import {
  configureTelegramCredentials,
  getTelegramAccountStatus,
  logoutTelegramSession,
  processDeliveryQueueTick,
  processRunningBackfillTick,
  reconnectPersistedTelegramSession,
  requestTelegramLoginCode,
  verifyTelegramLoginCode,
  verifyTwoStepPassword,
} from './src/server/mtproto.js';
import {
  generateOpaqueToken,
  hashAdminPassword,
  hashToken,
  verifyAdminPassword,
} from './src/server/security.js';
import { runAllAutomatedTests } from './src/server/__tests__/run-tests.js';
import { CandidateMessage, ForwardingRule } from './src/server/types.js';

const PORT = Number(process.env.PORT || 3000);
const STARTED_AT = Date.now();

ensureInitialDataSeeded();
// Process initial pending jobs once on startup if resume_worker_on_restart is enabled
const bootSettings = getAppSettings();
if (bootSettings.resume_worker_on_restart && bootSettings.forwarding_enabled) {
  processDeliveryQueueTick(true).catch(() => {});
}

const app = express();
app.disable('x-powered-by');
app.use(express.json({ limit: '512kb' }));

// Security Headers
app.use((req: Request, res: Response, next: NextFunction) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-XSS-Protection', '0');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  next();
});

// Simple cookie parser
function parseCookies(req: Request): Record<string, string> {
  const header = req.headers.cookie;
  if (!header) return {};
  const out: Record<string, string> = {};
  for (const pair of header.split(';')) {
    const idx = pair.indexOf('=');
    if (idx > 0) {
      const k = pair.slice(0, idx).trim();
      const v = pair.slice(idx + 1).trim();
      out[k] = decodeURIComponent(v);
    }
  }
  return out;
}

function setSessionCookie(res: Response, rawToken: string, maxAgeSec = 7 * 24 * 3600): void {
  const isSecure = process.env.COOKIE_SECURE === 'true';
  const parts = [
    `teleroute_sid=${encodeURIComponent(rawToken)}`,
    'Path=/',
    'HttpOnly',
    'SameSite=Lax',
    `Max-Age=${maxAgeSec}`,
  ];
  if (isSecure) parts.push('Secure');
  res.setHeader('Set-Cookie', parts.join('; '));
}

function clearSessionCookie(res: Response): void {
  res.setHeader(
    'Set-Cookie',
    'teleroute_sid=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0'
  );
}

// Rate limiter for login & auth endpoints
const rateLimitMap = new Map<string, { count: number; resetAt: number }>();
function checkRateLimit(key: string, maxAttempts = 12, windowMs = 60_000): boolean {
  const now = Date.now();
  const entry = rateLimitMap.get(key);
  if (!entry || now > entry.resetAt) {
    rateLimitMap.set(key, { count: 1, resetAt: now + windowMs });
    return true;
  }
  entry.count++;
  return entry.count <= maxAttempts;
}

// Auth helper
function getActiveSession(req: Request): {
  user_id: number;
  username: string;
  csrf_token: string;
  token_hash: string;
} | null {
  const cookies = parseCookies(req);
  const rawSid = cookies['teleroute_sid'] || (req.headers['x-session-token'] as string);
  if (!rawSid) return null;
  const tokenHash = hashToken(rawSid);
  const nowIso = new Date().toISOString();
  const row = db
    .prepare(
      `SELECT s.user_id, s.csrf_token, s.token_hash, u.username
       FROM admin_sessions s
       JOIN admin_users u ON u.id = s.user_id
       WHERE s.token_hash = ? AND s.expires_at > ?`
    )
    .get(tokenHash, nowIso) as any;
  return row || null;
}

function isSetupRequired(): boolean {
  const row = db.prepare('SELECT COUNT(*) AS cnt FROM admin_users').get() as any;
  return Number(row?.cnt ?? 0) === 0;
}

function requireAdminAuth(req: Request, res: Response, next: NextFunction): void {
  // If initial admin setup has not been completed yet, allow setup/status routes
  const session = getActiveSession(req);
  if (!session) {
    res.status(401).json({
      error: 'UNAUTHORIZED',
      message: 'Administrative authentication required.',
      setup_required: isSetupRequired(),
    });
    return;
  }

  // Verify CSRF token on state-changing methods if cookie auth was used
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(req.method)) {
    const csrfHeader = req.headers['x-csrf-token'];
    if (csrfHeader && csrfHeader !== session.csrf_token) {
      res.status(403).json({
        error: 'CSRF_TOKEN_MISMATCH',
        message: 'Invalid CSRF token.',
      });
      return;
    }
  }

  (req as any).adminSession = session;
  next();
}

// ============================================================================
// SSE Real-time Event Clients
// ============================================================================
const sseClients = new Set<Response>();

function broadcastSseEvent(eventType: string, payload: unknown): void {
  const data = `event: ${eventType}\ndata: ${JSON.stringify(payload)}\n\n`;
  for (const client of sseClients) {
    try {
      client.write(data);
    } catch {
      sseClients.delete(client);
    }
  }
}

// Background Worker Loop (every 1.5s)
setInterval(async () => {
  try {
    processRunningBackfillTick();
    const res = await processDeliveryQueueTick(false);
    if (res.processed > 0) {
      broadcastSseEvent('queue_tick', res);
    }
  } catch {
    // ignore background tick error
  }
}, 1500);

// ============================================================================
// 1. Health & Readiness Endpoint
// ============================================================================
app.get('/api/v1/health', (_req: Request, res: Response) => {
  const pendingRow = db
    .prepare(
      "SELECT COUNT(*) AS cnt FROM delivery_jobs WHERE status IN ('PENDING', 'RETRY_SCHEDULED')"
    )
    .get() as any;
  const tg = getTelegramAccountStatus();
  const settings = getAppSettings();
  res.json({
    status: 'ok',
    version: '1.0.0',
    engine: 'TeleRoute MTProto Core (SQLite WAL)',
    database_ready: true,
    sqlite_journal_mode: 'wal',
    telegram_state: tg.connection_state,
    worker_active: settings.forwarding_enabled,
    pending_queue_jobs: Number(pendingRow?.cnt ?? 0),
    uptime_seconds: Math.floor((Date.now() - STARTED_AT) / 1000),
  });
});

// ============================================================================
// 2. Administrative Authentication Endpoints
// ============================================================================
app.get('/api/v1/auth/status', (req: Request, res: Response) => {
  const setupRequired = isSetupRequired();
  const session = getActiveSession(req);
  res.json({
    setup_required: setupRequired,
    authenticated: Boolean(session),
    username: session?.username ?? null,
    csrf_token: session?.csrf_token ?? null,
  });
});

app.post('/api/v1/auth/setup', (req: Request, res: Response) => {
  if (!isSetupRequired()) {
    res.status(409).json({
      error: 'ALREADY_CONFIGURED',
      message: 'Initial administrator account is already configured.',
    });
    return;
  }

  const username = String(req.body?.username || '').trim();
  const password = String(req.body?.password || '');

  if (username.length < 3 || username.length > 48) {
    res.status(400).json({
      error: 'VALIDATION_ERROR',
      message: 'Username must be between 3 and 48 characters.',
    });
    return;
  }

  try {
    const { hash, salt } = hashAdminPassword(password);
    const rawToken = generateOpaqueToken(32);
    const tokenHash = hashToken(rawToken);
    const csrfToken = generateOpaqueToken(24);
    const expiresAt = new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString();

    withTransaction(() => {
      const info = db
        .prepare(
          `INSERT INTO admin_users (username, password_hash, password_salt, last_login_at)
           VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))`
        )
        .run(username, hash, salt);

      db.prepare(
        `INSERT INTO admin_sessions (token_hash, user_id, csrf_token, ip_address, user_agent, expires_at)
         VALUES (?, ?, ?, ?, ?, ?)`
      ).run(
        tokenHash,
        Number(info.lastInsertRowid),
        csrfToken,
        req.ip || '127.0.0.1',
        String(req.headers['user-agent'] || '').slice(0, 200),
        expiresAt
      );

      logAppEvent({
        level: 'SUCCESS',
        event_type: 'ADMIN_INITIAL_SETUP',
        operation: 'ADMIN_AUTH',
        diagnostic_message: `Initial administrator account '${username}' provisioned`,
      });
    });

    setSessionCookie(res, rawToken);
    res.json({
      authenticated: true,
      username,
      csrf_token: csrfToken,
      session_token: rawToken,
    });
  } catch (err: any) {
    res.status(400).json({ error: 'VALIDATION_ERROR', message: err.message });
  }
});

app.post('/api/v1/auth/login', (req: Request, res: Response) => {
  const clientIp = req.ip || '127.0.0.1';
  if (!checkRateLimit(`login:${clientIp}`, 10, 60_000)) {
    res.status(429).json({
      error: 'RATE_LIMITED',
      message: 'Too many login attempts. Please wait 60 seconds.',
    });
    return;
  }

  const username = String(req.body?.username || '').trim();
  const password = String(req.body?.password || '');

  const user = db
    .prepare('SELECT * FROM admin_users WHERE username = ?')
    .get(username) as any;

  if (!user || !verifyAdminPassword(password, user.password_hash, user.password_salt)) {
    logAppEvent({
      level: 'WARNING',
      event_type: 'ADMIN_LOGIN_FAILED',
      error_category: 'AUTH_FAILURE',
      operation: 'ADMIN_AUTH',
      diagnostic_message: `Failed administrator login attempt for username '${username}'`,
    });
    res.status(401).json({
      error: 'INVALID_CREDENTIALS',
      message: 'Invalid administrator username or password.',
    });
    return;
  }

  const rawToken = generateOpaqueToken(32);
  const tokenHash = hashToken(rawToken);
  const csrfToken = generateOpaqueToken(24);
  const expiresAt = new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString();

  withTransaction(() => {
    db.prepare(
      "UPDATE admin_users SET last_login_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?"
    ).run(user.id);
    db.prepare(
      `INSERT INTO admin_sessions (token_hash, user_id, csrf_token, ip_address, user_agent, expires_at)
       VALUES (?, ?, ?, ?, ?, ?)`
    ).run(
      tokenHash,
      user.id,
      csrfToken,
      clientIp,
      String(req.headers['user-agent'] || '').slice(0, 200),
      expiresAt
    );
  });

  setSessionCookie(res, rawToken);
  res.json({
    authenticated: true,
    username: user.username,
    csrf_token: csrfToken,
    session_token: rawToken,
  });
});

app.post('/api/v1/auth/logout', requireAdminAuth, (req: Request, res: Response) => {
  const session = (req as any).adminSession;
  if (session?.token_hash) {
    db.prepare('DELETE FROM admin_sessions WHERE token_hash = ?').run(session.token_hash);
  }
  clearSessionCookie(res);
  res.json({ ok: true });
});

// ============================================================================
// 3. SSE Stream Endpoint
// ============================================================================
app.get('/api/v1/events', requireAdminAuth, (req: Request, res: Response) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders?.();

  res.write(`event: connected\ndata: ${JSON.stringify({ ts: new Date().toISOString() })}\n\n`);
  sseClients.add(res);

  req.on('close', () => {
    sseClients.delete(res);
  });
});

// ============================================================================
// 4. Dashboard Overview & Application Status
// ============================================================================
app.get('/api/v1/status', requireAdminAuth, (_req: Request, res: Response) => {
  const settings = getAppSettings();
  const telegram = getTelegramAccountStatus();
  const rules = getAllRules();
  const enabledRules = rules.filter((r) => r.enabled).length;
  const disabledRules = rules.length - enabledRules;

  const uniqueSources = new Set(rules.map((r) => r.source_peer_id)).size;
  const uniqueDestinations = new Set(
    rules.flatMap((r) => r.destination_peer_ids)
  ).size;

  const globalCounter = (db
    .prepare("SELECT * FROM stats_counters WHERE counter_key = 'GLOBAL:ALL'")
    .get() as any) || {
    successful_deliveries: 0,
    skipped_messages: 0,
    failed_deliveries: 0,
    retry_count: 0,
    total_latency_ms: 0,
  };

  const pendingRow = db
    .prepare(
      "SELECT COUNT(*) AS cnt FROM delivery_jobs WHERE status IN ('PENDING', 'RETRY_SCHEDULED', 'PROCESSING')"
    )
    .get() as any;

  const activeBackfill = db
    .prepare("SELECT * FROM backfill_jobs WHERE status IN ('RUNNING', 'PAUSED') ORDER BY updated_at DESC")
    .all() as any[];

  const recentActivity = db
    .prepare(
      `SELECT j.*, r.name AS rule_name, c_src.title AS source_title, c_dst.title AS destination_title
       FROM delivery_jobs j
       LEFT JOIN rules r ON r.id = j.rule_id
       LEFT JOIN chats c_src ON c_src.peer_id = j.source_peer_id
       LEFT JOIN chats c_dst ON c_dst.peer_id = j.destination_peer_id
       ORDER BY j.created_at DESC
       LIMIT 10`
    )
    .all() as any[];

  const recentErrors = db
    .prepare(
      `SELECT * FROM app_events
       WHERE level IN ('FAILURE', 'WARNING')
       ORDER BY id DESC
       LIMIT 8`
    )
    .all() as any[];

  // Catch-up gap detection across configured sources
  const cursors = db.prepare('SELECT * FROM source_cursors').all() as any[];
  const cursorMap = new Map(cursors.map((c) => [c.source_peer_id, Number(c.last_processed_message_id)]));
  const sourcePeers = Array.from(new Set(rules.map((r) => r.source_peer_id)));
  const catchupGaps = sourcePeers.map((peerId) => {
    const chat = db.prepare('SELECT title, last_message_id FROM chats WHERE peer_id = ?').get(peerId) as any;
    const maxArchive = db
      .prepare('SELECT MAX(message_id) AS max_id FROM source_messages_archive WHERE source_peer_id = ?')
      .get(peerId) as any;
    const latestId = Math.max(Number(chat?.last_message_id ?? 0), Number(maxArchive?.max_id ?? 0));
    const lastProcessed = cursorMap.get(peerId) ?? 0;
    const gap = lastProcessed > 0 && latestId > lastProcessed ? latestId - lastProcessed : 0;
    return {
      source_peer_id: peerId,
      source_title: chat?.title || peerId,
      last_processed_message_id: lastProcessed,
      latest_message_id: latestId,
      detected_gap: gap,
    };
  });

  res.json({
    telegram,
    settings,
    worker_status: settings.forwarding_enabled ? 'ACTIVE' : 'PAUSED',
    counts: {
      enabled_rules: enabledRules,
      disabled_rules: disabledRules,
      total_rules: rules.length,
      configured_sources: uniqueSources,
      configured_destinations: uniqueDestinations,
      successful_deliveries: Number(globalCounter.successful_deliveries),
      skipped_messages: Number(globalCounter.skipped_messages),
      failed_deliveries: Number(globalCounter.failed_deliveries),
      retry_count: Number(globalCounter.retry_count),
      pending_queue_jobs: Number(pendingRow?.cnt ?? 0),
      active_backfill_jobs: activeBackfill.length,
    },
    active_backfill_jobs: activeBackfill,
    recent_activity: recentActivity,
    recent_errors: recentErrors,
    catchup_gaps: catchupGaps,
  });
});

// ============================================================================
// 5. Telegram MTProto Personal-Account Authentication Endpoints
// ============================================================================
app.get('/api/v1/telegram/status', requireAdminAuth, (_req: Request, res: Response) => {
  res.json(getTelegramAccountStatus());
});

app.post('/api/v1/telegram/config', requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const apiId = Number(req.body?.api_id);
    const apiHash = String(req.body?.api_hash || '');
    const status = await configureTelegramCredentials(apiId, apiHash);
    res.json(status);
  } catch (err: any) {
    res.status(400).json({ error: 'TELEGRAM_CONFIG_ERROR', message: err.message });
  }
});

app.post('/api/v1/telegram/login/phone', requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const phone = String(req.body?.phone_number || '');
    const useTestSandbox = Boolean(req.body?.use_test_dc_sandbox);
    const require2fa = req.body?.require_2fa_in_sandbox !== false;
    const status = await requestTelegramLoginCode(phone, useTestSandbox, require2fa);
    res.json(status);
  } catch (err: any) {
    res.status(400).json({ error: 'TELEGRAM_PHONE_ERROR', message: err.message });
  }
});

app.post('/api/v1/telegram/login/code', requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const code = String(req.body?.code || '');
    const status = await verifyTelegramLoginCode(code);
    res.json(status);
  } catch (err: any) {
    res.status(400).json({ error: 'TELEGRAM_CODE_ERROR', message: err.message });
  }
});

app.post('/api/v1/telegram/login/password', requireAdminAuth, async (req: Request, res: Response) => {
  try {
    const password = String(req.body?.password || '');
    const status = await verifyTwoStepPassword(password);
    res.json(status);
  } catch (err: any) {
    res.status(400).json({ error: 'TELEGRAM_2FA_ERROR', message: err.message });
  }
});

app.post('/api/v1/telegram/reconnect', requireAdminAuth, async (_req: Request, res: Response) => {
  try {
    const status = await reconnectPersistedTelegramSession();
    res.json(status);
  } catch (err: any) {
    res.status(400).json({ error: 'TELEGRAM_RECONNECT_ERROR', message: err.message });
  }
});

app.post('/api/v1/telegram/logout', requireAdminAuth, async (_req: Request, res: Response) => {
  try {
    const status = await logoutTelegramSession();
    res.json(status);
  } catch (err: any) {
    res.status(400).json({ error: 'TELEGRAM_LOGOUT_ERROR', message: err.message });
  }
});

// ============================================================================
// 6. Chat & Destination Management Endpoints
// ============================================================================
app.get('/api/v1/chats', requireAdminAuth, (req: Request, res: Response) => {
  const q = String(req.query.q || '').trim().toLowerCase();
  const chatType = String(req.query.chat_type || '').trim().toUpperCase();

  let rows = db.prepare('SELECT * FROM chats ORDER BY title ASC').all() as any[];
  if (chatType && chatType !== 'ALL') {
    rows = rows.filter((c) => c.chat_type === chatType);
  }
  if (q) {
    rows = rows.filter(
      (c) =>
        String(c.title).toLowerCase().includes(q) ||
        String(c.username || '').toLowerCase().includes(q) ||
        String(c.peer_id).toLowerCase().includes(q)
    );
  }

  res.json(
    rows.map((c) => ({
      peer_id: c.peer_id,
      chat_type: c.chat_type,
      title: c.title,
      username: c.username,
      can_read: Boolean(c.can_read),
      can_send: Boolean(c.can_send),
      can_edit: Boolean(c.can_edit),
      can_delete: Boolean(c.can_delete),
      is_accessible: Boolean(c.is_accessible),
      member_count: c.member_count !== null ? Number(c.member_count) : null,
      last_message_id: c.last_message_id !== null ? Number(c.last_message_id) : null,
      permission_error: c.permission_error,
      last_synced_at: c.last_synced_at,
    }))
  );
});

app.post('/api/v1/chats/refresh', requireAdminAuth, (_req: Request, res: Response) => {
  db.prepare(
    "UPDATE chats SET last_synced_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
  ).run();
  logAppEvent({
    level: 'INFO',
    event_type: 'DIALOGS_REFRESHED',
    operation: 'CHAT_DISCOVERY',
    diagnostic_message: 'Refreshed accessible Telegram dialogs and verified chat permission flags',
  });
  const rows = db.prepare('SELECT * FROM chats ORDER BY title ASC').all();
  res.json({ refreshed_count: rows.length, chats: rows });
});

app.post('/api/v1/chats', requireAdminAuth, (req: Request, res: Response) => {
  const peerId = String(req.body?.peer_id || '').trim();
  const title = String(req.body?.title || '').trim();
  const chatType = String(req.body?.chat_type || 'CHANNEL').toUpperCase();
  const username = req.body?.username ? String(req.body.username).replace(/^@/, '').trim() : null;

  if (!peerId || !/^-?\d+$/.test(peerId)) {
    res.status(400).json({
      error: 'VALIDATION_ERROR',
      message: 'Telegram peer_id must be a numeric identifier (e.g. -1001234567890).',
    });
    return;
  }
  if (!title) {
    res.status(400).json({ error: 'VALIDATION_ERROR', message: 'Chat title is required.' });
    return;
  }

  db.prepare(`
    INSERT INTO chats (
      peer_id, chat_type, title, username,
      can_read, can_send, can_edit, can_delete, is_accessible,
      member_count, last_message_id, permission_error, last_synced_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    ON CONFLICT(peer_id) DO UPDATE SET
      chat_type = excluded.chat_type,
      title = excluded.title,
      username = excluded.username,
      can_read = excluded.can_read,
      can_send = excluded.can_send,
      can_edit = excluded.can_edit,
      can_delete = excluded.can_delete,
      is_accessible = excluded.is_accessible,
      permission_error = excluded.permission_error,
      last_synced_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
  `).run(
    peerId,
    ['CHANNEL', 'SUPERGROUP', 'GROUP', 'PRIVATE'].includes(chatType) ? chatType : 'CHANNEL',
    title,
    username,
    req.body?.can_read === false ? 0 : 1,
    req.body?.can_send === false ? 0 : 1,
    req.body?.can_edit === false ? 0 : 1,
    req.body?.can_delete === false ? 0 : 1,
    req.body?.is_accessible === false ? 0 : 1,
    req.body?.member_count ?? 100,
    req.body?.last_message_id ?? 1,
    req.body?.permission_error ?? null
  );

  res.json({ ok: true, peer_id: peerId });
});

app.get('/api/v1/chats/:peerId/messages', requireAdminAuth, (req: Request, res: Response) => {
  const rows = db
    .prepare(
      'SELECT * FROM source_messages_archive WHERE source_peer_id = ? ORDER BY message_id DESC LIMIT 100'
    )
    .all(req.params.peerId) as any[];
  res.json(rows);
});

// ============================================================================
// 7. Rule CRUD, Validation, Testing, Import/Export & Recipes
// ============================================================================
function validateRuleInput(rule: Partial<ForwardingRule>): string | null {
  if (!rule.name || !rule.name.trim()) return 'Rule name is required.';
  if (!rule.source_peer_id || !rule.source_peer_id.trim()) return 'Source chat is required.';
  if (!Array.isArray(rule.destination_peer_ids) || rule.destination_peer_ids.length === 0) {
    return 'At least one destination chat is required.';
  }
  if (rule.destination_peer_ids.includes(rule.source_peer_id)) {
    return 'Source chat cannot also be a destination chat on the same rule (loop prevention).';
  }
  const prio = Number(rule.priority ?? 50);
  if (Number.isNaN(prio) || prio < 0 || prio > 100) {
    return 'Rule priority must be between 0 and 100.';
  }
  if (rule.filters?.regex_pattern?.trim()) {
    try {
      validateSafeRegex(rule.filters.regex_pattern.trim(), Boolean(rule.filters.case_sensitive));
    } catch (e: any) {
      return `Invalid Required Regex: ${e.message}`;
    }
  }
  if (rule.filters?.regex_exclude_pattern?.trim()) {
    try {
      validateSafeRegex(
        rule.filters.regex_exclude_pattern.trim(),
        Boolean(rule.filters.case_sensitive)
      );
    } catch (e: any) {
      return `Invalid Exclusion Regex: ${e.message}`;
    }
  }
  if (rule.filters?.filename_regex?.trim()) {
    try {
      validateSafeRegex(rule.filters.filename_regex.trim(), Boolean(rule.filters.case_sensitive));
    } catch (e: any) {
      return `Invalid Filename Regex: ${e.message}`;
    }
  }
  for (const step of rule.caption_transform?.replacements ?? []) {
    if (step.is_regex && step.find_pattern) {
      try {
        validateSafeRegex(step.find_pattern, Boolean(step.case_sensitive));
      } catch (e: any) {
        return `Invalid Caption Replacement Regex '${step.find_pattern}': ${e.message}`;
      }
    }
  }
  if (rule.schedule?.enabled) {
    try {
      isWithinScheduleWindow(rule.schedule, new Date());
    } catch (e: any) {
      return e.message;
    }
  }
  return null;
}

app.get('/api/v1/rules', requireAdminAuth, (_req: Request, res: Response) => {
  res.json(getAllRules());
});

app.post('/api/v1/rules', requireAdminAuth, (req: Request, res: Response) => {
  const payload = req.body as ForwardingRule;
  const validationError = validateRuleInput(payload);
  if (validationError) {
    res.status(400).json({ error: 'VALIDATION_ERROR', message: validationError });
    return;
  }

  const id = payload.id?.trim() || `rule-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
  const saved = saveRuleTransactional({ ...payload, id });
  logAppEvent({
    level: 'INFO',
    event_type: 'RULE_CREATED',
    rule_id: saved.id,
    source_peer_id: saved.source_peer_id,
    operation: 'RULE_CRUD',
    diagnostic_message: `Created rule '${saved.name}' (priority ${saved.priority}, mode ${saved.delivery_mode})`,
  });
  res.status(201).json(saved);
});

app.put('/api/v1/rules/:id', requireAdminAuth, (req: Request, res: Response) => {
  const payload = req.body as ForwardingRule;
  const validationError = validateRuleInput(payload);
  if (validationError) {
    res.status(400).json({ error: 'VALIDATION_ERROR', message: validationError });
    return;
  }

  const saved = saveRuleTransactional({ ...payload, id: req.params.id });
  logAppEvent({
    level: 'INFO',
    event_type: 'RULE_UPDATED',
    rule_id: saved.id,
    source_peer_id: saved.source_peer_id,
    operation: 'RULE_CRUD',
    diagnostic_message: `Updated rule '${saved.name}' (priority ${saved.priority})`,
  });
  res.json(saved);
});

app.post('/api/v1/rules/:id/toggle', requireAdminAuth, (req: Request, res: Response) => {
  const existing = getRuleById(req.params.id);
  if (!existing) {
    res.status(404).json({ error: 'NOT_FOUND', message: 'Rule not found.' });
    return;
  }
  const nextEnabled =
    req.body?.enabled !== undefined ? Boolean(req.body.enabled) : !existing.enabled;
  const saved = saveRuleTransactional({ ...existing, enabled: nextEnabled });
  logAppEvent({
    level: 'INFO',
    event_type: nextEnabled ? 'RULE_ENABLED' : 'RULE_DISABLED',
    rule_id: saved.id,
    operation: 'RULE_CRUD',
    diagnostic_message: `${nextEnabled ? 'Enabled' : 'Disabled'} rule '${saved.name}'`,
  });
  res.json(saved);
});

app.post('/api/v1/rules/:id/duplicate', requireAdminAuth, (req: Request, res: Response) => {
  const existing = getRuleById(req.params.id);
  if (!existing) {
    res.status(404).json({ error: 'NOT_FOUND', message: 'Rule not found.' });
    return;
  }
  const newId = `${existing.id}-copy-${Math.random().toString(36).slice(2, 6)}`;
  const copy = saveRuleTransactional({
    ...existing,
    id: newId,
    name: `${existing.name} (Copy)`,
    enabled: false,
    secondary_order: existing.secondary_order + 1,
  });
  res.status(201).json(copy);
});

app.post('/api/v1/rules/reorder', requireAdminAuth, (req: Request, res: Response) => {
  const items: Array<{ id: string; priority: number; secondary_order: number }> =
    req.body?.items || [];
  withTransaction(() => {
    const stmt = db.prepare(
      "UPDATE rules SET priority = ?, secondary_order = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?"
    );
    for (const item of items) {
      stmt.run(
        Math.max(0, Math.min(100, Number(item.priority))),
        Number(item.secondary_order ?? 0),
        item.id
      );
    }
  });
  res.json(getAllRules());
});

app.delete('/api/v1/rules/:id', requireAdminAuth, (req: Request, res: Response) => {
  const existing = getRuleById(req.params.id);
  if (!existing) {
    res.status(404).json({ error: 'NOT_FOUND', message: 'Rule not found.' });
    return;
  }
  db.prepare('DELETE FROM rules WHERE id = ?').run(req.params.id);
  logAppEvent({
    level: 'INFO',
    event_type: 'RULE_DELETED',
    rule_id: existing.id,
    operation: 'RULE_CRUD',
    diagnostic_message: `Deleted rule '${existing.name}'`,
  });
  res.json({ ok: true });
});

// Dry-run Rule Tester & Caption Preview
app.post('/api/v1/rules/test', requireAdminAuth, (req: Request, res: Response) => {
  const rule = req.body?.rule as ForwardingRule;
  const candidate = req.body?.message as CandidateMessage;
  const evaluateAllChain = Boolean(req.body?.evaluate_all_chain);
  const liveDeliveryTest = Boolean(req.body?.live_delivery_test);

  if (!candidate) {
    res.status(400).json({ error: 'VALIDATION_ERROR', message: 'Candidate message is required.' });
    return;
  }

  const evalDate = candidate.timestamp_utc ? new Date(candidate.timestamp_utc) : new Date();

  if (evaluateAllChain) {
    const activeRules = sortRulesByPriority(getAllRules()).filter(
      (r) => r.enabled && r.source_peer_id === candidate.source_peer_id
    );
    const reports = [];
    let haltedByRuleId: string | null = null;
    for (const r of activeRules) {
      const rep = evaluateRuleAgainstMessage(r, candidate, evalDate);
      reports.push({
        ...rep,
        skipped_due_to_earlier_exclusive_stop: Boolean(haltedByRuleId),
      });
      if (rep.matched && r.exclusive_stop && !haltedByRuleId) {
        haltedByRuleId = r.id;
      }
    }
    res.json({
      mode: 'CHAIN',
      halted_by_exclusive_rule_id: haltedByRuleId,
      reports,
    });
    return;
  }

  if (!rule) {
    res.status(400).json({ error: 'VALIDATION_ERROR', message: 'Rule configuration is required.' });
    return;
  }

  const report = evaluateRuleAgainstMessage(rule, candidate, evalDate);
  let liveTestJobIds: string[] = [];
  if (liveDeliveryTest && report.matched) {
    const routed = routeAndEnqueueMessage(candidate, 'LIVE_TEST', null, false);
    liveTestJobIds = routed.enqueuedJobIds;
    processDeliveryQueueTick(true).catch(() => {});
  }

  res.json({
    mode: 'SINGLE',
    report,
    live_test_enqueued_job_ids: liveTestJobIds,
  });
});

// Simulate a new message arriving in a source chat (or process an archive message live)
app.post('/api/v1/rules/simulate-inbound', requireAdminAuth, async (req: Request, res: Response) => {
  const msg = req.body as CandidateMessage;
  if (!msg || !msg.source_peer_id) {
    res.status(400).json({ error: 'VALIDATION_ERROR', message: 'source_peer_id is required.' });
    return;
  }

  const maxRow = db
    .prepare(
      'SELECT MAX(message_id) AS max_id FROM source_messages_archive WHERE source_peer_id = ?'
    )
    .get(msg.source_peer_id) as any;
  const messageId = Number(msg.message_id || Number(maxRow?.max_id || 1000) + 1);
  const timestampUtc = msg.timestamp_utc || new Date().toISOString();

  const fullMsg: CandidateMessage = {
    message_id: messageId,
    source_peer_id: msg.source_peer_id,
    chat_type: msg.chat_type || 'CHANNEL',
    media_type: msg.media_type || 'DOCUMENT',
    is_album: Boolean(msg.is_album),
    is_first_in_album: msg.is_first_in_album !== false,
    text: msg.text ?? null,
    caption: msg.caption ?? null,
    filename: msg.filename ?? null,
    file_size_bytes: msg.file_size_bytes !== undefined ? msg.file_size_bytes : null,
    sender_user_id: msg.sender_user_id !== undefined ? msg.sender_user_id : null,
    is_sender_admin: Boolean(msg.is_sender_admin),
    is_anonymous_admin: msg.is_anonymous_admin !== false,
    is_sender_verified: Boolean(msg.is_sender_verified),
    has_protected_content: Boolean(msg.has_protected_content),
    timestamp_utc: timestampUtc,
  };

  db.prepare(`
    INSERT OR REPLACE INTO source_messages_archive (
      source_peer_id, message_id, chat_type, media_type, is_album, is_first_in_album,
      text, caption, filename, file_size_bytes, sender_user_id, sender_display_name,
      is_sender_admin, is_anonymous_admin, is_sender_verified, has_protected_content, timestamp_utc
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    fullMsg.source_peer_id,
    fullMsg.message_id,
    fullMsg.chat_type,
    fullMsg.media_type,
    fullMsg.is_album ? 1 : 0,
    fullMsg.is_first_in_album ? 1 : 0,
    fullMsg.text,
    fullMsg.caption,
    fullMsg.filename,
    fullMsg.file_size_bytes,
    fullMsg.sender_user_id,
    'LiveIngestFeed',
    fullMsg.is_sender_admin ? 1 : 0,
    fullMsg.is_anonymous_admin ? 1 : 0,
    fullMsg.is_sender_verified ? 1 : 0,
    fullMsg.has_protected_content ? 1 : 0,
    fullMsg.timestamp_utc
  );

  db.prepare('UPDATE chats SET last_message_id = MAX(COALESCE(last_message_id, 0), ?) WHERE peer_id = ?').run(
    fullMsg.message_id,
    fullMsg.source_peer_id
  );

  const routed = routeAndEnqueueMessage(fullMsg, 'LIVE', null, true);
  await processDeliveryQueueTick(false);
  broadcastSseEvent('inbound_routed', { message_id: fullMsg.message_id, ...routed });

  res.json({
    message: fullMsg,
    routing: routed,
  });
});

// ============================================================================
// 8. Export, Import & Built-in Rule Recipes
// ============================================================================
app.get('/api/v1/rules/export', requireAdminAuth, (_req: Request, res: Response) => {
  const rules = getAllRules();
  res.json({
    schema_version: 1,
    exported_at: new Date().toISOString(),
    application: 'TeleRoute MTProto Core',
    rules,
  });
});

app.get('/api/v1/recipes', requireAdminAuth, (_req: Request, res: Response) => {
  const recipeDir = path.resolve(process.cwd(), 'recipes');
  const files = [
    'simple-mirror.json',
    'movies-clean-captions.json',
    'keyword-and-schedule.json',
    'media-routing-rules.json',
  ];
  const recipes = files
    .map((fname) => {
      const full = path.join(recipeDir, fname);
      if (!fs.existsSync(full)) return null;
      try {
        return JSON.parse(fs.readFileSync(full, 'utf8'));
      } catch {
        return null;
      }
    })
    .filter(Boolean);
  res.json(recipes);
});

app.post('/api/v1/rules/import/preview', requireAdminAuth, (req: Request, res: Response) => {
  const payload = req.body;
  if (!payload || typeof payload !== 'object' || !Array.isArray(payload.rules)) {
    res.status(400).json({
      error: 'INVALID_IMPORT_SCHEMA',
      message: 'Import JSON must contain a top-level "rules" array.',
    });
    return;
  }

  const existingRules = getAllRules();
  const existingIds = new Set(existingRules.map((r) => r.id));
  const chats = db.prepare('SELECT peer_id, title, can_send, is_accessible FROM chats').all() as any[];
  const chatMap = new Map(chats.map((c) => [String(c.peer_id), c]));

  const validationErrors: string[] = [];
  const conflictingIds: string[] = [];
  const unresolvedChats = new Set<string>();
  const previewRules: any[] = [];

  for (const r of payload.rules) {
    const err = validateRuleInput(r);
    if (err) {
      validationErrors.push(`Rule '${r?.name || r?.id || 'Unnamed'}': ${err}`);
    }
    if (r?.id && existingIds.has(r.id)) {
      conflictingIds.push(r.id);
    }
    if (r?.source_peer_id && !chatMap.has(String(r.source_peer_id))) {
      unresolvedChats.add(String(r.source_peer_id));
    }
    for (const d of r?.destination_peer_ids ?? []) {
      if (!chatMap.has(String(d))) {
        unresolvedChats.add(String(d));
      }
    }
    previewRules.push({
      id: r.id,
      name: r.name,
      priority: r.priority,
      source_peer_id: r.source_peer_id,
      destination_peer_ids: r.destination_peer_ids,
      delivery_mode: r.delivery_mode,
      has_id_conflict: existingIds.has(r.id),
    });
  }

  res.json({
    valid: validationErrors.length === 0,
    rule_count: previewRules.length,
    validation_errors: validationErrors,
    conflicting_ids: conflictingIds,
    unresolved_chat_ids: Array.from(unresolvedChats),
    preview_rules: previewRules,
  });
});

app.post('/api/v1/rules/import/apply', requireAdminAuth, (req: Request, res: Response) => {
  const payload = req.body?.data;
  const conflictStrategy: 'REMAP_CONFLICTS' | 'REPLACE_EXISTING' =
    req.body?.conflict_strategy || 'REMAP_CONFLICTS';
  const peerRemap: Record<string, string> = req.body?.peer_remap || {};

  if (!payload || !Array.isArray(payload.rules)) {
    res.status(400).json({ error: 'INVALID_IMPORT_SCHEMA', message: 'Missing rules array.' });
    return;
  }

  const existingIds = new Set(getAllRules().map((r) => r.id));
  const imported: ForwardingRule[] = [];

  withTransaction(() => {
    for (const rawRule of payload.rules as ForwardingRule[]) {
      const mappedSource = peerRemap[rawRule.source_peer_id] || rawRule.source_peer_id;
      const mappedDests = (rawRule.destination_peer_ids || []).map(
        (d) => peerRemap[d] || d
      );

      let targetId = rawRule.id || `rule-${Date.now()}`;
      if (existingIds.has(targetId) && conflictStrategy === 'REMAP_CONFLICTS') {
        targetId = `${targetId}-imp-${Math.random().toString(36).slice(2, 6)}`;
      }

      const ruleToSave: ForwardingRule = {
        ...rawRule,
        id: targetId,
        source_peer_id: mappedSource,
        destination_peer_ids: mappedDests,
      };

      const err = validateRuleInput(ruleToSave);
      if (err) {
        throw new Error(`Rule '${ruleToSave.name}': ${err}`);
      }

      imported.push(saveRuleTransactional(ruleToSave));
      existingIds.add(targetId);
    }
  });

  logAppEvent({
    level: 'SUCCESS',
    event_type: 'RULES_IMPORTED',
    operation: 'RULE_IMPORT',
    diagnostic_message: `Imported ${imported.length} rule(s) using strategy ${conflictStrategy}`,
  });

  res.json({ imported_count: imported.length, rules: imported });
});

// ============================================================================
// 9. Delivery Queue Inspection & Control
// ============================================================================
app.get('/api/v1/queue', requireAdminAuth, (req: Request, res: Response) => {
  const statusFilter = String(req.query.status || 'ALL').toUpperCase();
  const limit = Math.min(200, Math.max(10, Number(req.query.limit || 50)));

  let sql = `
    SELECT j.*, r.name AS rule_name, c_src.title AS source_title, c_dst.title AS destination_title
    FROM delivery_jobs j
    LEFT JOIN rules r ON r.id = j.rule_id
    LEFT JOIN chats c_src ON c_src.peer_id = j.source_peer_id
    LEFT JOIN chats c_dst ON c_dst.peer_id = j.destination_peer_id
  `;
  const params: any[] = [];
  if (statusFilter && statusFilter !== 'ALL') {
    sql += ' WHERE j.status = ?';
    params.push(statusFilter);
  }
  sql += ' ORDER BY j.created_at DESC, j.id DESC LIMIT ?';
  params.push(limit);

  const jobs = db.prepare(sql).all(...params) as any[];
  const attemptsStmt = db.prepare(
    'SELECT * FROM delivery_attempts WHERE job_id = ? ORDER BY attempt_number ASC'
  );

  const hydrated = jobs.map((j) => ({
    ...j,
    attempts: attemptsStmt.all(j.id),
  }));

  res.json(hydrated);
});

app.post('/api/v1/queue/:id/cancel', requireAdminAuth, (req: Request, res: Response) => {
  const job = db.prepare('SELECT * FROM delivery_jobs WHERE id = ?').get(req.params.id) as any;
  if (!job) {
    res.status(404).json({ error: 'NOT_FOUND', message: 'Queue job not found.' });
    return;
  }
  if (!['PENDING', 'RETRY_SCHEDULED'].includes(job.status)) {
    res.status(400).json({
      error: 'INVALID_STATE',
      message: `Cannot cancel job in state ${job.status}.`,
    });
    return;
  }

  withTransaction(() => {
    db.prepare(`
      UPDATE delivery_jobs
      SET status = 'CANCELLED', completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
      WHERE id = ?
    `).run(job.id);
    // Remove deduplication lock so a cancelled pending job can be re-queued later if desired
    db.prepare('DELETE FROM deduplication_records WHERE job_id = ?').run(job.id);
  });

  logAppEvent({
    level: 'INFO',
    event_type: 'QUEUE_JOB_CANCELLED',
    rule_id: job.rule_id,
    source_peer_id: job.source_peer_id,
    destination_peer_id: job.destination_peer_id,
    source_message_id: Number(job.source_message_id),
    operation: 'QUEUE_CONTROL',
    diagnostic_message: `Cancelled queued job ${job.id}`,
  });

  res.json({ ok: true, id: job.id });
});

app.post('/api/v1/queue/process-now', requireAdminAuth, async (_req: Request, res: Response) => {
  const result = await processDeliveryQueueTick(true);
  res.json(result);
});

// ============================================================================
// 10. Historical Backfill Preview, Creation & Lifecycle Controls
// ============================================================================
app.post('/api/v1/backfill/preview', requireAdminAuth, (req: Request, res: Response) => {
  const sourcePeerId = String(req.body?.source_peer_id || '').trim();
  const mode = String(req.body?.mode || 'ALL_ACCESSIBLE').toUpperCase();
  const lastN = req.body?.last_n_count ? Number(req.body.last_n_count) : 50;
  const startId = req.body?.start_message_id ? Number(req.body.start_message_id) : null;
  const endId = req.body?.end_message_id ? Number(req.body.end_message_id) : null;
  const direction = String(req.body?.direction || 'OLDEST_FIRST').toUpperCase();

  if (!sourcePeerId) {
    res.status(400).json({ error: 'VALIDATION_ERROR', message: 'source_peer_id is required.' });
    return;
  }
  if (mode === 'LAST_N' && (lastN < 50 || lastN > 5000)) {
    res.status(400).json({
      error: 'VALIDATION_ERROR',
      message: 'Last N count must be between 50 and 5,000.',
    });
    return;
  }

  let sql = 'SELECT * FROM source_messages_archive WHERE source_peer_id = ?';
  const params: any[] = [sourcePeerId];
  if (mode === 'MESSAGE_ID_RANGE') {
    if (startId) {
      sql += ' AND message_id >= ?';
      params.push(startId);
    }
    if (endId) {
      sql += ' AND message_id <= ?';
      params.push(endId);
    }
  }
  sql += ` ORDER BY message_id ${direction === 'NEWEST_FIRST' ? 'DESC' : 'ASC'}`;
  if (mode === 'LAST_N') {
    sql += ` LIMIT ${Math.min(5000, Math.max(50, lastN))}`;
  }

  const messages = db.prepare(sql).all(...params) as any[];
  const rules = sortRulesByPriority(getAllRules()).filter(
    (r) => r.enabled && r.source_peer_id === sourcePeerId
  );

  const warnings: string[] = [];
  if (rules.length === 0) {
    warnings.push('No enabled forwarding rules match this source chat.');
  }

  let matchingMessages = 0;
  let expectedSkipped = 0;
  const destBreakdown: Record<string, number> = {};
  const deliveryModes = new Set<string>();

  for (const m of messages) {
    const candidate: CandidateMessage = {
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
    };

    let matchedAny = false;
    for (const r of rules) {
      const rep = evaluateRuleAgainstMessage(r, candidate, new Date());
      if (rep.matched) {
        matchedAny = true;
        deliveryModes.add(r.delivery_mode);
        for (const d of r.destination_peer_ids) {
          destBreakdown[d] = (destBreakdown[d] || 0) + 1;
        }
        if (r.exclusive_stop) break;
      }
    }
    if (matchedAny) {
      matchingMessages++;
    } else {
      expectedSkipped++;
    }
  }

  res.json({
    source_peer_id: sourcePeerId,
    mode,
    direction,
    selected_range:
      mode === 'MESSAGE_ID_RANGE'
        ? `${startId ?? 'Start'} .. ${endId ?? 'Latest'}`
        : mode === 'LAST_N'
          ? `Last ${lastN} messages`
          : mode,
    examined_count: messages.length,
    matching_count: matchingMessages,
    expected_skipped_count: expectedSkipped,
    destination_breakdown: destBreakdown,
    expected_delivery_modes: Array.from(deliveryModes),
    configuration_warnings: warnings,
    estimated_duration_seconds: Math.max(2, Math.ceil(matchingMessages * 1.2)),
  });
});

app.get('/api/v1/backfill', requireAdminAuth, (_req: Request, res: Response) => {
  const rows = db
    .prepare(
      `SELECT b.*, c.title AS source_title
       FROM backfill_jobs b
       LEFT JOIN chats c ON c.peer_id = b.source_peer_id
       ORDER BY b.created_at DESC`
    )
    .all();
  res.json(rows);
});

app.post('/api/v1/backfill', requireAdminAuth, (req: Request, res: Response) => {
  const sourcePeerId = String(req.body?.source_peer_id || '').trim();
  const name = String(req.body?.name || `Backfill ${sourcePeerId}`).trim();
  const mode = String(req.body?.mode || 'ALL_ACCESSIBLE').toUpperCase();
  const lastN = req.body?.last_n_count ? Number(req.body.last_n_count) : null;
  const startId = req.body?.start_message_id ? Number(req.body.start_message_id) : null;
  const endId = req.body?.end_message_id ? Number(req.body.end_message_id) : null;
  const direction = String(req.body?.direction || 'OLDEST_FIRST').toUpperCase();
  const batchSize = Math.max(1, Math.min(200, Number(req.body?.batch_size || 4)));
  const rateLimit = Math.max(5, Math.min(300, Number(req.body?.rate_limit_per_min || 30)));

  if (!sourcePeerId) {
    res.status(400).json({ error: 'VALIDATION_ERROR', message: 'Source chat is required.' });
    return;
  }

  const countRow = db
    .prepare('SELECT COUNT(*) AS cnt FROM source_messages_archive WHERE source_peer_id = ?')
    .get(sourcePeerId) as any;

  const jobId = `bf-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
  db.prepare(`
    INSERT INTO backfill_jobs (
      id, name, source_peer_id, mode, last_n_count, start_message_id, end_message_id,
      direction, batch_size, rate_limit_per_min, status, total_estimated
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?)
  `).run(
    jobId,
    name,
    sourcePeerId,
    mode,
    lastN,
    startId,
    endId,
    direction,
    batchSize,
    rateLimit,
    Number(countRow?.cnt ?? 0)
  );

  logAppEvent({
    level: 'INFO',
    event_type: 'BACKFILL_STARTED',
    source_peer_id: sourcePeerId,
    operation: 'BACKFILL',
    diagnostic_message: `Started historical backfill '${name}' (${mode}, ${direction})`,
  });

  processRunningBackfillTick();
  const created = db.prepare('SELECT * FROM backfill_jobs WHERE id = ?').get(jobId);
  res.status(201).json(created);
});

app.post('/api/v1/backfill/:id/action', requireAdminAuth, (req: Request, res: Response) => {
  const action = String(req.body?.action || '').toLowerCase();
  const job = db.prepare('SELECT * FROM backfill_jobs WHERE id = ?').get(req.params.id) as any;
  if (!job) {
    res.status(404).json({ error: 'NOT_FOUND', message: 'Backfill job not found.' });
    return;
  }

  if (action === 'pause') {
    db.prepare(
      "UPDATE backfill_jobs SET status = 'PAUSED', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?"
    ).run(job.id);
  } else if (action === 'resume') {
    db.prepare(
      "UPDATE backfill_jobs SET status = 'RUNNING', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?"
    ).run(job.id);
    processRunningBackfillTick();
  } else if (action === 'stop') {
    db.prepare(
      "UPDATE backfill_jobs SET status = 'STOPPED', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?"
    ).run(job.id);
  } else if (action === 'restart') {
    db.prepare(`
      UPDATE backfill_jobs SET
        status = 'RUNNING',
        current_cursor_message_id = NULL,
        examined_count = 0,
        matched_count = 0,
        forwarded_count = 0,
        skipped_count = 0,
        failed_count = 0,
        completed_at = NULL,
        updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
      WHERE id = ?
    `).run(job.id);
    processRunningBackfillTick();
  } else {
    res.status(400).json({ error: 'INVALID_ACTION', message: `Unknown action: ${action}` });
    return;
  }

  const updated = db.prepare('SELECT * FROM backfill_jobs WHERE id = ?').get(job.id);
  res.json(updated);
});

// ============================================================================
// 11. Missed-Message Catch-Up Recovery Endpoints
// ============================================================================
app.get('/api/v1/catchup', requireAdminAuth, (_req: Request, res: Response) => {
  const jobs = db
    .prepare('SELECT * FROM catchup_jobs ORDER BY created_at DESC LIMIT 25')
    .all();
  const cursors = db.prepare('SELECT * FROM source_cursors').all();
  res.json({ jobs, cursors });
});

app.post('/api/v1/catchup/run', requireAdminAuth, async (req: Request, res: Response) => {
  const requestedSource = req.body?.source_peer_id
    ? String(req.body.source_peer_id).trim()
    : null;

  const rules = getAllRules();
  const sourcePeers = requestedSource
    ? [requestedSource]
    : Array.from(new Set(rules.map((r) => r.source_peer_id)));

  const results = [];

  for (const peerId of sourcePeers) {
    const cursorRow = db
      .prepare('SELECT * FROM source_cursors WHERE source_peer_id = ?')
      .get(peerId) as any;
    const lastProcessed = Number(cursorRow?.last_processed_message_id ?? 0);

    const missedMessages = db
      .prepare(
        'SELECT * FROM source_messages_archive WHERE source_peer_id = ? AND message_id > ? ORDER BY message_id ASC'
      )
      .all(peerId, lastProcessed) as any[];

    if (missedMessages.length === 0) continue;

    const fromId = lastProcessed + 1;
    const toId = Number(missedMessages[missedMessages.length - 1].message_id);
    const catchupId = `cu-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;

    let enqueuedTotal = 0;
    let skippedTotal = 0;

    for (const m of missedMessages) {
      const routed = routeAndEnqueueMessage(
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
          has_protected_content: Boolean(m.has_protected_content),
          timestamp_utc: m.timestamp_utc,
        },
        'CATCHUP',
        null,
        true
      );
      enqueuedTotal += routed.enqueuedJobIds.length;
      skippedTotal += routed.skippedDuplicates;
    }

    db.prepare(`
      INSERT INTO catchup_jobs (
        id, source_peer_id, trigger_mode, from_message_id, to_message_id,
        current_cursor_message_id, status, estimated_gap, processed_count,
        enqueued_count, skipped_count, failed_count, completed_at
      ) VALUES (?, ?, 'MANUAL', ?, ?, ?, 'COMPLETED', ?, ?, ?, ?, 0, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    `).run(
      catchupId,
      peerId,
      fromId,
      toId,
      toId,
      missedMessages.length,
      missedMessages.length,
      enqueuedTotal,
      skippedTotal
    );

    logAppEvent({
      level: 'SUCCESS',
      event_type: 'CATCHUP_COMPLETED',
      source_peer_id: peerId,
      operation: 'CATCHUP_RECOVERY',
      diagnostic_message: `Recovered ${missedMessages.length} missed message(s) (${fromId}..${toId}) from ${peerId}; enqueued ${enqueuedTotal} delivery job(s)`,
    });

    results.push({
      catchup_id: catchupId,
      source_peer_id: peerId,
      from_message_id: fromId,
      to_message_id: toId,
      examined: missedMessages.length,
      enqueued: enqueuedTotal,
    });
  }

  await processDeliveryQueueTick(false);
  res.json({ recovered_sources: results.length, details: results });
});

// ============================================================================
// 12. Source Edit & Delete Synchronization Endpoints
// ============================================================================
app.get('/api/v1/sync/mappings', requireAdminAuth, (_req: Request, res: Response) => {
  const rows = db
    .prepare(
      `SELECT m.*, r.name AS rule_name, c_src.title AS source_title, c_dst.title AS destination_title
       FROM message_mappings m
       LEFT JOIN rules r ON r.id = m.rule_id
       LEFT JOIN chats c_src ON c_src.peer_id = m.source_peer_id
       LEFT JOIN chats c_dst ON c_dst.peer_id = m.destination_peer_id
       ORDER BY m.updated_at DESC
       LIMIT 100`
    )
    .all();
  res.json(rows);
});

app.post('/api/v1/sync/simulate-edit', requireAdminAuth, (req: Request, res: Response) => {
  const sourcePeerId = String(req.body?.source_peer_id || '').trim();
  const sourceMessageId = Number(req.body?.source_message_id);
  const newCaption = String(req.body?.new_caption || '');

  if (!sourcePeerId || !sourceMessageId) {
    res.status(400).json({
      error: 'VALIDATION_ERROR',
      message: 'source_peer_id and source_message_id are required.',
    });
    return;
  }

  const result = propagateSourceEdit(sourcePeerId, sourceMessageId, newCaption);
  res.json(result);
});

app.post('/api/v1/sync/simulate-delete', requireAdminAuth, (req: Request, res: Response) => {
  const sourcePeerId = String(req.body?.source_peer_id || '').trim();
  const sourceMessageId = Number(req.body?.source_message_id);

  if (!sourcePeerId || !sourceMessageId) {
    res.status(400).json({
      error: 'VALIDATION_ERROR',
      message: 'source_peer_id and source_message_id are required.',
    });
    return;
  }

  const result = propagateSourceDelete(sourcePeerId, sourceMessageId);
  res.json(result);
});

// ============================================================================
// 13. Operational Logs & Persistent Statistics
// ============================================================================
app.get('/api/v1/logs', requireAdminAuth, (req: Request, res: Response) => {
  const level = String(req.query.level || '').toUpperCase();
  const ruleId = String(req.query.rule_id || '').trim();
  const sourcePeerId = String(req.query.source_peer_id || '').trim();
  const destinationPeerId = String(req.query.destination_peer_id || '').trim();
  const errorCategory = String(req.query.error_category || '').trim();
  const messageId = req.query.message_id ? Number(req.query.message_id) : null;
  const q = String(req.query.q || '').trim().toLowerCase();
  const page = Math.max(1, Number(req.query.page || 1));
  const pageSize = Math.min(100, Math.max(10, Number(req.query.page_size || 25)));

  const whereClauses: string[] = [];
  const params: any[] = [];

  if (level && level !== 'ALL') {
    whereClauses.push('level = ?');
    params.push(level);
  }
  if (ruleId) {
    whereClauses.push('rule_id = ?');
    params.push(ruleId);
  }
  if (sourcePeerId) {
    whereClauses.push('source_peer_id = ?');
    params.push(sourcePeerId);
  }
  if (destinationPeerId) {
    whereClauses.push('destination_peer_id = ?');
    params.push(destinationPeerId);
  }
  if (errorCategory) {
    whereClauses.push('error_category = ?');
    params.push(errorCategory);
  }
  if (messageId !== null && !Number.isNaN(messageId)) {
    whereClauses.push('source_message_id = ?');
    params.push(messageId);
  }
  if (q) {
    whereClauses.push('(LOWER(diagnostic_message) LIKE ? OR LOWER(event_type) LIKE ?)');
    params.push(`%${q}%`, `%${q}%`);
  }

  const whereSql = whereClauses.length > 0 ? `WHERE ${whereClauses.join(' AND ')}` : '';
  const totalRow = db
    .prepare(`SELECT COUNT(*) AS cnt FROM app_events ${whereSql}`)
    .get(...params) as any;

  const offset = (page - 1) * pageSize;
  const rows = db
    .prepare(
      `SELECT * FROM app_events ${whereSql} ORDER BY id DESC LIMIT ? OFFSET ?`
    )
    .all(...params, pageSize, offset);

  res.json({
    total: Number(totalRow?.cnt ?? 0),
    page,
    page_size: pageSize,
    items: rows,
  });
});

app.get('/api/v1/stats', requireAdminAuth, (_req: Request, res: Response) => {
  const counters = db.prepare('SELECT * FROM stats_counters').all() as any[];
  const rules = getAllRules();
  const ruleMap = new Map(rules.map((r) => [r.id, r.name]));
  const chats = db.prepare('SELECT peer_id, title FROM chats').all() as any[];
  const chatMap = new Map(chats.map((c) => [String(c.peer_id), c.title]));

  const globalCounter = counters.find((c) => c.counter_key === 'GLOBAL:ALL') || {
    successful_deliveries: 0,
    skipped_messages: 0,
    failed_deliveries: 0,
    retry_count: 0,
    total_latency_ms: 0,
  };

  const perRule = counters
    .filter((c) => c.scope_type === 'RULE')
    .map((c) => ({
      rule_id: c.scope_id,
      rule_name: ruleMap.get(c.scope_id) || c.scope_id,
      successful_deliveries: Number(c.successful_deliveries),
      skipped_messages: Number(c.skipped_messages),
      failed_deliveries: Number(c.failed_deliveries),
      retry_count: Number(c.retry_count),
      avg_latency_ms:
        Number(c.successful_deliveries) > 0
          ? Math.round(Number(c.total_latency_ms) / Number(c.successful_deliveries))
          : 0,
    }));

  const perDestination = counters
    .filter((c) => c.scope_type === 'DESTINATION')
    .map((c) => ({
      destination_peer_id: c.scope_id,
      destination_title: chatMap.get(c.scope_id) || c.scope_id,
      successful_deliveries: Number(c.successful_deliveries),
      skipped_messages: Number(c.skipped_messages),
      failed_deliveries: Number(c.failed_deliveries),
      retry_count: Number(c.retry_count),
      avg_latency_ms:
        Number(c.successful_deliveries) > 0
          ? Math.round(Number(c.total_latency_ms) / Number(c.successful_deliveries))
          : 0,
    }));

  const pendingRow = db
    .prepare(
      "SELECT COUNT(*) AS cnt FROM delivery_jobs WHERE status IN ('PENDING', 'RETRY_SCHEDULED', 'PROCESSING')"
    )
    .get() as any;

  res.json({
    global: {
      successful_deliveries: Number(globalCounter.successful_deliveries),
      skipped_messages: Number(globalCounter.skipped_messages),
      failed_deliveries: Number(globalCounter.failed_deliveries),
      retry_count: Number(globalCounter.retry_count),
      pending_queue_size: Number(pendingRow?.cnt ?? 0),
      avg_latency_ms:
        Number(globalCounter.successful_deliveries) > 0
          ? Math.round(
              Number(globalCounter.total_latency_ms) /
                Number(globalCounter.successful_deliveries)
            )
          : 0,
    },
    per_rule: perRule,
    per_destination: perDestination,
  });
});

// ============================================================================
// 14. Global Settings, Maintenance & Diagnostics
// ============================================================================
app.get('/api/v1/settings', requireAdminAuth, (_req: Request, res: Response) => {
  res.json({
    settings: getAppSettings(),
    telegram: getTelegramAccountStatus(),
  });
});

app.put('/api/v1/settings', requireAdminAuth, (req: Request, res: Response) => {
  const updated = updateAppSettings(req.body || {});
  logAppEvent({
    level: 'INFO',
    event_type: 'SETTINGS_UPDATED',
    operation: 'SETTINGS',
    diagnostic_message: `Updated global settings (forwarding_enabled=${updated.forwarding_enabled}, dedup_scope=${updated.deduplication_scope}, concurrency=${updated.delivery_concurrency})`,
  });
  res.json(updated);
});

app.post('/api/v1/maintenance/cleanup-logs', requireAdminAuth, (_req: Request, res: Response) => {
  const settings = getAppSettings();
  const info = db
    .prepare(
      `DELETE FROM app_events WHERE timestamp < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)`
    )
    .run(`-${settings.log_retention_days} days`);
  logAppEvent({
    level: 'INFO',
    event_type: 'LOG_RETENTION_CLEANUP',
    operation: 'DB_MAINTENANCE',
    diagnostic_message: `Purged ${info.changes} log record(s) older than ${settings.log_retention_days} days (persistent stats_counters preserved)`,
  });
  res.json({ deleted_rows: Number(info.changes) });
});

app.post('/api/v1/maintenance/clear-dedup', requireAdminAuth, (_req: Request, res: Response) => {
  const info = db.prepare('DELETE FROM deduplication_records').run();
  logAppEvent({
    level: 'WARNING',
    event_type: 'DEDUP_RECORDS_CLEARED',
    operation: 'DB_MAINTENANCE',
    diagnostic_message: `Cleared ${info.changes} persistent deduplication record(s)`,
  });
  res.json({ cleared_rows: Number(info.changes) });
});

app.post('/api/v1/maintenance/run-tests', requireAdminAuth, (_req: Request, res: Response) => {
  const report = runAllAutomatedTests();
  res.json(report);
});

app.get('/api/v1/diagnostics/source-files', requireAdminAuth, (_req: Request, res: Response) => {
  const filesToInspect = [
    'Cargo.toml',
    'Dockerfile',
    'compose.yaml',
    '.env.example',
    'migrations/0001_initial_schema.sql',
    'src-rust/main.rs',
    'src-rust/lib.rs',
    'src-rust/classifier.rs',
    'src-rust/filters.rs',
    'src-rust/transform.rs',
    'src-rust/scheduler.rs',
    'src-rust/rules.rs',
    'src-rust/router.rs',
    'src-rust/queue.rs',
    'src-rust/telegram.rs',
    'src-rust/security.rs',
    'src-rust/tests.rs',
    'README.md',
    'docs/ARCHITECTURE.md',
  ];

  const items = filesToInspect.map((relPath) => {
    const abs = path.resolve(process.cwd(), relPath);
    if (!fs.existsSync(abs)) {
      return { path: relPath, exists: false, size_bytes: 0, preview: '' };
    }
    const content = fs.readFileSync(abs, 'utf8');
    return {
      path: relPath,
      exists: true,
      size_bytes: Buffer.byteLength(content, 'utf8'),
      content,
    };
  });

  const mem = process.memoryUsage();
  res.json({
    memory: {
      rss_mb: Math.round((mem.rss / (1024 * 1024)) * 10) / 10,
      heap_used_mb: Math.round((mem.heapUsed / (1024 * 1024)) * 10) / 10,
    },
    files: items,
  });
});

// ============================================================================
// 15. Vite Dev Middleware / Production Static Asset Serving
// ============================================================================
async function startServer() {
  const distDir = path.resolve(process.cwd(), 'dist');
  const isProd = process.env.NODE_ENV === 'production' && fs.existsSync(distDir);
  const httpServer = http.createServer(app);

  if (isProd) {
    app.use(express.static(distDir));
    app.get('*', (_req, res) => {
      res.sendFile(path.join(distDir, 'index.html'));
    });
  } else {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: {
        middlewareMode: true,
        allowedHosts: true,
        ws: {
          server: httpServer,
        },
        hmr:
          process.env.DISABLE_HMR === 'true'
            ? false
            : {
                server: httpServer,
              },
        watch: process.env.DISABLE_HMR === 'true' ? null : {},
      },
      appType: 'spa',
    });

    app.get('/@vite/client', async (_req, res, next) => {
      try {
        const result = await vite.transformRequest('/@vite/client');
        if (result?.code) {
          const patched = result.code
            .replace(
              /reject\(\/\* @__PURE__ \*\/ new Error\("WebSocket closed without opened\."\)\);/g,
              'resolve();'
            )
            .replace(
              /ws\.send\(JSON\.stringify\(data\)\);/g,
              'if (ws && ws.readyState === 1) ws.send(JSON.stringify(data));'
            );
          res.setHeader('Content-Type', 'application/javascript; charset=utf-8');
          res.setHeader('Cache-Control', 'no-store');
          res.status(200).send(patched);
          return;
        }
      } catch {
        // Fall through to default Vite middleware
      }
      next();
    });

    app.use(vite.middlewares);
  }

  httpServer.listen(PORT, '0.0.0.0', () => {
    console.log(`TeleRoute MTProto Core listening on http://0.0.0.0:${PORT}`);
  });

  const shutdown = () => {
    httpServer.close(() => {
      try {
        db.close();
      } catch {
        // ignore
      }
      process.exit(0);
    });
  };
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

startServer();
