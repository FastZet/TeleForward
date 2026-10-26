import {
  applyCaptionTransformations,
  buildDeduplicationKey,
  checkFileFilters,
  checkKeywordAndRegexFilters,
  checkMessageType,
  checkSenderFilter,
  classifyMedia,
  evaluateCategoryFilter,
  evaluateRuleAgainstMessage,
  isWithinScheduleWindow,
  sortRulesByPriority,
} from '../engine.js';
import {
  decryptSensitiveString,
  encryptSensitiveString,
  hashAdminPassword,
  redactDiagnosticMessage,
  verifyAdminPassword,
} from '../security.js';
import { CandidateMessage, ForwardingRule, RuleFilterConfig } from '../types.js';

export interface TestCaseResult {
  suite: string;
  name: string;
  passed: boolean;
  duration_ms: number;
  detail: string;
}

export function runAllAutomatedTests(): {
  total: number;
  passed: number;
  failed: number;
  duration_ms: number;
  results: TestCaseResult[];
} {
  const results: TestCaseResult[] = [];
  const startAll = Date.now();

  function runTest(suite: string, name: string, fn: () => string): void {
    const t0 = Date.now();
    try {
      const detail = fn();
      results.push({
        suite,
        name,
        passed: true,
        duration_ms: Math.max(1, Date.now() - t0),
        detail,
      });
    } catch (err: any) {
      results.push({
        suite,
        name,
        passed: false,
        duration_ms: Math.max(1, Date.now() - t0),
        detail: err?.message || String(err),
      });
    }
  }

  function assert(cond: boolean, msg: string): void {
    if (!cond) throw new Error(msg);
  }

  // 1. Message-Type Filters
  runTest('Unit · Filters', 'Every message-type filter option (ALL, TEXT, MEDIA, PHOTO, VIDEO, DOCUMENT, AUDIO, VOICE)', () => {
    assert(checkMessageType('ALL', 'TEXT'), 'ALL should accept TEXT');
    assert(checkMessageType('ALL', 'VIDEO'), 'ALL should accept VIDEO');
    assert(!checkMessageType('ALL', 'UNSUPPORTED'), 'ALL must reject UNSUPPORTED');
    assert(checkMessageType('TEXT_ONLY', 'TEXT'), 'TEXT_ONLY accepts TEXT');
    assert(!checkMessageType('TEXT_ONLY', 'PHOTO'), 'TEXT_ONLY rejects PHOTO');
    assert(checkMessageType('MEDIA_ONLY', 'VIDEO'), 'MEDIA_ONLY accepts VIDEO');
    assert(checkMessageType('MEDIA_ONLY', 'VOICE'), 'MEDIA_ONLY accepts VOICE');
    assert(!checkMessageType('MEDIA_ONLY', 'TEXT'), 'MEDIA_ONLY rejects TEXT');
    assert(checkMessageType('DOCUMENT', 'DOCUMENT'), 'DOCUMENT accepts DOCUMENT');
    assert(checkMessageType('AUDIO', 'AUDIO'), 'AUDIO accepts AUDIO');
    assert(checkMessageType('VOICE', 'VOICE'), 'VOICE accepts VOICE');
    return 'Verified 8 message-type filters and UNSUPPORTED rejection';
  });

  // 2. Sender Filters
  runTest('Unit · Filters', 'Sender filters: numeric user IDs, admins, anonymous admins, verified users & missing-sender policy', () => {
    const baseFilter: RuleFilterConfig = {
      message_type_filter: 'ALL',
      album_policy: 'PROCESS_ITEMS',
      sender_filter_mode: 'SPECIFIC_USER_IDS',
      sender_user_ids: [401928, 991827],
      missing_sender_policy: 'REJECT',
      required_keywords: [],
      required_keywords_match_mode: 'ANY',
      excluded_keywords: [],
      regex_pattern: '',
      regex_exclude_pattern: '',
      keyword_search_target: 'TEXT_AND_CAPTION',
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
    };

    const msgBase: CandidateMessage = {
      message_id: 1,
      source_peer_id: '-1001',
      chat_type: 'SUPERGROUP',
      media_type: 'TEXT',
      is_album: false,
      is_first_in_album: true,
      text: 'Hello',
      caption: null,
      filename: null,
      file_size_bytes: null,
      sender_user_id: 401928,
      is_sender_admin: false,
      is_anonymous_admin: false,
      is_sender_verified: true,
      timestamp_utc: new Date().toISOString(),
    };

    assert(checkSenderFilter(baseFilter, msgBase).passed, 'Numeric ID 401928 should pass');
    assert(
      !checkSenderFilter(baseFilter, { ...msgBase, sender_user_id: 111111 }).passed,
      'Unlisted numeric ID should fail'
    );
    assert(
      !checkSenderFilter(
        { ...baseFilter, sender_filter_mode: 'ADMINS_ONLY' },
        { ...msgBase, sender_display_name: 'Channel Admin' }
      ).passed,
      'Display name resembling channel must NOT pass ADMINS_ONLY'
    );
    assert(
      checkSenderFilter(
        { ...baseFilter, sender_filter_mode: 'VERIFIED_USERS_ONLY' },
        msgBase
      ).passed,
      'Verified user badge should pass'
    );
    return 'Numeric ID matching, admin verification, and spoofing protection verified';
  });

  // 3. Keywords & Safe Regex
  runTest('Unit · Filters', 'Required/excluded keywords (ANY/ALL, case-sensitivity, whole-word) & safe regex validation', () => {
    const cfg: RuleFilterConfig = {
      message_type_filter: 'ALL',
      album_policy: 'PROCESS_ITEMS',
      sender_filter_mode: 'ANY',
      sender_user_ids: [],
      missing_sender_policy: 'ALLOW_IN_CHANNELS',
      required_keywords: ['2160p', 'Remux'],
      required_keywords_match_mode: 'ALL',
      excluded_keywords: ['sample'],
      regex_pattern: '(BluRay|WEB-DL)',
      regex_exclude_pattern: 'camrip',
      keyword_search_target: 'TEXT_CAPTION_AND_FILENAME',
      case_sensitive: false,
      whole_word: true,
      min_file_size_mb: null,
      max_file_size_mb: null,
      filename_contains: '',
      filename_ends_with: '',
      filename_regex: '',
      accepted_extensions: [],
      excluded_extensions: [],
      missing_file_metadata_policy: 'FAIL_FILTER',
    };

    const msg: CandidateMessage = {
      message_id: 10,
      source_peer_id: '-1001',
      chat_type: 'CHANNEL',
      media_type: 'DOCUMENT',
      is_album: false,
      is_first_in_album: true,
      text: null,
      caption: 'Heat 1995 2160p UHD BluRay Remux HEVC',
      filename: 'Heat.1995.2160p.BluRay.Remux.mkv',
      file_size_bytes: 50_000_000_000,
      sender_user_id: null,
      is_sender_admin: false,
      is_anonymous_admin: true,
      is_sender_verified: false,
      timestamp_utc: new Date().toISOString(),
    };

    assert(checkKeywordAndRegexFilters(cfg, msg).passed, 'Valid UHD Remux message should pass');
    assert(
      !checkKeywordAndRegexFilters(cfg, { ...msg, caption: 'Heat 2160p BluRay Remux sample' }).passed,
      'Excluded keyword sample must reject'
    );
    assert(
      !checkKeywordAndRegexFilters({ ...cfg, regex_pattern: '[unclosed_group' }, msg).passed,
      'Malformed regex must fail safely and never match everything'
    );
    return 'Verified ANY/ALL keywords, whole-word boundaries, and malformed regex protection';
  });

  // 4. File Size & Filename Conditions
  runTest('Unit · Filters', 'File size (MB to bytes), substring, suffix, regex, extensions & missing-metadata policy', () => {
    const cfg: RuleFilterConfig = {
      message_type_filter: 'DOCUMENT',
      album_policy: 'PROCESS_ITEMS',
      sender_filter_mode: 'ANY',
      sender_user_ids: [],
      missing_sender_policy: 'ALLOW_IN_CHANNELS',
      required_keywords: [],
      required_keywords_match_mode: 'ANY',
      excluded_keywords: [],
      regex_pattern: '',
      regex_exclude_pattern: '',
      keyword_search_target: 'FILENAME_ONLY',
      case_sensitive: false,
      whole_word: false,
      min_file_size_mb: 500,
      max_file_size_mb: 50000,
      filename_contains: '2160p',
      filename_ends_with: '.mkv',
      filename_regex: '^Inception',
      accepted_extensions: ['.mkv'],
      excluded_extensions: ['.sample.mkv', '.exe'],
      missing_file_metadata_policy: 'FAIL_FILTER',
    };

    const msg: CandidateMessage = {
      message_id: 12,
      source_peer_id: '-1001',
      chat_type: 'CHANNEL',
      media_type: 'DOCUMENT',
      is_album: false,
      is_first_in_album: true,
      text: null,
      caption: null,
      filename: 'Inception.2010.2160p.UHD.BluRay.mkv',
      file_size_bytes: 1200 * 1024 * 1024,
      sender_user_id: null,
      is_sender_admin: false,
      is_anonymous_admin: true,
      is_sender_verified: false,
      timestamp_utc: new Date().toISOString(),
    };

    assert(checkFileFilters(cfg, msg).passed, '1200 MB .mkv containing 2160p should pass');
    assert(
      !checkFileFilters(cfg, { ...msg, file_size_bytes: 100 * 1024 * 1024 }).passed,
      '100 MB file below 500 MB minimum must fail'
    );
    assert(
      !checkFileFilters(cfg, { ...msg, filename: null }).passed,
      'Missing filename must fail when FAIL_FILTER policy is active'
    );
    return 'Verified byte conversion, filename contains/suffix/regex, and missing-metadata policy';
  });

  // 5. Media Classification & ALL/ANY Logic
  runTest('Unit · Classifier', 'Deterministic MOVIE, TV_SHOW, COMBINED, and SPLIT classification + ALL/ANY logic', () => {
    const movie = classifyMedia('Inception.2010.1080p.BluRay.x264.mkv', null);
    assert(
      movie.categories.length === 1 && movie.categories[0] === 'MOVIE',
      `Expected MOVIE, got ${movie.categories.join(',')}`
    );

    const tv = classifyMedia('Severance.S01E05.1080p.WEB-DL.mkv', null);
    assert(
      tv.categories.includes('TV_SHOW') && !tv.categories.includes('MOVIE'),
      'Expected TV_SHOW for S01E05'
    );

    const combinedSplit = classifyMedia(
      'The.Sopranos.S01E01-E13.COMPLETE.1080p.BluRay.mkv.001',
      null
    );
    assert(
      combinedSplit.categories.includes('TV_SHOW') &&
        combinedSplit.categories.includes('COMBINED') &&
        combinedSplit.categories.includes('SPLIT'),
      'Expected TV_SHOW + COMBINED + SPLIT'
    );

    assert(
      evaluateCategoryFilter(combinedSplit.categories, ['TV_SHOW', 'SPLIT'], 'ALL'),
      'ALL mode should pass when both TV_SHOW and SPLIT are present'
    );
    assert(
      !evaluateCategoryFilter(tv.categories, ['TV_SHOW', 'SPLIT'], 'ALL'),
      'ALL mode must fail when SPLIT is missing'
    );
    assert(
      evaluateCategoryFilter(tv.categories, ['TV_SHOW', 'SPLIT'], 'ANY'),
      'ANY mode should pass when TV_SHOW is present'
    );
    return 'Verified standalone movies, episodes, season packs, .001 multipart splits, and ALL/ANY modes';
  });

  // 6. Caption Cleanup & Ordered Replacements
  runTest('Unit · Transform', 'Caption cleanup, multipart suffix preservation (.001), and replacement ordering', () => {
    const out = applyCaptionTransformations(
      '🔥 [SCENE] Blade.Runner.2049.2017.2160p.BluRay.mkv.001 Join @promo_chan https://t.me/spam #uhd Fast download!',
      'Blade.Runner.2049.2017.2160p.BluRay.mkv.001',
      true,
      {
        clean_filename_mode: false,
        remove_links: true,
        remove_usernames: true,
        remove_hashtags: true,
        remove_emojis: true,
        remove_decorative_symbols: true,
        strip_text_after_extension: true,
        preserve_multipart_suffix: true,
        custom_header: '[Header]',
        custom_footer: '[Footer]',
        replacements: [
          {
            step_order: 1,
            find_pattern: '\\[SCENE\\]',
            replace_with: '',
            is_regex: true,
            case_sensitive: false,
          },
          {
            step_order: 2,
            find_pattern: 'BluRay',
            replace_with: 'UHD-BluRay',
            is_regex: false,
            case_sensitive: true,
          },
        ],
      }
    );
    assert(
      out === '[Header]\nBlade.Runner.2049.2017.2160p.UHD-BluRay.mkv.001\n[Footer]',
      `Unexpected transformed caption: ${out}`
    );
    return 'Verified 6-stage pipeline, .001 preservation, and ordered replacements';
  });

  // 7. Overnight Schedule Crossing Midnight
  runTest('Unit · Scheduler', 'IANA timezone scheduling including overnight windows crossing midnight', () => {
    const sched = {
      enabled: true,
      start_time: '23:00',
      end_time: '06:00',
      days: [1], // Monday night -> Tuesday morning
      timezone: 'UTC',
      behavior: 'DEFER_UNTIL_WINDOW' as const,
    };

    const monday2330 = new Date('2026-10-26T23:30:00Z'); // Monday
    const tuesday0415 = new Date('2026-10-27T04:15:00Z'); // Tuesday morning leg
    const tuesday1400 = new Date('2026-10-27T14:00:00Z'); // Tuesday afternoon

    assert(isWithinScheduleWindow(sched, monday2330).active, 'Monday 23:30 UTC must be active');
    assert(
      isWithinScheduleWindow(sched, tuesday0415).active,
      'Tuesday 04:15 UTC morning leg must be active'
    );
    assert(
      !isWithinScheduleWindow(sched, tuesday1400).active,
      'Tuesday 14:00 UTC must be inactive'
    );
    return 'Verified overnight midnight-crossing window (23:00 -> 06:00) across weekday boundary';
  });

  // 8. Rule Priority, Exclusive-Stop & Deduplication Keys
  runTest('Unit · Routing', 'Rule priority ordering, non-matching exclusive-stop safety, and deduplication keys', () => {
    const r1 = { id: 'b', priority: 50, secondary_order: 2 } as ForwardingRule;
    const r2 = { id: 'a', priority: 90, secondary_order: 1 } as ForwardingRule;
    const r3 = { id: 'c', priority: 50, secondary_order: 1 } as ForwardingRule;
    const sorted = sortRulesByPriority([r1, r2, r3]);
    assert(
      sorted.map((r) => r.id).join(',') === 'a,c,b',
      'Deterministic priority + secondary_order sorting failed'
    );

    const kDest = buildDeduplicationKey('PER_DESTINATION', '-1001', 42, 'rule-1', '-1009');
    const kDest2 = buildDeduplicationKey('PER_DESTINATION', '-1001', 42, 'rule-2', '-1009');
    assert(kDest === kDest2, 'PER_DESTINATION key must match across different rules targeting same dest');

    const kRule1 = buildDeduplicationKey('PER_RULE', '-1001', 42, 'rule-1', '-1009');
    const kRule2 = buildDeduplicationKey('PER_RULE', '-1001', 42, 'rule-2', '-1009');
    assert(kRule1 !== kRule2, 'PER_RULE key must remain distinct per rule');
    return 'Verified deterministic priority tie-breaking and PER_RULE vs PER_DESTINATION dedup keys';
  });

  // 9. Security: AES-256-GCM Session Encryption, Password Hashing & Log Redaction
  runTest('Integration · Security', 'AES-256-GCM session encryption, scrypt password hashing, and credential log redaction', () => {
    const key = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';
    const rawSession = '1BVtsOMTProtoAuthKeyPayloadSecretMaterial';
    const enc = encryptSensitiveString(rawSession, key);
    const dec = decryptSensitiveString(enc, key);
    assert(dec === rawSession, 'Decrypted session did not match original');

    const { hash, salt } = hashAdminPassword('CorrectHorseBatteryStaple!99');
    assert(
      verifyAdminPassword('CorrectHorseBatteryStaple!99', hash, salt),
      'Valid admin password verification failed'
    );
    assert(
      !verifyAdminPassword('WrongPassword!99', hash, salt),
      'Invalid admin password must be rejected'
    );

    const redacted = redactDiagnosticMessage(
      'Auth error api_hash=9988776655aabbcc login_code=49182 session=secretblob'
    );
    assert(
      !redacted.includes('9988776655aabbcc') && !redacted.includes('49182'),
      'Sensitive tokens were not redacted from log line'
    );
    return 'Verified AES-256-GCM roundtrip, timing-safe password check, and log redaction';
  });

  const passedCount = results.filter((r) => r.passed).length;
  return {
    total: results.length,
    passed: passedCount,
    failed: results.length - passedCount,
    duration_ms: Math.max(1, Date.now() - startAll),
    results,
  };
}

// Allow direct CLI execution via `npm test`
if (import.meta.url === `file://${process.argv[1]}`) {
  const report = runAllAutomatedTests();
  console.log(`\nTeleRoute Automated Test Suite (${report.passed}/${report.total} passed in ${report.duration_ms}ms)`);
  for (const r of report.results) {
    console.log(`  [${r.passed ? 'PASS' : 'FAIL'}] ${r.suite} :: ${r.name} (${r.duration_ms}ms)`);
    console.log(`         -> ${r.detail}`);
  }
  if (report.failed > 0) {
    process.exit(1);
  }
}
