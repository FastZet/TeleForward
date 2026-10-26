import crypto from 'node:crypto';

const DEFAULT_FALLBACK_KEY =
  process.env.SESSION_ENCRYPTION_KEY && process.env.SESSION_ENCRYPTION_KEY.trim().length >= 16
    ? process.env.SESSION_ENCRYPTION_KEY.trim()
    : 'teleroute-ephemeral-dev-key-override-in-production-env-32b';

export function isExplicitEncryptionKeyConfigured(): boolean {
  return Boolean(
    process.env.SESSION_ENCRYPTION_KEY && process.env.SESSION_ENCRYPTION_KEY.trim().length >= 16
  );
}

export function derive256BitKey(secretInput: string = DEFAULT_FALLBACK_KEY): Buffer {
  return crypto.createHash('sha256').update(secretInput, 'utf8').digest();
}

export function getEncryptionKeyFingerprint(secretInput: string = DEFAULT_FALLBACK_KEY): string {
  const key = derive256BitKey(secretInput);
  return crypto
    .createHash('sha256')
    .update('teleroute-key-fp:')
    .update(key)
    .digest('hex')
    .slice(0, 16);
}

export interface EncryptedBlob {
  ciphertext_b64: string;
  nonce_b64: string;
  auth_tag_b64: string;
  key_fingerprint: string;
}

export function encryptSensitiveString(
  plaintext: string,
  secretInput: string = DEFAULT_FALLBACK_KEY
): EncryptedBlob {
  const key = derive256BitKey(secretInput);
  const nonce = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, nonce);
  const encrypted = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
  const authTag = cipher.getAuthTag();
  return {
    ciphertext_b64: encrypted.toString('base64'),
    nonce_b64: nonce.toString('base64'),
    auth_tag_b64: authTag.toString('base64'),
    key_fingerprint: getEncryptionKeyFingerprint(secretInput),
  };
}

export function decryptSensitiveString(
  blob: EncryptedBlob,
  secretInput: string = DEFAULT_FALLBACK_KEY
): string {
  const expectedFp = getEncryptionKeyFingerprint(secretInput);
  if (blob.key_fingerprint && blob.key_fingerprint !== expectedFp) {
    throw new Error('Encryption key fingerprint mismatch; cannot decrypt session material.');
  }
  const key = derive256BitKey(secretInput);
  const nonce = Buffer.from(blob.nonce_b64, 'base64');
  const ciphertext = Buffer.from(blob.ciphertext_b64, 'base64');
  const authTag = Buffer.from(blob.auth_tag_b64, 'base64');
  if (nonce.length !== 12) {
    throw new Error('Invalid AES-256-GCM nonce length.');
  }
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, nonce);
  decipher.setAuthTag(authTag);
  const decrypted = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  return decrypted.toString('utf8');
}

export function hashAdminPassword(password: string): { hash: string; salt: string } {
  if (!password || password.length < 8) {
    throw new Error('Administrator password must be at least 8 characters.');
  }
  const salt = crypto.randomBytes(16).toString('hex');
  const derived = crypto.scryptSync(password, salt, 64, { N: 16384, r: 8, p: 1 });
  return {
    hash: derived.toString('hex'),
    salt,
  };
}

export function verifyAdminPassword(password: string, storedHash: string, storedSalt: string): boolean {
  try {
    const derived = crypto.scryptSync(password, storedSalt, 64, { N: 16384, r: 8, p: 1 });
    const storedBuf = Buffer.from(storedHash, 'hex');
    if (derived.length !== storedBuf.length) return false;
    return crypto.timingSafeEqual(derived, storedBuf);
  } catch {
    return false;
  }
}

export function generateOpaqueToken(bytes = 32): string {
  return crypto.randomBytes(bytes).toString('hex');
}

export function hashToken(rawToken: string): string {
  return crypto.createHash('sha256').update(rawToken, 'utf8').digest('hex');
}

const SENSITIVE_LOG_RE =
  /\b(api_hash|password|login_code|phone_code|session|secret|token|auth_key)\s*[:=]\s*([^\s,;]+)/gi;

export function redactDiagnosticMessage(message: string): string {
  if (!message) return '';
  return message.replace(SENSITIVE_LOG_RE, '$1=[REDACTED]');
}

export function maskPhoneNumber(phone: string): string {
  const cleaned = phone.replace(/[^\d+]/g, '');
  if (cleaned.length <= 5) return '***';
  return `${cleaned.slice(0, 4)}••••${cleaned.slice(-2)}`;
}
