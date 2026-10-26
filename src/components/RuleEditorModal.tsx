import React, { useState, useMemo } from 'react';
import {
  ForwardingRule,
  MediaCategory,
  MessageTypeFilter,
  SenderFilterMode,
  KeywordSearchTarget,
  RuleEvaluationReport,
} from '../server/types';
import { apiRequest } from '../api';
import { X, CheckCircle2, AlertTriangle, Play, Plus, Trash2 } from 'lucide-react';

interface RuleEditorModalProps {
  initialRule: ForwardingRule | null;
  chats: any[];
  onClose: () => void;
  onSaved: (saved: ForwardingRule) => void;
  notify: (msg: string, type?: 'success' | 'error') => void;
}

const DEFAULT_RULE: ForwardingRule = {
  id: '',
  name: '',
  description: '',
  enabled: true,
  source_peer_id: '-1001000000001',
  destination_peer_ids: ['-1002000000101'],
  priority: 75,
  secondary_order: 1,
  exclusive_stop: false,
  delivery_mode: 'COPY',
  delay_seconds: 0,
  max_retries: 3,
  sync_edits: true,
  sync_deletes: true,
  deduplication_override: 'GLOBAL',
  schedule: {
    enabled: false,
    start_time: '23:00',
    end_time: '06:00',
    days: [0, 1, 2, 3, 4, 5, 6],
    timezone: 'UTC',
    behavior: 'DEFER_UNTIL_WINDOW',
  },
  filters: {
    message_type_filter: 'ALL',
    album_policy: 'PROCESS_ITEMS',
    sender_filter_mode: 'ANY',
    sender_user_ids: [],
    missing_sender_policy: 'ALLOW_IN_CHANNELS',
    required_keywords: [],
    required_keywords_match_mode: 'ANY',
    excluded_keywords: [],
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
    enabled: false,
    selected: [],
    match_mode: 'ANY',
  },
  caption_transform: {
    clean_filename_mode: false,
    remove_links: true,
    remove_usernames: true,
    remove_hashtags: false,
    remove_emojis: false,
    remove_decorative_symbols: false,
    strip_text_after_extension: true,
    preserve_multipart_suffix: true,
    custom_header: '',
    custom_footer: '',
    replacements: [],
  },
};

const TABS = [
  { id: '1', label: '1. General' },
  { id: '2', label: '2. Source & Destinations' },
  { id: '3', label: '3. Message & Sender' },
  { id: '4', label: '4. Keywords & Regex' },
  { id: '5', label: '5. File Filters' },
  { id: '6', label: '6. Media Categories' },
  { id: '7', label: '7. Scheduling' },
  { id: '8', label: '8. Delivery Settings' },
  { id: '9', label: '9. Caption Transforms' },
  { id: '10', label: '10. Advanced & Test' },
];

export const RuleEditorModal: React.FC<RuleEditorModalProps> = ({
  initialRule,
  chats,
  onClose,
  onSaved,
  notify,
}) => {
  const [activeTab, setActiveTab] = useState('1');
  const [rule, setRule] = useState<ForwardingRule>(() =>
    initialRule ? JSON.parse(JSON.stringify(initialRule)) : JSON.parse(JSON.stringify(DEFAULT_RULE))
  );
  const [saving, setSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Comma-separated input helpers
  const [reqKeywordsInput, setReqKeywordsInput] = useState(
    (rule.filters.required_keywords || []).join(', ')
  );
  const [excKeywordsInput, setExcKeywordsInput] = useState(
    (rule.filters.excluded_keywords || []).join(', ')
  );
  const [senderIdsInput, setSenderIdsInput] = useState(
    (rule.filters.sender_user_ids || []).join(', ')
  );
  const [acceptedExtsInput, setAcceptedExtsInput] = useState(
    (rule.filters.accepted_extensions || []).join(', ')
  );
  const [excludedExtsInput, setExcludedExtsInput] = useState(
    (rule.filters.excluded_extensions || []).join(', ')
  );

  // Caption preview sample
  const [sampleCaption, setSampleCaption] = useState(
    '🔥 [TG] Dune.Part.Two.2024.2160p.UHD.BluRay.Remux.HEVC.mkv.001 Join @scene_raw_ingest https://t.me/promo #uhd Fast mirror!'
  );
  const [sampleFilename, setSampleFilename] = useState(
    'Dune.Part.Two.2024.2160p.UHD.BluRay.Remux.HEVC.mkv.001'
  );
  const [sampleFileSizeMb, setSampleFileSizeMb] = useState<number>(24000);
  const [testReport, setTestReport] = useState<RuleEvaluationReport | null>(null);
  const [testingRule, setTestingRule] = useState(false);

  const syncTextArraysIntoRule = (draft: ForwardingRule): ForwardingRule => {
    const splitCsv = (s: string) =>
      s
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean);
    return {
      ...draft,
      filters: {
        ...draft.filters,
        required_keywords: splitCsv(reqKeywordsInput),
        excluded_keywords: splitCsv(excKeywordsInput),
        sender_user_ids: splitCsv(senderIdsInput)
          .map((n) => Number(n))
          .filter((n) => !Number.isNaN(n)),
        accepted_extensions: splitCsv(acceptedExtsInput),
        excluded_extensions: splitCsv(excludedExtsInput),
      },
    };
  };

  // Live local preview of caption transformation
  const liveCaptionPreview = useMemo(() => {
    if (rule.delivery_mode === 'FORWARD') {
      return sampleCaption;
    }
    let text =
      rule.caption_transform.clean_filename_mode && sampleFilename.trim()
        ? sampleFilename.trim()
        : sampleCaption;

    if (rule.caption_transform.strip_text_after_extension) {
      const re = rule.caption_transform.preserve_multipart_suffix
        ? /^(.*?\.(?:mkv|mp4|avi|mov|ts|iso|7z|rar|zip)(?:\.\d{3}|\.part\d+\.rar)?)\b[\s\S]*$/i
        : /^(.*?\.(?:mkv|mp4|avi|mov|ts|iso|7z|rar|zip))\b[\s\S]*$/i;
      const m = text.match(re);
      if (m && m[1]) text = m[1];
    }
    if (rule.caption_transform.remove_links) {
      text = text.replace(/(?:https?:\/\/|t\.me\/|telegram\.me\/|www\.)\S+/gi, '');
    }
    if (rule.caption_transform.remove_usernames) {
      text = text.replace(/(?:^|\s)@[A-Za-z0-9_]{3,32}\b/g, ' ');
    }
    if (rule.caption_transform.remove_hashtags) {
      text = text.replace(/(?:^|\s)#[A-Za-z0-9_]+\b/g, ' ');
    }
    if (rule.caption_transform.remove_decorative_symbols) {
      text = text.replace(/[★☆✦✧❖⚡🔥💥🎬📺💎👑🔔📢✅❌⭕➖➗➕💲🔗]+/g, '');
    }
    if (rule.caption_transform.remove_emojis) {
      text = text.replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '');
    }
    for (const step of rule.caption_transform.replacements) {
      if (!step.find_pattern) continue;
      try {
        const re = new RegExp(
          step.is_regex
            ? step.find_pattern
            : step.find_pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
          step.case_sensitive ? 'g' : 'gi'
        );
        text = text.replace(re, step.replace_with ?? '');
      } catch {
        // ignore invalid regex in live preview
      }
    }
    text = text.replace(/\s+/g, ' ').trim();
    const parts: string[] = [];
    if (rule.caption_transform.custom_header.trim()) {
      parts.push(rule.caption_transform.custom_header.trim());
    }
    if (text) parts.push(text);
    if (rule.caption_transform.custom_footer.trim()) {
      parts.push(rule.caption_transform.custom_footer.trim());
    }
    return parts.join('\n').slice(0, 1024);
  }, [rule.delivery_mode, rule.caption_transform, sampleCaption, sampleFilename]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    const prepared = syncTextArraysIntoRule(rule);

    if (!prepared.name.trim()) {
      setErrorMsg('Rule name is required (Section 1).');
      return;
    }
    if (!prepared.source_peer_id) {
      setErrorMsg('Select a source chat (Section 2).');
      return;
    }
    if (prepared.destination_peer_ids.length === 0) {
      setErrorMsg('Select at least one destination chat (Section 2).');
      return;
    }

    setSaving(true);
    try {
      const isEdit = Boolean(initialRule?.id);
      const saved = await apiRequest<ForwardingRule>(
        isEdit ? `/api/v1/rules/${initialRule!.id}` : '/api/v1/rules',
        {
          method: isEdit ? 'PUT' : 'POST',
          body: JSON.stringify(prepared),
        }
      );
      notify(`Saved rule "${saved.name}"`, 'success');
      onSaved(saved);
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleRunRuleTest = async (liveSend = false) => {
    setTestingRule(true);
    setErrorMsg(null);
    try {
      const prepared = syncTextArraysIntoRule(rule);
      const res = await apiRequest<{ report: RuleEvaluationReport; live_test_enqueued_job_ids: string[] }>(
        '/api/v1/rules/test',
        {
          method: 'POST',
          body: JSON.stringify({
            rule: prepared,
            live_delivery_test: liveSend,
            message: {
              message_id: 9999,
              source_peer_id: prepared.source_peer_id,
              chat_type: 'CHANNEL',
              media_type: 'DOCUMENT',
              is_album: false,
              is_first_in_album: true,
              text: null,
              caption: sampleCaption,
              filename: sampleFilename || null,
              file_size_bytes: sampleFileSizeMb ? Math.round(sampleFileSizeMb * 1024 * 1024) : null,
              sender_user_id: null,
              is_sender_admin: true,
              is_anonymous_admin: true,
              is_sender_verified: false,
              timestamp_utc: new Date().toISOString(),
            },
          }),
        }
      );
      setTestReport(res.report);
      if (liveSend && res.live_test_enqueued_job_ids?.length > 0) {
        notify(`Enqueued ${res.live_test_enqueued_job_ids.length} live test delivery job(s)`, 'success');
      }
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setTestingRule(false);
    }
  };

  const toggleCategory = (cat: MediaCategory) => {
    const exists = rule.categories.selected.includes(cat);
    const next = exists
      ? rule.categories.selected.filter((c) => c !== cat)
      : [...rule.categories.selected, cat];
    setRule({
      ...rule,
      categories: { ...rule.categories, enabled: next.length > 0, selected: next },
    });
  };

  const toggleDestination = (peerId: string) => {
    const exists = rule.destination_peer_ids.includes(peerId);
    const next = exists
      ? rule.destination_peer_ids.filter((id) => id !== peerId)
      : [...rule.destination_peer_ids, peerId];
    setRule({ ...rule, destination_peer_ids: next });
  };

  const toggleScheduleDay = (day: number) => {
    const exists = rule.schedule.days.includes(day);
    const next = exists
      ? rule.schedule.days.filter((d) => d !== day)
      : [...rule.schedule.days, day].sort();
    setRule({ ...rule, schedule: { ...rule.schedule, days: next } });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 overflow-y-auto">
      <div className="w-full max-w-5xl bg-slate-900 border border-slate-800 rounded-lg shadow-2xl overflow-hidden flex flex-col max-h-[92vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/60">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">
              {initialRule ? `Edit Rule: ${initialRule.name}` : 'Create Forwarding Rule'}
            </h2>
            <p className="text-xs text-slate-400">
              10-stage deterministic routing, filter, media classification, and caption transformation configuration
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-slate-200 rounded-md"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {errorMsg && (
          <div className="mx-6 mt-4 p-3 bg-red-950/60 border border-red-800 rounded-md flex items-center gap-2 text-xs text-red-200">
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Body Layout: Left Section Tabs + Right Form Area */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          <div className="w-56 border-r border-slate-800 bg-slate-950/40 p-3 overflow-y-auto space-y-1 shrink-0">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setActiveTab(t.id)}
                className={`w-full text-left px-3 py-2 rounded-md text-xs font-medium transition-colors whitespace-nowrap ${
                  activeTab === t.id
                    ? 'bg-sky-600 text-white'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <form onSubmit={handleSave} className="flex-1 p-6 overflow-y-auto space-y-6">
            {/* Section 1: General */}
            {activeTab === '1' && (
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-slate-200">01. General Rule Identity & Priority</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">Rule Name *</label>
                    <input
                      type="text"
                      required
                      value={rule.name}
                      onChange={(e) => setRule({ ...rule, name: e.target.value })}
                      placeholder="e.g. 2160p UHD Movies — Clean Copy"
                      className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Rule Identifier (Immutable Key / Optional Custom Slug)
                    </label>
                    <input
                      type="text"
                      disabled={Boolean(initialRule?.id)}
                      value={rule.id}
                      onChange={(e) => setRule({ ...rule, id: e.target.value })}
                      placeholder="Auto-generated if left blank"
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-300 disabled:opacity-60"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Description</label>
                  <textarea
                    rows={2}
                    value={rule.description}
                    onChange={(e) => setRule({ ...rule, description: e.target.value })}
                    placeholder="Operational notes explaining what this rule matches and where it delivers..."
                    className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Priority (0 to 100, evaluated descending)
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={rule.priority}
                      onChange={(e) => setRule({ ...rule, priority: Number(e.target.value) })}
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Secondary Tie-Break Order
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={999}
                      value={rule.secondary_order}
                      onChange={(e) => setRule({ ...rule, secondary_order: Number(e.target.value) })}
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div className="flex flex-col justify-end space-y-2">
                    <label className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={rule.enabled}
                        onChange={(e) => setRule({ ...rule, enabled: e.target.checked })}
                        className="rounded border-slate-700"
                      />
                      <span>Rule Enabled</span>
                    </label>
                    <label className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={rule.exclusive_stop}
                        onChange={(e) => setRule({ ...rule, exclusive_stop: e.target.checked })}
                        className="rounded border-slate-700"
                      />
                      <span>Exclusive Stop (halt lower rules on match)</span>
                    </label>
                  </div>
                </div>
              </div>
            )}

            {/* Section 2: Source & Destinations */}
            {activeTab === '2' && (
              <div className="space-y-5">
                <h3 className="text-sm font-semibold text-slate-200">02. Source Chat & Destination Selection</h3>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Source Chat (Stable Telegram Peer ID) *
                  </label>
                  <select
                    value={rule.source_peer_id}
                    onChange={(e) => setRule({ ...rule, source_peer_id: e.target.value })}
                    className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                  >
                    {chats.map((c) => (
                      <option key={c.peer_id} value={c.peer_id}>
                        {c.title} ({c.chat_type} · {c.peer_id})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-2">
                    Destination Chats (Select one or multiple) *
                  </label>
                  <div className="border border-slate-800 rounded-md divide-y divide-slate-800 bg-slate-950 max-h-64 overflow-y-auto">
                    {chats
                      .filter((c) => c.peer_id !== rule.source_peer_id)
                      .map((c) => {
                        const checked = rule.destination_peer_ids.includes(c.peer_id);
                        return (
                          <label
                            key={c.peer_id}
                            className="flex items-center justify-between px-3 py-2.5 text-xs hover:bg-slate-900 cursor-pointer"
                          >
                            <div className="flex items-center gap-3">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => toggleDestination(c.peer_id)}
                              />
                              <div>
                                <div className="font-medium text-slate-200">{c.title}</div>
                                <div className="text-slate-400 font-mono">
                                  {c.peer_id} · {c.chat_type}
                                  {c.username ? ` · @${c.username}` : ''}
                                </div>
                              </div>
                            </div>
                            <div className="text-right">
                              {c.can_send ? (
                                <span className="text-emerald-400">Writable</span>
                              ) : (
                                <span className="text-amber-400">Read-Only (No Send Permission)</span>
                              )}
                            </div>
                          </label>
                        );
                      })}
                  </div>
                </div>
              </div>
            )}

            {/* Section 3: Message & Sender Filters */}
            {activeTab === '3' && (
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-slate-200">03. Message-Type & Sender Filters</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Message-Type Filter
                    </label>
                    <select
                      value={rule.filters.message_type_filter}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: {
                            ...rule.filters,
                            message_type_filter: e.target.value as MessageTypeFilter,
                          },
                        })
                      }
                      className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    >
                      <option value="ALL">All Supported Types</option>
                      <option value="TEXT_ONLY">Text Only</option>
                      <option value="MEDIA_ONLY">Media Only (Photo/Video/Doc/Audio/Voice)</option>
                      <option value="PHOTO">Photos</option>
                      <option value="VIDEO">Videos</option>
                      <option value="DOCUMENT">Documents and Files</option>
                      <option value="AUDIO">Audio</option>
                      <option value="VOICE">Voice Messages</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Media Album / Grouped Media Handling
                    </label>
                    <select
                      value={rule.filters.album_policy}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: { ...rule.filters, album_policy: e.target.value as any },
                        })
                      }
                      className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    >
                      <option value="PROCESS_ITEMS">Process All Album Items</option>
                      <option value="FIRST_ITEM_ONLY">First Captioned Album Item Only</option>
                      <option value="SKIP_ALBUMS">Skip Media Albums</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Sender Filter Mode
                    </label>
                    <select
                      value={rule.filters.sender_filter_mode}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: {
                            ...rule.filters,
                            sender_filter_mode: e.target.value as SenderFilterMode,
                          },
                        })
                      }
                      className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    >
                      <option value="ANY">Any Sender</option>
                      <option value="SPECIFIC_USER_IDS">Specific Numeric User IDs</option>
                      <option value="ADMINS_ONLY">Verified Chat Administrators Only</option>
                      <option value="ANONYMOUS_ADMINS_ONLY">Anonymous Administrators Only</option>
                      <option value="VERIFIED_USERS_ONLY">Telegram Verified Users Only</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Missing Sender Identity Policy
                    </label>
                    <select
                      value={rule.filters.missing_sender_policy}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: {
                            ...rule.filters,
                            missing_sender_policy: e.target.value as any,
                          },
                        })
                      }
                      className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    >
                      <option value="ALLOW_IN_CHANNELS">Allow Unsigned Posts in Broadcast Channels</option>
                      <option value="REJECT">Reject Whenever Numeric Sender ID is Absent</option>
                    </select>
                  </div>
                </div>

                {rule.filters.sender_filter_mode === 'SPECIFIC_USER_IDS' && (
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Allowed Numeric Telegram User IDs (comma-separated)
                    </label>
                    <input
                      type="text"
                      value={senderIdsInput}
                      onChange={(e) => setSenderIdsInput(e.target.value)}
                      placeholder="e.g. 40192831, 99182736"
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                )}
              </div>
            )}

            {/* Section 4: Keywords & Regular Expressions */}
            {activeTab === '4' && (
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-slate-200">04. Keywords & Safe Regular Expressions</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Inspected Search Field (Explicit Field Scope)
                    </label>
                    <select
                      value={rule.filters.keyword_search_target}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: {
                            ...rule.filters,
                            keyword_search_target: e.target.value as KeywordSearchTarget,
                          },
                        })
                      }
                      className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    >
                      <option value="TEXT_CAPTION_AND_FILENAME">Message Text + Caption + Filename</option>
                      <option value="TEXT_AND_CAPTION">Message Text + Media Caption</option>
                      <option value="CAPTION_ONLY">Media Caption Only</option>
                      <option value="TEXT_ONLY">Message Text Only</option>
                      <option value="FILENAME_ONLY">Filename Only</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Required Keywords Match Mode
                    </label>
                    <select
                      value={rule.filters.required_keywords_match_mode}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: {
                            ...rule.filters,
                            required_keywords_match_mode: e.target.value as 'ANY' | 'ALL',
                          },
                        })
                      }
                      className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    >
                      <option value="ANY">ANY required keyword may match (Logical OR)</option>
                      <option value="ALL">ALL required keywords must match (Logical AND)</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Only-If-Contains Terms (Comma-separated alternatives)
                  </label>
                  <input
                    type="text"
                    value={reqKeywordsInput}
                    onChange={(e) => setReqKeywordsInput(e.target.value)}
                    placeholder="e.g. 2160p, UHD, 4K, Remux"
                    className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Skip-If-Contains Terms (Comma-separated exclusions)
                  </label>
                  <input
                    type="text"
                    value={excKeywordsInput}
                    onChange={(e) => setExcKeywordsInput(e.target.value)}
                    placeholder="e.g. sample, trailer, camrip, advertisement"
                    className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Required Regular Expression (Safe DFA/NFA validated)
                    </label>
                    <input
                      type="text"
                      value={rule.filters.regex_pattern}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: { ...rule.filters, regex_pattern: e.target.value },
                        })
                      }
                      placeholder="e.g. (2160p|1080p).*(BluRay|WEB-DL)"
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Exclusion Regular Expression
                    </label>
                    <input
                      type="text"
                      value={rule.filters.regex_exclude_pattern}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: { ...rule.filters, regex_exclude_pattern: e.target.value },
                        })
                      }
                      placeholder="e.g. (sample|promo|betting)"
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                </div>

                <div className="flex items-center gap-6 pt-2">
                  <label className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={rule.filters.case_sensitive}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: { ...rule.filters, case_sensitive: e.target.checked },
                        })
                      }
                    />
                    <span>Case-Sensitive Matching</span>
                  </label>
                  <label className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={rule.filters.whole_word}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: { ...rule.filters, whole_word: e.target.checked },
                        })
                      }
                    />
                    <span>Whole-Word Matching (\bword\b)</span>
                  </label>
                </div>
              </div>
            )}

            {/* Section 5: File Filters */}
            {activeTab === '5' && (
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-slate-200">
                  05. File Size & Filename Filters (Logical AND)
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Minimum File Size (MB)
                    </label>
                    <input
                      type="number"
                      min={0}
                      step="any"
                      value={rule.filters.min_file_size_mb ?? ''}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: {
                            ...rule.filters,
                            min_file_size_mb: e.target.value ? Number(e.target.value) : null,
                          },
                        })
                      }
                      placeholder="e.g. 500"
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Maximum File Size (MB)
                    </label>
                    <input
                      type="number"
                      min={0}
                      step="any"
                      value={rule.filters.max_file_size_mb ?? ''}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: {
                            ...rule.filters,
                            max_file_size_mb: e.target.value ? Number(e.target.value) : null,
                          },
                        })
                      }
                      placeholder="e.g. 80000"
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Missing File Metadata Policy
                    </label>
                    <select
                      value={rule.filters.missing_file_metadata_policy}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: {
                            ...rule.filters,
                            missing_file_metadata_policy: e.target.value as any,
                          },
                        })
                      }
                      className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    >
                      <option value="FAIL_FILTER">Fail Condition When Metadata Absent</option>
                      <option value="PASS_IF_NON_FILE">Allow Non-File Messages Without Size/Name</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Filename Contains Substring
                    </label>
                    <input
                      type="text"
                      value={rule.filters.filename_contains}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: { ...rule.filters, filename_contains: e.target.value },
                        })
                      }
                      placeholder="e.g. 2160p"
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Filename Ends With Suffix
                    </label>
                    <input
                      type="text"
                      value={rule.filters.filename_ends_with}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: { ...rule.filters, filename_ends_with: e.target.value },
                        })
                      }
                      placeholder="e.g. .mkv"
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Filename Regular Expression
                    </label>
                    <input
                      type="text"
                      value={rule.filters.filename_regex}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          filters: { ...rule.filters, filename_regex: e.target.value },
                        })
                      }
                      placeholder="e.g. ^.*1080p.*\.mkv$"
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Accepted Extensions (comma-separated)
                    </label>
                    <input
                      type="text"
                      value={acceptedExtsInput}
                      onChange={(e) => setAcceptedExtsInput(e.target.value)}
                      placeholder="e.g. .mkv, .mp4, .001"
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Excluded Extensions (comma-separated)
                    </label>
                    <input
                      type="text"
                      value={excludedExtsInput}
                      onChange={(e) => setExcludedExtsInput(e.target.value)}
                      placeholder="e.g. .exe, .scr, .txt"
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Section 6: Media Categories */}
            {activeTab === '6' && (
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-slate-200">
                  06. Automatic Offline Media Classification
                </h3>
                <label className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={rule.categories.enabled}
                    onChange={(e) =>
                      setRule({
                        ...rule,
                        categories: { ...rule.categories, enabled: e.target.checked },
                      })
                    }
                  />
                  <span>Enable Automatic Content Category Filtering</span>
                </label>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {(
                    [
                      { id: 'MOVIE', title: 'MOVIE', desc: 'Standalone films with release year & encoding signature' },
                      { id: 'TV_SHOW', title: 'TV_SHOW', desc: 'Episodic television (S01E05, 1x05, Season/Episode)' },
                      { id: 'COMBINED', title: 'COMBINED', desc: 'Complete season packs & multi-episode ranges (S01E01-E10)' },
                      { id: 'SPLIT', title: 'SPLIT', desc: 'Multipart split archives (.mkv.001, .7z.002, .part1, cd1)' },
                    ] as const
                  ).map((cat) => {
                    const active = rule.categories.selected.includes(cat.id);
                    return (
                      <button
                        key={cat.id}
                        type="button"
                        onClick={() => toggleCategory(cat.id)}
                        className={`p-3 rounded-md border text-left transition-colors ${
                          active
                            ? 'bg-sky-950/60 border-sky-500 text-slate-100'
                            : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
                        }`}
                      >
                        <div className="text-xs font-mono font-semibold">{cat.title}</div>
                        <div className="text-[11px] text-slate-400 mt-1">{cat.desc}</div>
                      </button>
                    );
                  })}
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Multi-Category Match Requirement
                  </label>
                  <select
                    value={rule.categories.match_mode}
                    onChange={(e) =>
                      setRule({
                        ...rule,
                        categories: {
                          ...rule.categories,
                          match_mode: e.target.value as 'ALL' | 'ANY',
                        },
                      })
                    }
                    className="w-full md:w-96 px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                  >
                    <option value="ALL">ALL selected categories must match (e.g. TV_SHOW + SPLIT)</option>
                    <option value="ANY">ANY selected category may match (e.g. TV_SHOW or COMBINED)</option>
                  </select>
                </div>
              </div>
            )}

            {/* Section 7: Scheduling */}
            {activeTab === '7' && (
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-slate-200">
                  07. Time-Window Scheduling (Supports Midnight Crossing)
                </h3>
                <label className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={rule.schedule.enabled}
                    onChange={(e) =>
                      setRule({
                        ...rule,
                        schedule: { ...rule.schedule, enabled: e.target.checked },
                      })
                    }
                  />
                  <span>Restrict rule by time-of-day and day-of-week schedule</span>
                </label>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Start Time (24h HH:MM)
                    </label>
                    <input
                      type="time"
                      value={rule.schedule.start_time}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          schedule: { ...rule.schedule, start_time: e.target.value },
                        })
                      }
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      End Time (24h HH:MM — crosses midnight if &lt; Start)
                    </label>
                    <input
                      type="time"
                      value={rule.schedule.end_time}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          schedule: { ...rule.schedule, end_time: e.target.value },
                        })
                      }
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Explicit IANA Timezone
                    </label>
                    <select
                      value={rule.schedule.timezone}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          schedule: { ...rule.schedule, timezone: e.target.value },
                        })
                      }
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    >
                      <option value="UTC">UTC</option>
                      <option value="America/New_York">America/New_York</option>
                      <option value="America/Los_Angeles">America/Los_Angeles</option>
                      <option value="Europe/London">Europe/London</option>
                      <option value="Europe/Berlin">Europe/Berlin</option>
                      <option value="Asia/Singapore">Asia/Singapore</option>
                      <option value="Asia/Tokyo">Asia/Tokyo</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-2">
                    Active Days of the Week
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((label, idx) => {
                      const active = rule.schedule.days.includes(idx);
                      return (
                        <button
                          key={label}
                          type="button"
                          onClick={() => toggleScheduleDay(idx)}
                          className={`px-3 py-1.5 rounded-md text-xs font-medium border ${
                            active
                              ? 'bg-sky-600 border-sky-500 text-white'
                              : 'bg-slate-950 border-slate-800 text-slate-400'
                          }`}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Out-of-Window Schedule Semantics
                  </label>
                  <select
                    value={rule.schedule.behavior}
                    onChange={(e) =>
                      setRule({
                        ...rule,
                        schedule: { ...rule.schedule, behavior: e.target.value as any },
                      })
                    }
                    className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                  >
                    <option value="DEFER_UNTIL_WINDOW">
                      Allow queued messages to be sent only during window (Defer delivery until window opens)
                    </option>
                    <option value="ONLY_ARRIVING_DURING_WINDOW">
                      Only match messages arriving during window (Skip messages arriving outside window)
                    </option>
                  </select>
                </div>
              </div>
            )}

            {/* Section 8: Delivery Settings */}
            {activeTab === '8' && (
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-slate-200">08. Delivery Mode, Pacing & Retries</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Delivery Mode
                    </label>
                    <select
                      value={rule.delivery_mode}
                      onChange={(e) =>
                        setRule({ ...rule, delivery_mode: e.target.value as 'FORWARD' | 'COPY' })
                      }
                      className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    >
                      <option value="COPY">Copy Mode (No Forward Header + Caption Transforms)</option>
                      <option value="FORWARD">Forward Mode (Preserve Native Forward Attribution)</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Per-Rule Send Delay (0 to 120 seconds)
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={120}
                      value={rule.delay_seconds}
                      onChange={(e) => setRule({ ...rule, delay_seconds: Number(e.target.value) })}
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Max Retries on Transient / FloodWait Error (0 to 10)
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={10}
                      value={rule.max_retries}
                      onChange={(e) => setRule({ ...rule, max_retries: Number(e.target.value) })}
                      className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Section 9: Caption Transformations */}
            {activeTab === '9' && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-200">
                    09. Caption Transformations (Copy Mode Pipeline)
                  </h3>
                  {rule.delivery_mode === 'FORWARD' && (
                    <span className="text-xs text-amber-400">
                      Note: Switch Delivery Mode to COPY in Section 8 to apply caption transformations.
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs text-slate-200">
                  {[
                    ['clean_filename_mode', 'Clean-Filename Caption Mode'],
                    ['strip_text_after_extension', 'Strip Text After Extension'],
                    ['preserve_multipart_suffix', 'Preserve .001 Multipart Suffix'],
                    ['remove_links', 'Remove Links (http / t.me)'],
                    ['remove_usernames', 'Remove @usernames'],
                    ['remove_hashtags', 'Remove #hashtags'],
                    ['remove_emojis', 'Remove Emojis'],
                    ['remove_decorative_symbols', 'Remove Decorative Symbols'],
                  ].map(([field, label]) => (
                    <label
                      key={field}
                      className="flex items-center gap-2 p-2.5 bg-slate-950 border border-slate-800 rounded-md cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={Boolean((rule.caption_transform as any)[field])}
                        onChange={(e) =>
                          setRule({
                            ...rule,
                            caption_transform: {
                              ...rule.caption_transform,
                              [field]: e.target.checked,
                            },
                          })
                        }
                      />
                      <span>{label}</span>
                    </label>
                  ))}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Custom Header (Prepend Line)
                    </label>
                    <input
                      type="text"
                      value={rule.caption_transform.custom_header}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          caption_transform: {
                            ...rule.caption_transform,
                            custom_header: e.target.value,
                          },
                        })
                      }
                      placeholder="e.g. [Vault 4K UHD Cinema]"
                      className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Custom Footer (Append Line)
                    </label>
                    <input
                      type="text"
                      value={rule.caption_transform.custom_footer}
                      onChange={(e) =>
                        setRule({
                          ...rule,
                          caption_transform: {
                            ...rule.caption_transform,
                            custom_footer: e.target.value,
                          },
                        })
                      }
                      placeholder="e.g. Verified Remux Index"
                      className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    />
                  </div>
                </div>

                {/* Ordered Find-and-Replace Steps */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-slate-300">
                      Ordered Find-and-Replace Transformations
                    </label>
                    <button
                      type="button"
                      onClick={() =>
                        setRule({
                          ...rule,
                          caption_transform: {
                            ...rule.caption_transform,
                            replacements: [
                              ...rule.caption_transform.replacements,
                              {
                                step_order: rule.caption_transform.replacements.length + 1,
                                find_pattern: '',
                                replace_with: '',
                                is_regex: false,
                                case_sensitive: false,
                              },
                            ],
                          },
                        })
                      }
                      className="flex items-center gap-1 px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-md"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>Add Replacement Step</span>
                    </button>
                  </div>

                  {rule.caption_transform.replacements.map((step, idx) => (
                    <div
                      key={idx}
                      className="grid grid-cols-12 gap-2 items-center bg-slate-950 p-2 rounded-md border border-slate-800"
                    >
                      <input
                        type="text"
                        placeholder="Find pattern..."
                        value={step.find_pattern}
                        onChange={(e) => {
                          const next = [...rule.caption_transform.replacements];
                          next[idx] = { ...step, find_pattern: e.target.value };
                          setRule({
                            ...rule,
                            caption_transform: { ...rule.caption_transform, replacements: next },
                          });
                        }}
                        className="col-span-4 px-2.5 py-1.5 text-xs font-mono bg-slate-900 border border-slate-800 rounded text-slate-100"
                      />
                      <input
                        type="text"
                        placeholder="Replace with..."
                        value={step.replace_with}
                        onChange={(e) => {
                          const next = [...rule.caption_transform.replacements];
                          next[idx] = { ...step, replace_with: e.target.value };
                          setRule({
                            ...rule,
                            caption_transform: { ...rule.caption_transform, replacements: next },
                          });
                        }}
                        className="col-span-4 px-2.5 py-1.5 text-xs font-mono bg-slate-900 border border-slate-800 rounded text-slate-100"
                      />
                      <label className="col-span-2 flex items-center gap-1 text-xs text-slate-300">
                        <input
                          type="checkbox"
                          checked={step.is_regex}
                          onChange={(e) => {
                            const next = [...rule.caption_transform.replacements];
                            next[idx] = { ...step, is_regex: e.target.checked };
                            setRule({
                              ...rule,
                              caption_transform: { ...rule.caption_transform, replacements: next },
                            });
                          }}
                        />
                        <span>Regex</span>
                      </label>
                      <label className="col-span-1 flex items-center gap-1 text-xs text-slate-300">
                        <input
                          type="checkbox"
                          checked={step.case_sensitive}
                          onChange={(e) => {
                            const next = [...rule.caption_transform.replacements];
                            next[idx] = { ...step, case_sensitive: e.target.checked };
                            setRule({
                              ...rule,
                              caption_transform: { ...rule.caption_transform, replacements: next },
                            });
                          }}
                        />
                        <span>Aa</span>
                      </label>
                      <button
                        type="button"
                        onClick={() => {
                          const next = rule.caption_transform.replacements.filter((_, i) => i !== idx);
                          setRule({
                            ...rule,
                            caption_transform: { ...rule.caption_transform, replacements: next },
                          });
                        }}
                        className="col-span-1 p-1.5 text-slate-400 hover:text-red-400"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>

                {/* Live Transformed Caption Preview */}
                <div className="p-4 bg-slate-950 border border-slate-800 rounded-md space-y-3">
                  <div className="text-xs font-semibold text-slate-300">
                    Live Deterministic Transformation Preview
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">
                        Sample Input Caption
                      </label>
                      <textarea
                        rows={2}
                        value={sampleCaption}
                        onChange={(e) => setSampleCaption(e.target.value)}
                        className="w-full px-2.5 py-1.5 text-xs font-mono bg-slate-900 border border-slate-800 rounded text-slate-300"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">
                        Transformed Output ({liveCaptionPreview.length} / 1024 chars)
                      </label>
                      <pre className="w-full p-2.5 text-xs font-mono bg-slate-900 border border-slate-800 rounded text-emerald-300 whitespace-pre-wrap min-h-[54px]">
                        {liveCaptionPreview || '(Empty caption)'}
                      </pre>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Section 10: Advanced & Dry-Run Rule Tester */}
            {activeTab === '10' && (
              <div className="space-y-5">
                <h3 className="text-sm font-semibold text-slate-200">
                  10. Synchronization, Deduplication Override & Dry-Run Rule Tester
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Deduplication Scope Override
                    </label>
                    <select
                      value={rule.deduplication_override}
                      onChange={(e) =>
                        setRule({ ...rule, deduplication_override: e.target.value as any })
                      }
                      className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    >
                      <option value="GLOBAL">Inherit Global Deduplication Scope</option>
                      <option value="PER_DESTINATION">Per-Destination (Prevent duplicate to same chat)</option>
                      <option value="PER_RULE">Per-Rule (Independent per rule)</option>
                    </select>
                  </div>
                  <div className="flex flex-col justify-end space-y-2">
                    <label className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={rule.sync_edits}
                        onChange={(e) => setRule({ ...rule, sync_edits: e.target.checked })}
                      />
                      <span>Synchronize Source Caption Edits (Copy Mode)</span>
                    </label>
                    <label className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={rule.sync_deletes}
                        onChange={(e) => setRule({ ...rule, sync_deletes: e.target.checked })}
                      />
                      <span>Synchronize Source Message Deletions</span>
                    </label>
                  </div>
                </div>

                {/* Rule Tester Box */}
                <div className="p-4 bg-slate-950 border border-slate-800 rounded-md space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs font-semibold text-slate-200">
                        Test Rule Against Representative Message
                      </div>
                      <div className="text-[11px] text-slate-400">
                        Dry-run evaluation never sends a message unless you click the explicit Live-Delivery Test button.
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        disabled={testingRule}
                        onClick={() => handleRunRuleTest(false)}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-md"
                      >
                        <Play className="w-3.5 h-3.5" />
                        <span>Evaluate Dry-Run</span>
                      </button>
                      <button
                        type="button"
                        disabled={testingRule}
                        onClick={() => handleRunRuleTest(true)}
                        className="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-amber-300 border border-slate-700 rounded-md"
                      >
                        Live-Delivery Test
                      </button>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Filename</label>
                      <input
                        type="text"
                        value={sampleFilename}
                        onChange={(e) => setSampleFilename(e.target.value)}
                        className="w-full px-2.5 py-1.5 text-xs font-mono bg-slate-900 border border-slate-800 rounded text-slate-200"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">File Size (MB)</label>
                      <input
                        type="number"
                        value={sampleFileSizeMb}
                        onChange={(e) => setSampleFileSizeMb(Number(e.target.value))}
                        className="w-full px-2.5 py-1.5 text-xs font-mono bg-slate-900 border border-slate-800 rounded text-slate-200"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Caption / Text</label>
                      <input
                        type="text"
                        value={sampleCaption}
                        onChange={(e) => setSampleCaption(e.target.value)}
                        className="w-full px-2.5 py-1.5 text-xs font-mono bg-slate-900 border border-slate-800 rounded text-slate-200"
                      />
                    </div>
                  </div>

                  {testReport && (
                    <div className="p-3 bg-slate-900 border border-slate-800 rounded space-y-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold flex items-center gap-1.5">
                          {testReport.matched ? (
                            <span className="text-emerald-400 flex items-center gap-1">
                              <CheckCircle2 className="w-4 h-4" /> RULE MATCHED
                            </span>
                          ) : (
                            <span className="text-red-400 flex items-center gap-1">
                              <AlertTriangle className="w-4 h-4" /> DID NOT MATCH
                            </span>
                          )}
                        </span>
                        <span className="font-mono text-slate-400">
                          Categories: {testReport.assigned_categories.join(', ') || 'NONE'} · Exclusive-Stop:{' '}
                          {testReport.exclusive_stop_triggered ? 'YES' : 'NO'}
                        </span>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div>
                          <div className="text-[11px] font-medium text-emerald-400 mb-1">
                            Passed Conditions ({testReport.passed_conditions.length})
                          </div>
                          <ul className="space-y-0.5 text-[11px] text-slate-300 font-mono">
                            {testReport.passed_conditions.map((c, i) => (
                              <li key={i}>✓ {c}</li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <div className="text-[11px] font-medium text-red-400 mb-1">
                            Failed Conditions ({testReport.failed_conditions.length})
                          </div>
                          <ul className="space-y-0.5 text-[11px] text-red-300 font-mono">
                            {testReport.failed_conditions.map((c, i) => (
                              <li key={i}>✕ {c}</li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Footer Controls */}
            <div className="flex items-center justify-between pt-4 border-t border-slate-800">
              <div className="text-xs text-slate-400">
                Section {activeTab} of 10 · All changes are validated and saved atomically in SQLite WAL
              </div>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-md"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 text-xs font-medium text-white bg-sky-600 hover:bg-sky-500 rounded-md disabled:opacity-50"
                >
                  {saving ? 'Saving Rule...' : 'Save Rule'}
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};
