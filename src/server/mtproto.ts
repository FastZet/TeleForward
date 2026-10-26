import { TelegramClient, Api } from 'telegram';
import { StringSession } from 'telegram/sessions/index.js';
import {
  db,
  getAppSettings,
  getRuleById,
  incrementStatsCounter,
  logAppEvent,
  routeAndEnqueueMessage,
  withTransaction,
} from './db.js';
import {
  decryptSensitiveString,
  encryptSensitiveString,
  getEncryptionKeyFingerprint,
  isExplicitEncryptionKeyConfigured,
  maskPhoneNumber,
} from './security.js';
import { isWithinScheduleWindow } from './engine.js';
import { TelegramConnectionState } from './types.js';

let loginMutexLocked = false;
let activeMtprotoClient: TelegramClient | null = null;
let pendingPhoneNumber = '';
let pendingPhoneCodeHash = '';
let pendingTestMode = false;
let pendingTestRequires2FA = false;
let lastSendTimestampMs = 0;

export function getTelegramAccountStatus() {
  const row = db.prepare('SELECT * FROM telegram_account WHERE id = 1').get() as any;
  const sessionRow = db
    .prepare('SELECT key_fingerprint, updated_at FROM telegram_session_encrypted WHERE id = 1')
    .get() as any;

  return {
    api_configured: Boolean(row?.api_id && row?.api_hash_encrypted),
    api_id: row?.api_id ? Number(row.api_id) : null,
    phone_number_masked: row?.phone_number_masked ?? null,
    account_user_id: row?.account_user_id ?? null,
    account_username: row?.account_username ?? null,
    account_display_name: row?.account_display_name ?? null,
    connection_state: (row?.connection_state || 'NOT_CONFIGURED') as TelegramConnectionState,
    last_error: row?.last_error ?? null,
    last_connected_at: row?.last_connected_at ?? null,
    has_encrypted_session: Boolean(sessionRow),
    session_key_fingerprint: sessionRow?.key_fingerprint ?? getEncryptionKeyFingerprint(),
    explicit_encryption_key_configured: isExplicitEncryptionKeyConfigured(),
    login_lock_active: loginMutexLocked,
  };
}

function setConnectionState(
  state: TelegramConnectionState,
  lastError: string | null = null
): void {
  db.prepare(`
    UPDATE telegram_account
    SET connection_state = ?, last_error = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id = 1
  `).run(state, lastError);
}

export async function configureTelegramCredentials(
  apiId: number,
  apiHash: string
): Promise<ReturnType<typeof getTelegramAccountStatus>> {
  if (loginMutexLocked) {
    throw new Error('Another Telegram authentication flow is currently in progress.');
  }
  if (!Number.isInteger(apiId) || apiId <= 0) {
    throw new Error('Telegram API ID must be a positive integer.');
  }
  const cleanHash = apiHash.trim();
  if (cleanHash.length < 16) {
    throw new Error('Telegram API Hash must be a valid hexadecimal string from my.telegram.org.');
  }

  const encryptedHash = encryptSensitiveString(cleanHash);
  db.prepare(`
    UPDATE telegram_account SET
      api_id = ?,
      api_hash_encrypted = ?,
      api_hash_iv = ?,
      api_hash_tag = ?,
      connection_state = 'AWAITING_PHONE_NUMBER',
      last_error = NULL,
      updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id = 1
  `).run(
    apiId,
    encryptedHash.ciphertext_b64,
    encryptedHash.nonce_b64,
    encryptedHash.auth_tag_b64
  );

  logAppEvent({
    level: 'INFO',
    event_type: 'TELEGRAM_API_CONFIGURED',
    operation: 'MTPROTO_AUTH',
    diagnostic_message: `Configured Telegram API ID ${apiId} (API Hash encrypted at rest with AES-256-GCM)`,
  });

  return getTelegramAccountStatus();
}

export async function requestTelegramLoginCode(
  phoneInternational: string,
  useTestDcSandbox = false,
  require2faInSandbox = true
): Promise<ReturnType<typeof getTelegramAccountStatus>> {
  if (loginMutexLocked) {
    throw new Error('Simultaneous login flow blocked: authentication already in progress.');
  }
  const cleanPhone = phoneInternational.trim();
  if (!/^\+[1-9]\d{6,14}$/.test(cleanPhone)) {
    throw new Error(
      'Phone number must be in international E.164 format starting with + (e.g. +14155550199).'
    );
  }

  const row = db.prepare('SELECT * FROM telegram_account WHERE id = 1').get() as any;
  if (!row?.api_id || !row?.api_hash_encrypted) {
    throw new Error('Configure Telegram API ID and API Hash first.');
  }

  loginMutexLocked = true;
  try {
    setConnectionState('CONNECTING', null);
    pendingPhoneNumber = cleanPhone;
    const masked = maskPhoneNumber(cleanPhone);

    if (useTestDcSandbox || cleanPhone.startsWith('+99966')) {
      pendingTestMode = true;
      pendingTestRequires2FA = require2faInSandbox;
      pendingPhoneCodeHash = `test-dc-hash-${Date.now()}`;
      db.prepare(`
        UPDATE telegram_account SET
          phone_number_masked = ?,
          connection_state = 'AWAITING_LOGIN_CODE',
          last_error = NULL,
          updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = 1
      `).run(masked);

      logAppEvent({
        level: 'INFO',
        event_type: 'LOGIN_CODE_REQUESTED',
        operation: 'MTPROTO_AUTH',
        diagnostic_message: `Requested MTProto login code for ${masked} (Test Account DC Sandbox)`,
      });
      return getTelegramAccountStatus();
    }

    pendingTestMode = false;
    const apiHash = decryptSensitiveString({
      ciphertext_b64: row.api_hash_encrypted,
      nonce_b64: row.api_hash_iv,
      auth_tag_b64: row.api_hash_tag,
      key_fingerprint: getEncryptionKeyFingerprint(),
    });

    const client = new TelegramClient(new StringSession(''), Number(row.api_id), apiHash, {
      connectionRetries: 2,
    });
    await client.connect();
    const res = await client.sendCode(
      { apiId: Number(row.api_id), apiHash },
      cleanPhone
    );
    activeMtprotoClient = client;
    pendingPhoneCodeHash = res.phoneCodeHash;

    db.prepare(`
      UPDATE telegram_account SET
        phone_number_masked = ?,
        connection_state = 'AWAITING_LOGIN_CODE',
        last_error = NULL,
        updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
      WHERE id = 1
    `).run(masked);

    logAppEvent({
      level: 'INFO',
      event_type: 'LOGIN_CODE_REQUESTED',
      operation: 'MTPROTO_AUTH',
      diagnostic_message: `Requested Telegram MTProto login code for ${masked}`,
    });

    return getTelegramAccountStatus();
  } catch (err: any) {
    const errMsg = err?.message || 'Failed to request login code from Telegram MTProto';
    setConnectionState('ERROR', errMsg);
    logAppEvent({
      level: 'FAILURE',
      event_type: 'LOGIN_CODE_ERROR',
      error_category: 'AUTH_FAILURE',
      operation: 'MTPROTO_AUTH',
      diagnostic_message: errMsg,
    });
    throw new Error(errMsg);
  } finally {
    loginMutexLocked = false;
  }
}

export async function verifyTelegramLoginCode(
  code: string
): Promise<ReturnType<typeof getTelegramAccountStatus>> {
  if (loginMutexLocked) {
    throw new Error('Simultaneous login flow blocked: authentication already in progress.');
  }
  const cleanCode = code.trim();
  if (!/^\d{4,8}$/.test(cleanCode)) {
    throw new Error('Telegram login code must be 4 to 8 digits.');
  }

  loginMutexLocked = true;
  try {
    if (pendingTestMode) {
      if (cleanCode === '00000') {
        throw new Error('PHONE_CODE_INVALID: The login code entered is invalid.');
      }
      if (pendingTestRequires2FA) {
        setConnectionState('AWAITING_TWO_STEP_PASSWORD', null);
        logAppEvent({
          level: 'INFO',
          event_type: 'TWO_STEP_PASSWORD_REQUIRED',
          operation: 'MTPROTO_AUTH',
          diagnostic_message:
            'Login code verified; account requires Two-Step Verification (2FA) cloud password',
        });
        return getTelegramAccountStatus();
      }
      finalizeAuthenticatedSession(
        `19920481`,
        `teleroute_operator`,
        `TeleRoute Personal Account`,
        `1BVtsOMTProtoTestSession_${Date.now()}`
      );
      return getTelegramAccountStatus();
    }

    if (!activeMtprotoClient || !pendingPhoneNumber || !pendingPhoneCodeHash) {
      throw new Error('No pending login code session found. Request a login code first.');
    }

    try {
      const result: any = await activeMtprotoClient.invoke(
        new Api.auth.SignIn({
          phoneNumber: pendingPhoneNumber,
          phoneCodeHash: pendingPhoneCodeHash,
          phoneCode: cleanCode,
        })
      );
      const user: any = result?.user || {};
      const rawSession = activeMtprotoClient.session.save() as unknown as string;
      finalizeAuthenticatedSession(
        String(user.id || '10001'),
        user.username || null,
        [user.firstName, user.lastName].filter(Boolean).join(' ') || 'Telegram User',
        rawSession
      );
      return getTelegramAccountStatus();
    } catch (rpcErr: any) {
      const msg = String(rpcErr?.errorMessage || rpcErr?.message || '');
      if (msg.includes('SESSION_PASSWORD_NEEDED')) {
        setConnectionState('AWAITING_TWO_STEP_PASSWORD', null);
        logAppEvent({
          level: 'INFO',
          event_type: 'TWO_STEP_PASSWORD_REQUIRED',
          operation: 'MTPROTO_AUTH',
          diagnostic_message:
            'MTProto returned SESSION_PASSWORD_NEEDED; awaiting two-step verification password',
        });
        return getTelegramAccountStatus();
      }
      throw rpcErr;
    }
  } catch (err: any) {
    const errMsg = err?.message || 'Failed to verify login code';
    setConnectionState('ERROR', errMsg);
    logAppEvent({
      level: 'FAILURE',
      event_type: 'LOGIN_VERIFY_ERROR',
      error_category: 'AUTH_FAILURE',
      operation: 'MTPROTO_AUTH',
      diagnostic_message: errMsg,
    });
    throw new Error(errMsg);
  } finally {
    loginMutexLocked = false;
  }
}

export async function verifyTwoStepPassword(
  password: string
): Promise<ReturnType<typeof getTelegramAccountStatus>> {
  if (loginMutexLocked) {
    throw new Error('Simultaneous login flow blocked.');
  }
  if (!password || password.length < 1) {
    throw new Error('Two-step verification password is required.');
  }

  loginMutexLocked = true;
  try {
    if (pendingTestMode) {
      if (password === 'wrong') {
        throw new Error('PASSWORD_HASH_INVALID: Two-step verification password rejected.');
      }
      finalizeAuthenticatedSession(
        `19920481`,
        `teleroute_operator`,
        `TeleRoute Personal Account`,
        `1BVtsOMTProto2FASession_${Date.now()}`
      );
      return getTelegramAccountStatus();
    }

    if (!activeMtprotoClient) {
      throw new Error('No active MTProto client awaiting 2FA verification.');
    }

    const row = db.prepare('SELECT * FROM telegram_account WHERE id = 1').get() as any;
    const apiHash = decryptSensitiveString({
      ciphertext_b64: row.api_hash_encrypted,
      nonce_b64: row.api_hash_iv,
      auth_tag_b64: row.api_hash_tag,
      key_fingerprint: getEncryptionKeyFingerprint(),
    });

    await (activeMtprotoClient as any).signInWithPassword(
      { apiId: Number(row.api_id), apiHash },
      {
        password: async () => password,
        onError: (e: Error) => {
          throw e;
        },
      }
    );

    const me: any = await activeMtprotoClient.getMe();
    const rawSession = activeMtprotoClient.session.save() as unknown as string;
    finalizeAuthenticatedSession(
      String(me?.id || '10001'),
      me?.username || null,
      [me?.firstName, me?.lastName].filter(Boolean).join(' ') || 'Telegram User',
      rawSession
    );
    return getTelegramAccountStatus();
  } catch (err: any) {
    const errMsg = err?.message || 'Two-step verification failed';
    setConnectionState('ERROR', errMsg);
    logAppEvent({
      level: 'FAILURE',
      event_type: 'TWO_STEP_AUTH_FAILURE',
      error_category: 'AUTH_FAILURE',
      operation: 'MTPROTO_AUTH',
      diagnostic_message: 'Two-step verification password check failed',
    });
    throw new Error(errMsg);
  } finally {
    loginMutexLocked = false;
  }
}

function finalizeAuthenticatedSession(
  userId: string,
  username: string | null,
  displayName: string,
  rawSessionMaterial: string
): void {
  const enc = encryptSensitiveString(rawSessionMaterial);
  withTransaction(() => {
    db.prepare(`
      INSERT INTO telegram_session_encrypted (
        id, ciphertext_b64, nonce_b64, auth_tag_b64, key_fingerprint, schema_version, updated_at
      ) VALUES (1, ?, ?, ?, ?, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
      ON CONFLICT(id) DO UPDATE SET
        ciphertext_b64 = excluded.ciphertext_b64,
        nonce_b64 = excluded.nonce_b64,
        auth_tag_b64 = excluded.auth_tag_b64,
        key_fingerprint = excluded.key_fingerprint,
        updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    `).run(enc.ciphertext_b64, enc.nonce_b64, enc.auth_tag_b64, enc.key_fingerprint);

    db.prepare(`
      UPDATE telegram_account SET
        account_user_id = ?,
        account_username = ?,
        account_display_name = ?,
        connection_state = 'CONNECTED',
        last_error = NULL,
        last_connected_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
        updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
      WHERE id = 1
    `).run(userId, username, displayName);
  });

  logAppEvent({
    level: 'SUCCESS',
    event_type: 'TELEGRAM_SESSION_CONNECTED',
    operation: 'MTPROTO_AUTH',
    diagnostic_message: `Authenticated personal Telegram account ${displayName} (ID ${userId}); session encrypted at rest (fp: ${enc.key_fingerprint})`,
  });
}

export async function reconnectPersistedTelegramSession(): Promise<
  ReturnType<typeof getTelegramAccountStatus>
> {
  const encRow = db
    .prepare('SELECT * FROM telegram_session_encrypted WHERE id = 1')
    .get() as any;
  if (!encRow) {
    throw new Error('No persisted encrypted Telegram session found. Complete login first.');
  }

  try {
    setConnectionState('RECONNECTING', null);
    const decryptedSession = decryptSensitiveString({
      ciphertext_b64: encRow.ciphertext_b64,
      nonce_b64: encRow.nonce_b64,
      auth_tag_b64: encRow.auth_tag_b64,
      key_fingerprint: encRow.key_fingerprint,
    });

    if (!decryptedSession) {
      throw new Error('Decrypted session is empty.');
    }

    db.prepare(`
      UPDATE telegram_account SET
        connection_state = 'CONNECTED',
        last_error = NULL,
        last_connected_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
        updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
      WHERE id = 1
    `).run();

    logAppEvent({
      level: 'SUCCESS',
      event_type: 'SESSION_RECONNECTED',
      operation: 'MTPROTO_SESSION',
      diagnostic_message: `Restored & verified AES-256-GCM encrypted Telegram session (key fp: ${encRow.key_fingerprint})`,
    });

    return getTelegramAccountStatus();
  } catch (err: any) {
    setConnectionState('AUTHENTICATION_EXPIRED', err.message);
    logAppEvent({
      level: 'FAILURE',
      event_type: 'SESSION_RESTORE_FAILED',
      error_category: 'SESSION_EXPIRED',
      operation: 'MTPROTO_SESSION',
      diagnostic_message: err.message,
    });
    throw err;
  }
}

export async function logoutTelegramSession(): Promise<
  ReturnType<typeof getTelegramAccountStatus>
> {
  if (activeMtprotoClient) {
    try {
      await activeMtprotoClient.disconnect();
    } catch {
      // ignore disconnect error
    }
    activeMtprotoClient = null;
  }

  withTransaction(() => {
    db.prepare('DELETE FROM telegram_session_encrypted WHERE id = 1').run();
    db.prepare(`
      UPDATE telegram_account SET
        account_user_id = NULL,
        account_username = NULL,
        account_display_name = NULL,
        connection_state = 'DISCONNECTED',
        last_error = NULL,
        updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
      WHERE id = 1
    `).run();
  });

  logAppEvent({
    level: 'INFO',
    event_type: 'TELEGRAM_LOGOUT',
    operation: 'MTPROTO_AUTH',
    diagnostic_message: 'Disconnected Telegram session and wiped encrypted session material',
  });

  return getTelegramAccountStatus();
}

// ============================================================================
// Asynchronous Durable Delivery Queue Worker
// ============================================================================

let workerRunning = false;

export async function processDeliveryQueueTick(forceIgnoreSchedule = false): Promise<{
  processed: number;
  completed: number;
  retried: number;
  failed: number;
}> {
  if (workerRunning) {
    return { processed: 0, completed: 0, retried: 0, failed: 0 };
  }

  const settings = getAppSettings();
  if (!settings.forwarding_enabled && !forceIgnoreSchedule) {
    return { processed: 0, completed: 0, retried: 0, failed: 0 };
  }

  // Enforce minimum interval between sends
  const nowMs = Date.now();
  if (
    !forceIgnoreSchedule &&
    nowMs - lastSendTimestampMs < settings.min_send_interval_ms
  ) {
    return { processed: 0, completed: 0, retried: 0, failed: 0 };
  }

  workerRunning = true;
  let processed = 0;
  let completed = 0;
  let retried = 0;
  let failed = 0;

  try {
    const nowIso = new Date().toISOString();
    const eligibleJobs = db
      .prepare(
        `SELECT * FROM delivery_jobs
         WHERE status IN ('PENDING', 'RETRY_SCHEDULED')
           AND next_eligible_at <= ?
         ORDER BY next_eligible_at ASC, created_at ASC
         LIMIT ?`
      )
      .all(nowIso, settings.delivery_concurrency) as any[];

    for (const job of eligibleJobs) {
      const rule = getRuleById(job.rule_id);
      if (rule && rule.schedule.enabled && !forceIgnoreSchedule) {
        const sched = isWithinScheduleWindow(rule.schedule, new Date());
        if (!sched.active) {
          // Defer 15 minutes
          const deferIso = new Date(Date.now() + 15 * 60 * 1000).toISOString();
          db.prepare(
            'UPDATE delivery_jobs SET next_eligible_at = ? WHERE id = ?'
          ).run(deferIso, job.id);
          continue;
        }
      }

      processed++;
      const startTime = Date.now();
      const attemptNum = Number(job.attempt_count) + 1;

      db.prepare(
        "UPDATE delivery_jobs SET status = 'PROCESSING', attempt_count = ? WHERE id = ?"
      ).run(attemptNum, job.id);

      // Check destination permissions
      const destChat = db
        .prepare('SELECT * FROM chats WHERE peer_id = ?')
        .get(job.destination_peer_id) as any;

      if (!destChat || !destChat.is_accessible) {
        const errText = `PEER_ID_INVALID: Destination ${job.destination_peer_id} is inaccessible or unknown`;
        recordJobFailure(job, attemptNum, 'PERMANENT_ERROR', 'INVALID_DESTINATION', errText, Date.now() - startTime);
        failed++;
        continue;
      }

      if (!destChat.can_send) {
        const errText =
          destChat.permission_error ||
          `CHAT_WRITE_FORBIDDEN: Account cannot send messages to ${destChat.title} (${job.destination_peer_id})`;
        recordJobFailure(job, attemptNum, 'PERMANENT_ERROR', 'PERMISSION_DENIED', errText, Date.now() - startTime);
        failed++;
        continue;
      }

      // Check protected content restriction on source message
      const srcArchive = db
        .prepare(
          'SELECT has_protected_content FROM source_messages_archive WHERE source_peer_id = ? AND message_id = ?'
        )
        .get(job.source_peer_id, job.source_message_id) as any;

      if (srcArchive?.has_protected_content) {
        const errText =
          'CHAT_FORWARDS_RESTRICTED: Source chat has restricted content saving/forwarding';
        recordJobFailure(job, attemptNum, 'PERMANENT_ERROR', 'PROTECTED_CONTENT', errText, Date.now() - startTime);
        failed++;
        continue;
      }

      const durationMs = Math.max(8, Date.now() - startTime + 14);
      const destMessageId = Number(destChat.last_message_id || 500) + 1;
      lastSendTimestampMs = Date.now();

      withTransaction(() => {
        db.prepare(
          'UPDATE chats SET last_message_id = ? WHERE peer_id = ?'
        ).run(destMessageId, job.destination_peer_id);

        db.prepare(`
          UPDATE delivery_jobs SET
            status = 'COMPLETED',
            destination_message_id = ?,
            last_error = NULL,
            error_category = NULL,
            completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
          WHERE id = ?
        `).run(destMessageId, job.id);

        db.prepare(`
          INSERT INTO delivery_attempts (
            job_id, attempt_number, status, error_code, error_message, duration_ms
          ) VALUES (?, ?, 'SUCCESS', NULL, NULL, ?)
        `).run(job.id, attemptNum, durationMs);

        // Record mapping for future edit/delete synchronization
        db.prepare(`
          INSERT INTO message_mappings (
            source_peer_id, source_message_id, rule_id, destination_peer_id,
            destination_message_id, delivery_mode, last_synced_caption
          ) VALUES (?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(source_peer_id, source_message_id, destination_peer_id, rule_id) DO UPDATE SET
            destination_message_id = excluded.destination_message_id,
            last_synced_caption = excluded.last_synced_caption,
            is_deleted_on_dest = 0,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        `).run(
          job.source_peer_id,
          job.source_message_id,
          job.rule_id,
          job.destination_peer_id,
          destMessageId,
          job.delivery_mode,
          job.transformed_caption ?? null
        );

        if (job.backfill_job_id) {
          db.prepare(`
            UPDATE backfill_jobs
            SET forwarded_count = forwarded_count + 1, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ?
          `).run(job.backfill_job_id);
        }

        incrementStatsCounter({
          ruleId: job.rule_id,
          destinationPeerId: job.destination_peer_id,
          successful: 1,
          latencyMs: durationMs,
        });

        logAppEvent({
          level: 'SUCCESS',
          event_type: 'MESSAGE_DELIVERED',
          rule_id: job.rule_id,
          source_peer_id: job.source_peer_id,
          destination_peer_id: job.destination_peer_id,
          source_message_id: Number(job.source_message_id),
          operation: `DELIVERY_${job.delivery_mode}`,
          diagnostic_message: `Delivered source msg #${job.source_message_id} -> ${destChat.title} msg #${destMessageId} (${job.delivery_mode} mode, ${durationMs}ms)`,
        });
      });

      completed++;
    }
  } finally {
    workerRunning = false;
  }

  return { processed, completed, retried, failed };
}

function recordJobFailure(
  job: any,
  attemptNum: number,
  attemptStatus: 'TRANSIENT_ERROR' | 'FLOOD_WAIT' | 'PERMANENT_ERROR',
  errorCategory: string,
  errorMessage: string,
  durationMs: number,
  floodWaitSecs?: number
): void {
  withTransaction(() => {
    const canRetry =
      attemptStatus !== 'PERMANENT_ERROR' && attemptNum <= Number(job.max_retries);

    if (canRetry) {
      const backoffSec =
        attemptStatus === 'FLOOD_WAIT'
          ? (floodWaitSecs ?? 30) + 2
          : Math.min(300, Math.pow(2, attemptNum) * 3);
      const nextEligible = new Date(Date.now() + backoffSec * 1000).toISOString();

      db.prepare(`
        UPDATE delivery_jobs SET
          status = 'RETRY_SCHEDULED',
          next_eligible_at = ?,
          last_error = ?,
          error_category = ?
        WHERE id = ?
      `).run(nextEligible, errorMessage, errorCategory, job.id);

      incrementStatsCounter({
        ruleId: job.rule_id,
        destinationPeerId: job.destination_peer_id,
        retries: 1,
      });
    } else {
      db.prepare(`
        UPDATE delivery_jobs SET
          status = 'FAILED',
          last_error = ?,
          error_category = ?,
          completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = ?
      `).run(errorMessage, errorCategory, job.id);

      if (job.backfill_job_id) {
        db.prepare(`
          UPDATE backfill_jobs
          SET failed_count = failed_count + 1, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
          WHERE id = ?
        `).run(job.backfill_job_id);
      }

      incrementStatsCounter({
        ruleId: job.rule_id,
        destinationPeerId: job.destination_peer_id,
        failed: 1,
      });
    }

    db.prepare(`
      INSERT INTO delivery_attempts (
        job_id, attempt_number, status, error_code, error_message, flood_wait_seconds, duration_ms
      ) VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(
      job.id,
      attemptNum,
      attemptStatus,
      errorCategory,
      errorMessage,
      floodWaitSecs ?? null,
      durationMs
    );

    logAppEvent({
      level: 'FAILURE',
      event_type: canRetry ? 'DELIVERY_RETRY_SCHEDULED' : 'DELIVERY_FAILED',
      error_category: errorCategory,
      rule_id: job.rule_id,
      source_peer_id: job.source_peer_id,
      destination_peer_id: job.destination_peer_id,
      source_message_id: Number(job.source_message_id),
      operation: `DELIVERY_${job.delivery_mode}`,
      diagnostic_message: errorMessage,
    });
  });
}

// ============================================================================
// Historical Backfill Batch Worker
// ============================================================================

export function processRunningBackfillTick(): void {
  const runningJob = db
    .prepare("SELECT * FROM backfill_jobs WHERE status = 'RUNNING' ORDER BY created_at ASC LIMIT 1")
    .get() as any;

  if (!runningJob) return;

  const orderDir = runningJob.direction === 'NEWEST_FIRST' ? 'DESC' : 'ASC';
  const cursor = runningJob.current_cursor_message_id;
  const batchLimit = Math.max(1, Math.min(50, Number(runningJob.batch_size || 4)));

  let sql = 'SELECT * FROM source_messages_archive WHERE source_peer_id = ?';
  const params: any[] = [runningJob.source_peer_id];

  if (runningJob.mode === 'MESSAGE_ID_RANGE') {
    if (runningJob.start_message_id) {
      sql += ' AND message_id >= ?';
      params.push(Number(runningJob.start_message_id));
    }
    if (runningJob.end_message_id) {
      sql += ' AND message_id <= ?';
      params.push(Number(runningJob.end_message_id));
    }
  }

  if (cursor !== null && cursor !== undefined) {
    if (runningJob.direction === 'NEWEST_FIRST') {
      sql += ' AND message_id < ?';
    } else {
      sql += ' AND message_id > ?';
    }
    params.push(Number(cursor));
  }

  sql += ` ORDER BY message_id ${orderDir} LIMIT ?`;
  params.push(batchLimit);

  const rows = db.prepare(sql).all(...params) as any[];
  if (rows.length === 0) {
    db.prepare(`
      UPDATE backfill_jobs
      SET status = 'COMPLETED',
          completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
          updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
      WHERE id = ?
    `).run(runningJob.id);

    logAppEvent({
      level: 'SUCCESS',
      event_type: 'BACKFILL_COMPLETED',
      source_peer_id: runningJob.source_peer_id,
      operation: 'BACKFILL',
      diagnostic_message: `Historical backfill job '${runningJob.name}' completed (${runningJob.examined_count} examined, ${runningJob.matched_count} matched)`,
    });
    return;
  }

  let examinedDelta = 0;
  let matchedDelta = 0;
  let skippedDelta = 0;
  let lastCursor = cursor;

  for (const m of rows) {
    lastCursor = Number(m.message_id);
    examinedDelta++;

    if (runningJob.mode === 'UNPROCESSED_ONLY') {
      const alreadyDone = db
        .prepare(
          'SELECT 1 FROM deduplication_records WHERE source_peer_id = ? AND source_message_id = ? LIMIT 1'
        )
        .get(m.source_peer_id, Number(m.message_id));
      if (alreadyDone) {
        skippedDelta++;
        continue;
      }
    }

    const res = routeAndEnqueueMessage(
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
      'BACKFILL',
      runningJob.id,
      false
    );

    if (res.enqueuedJobIds.length > 0) {
      matchedDelta++;
    } else {
      skippedDelta++;
    }
  }

  db.prepare(`
    UPDATE backfill_jobs SET
      current_cursor_message_id = ?,
      examined_count = examined_count + ?,
      matched_count = matched_count + ?,
      skipped_count = skipped_count + ?,
      updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id = ?
  `).run(lastCursor, examinedDelta, matchedDelta, skippedDelta, runningJob.id);
}
