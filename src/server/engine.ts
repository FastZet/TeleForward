import {
  CandidateMessage,
  CaptionTransformConfig,
  CategoryMatchMode,
  DeduplicationScope,
  ForwardingRule,
  KeywordSearchTarget,
  MediaCategory,
  MessageMediaType,
  MessageTypeFilter,
  RuleEvaluationReport,
  RuleFilterConfig,
  RuleScheduleConfig,
} from './types.js';

export const TELEGRAM_MAX_CAPTION_CHARS = 1024;
export const TELEGRAM_MAX_TEXT_CHARS = 4096;
export const MAX_REGEX_PATTERN_LEN = 512;
export const MAX_SEARCHABLE_TEXT_LEN = 16384;

// ============================================================================
// 1. Automatic Deterministic Media Classifier (MOVIE, TV_SHOW, COMBINED, SPLIT)
// ============================================================================

const RE_TV_SINGLE =
  /(?:^|[\s._\-[\]()])(?:S\d{1,2}\s*E\d{1,3}|\d{1,2}x\d{2,3}|Season\s*\d{1,2}\s*Episode\s*\d{1,3}|E\d{2,3}|EP\s*\d{1,4})(?:$|[\s._\-[\])])/i;

const RE_COMBINED_PACK =
  /(?:^|[\s._\-[\]()])(?:S\d{1,2}\s*E\d{1,3}\s*[-~]\s*(?:S\d{1,2}\s*)?E?\d{1,3}|S\d{1,2}\s*(?:COMPLETE|FULL|PACK)|COMPLETE\s+SEASON|SEASON\s+\d{1,2}\s*(?:-\s*\d{1,2}\s*)?(?:COMPLETE|PACK|FULL)|S\d{1,2}\s*-\s*S\d{1,2}|(?:^|[\s._\-])S\d{1,2}(?:$|[\s._\-])(?!E\d))(?:$|[\s._\-[\])])/i;

const RE_MULTI_EP_MARKERS = /S\d{1,2}E\d{1,3}(?:[._\-]?E\d{1,3})+/i;

const RE_SPLIT_EXT =
  /(?:\.(?:mkv|mp4|avi|ts|7z|zip|rar|tar)\.\d{3}$|\.part0*\d+\.rar$|\.r\d{2,3}$|(?:^|[\s._\-])(?:part|pt|cd|disc|disk|dvd)\s*0*\d{1,2}(?:$|[\s._\-]))/i;

const RE_MOVIE_YEAR_QUALITY =
  /(?:^|[\s._\-([])(19[2-9]\d|20[0-3]\d)(?:$|[\s._\-)\]]).*(?:2160p|1080p|720p|480p|UHD|4K|BluRay|BDRip|BRRip|WEB-DL|WEBRip|HDRip|DVDRip|Remux|x264|x265|HEVC|H\.?264|H\.?265|AV1)/i;

const RE_VIDEO_EXT = /\.(?:mkv|mp4|avi|mov|m4v|ts|iso)(?:\.\d{3})?$/i;
const RE_RELEASE_YEAR = /(?:^|[\s._\-([])(19[2-9]\d|20[0-3]\d)(?:$|[\s._\-)\]])/;

export function classifyMedia(
  filename?: string | null,
  caption?: string | null
): { categories: MediaCategory[]; reasons: string[] } {
  const fname = (filename ?? '').trim();
  const cap = (caption ?? '').trim();
  const combined = fname && cap ? `${fname} ${cap}` : fname || cap;

  if (!combined) {
    return { categories: [], reasons: [] };
  }

  const found = new Set<MediaCategory>();
  const reasons: string[] = [];

  // 1. Split-file detection (.mkv.001, .7z.002, .part1.rar, part1, cd1)
  if (RE_SPLIT_EXT.test(fname) || RE_SPLIT_EXT.test(combined)) {
    found.add('SPLIT');
    reasons.push('Matched multipart/split archive or volume marker (.001 / partN / cdN)');
  }

  // 2. Combined-pack detection (Complete season, S01E01-E10, multi-episode markers)
  if (RE_COMBINED_PACK.test(combined) || RE_MULTI_EP_MARKERS.test(combined)) {
    found.add('COMBINED');
    found.add('TV_SHOW');
    reasons.push('Matched combined season pack or multi-episode range marker');
  }

  // 3. Television episode detection (S01E05, 1x05, Season 1 Episode 5)
  if (RE_TV_SINGLE.test(combined)) {
    found.add('TV_SHOW');
    reasons.push('Matched episodic television marker (SxxExx / NxNN)');
  }

  // 4. Movie detection (Release year + quality/source or video container, without TV markers)
  if (!found.has('TV_SHOW') && !found.has('COMBINED')) {
    if (
      RE_MOVIE_YEAR_QUALITY.test(combined) ||
      (RE_VIDEO_EXT.test(fname) && RE_RELEASE_YEAR.test(combined))
    ) {
      found.add('MOVIE');
      reasons.push('Matched standalone movie release year and encoding/container signature');
    }
  }

  const order: MediaCategory[] = ['MOVIE', 'TV_SHOW', 'COMBINED', 'SPLIT'];
  return {
    categories: order.filter((c) => found.has(c)),
    reasons,
  };
}

export function evaluateCategoryFilter(
  detected: MediaCategory[],
  selected: MediaCategory[],
  mode: CategoryMatchMode
): boolean {
  if (!selected || selected.length === 0) return true;
  if (mode === 'ALL') {
    return selected.every((req) => detected.includes(req));
  }
  return selected.some((req) => detected.includes(req));
}

// ============================================================================
// 2. Message-Type, Sender, Keyword, Safe Regex & File Filters
// ============================================================================

export function checkMessageType(
  filter: MessageTypeFilter,
  actual: MessageMediaType
): boolean {
  if (actual === 'UNSUPPORTED') return false;
  switch (filter) {
    case 'ALL':
      return true;
    case 'TEXT_ONLY':
      return actual === 'TEXT';
    case 'MEDIA_ONLY':
      return ['PHOTO', 'VIDEO', 'DOCUMENT', 'AUDIO', 'VOICE'].includes(actual);
    case 'PHOTO':
      return actual === 'PHOTO';
    case 'VIDEO':
      return actual === 'VIDEO';
    case 'DOCUMENT':
      return actual === 'DOCUMENT';
    case 'AUDIO':
      return actual === 'AUDIO';
    case 'VOICE':
      return actual === 'VOICE';
    default:
      return false;
  }
}

export function checkSenderFilter(
  cfg: RuleFilterConfig,
  msg: CandidateMessage
): { passed: boolean; reason: string } {
  switch (cfg.sender_filter_mode) {
    case 'ANY':
      return { passed: true, reason: 'Sender filter: ANY allowed' };
    case 'SPECIFIC_USER_IDS': {
      if (msg.sender_user_id !== null && msg.sender_user_id !== undefined) {
        const ok = cfg.sender_user_ids.includes(Number(msg.sender_user_id));
        return {
          passed: ok,
          reason: ok
            ? `Sender numeric ID ${msg.sender_user_id} matched allowlist`
            : `Sender numeric ID ${msg.sender_user_id} not in [${cfg.sender_user_ids.join(', ')}]`,
        };
      }
      if (msg.chat_type === 'CHANNEL' && cfg.missing_sender_policy === 'ALLOW_IN_CHANNELS') {
        return {
          passed: true,
          reason: 'Channel post without individual user ID allowed by ALLOW_IN_CHANNELS policy',
        };
      }
      return {
        passed: false,
        reason: 'Sender numeric user ID absent and policy is REJECT',
      };
    }
    case 'ADMINS_ONLY':
      // Never classify an unidentified sender as an administrator merely because display name resembles a channel
      return {
        passed: Boolean(msg.is_sender_admin),
        reason: msg.is_sender_admin
          ? 'Verified administrator status passed'
          : 'Sender is not a verified chat administrator',
      };
    case 'ANONYMOUS_ADMINS_ONLY':
      return {
        passed: Boolean(msg.is_anonymous_admin),
        reason: msg.is_anonymous_admin
          ? 'Anonymous administrator post matched'
          : 'Sender is not an anonymous administrator',
      };
    case 'VERIFIED_USERS_ONLY':
      return {
        passed: Boolean(msg.is_sender_verified),
        reason: msg.is_sender_verified
          ? 'Telegram verified sender badge matched'
          : 'Sender is not marked verified by Telegram',
      };
  }
}

export function extractSearchCorpus(
  target: KeywordSearchTarget,
  msg: CandidateMessage
): string {
  let raw = '';
  switch (target) {
    case 'TEXT_ONLY':
      raw = msg.text ?? '';
      break;
    case 'CAPTION_ONLY':
      raw = msg.caption ?? '';
      break;
    case 'FILENAME_ONLY':
      raw = msg.filename ?? '';
      break;
    case 'TEXT_AND_CAPTION':
      raw = [msg.text ?? '', msg.caption ?? ''].filter(Boolean).join('\n');
      break;
    case 'TEXT_CAPTION_AND_FILENAME':
      raw = [msg.text ?? '', msg.caption ?? '', msg.filename ?? ''].filter(Boolean).join('\n');
      break;
  }
  return raw.length > MAX_SEARCHABLE_TEXT_LEN ? raw.slice(0, MAX_SEARCHABLE_TEXT_LEN) : raw;
}

function escapeRegExp(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function validateSafeRegex(pattern: string, caseSensitive: boolean): RegExp {
  if (pattern.length > MAX_REGEX_PATTERN_LEN) {
    throw new Error(`Regular expression exceeds ${MAX_REGEX_PATTERN_LEN} characters.`);
  }
  // Reject nested catastrophic backtracking quantifiers like (a+)+ or (.*)*
  if (/(\([^)]*[+*][^)]*\))[+*]/.test(pattern)) {
    throw new Error(
      'Regular expression contains nested repeating quantifiers that risk catastrophic backtracking.'
    );
  }
  let cleaned = pattern;
  let flags = caseSensitive ? '' : 'i';
  if (cleaned.startsWith('(?i)')) {
    cleaned = cleaned.slice(4);
    flags = 'i';
  }
  return new RegExp(cleaned, flags);
}

function termMatches(
  corpus: string,
  term: string,
  caseSensitive: boolean,
  wholeWord: boolean
): boolean {
  const trimmed = term.trim();
  if (!trimmed) return true;
  if (wholeWord) {
    const re = new RegExp(`\\b${escapeRegExp(trimmed)}\\b`, caseSensitive ? '' : 'i');
    return re.test(corpus);
  }
  if (caseSensitive) {
    return corpus.includes(trimmed);
  }
  return corpus.toLowerCase().includes(trimmed.toLowerCase());
}

export function checkKeywordAndRegexFilters(
  cfg: RuleFilterConfig,
  msg: CandidateMessage
): { passed: boolean; passedReasons: string[]; failedReasons: string[] } {
  const corpus = extractSearchCorpus(cfg.keyword_search_target, msg);
  const passedReasons: string[] = [];
  const failedReasons: string[] = [];

  // 1. Excluded keywords
  const excluded = (cfg.excluded_keywords ?? []).map((k) => k.trim()).filter(Boolean);
  for (const kw of excluded) {
    if (termMatches(corpus, kw, cfg.case_sensitive, cfg.whole_word)) {
      failedReasons.push(`Excluded keyword matched in ${cfg.keyword_search_target}: '${kw}'`);
      return { passed: false, passedReasons, failedReasons };
    }
  }
  if (excluded.length > 0) {
    passedReasons.push(`Excluded keywords clear (${excluded.length} checked)`);
  }

  // 2. Required keywords
  const required = (cfg.required_keywords ?? []).map((k) => k.trim()).filter(Boolean);
  if (required.length > 0) {
    const matched =
      cfg.required_keywords_match_mode === 'ALL'
        ? required.every((kw) => termMatches(corpus, kw, cfg.case_sensitive, cfg.whole_word))
        : required.some((kw) => termMatches(corpus, kw, cfg.case_sensitive, cfg.whole_word));
    if (!matched) {
      failedReasons.push(
        `Required keywords (${cfg.required_keywords_match_mode}) failed on ${cfg.keyword_search_target}: [${required.join(', ')}]`
      );
      return { passed: false, passedReasons, failedReasons };
    }
    passedReasons.push(
      `Required keywords (${cfg.required_keywords_match_mode}) matched on ${cfg.keyword_search_target}`
    );
  }

  // 3. Positive Regex
  if (cfg.regex_pattern && cfg.regex_pattern.trim()) {
    try {
      const re = validateSafeRegex(cfg.regex_pattern.trim(), cfg.case_sensitive);
      if (!re.test(corpus)) {
        failedReasons.push(`Regex pattern /${cfg.regex_pattern.trim()}/ did not match`);
        return { passed: false, passedReasons, failedReasons };
      }
      passedReasons.push(`Regex pattern /${cfg.regex_pattern.trim()}/ matched`);
    } catch (err: any) {
      failedReasons.push(`Malformed regex pattern: ${err.message}`);
      return { passed: false, passedReasons, failedReasons };
    }
  }

  // 4. Exclusion Regex
  if (cfg.regex_exclude_pattern && cfg.regex_exclude_pattern.trim()) {
    try {
      const re = validateSafeRegex(cfg.regex_exclude_pattern.trim(), cfg.case_sensitive);
      if (re.test(corpus)) {
        failedReasons.push(`Exclusion regex /${cfg.regex_exclude_pattern.trim()}/ matched`);
        return { passed: false, passedReasons, failedReasons };
      }
      passedReasons.push(`Exclusion regex clear`);
    } catch (err: any) {
      failedReasons.push(`Malformed exclusion regex: ${err.message}`);
      return { passed: false, passedReasons, failedReasons };
    }
  }

  return { passed: true, passedReasons, failedReasons };
}

export function checkFileFilters(
  cfg: RuleFilterConfig,
  msg: CandidateMessage
): { passed: boolean; passedReasons: string[]; failedReasons: string[] } {
  const passedReasons: string[] = [];
  const failedReasons: string[] = [];

  const minBytes =
    cfg.min_file_size_mb !== null && cfg.min_file_size_mb !== undefined && cfg.min_file_size_mb > 0
      ? Math.round(cfg.min_file_size_mb * 1024 * 1024)
      : null;
  const maxBytes =
    cfg.max_file_size_mb !== null && cfg.max_file_size_mb !== undefined && cfg.max_file_size_mb > 0
      ? Math.round(cfg.max_file_size_mb * 1024 * 1024)
      : null;

  const hasSizeRule = minBytes !== null || maxBytes !== null;
  const acceptedExts = (cfg.accepted_extensions ?? []).map((e) => e.trim()).filter(Boolean);
  const excludedExts = (cfg.excluded_extensions ?? []).map((e) => e.trim()).filter(Boolean);
  const hasNameRule =
    Boolean(cfg.filename_contains?.trim()) ||
    Boolean(cfg.filename_ends_with?.trim()) ||
    Boolean(cfg.filename_regex?.trim()) ||
    acceptedExts.length > 0 ||
    excludedExts.length > 0;

  if (!hasSizeRule && !hasNameRule) {
    return { passed: true, passedReasons, failedReasons };
  }

  if (hasSizeRule) {
    if (msg.file_size_bytes === null || msg.file_size_bytes === undefined) {
      if (cfg.missing_file_metadata_policy === 'FAIL_FILTER') {
        failedReasons.push('Message is missing file_size_bytes (policy: FAIL_FILTER)');
        return { passed: false, passedReasons, failedReasons };
      }
    } else {
      const sz = msg.file_size_bytes;
      if (minBytes !== null && sz < minBytes) {
        failedReasons.push(
          `File size ${(sz / (1024 * 1024)).toFixed(1)} MB is below minimum ${cfg.min_file_size_mb} MB`
        );
        return { passed: false, passedReasons, failedReasons };
      }
      if (minBytes !== null) {
        passedReasons.push(`File size >= ${cfg.min_file_size_mb} MB passed`);
      }
      if (maxBytes !== null && sz > maxBytes) {
        failedReasons.push(
          `File size ${(sz / (1024 * 1024)).toFixed(1)} MB exceeds maximum ${cfg.max_file_size_mb} MB`
        );
        return { passed: false, passedReasons, failedReasons };
      }
      if (maxBytes !== null) {
        passedReasons.push(`File size <= ${cfg.max_file_size_mb} MB passed`);
      }
    }
  }

  if (hasNameRule) {
    const fname = msg.filename?.trim() ?? '';
    if (!fname) {
      if (cfg.missing_file_metadata_policy === 'FAIL_FILTER') {
        failedReasons.push('Message is missing filename metadata (policy: FAIL_FILTER)');
        return { passed: false, passedReasons, failedReasons };
      }
    } else {
      const fnameCmp = cfg.case_sensitive ? fname : fname.toLowerCase();

      if (cfg.filename_contains?.trim()) {
        const needle = cfg.case_sensitive
          ? cfg.filename_contains.trim()
          : cfg.filename_contains.trim().toLowerCase();
        if (!fnameCmp.includes(needle)) {
          failedReasons.push(`Filename does not contain '${cfg.filename_contains.trim()}'`);
          return { passed: false, passedReasons, failedReasons };
        }
        passedReasons.push(`Filename contains '${cfg.filename_contains.trim()}'`);
      }

      if (cfg.filename_ends_with?.trim()) {
        const suffix = cfg.case_sensitive
          ? cfg.filename_ends_with.trim()
          : cfg.filename_ends_with.trim().toLowerCase();
        if (!fnameCmp.endsWith(suffix)) {
          failedReasons.push(`Filename does not end with '${cfg.filename_ends_with.trim()}'`);
          return { passed: false, passedReasons, failedReasons };
        }
        passedReasons.push(`Filename ends with '${cfg.filename_ends_with.trim()}'`);
      }

      if (cfg.filename_regex?.trim()) {
        try {
          const re = validateSafeRegex(cfg.filename_regex.trim(), cfg.case_sensitive);
          if (!re.test(fname)) {
            failedReasons.push(`Filename regex /${cfg.filename_regex.trim()}/ did not match`);
            return { passed: false, passedReasons, failedReasons };
          }
          passedReasons.push(`Filename regex matched`);
        } catch (err: any) {
          failedReasons.push(`Invalid filename regex: ${err.message}`);
          return { passed: false, passedReasons, failedReasons };
        }
      }

      const lowerFname = fname.toLowerCase();
      if (excludedExts.length > 0) {
        for (const ext of excludedExts) {
          const norm = ext.startsWith('.') ? ext.toLowerCase() : `.${ext.toLowerCase()}`;
          if (lowerFname.endsWith(norm)) {
            failedReasons.push(`Excluded file extension matched: ${norm}`);
            return { passed: false, passedReasons, failedReasons };
          }
        }
        passedReasons.push('Excluded file extensions clear');
      }

      if (acceptedExts.length > 0) {
        const matchedExt = acceptedExts.some((ext) => {
          const norm = ext.startsWith('.') ? ext.toLowerCase() : `.${ext.toLowerCase()}`;
          return lowerFname.endsWith(norm);
        });
        if (!matchedExt) {
          failedReasons.push(
            `Filename does not match accepted extensions [${acceptedExts.join(', ')}]`
          );
          return { passed: false, passedReasons, failedReasons };
        }
        passedReasons.push(`Accepted file extension matched`);
      }
    }
  }

  return { passed: true, passedReasons, failedReasons };
}

// ============================================================================
// 3. Deterministic Caption Transformation Pipeline (Copy Mode)
// ============================================================================

const RE_LINKS = /(?:https?:\/\/|t\.me\/|telegram\.me\/|www\.)\S+/gi;
const RE_USERNAMES = /(?:^|\s)@[A-Za-z0-9_]{3,32}\b/g;
const RE_HASHTAGS = /(?:^|\s)#[A-Za-z0-9_]+\b/g;
const RE_DECORATIVE = /[★☆✦✧❖⚡🔥💥🎬📺💎👑🔔📢✅❌⭕➖➗➕💲🔗]+/g;
const RE_EMOJIS = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu;

const RE_STRIP_AFTER_EXT_MULTIPART =
  /^(.*?\.(?:mkv|mp4|avi|mov|ts|iso|7z|rar|zip)(?:\.\d{3}|\.part\d+\.rar)?)\b[\s\S]*$/i;
const RE_STRIP_AFTER_EXT_PLAIN =
  /^(.*?\.(?:mkv|mp4|avi|mov|ts|iso|7z|rar|zip))\b[\s\S]*$/i;

export function applyCaptionTransformations(
  originalCaption: string | null | undefined,
  filename: string | null | undefined,
  isMedia: boolean,
  cfg: CaptionTransformConfig
): string {
  // Step 1: Extract base caption or clean filename
  let text = '';
  if (cfg.clean_filename_mode && filename && filename.trim()) {
    text = filename.trim();
  } else {
    text = originalCaption ?? '';
  }

  // Step 2: Remove trailing promotional text after filename extension (preserving .001 if configured)
  if (cfg.strip_text_after_extension) {
    const re = cfg.preserve_multipart_suffix
      ? RE_STRIP_AFTER_EXT_MULTIPART
      : RE_STRIP_AFTER_EXT_PLAIN;
    const m = text.match(re);
    if (m && m[1]) {
      text = m[1];
    }
  }

  // Step 3: Optional cleanup operations
  if (cfg.remove_links) {
    text = text.replace(RE_LINKS, '');
  }
  if (cfg.remove_usernames) {
    text = text.replace(RE_USERNAMES, ' ');
  }
  if (cfg.remove_hashtags) {
    text = text.replace(RE_HASHTAGS, ' ');
  }
  if (cfg.remove_decorative_symbols) {
    text = text.replace(RE_DECORATIVE, '');
  }
  if (cfg.remove_emojis) {
    text = text.replace(RE_EMOJIS, '');
  }

  // Step 4: Custom find-and-replace steps in configured order
  const orderedSteps = [...(cfg.replacements ?? [])].sort(
    (a, b) => a.step_order - b.step_order
  );
  for (const step of orderedSteps) {
    if (!step.find_pattern) continue;
    if (step.is_regex) {
      const re = new RegExp(
        step.find_pattern,
        step.case_sensitive ? 'g' : 'gi'
      );
      text = text.replace(re, step.replace_with ?? '');
    } else {
      const re = new RegExp(
        escapeRegExp(step.find_pattern),
        step.case_sensitive ? 'g' : 'gi'
      );
      text = text.replace(re, step.replace_with ?? '');
    }
  }

  // Normalize horizontal spaces per line
  text = text
    .split('\n')
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .filter((line, idx, arr) => line.length > 0 || (idx > 0 && idx < arr.length - 1))
    .join('\n')
    .trim();

  // Step 5: Prepend custom header and append custom footer
  const parts: string[] = [];
  if (cfg.custom_header?.trim()) {
    parts.push(cfg.custom_header.trim());
  }
  if (text) {
    parts.push(text);
  }
  if (cfg.custom_footer?.trim()) {
    parts.push(cfg.custom_footer.trim());
  }

  let finalOut = parts.join('\n');

  // Step 6: Validate against Telegram length limits (1024 for media captions, 4096 for text)
  const maxLen = isMedia ? TELEGRAM_MAX_CAPTION_CHARS : TELEGRAM_MAX_TEXT_CHARS;
  if (finalOut.length > maxLen) {
    finalOut = finalOut.slice(0, maxLen);
  }

  return finalOut;
}

// ============================================================================
// 4. Timezone & Midnight-Crossing Schedule Window Evaluation
// ============================================================================

const WEEKDAY_MAP: Record<string, number> = {
  Sun: 0,
  Mon: 1,
  Tue: 2,
  Wed: 3,
  Thu: 4,
  Fri: 5,
  Sat: 6,
};

export function isWithinScheduleWindow(
  cfg: RuleScheduleConfig,
  evalDate: Date = new Date()
): { active: boolean; reason: string } {
  if (!cfg.enabled) {
    return { active: true, reason: 'Schedule disabled (24/7 active)' };
  }

  let formatter: Intl.DateTimeFormat;
  try {
    formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: cfg.timezone || 'UTC',
      weekday: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch {
    throw new Error(`Invalid IANA timezone '${cfg.timezone}'`);
  }

  const parts = formatter.formatToParts(evalDate);
  const weekdayStr = parts.find((p) => p.type === 'weekday')?.value ?? 'Sun';
  const hourStr = parts.find((p) => p.type === 'hour')?.value ?? '00';
  const minStr = parts.find((p) => p.type === 'minute')?.value ?? '00';

  const currentDay = WEEKDAY_MAP[weekdayStr] ?? 0;
  const currentMinutes = (parseInt(hourStr, 10) % 24) * 60 + parseInt(minStr, 10);

  const [sh, sm] = (cfg.start_time || '00:00').split(':').map((n) => parseInt(n, 10));
  const [eh, em] = (cfg.end_time || '23:59').split(':').map((n) => parseInt(n, 10));
  if (Number.isNaN(sh) || Number.isNaN(sm) || Number.isNaN(eh) || Number.isNaN(em)) {
    throw new Error('Invalid schedule time format (expected HH:MM)');
  }
  const startMinutes = sh * 60 + sm;
  const endMinutes = eh * 60 + em;
  const days = cfg.days ?? [0, 1, 2, 3, 4, 5, 6];

  const localClock = `${String(parseInt(hourStr, 10) % 24).padStart(2, '0')}:${minStr}`;

  if (startMinutes <= endMinutes) {
    // Standard same-day window
    const ok =
      days.includes(currentDay) &&
      currentMinutes >= startMinutes &&
      currentMinutes <= endMinutes;
    return {
      active: ok,
      reason: ok
        ? `Within schedule window (${cfg.start_time}–${cfg.end_time} ${cfg.timezone}, local ${localClock})`
        : `Outside schedule window (${cfg.start_time}–${cfg.end_time} ${cfg.timezone}, local ${localClock})`,
    };
  } else {
    // Overnight window crossing midnight (e.g., 23:00 -> 06:00)
    if (currentMinutes >= startMinutes) {
      const ok = days.includes(currentDay);
      return {
        active: ok,
        reason: ok
          ? `Within overnight window evening leg (${cfg.start_time}–${cfg.end_time} ${cfg.timezone})`
          : `Day not active for overnight window`,
      };
    } else if (currentMinutes <= endMinutes) {
      const prevDay = currentDay === 0 ? 6 : currentDay - 1;
      const ok = days.includes(prevDay);
      return {
        active: ok,
        reason: ok
          ? `Within overnight window morning leg (${cfg.start_time}–${cfg.end_time} ${cfg.timezone})`
          : `Previous day not active for overnight window`,
      };
    }
    return {
      active: false,
      reason: `Outside overnight schedule window (${cfg.start_time}–${cfg.end_time} ${cfg.timezone}, local ${localClock})`,
    };
  }
}

// ============================================================================
// 5. Rule Evaluation, Priority Sorting & Deduplication Keys
// ============================================================================

export function sortRulesByPriority(rules: ForwardingRule[]): ForwardingRule[] {
  return [...rules].sort((a, b) => {
    if (b.priority !== a.priority) return b.priority - a.priority;
    if (a.secondary_order !== b.secondary_order) return a.secondary_order - b.secondary_order;
    return a.id.localeCompare(b.id);
  });
}

export function evaluateRuleAgainstMessage(
  rule: ForwardingRule,
  msg: CandidateMessage,
  evalDate: Date = new Date()
): RuleEvaluationReport {
  const passed: string[] = [];
  const failed: string[] = [];

  const baseCaptionOrText =
    msg.media_type === 'TEXT' ? msg.text : msg.caption ?? msg.text;
  const classification = classifyMedia(msg.filename, baseCaptionOrText);

  if (!rule.enabled) {
    failed.push('Rule is disabled');
  } else {
    passed.push('Rule is enabled');
  }

  if (rule.source_peer_id !== msg.source_peer_id) {
    failed.push(
      `Source chat mismatch (rule expects ${rule.source_peer_id}, message from ${msg.source_peer_id})`
    );
  } else {
    passed.push(`Source chat matched (${rule.source_peer_id})`);
  }

  // Album policy check
  if (msg.is_album) {
    if (rule.filters.album_policy === 'SKIP_ALBUMS') {
      failed.push('Message is part of a media album (policy: SKIP_ALBUMS)');
    } else if (rule.filters.album_policy === 'FIRST_ITEM_ONLY' && !msg.is_first_in_album) {
      failed.push('Message is a secondary album item (policy: FIRST_ITEM_ONLY)');
    } else {
      passed.push(`Album policy (${rule.filters.album_policy}) accepted item`);
    }
  }

  // 1. Message type filter
  if (!checkMessageType(rule.filters.message_type_filter, msg.media_type)) {
    failed.push(
      `Message type '${msg.media_type}' rejected by filter '${rule.filters.message_type_filter}'`
    );
  } else {
    passed.push(`Message type '${msg.media_type}' accepted by '${rule.filters.message_type_filter}'`);
  }

  // 2. Sender filter
  const senderCheck = checkSenderFilter(rule.filters, msg);
  if (senderCheck.passed) {
    passed.push(senderCheck.reason);
  } else {
    failed.push(senderCheck.reason);
  }

  // 3. Keywords & Regex
  const kwCheck = checkKeywordAndRegexFilters(rule.filters, msg);
  passed.push(...kwCheck.passedReasons);
  failed.push(...kwCheck.failedReasons);

  // 4. File filters
  const fileCheck = checkFileFilters(rule.filters, msg);
  passed.push(...fileCheck.passedReasons);
  failed.push(...fileCheck.failedReasons);

  // 5. Media categories
  if (rule.categories.enabled && rule.categories.selected.length > 0) {
    const catOk = evaluateCategoryFilter(
      classification.categories,
      rule.categories.selected,
      rule.categories.match_mode
    );
    if (catOk) {
      passed.push(
        `Category filter (${rule.categories.match_mode}) matched [${classification.categories.join(', ')}]`
      );
    } else {
      failed.push(
        `Category filter (${rule.categories.match_mode}) required [${rule.categories.selected.join(', ')}], detected [${classification.categories.join(', ') || 'NONE'}]`
      );
    }
  }

  // 6. Schedule
  let deferredBySchedule = false;
  if (rule.schedule.enabled) {
    try {
      const sched = isWithinScheduleWindow(rule.schedule, evalDate);
      if (sched.active) {
        passed.push(sched.reason);
      } else if (rule.schedule.behavior === 'ONLY_ARRIVING_DURING_WINDOW') {
        failed.push(`${sched.reason} (mode: ONLY_ARRIVING_DURING_WINDOW)`);
      } else {
        deferredBySchedule = true;
        passed.push(`${sched.reason} -> Queued delivery deferred until window opens`);
      }
    } catch (err: any) {
      failed.push(err.message);
    }
  }

  const matched = failed.length === 0;
  const isMedia = msg.media_type !== 'TEXT';
  let transformedCaption: string | null = null;
  if (matched) {
    if (rule.delivery_mode === 'COPY') {
      transformedCaption = applyCaptionTransformations(
        baseCaptionOrText,
        msg.filename,
        isMedia,
        rule.caption_transform
      );
    } else {
      transformedCaption = baseCaptionOrText ?? null;
    }
  }

  return {
    rule_id: rule.id,
    rule_name: rule.name,
    priority: rule.priority,
    matched,
    passed_conditions: passed,
    failed_conditions: failed,
    assigned_categories: classification.categories,
    classification_reasons: classification.reasons,
    target_destinations: matched ? [...rule.destination_peer_ids] : [],
    exclusive_stop_triggered: matched && rule.exclusive_stop,
    deferred_by_schedule: deferredBySchedule,
    transformed_caption: transformedCaption,
  };
}

export function buildDeduplicationKey(
  scope: DeduplicationScope,
  sourcePeerId: string,
  sourceMessageId: number,
  ruleId: string,
  destinationPeerId: string
): string {
  if (scope === 'PER_RULE') {
    return `RULE:${sourcePeerId}:${sourceMessageId}:${ruleId}:${destinationPeerId}`;
  }
  return `DEST:${sourcePeerId}:${sourceMessageId}:${destinationPeerId}`;
}
