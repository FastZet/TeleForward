import React, { useState, useEffect } from 'react';
import { apiRequest } from '../api';
import { AppSettings } from '../server/types';
import {
  CheckCircle2,
  AlertTriangle,
  Play,
  ShieldCheck,
  KeyRound,
  LogOut,
  RefreshCw,
  Trash2,
  FileCode2,
} from 'lucide-react';

// ============================================================================
// 1. Operational Logs View (Searchable, Filtered, Paginated)
// ============================================================================
export const LogsView: React.FC<{
  rules: any[];
  chats: any[];
  notify: (msg: string, type?: 'success' | 'error') => void;
}> = ({ rules, chats, notify }) => {
  const [level, setLevel] = useState('ALL');
  const [ruleId, setRuleId] = useState('');
  const [sourcePeerId, setSourcePeerId] = useState('');
  const [destPeerId, setDestPeerId] = useState('');
  const [messageId, setMessageId] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ total: number; page: number; page_size: number; items: any[] }>({
    total: 0,
    page: 1,
    page_size: 25,
    items: [],
  });

  const loadLogs = async () => {
    try {
      const params = new URLSearchParams();
      if (level !== 'ALL') params.set('level', level);
      if (ruleId) params.set('rule_id', ruleId);
      if (sourcePeerId) params.set('source_peer_id', sourcePeerId);
      if (destPeerId) params.set('destination_peer_id', destPeerId);
      if (messageId) params.set('message_id', messageId);
      if (q) params.set('q', q);
      params.set('page', String(page));
      params.set('page_size', '25');
      const res = await apiRequest(`/api/v1/logs?${params.toString()}`);
      setData(res);
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  useEffect(() => {
    loadLogs();
  }, [level, ruleId, sourcePeerId, destPeerId, messageId, q, page]);

  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div className="space-y-5">
      <div className="p-4 bg-slate-900 border border-slate-800 rounded-lg space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-1 p-1 bg-slate-950 border border-slate-800 rounded-md">
            {['ALL', 'SUCCESS', 'SKIP', 'WARNING', 'FAILURE', 'INFO'].map((lv) => (
              <button
                key={lv}
                type="button"
                onClick={() => {
                  setLevel(lv);
                  setPage(1);
                }}
                className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
                  level === lv
                    ? 'bg-sky-600 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {lv}
              </button>
            ))}
          </div>

          <input
            type="text"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            placeholder="Search redacted diagnostic message or event type..."
            className="w-72 px-3 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded-md text-slate-100"
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <select
            value={ruleId}
            onChange={(e) => {
              setRuleId(e.target.value);
              setPage(1);
            }}
            className="px-2.5 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded text-slate-200"
          >
            <option value="">All Rules</option>
            {rules.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>

          <select
            value={sourcePeerId}
            onChange={(e) => {
              setSourcePeerId(e.target.value);
              setPage(1);
            }}
            className="px-2.5 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded text-slate-200"
          >
            <option value="">All Source Chats</option>
            {chats.map((c) => (
              <option key={c.peer_id} value={c.peer_id}>
                {c.title} ({c.peer_id})
              </option>
            ))}
          </select>

          <select
            value={destPeerId}
            onChange={(e) => {
              setDestPeerId(e.target.value);
              setPage(1);
            }}
            className="px-2.5 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded text-slate-200"
          >
            <option value="">All Destination Chats</option>
            {chats.map((c) => (
              <option key={c.peer_id} value={c.peer_id}>
                {c.title} ({c.peer_id})
              </option>
            ))}
          </select>

          <input
            type="number"
            value={messageId}
            onChange={(e) => {
              setMessageId(e.target.value);
              setPage(1);
            }}
            placeholder="Filter by Source Msg ID..."
            className="px-2.5 py-1.5 text-xs font-mono bg-slate-950 border border-slate-800 rounded text-slate-200"
          />
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/60 text-[11px] font-medium text-slate-400">
                <th className="py-3 px-4">Timestamp (UTC)</th>
                <th className="py-3 px-4">Level & Event</th>
                <th className="py-3 px-4">Operation & Rule</th>
                <th className="py-3 px-4">Chats & Msg ID</th>
                <th className="py-3 px-4">Diagnostic Message (Redacted)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-xs">
              {data.items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-10 text-center text-slate-400">
                    No operational events match the selected filters.
                  </td>
                </tr>
              ) : (
                data.items.map((ev) => (
                  <tr key={ev.id} className="hover:bg-slate-800/40">
                    <td className="py-2.5 px-4 font-mono text-[11px] text-slate-400 whitespace-nowrap">
                      {ev.timestamp}
                    </td>
                    <td className="py-2.5 px-4 font-mono whitespace-nowrap">
                      <span
                        className={
                          ev.level === 'SUCCESS'
                            ? 'text-emerald-400'
                            : ev.level === 'FAILURE'
                              ? 'text-red-400'
                              : ev.level === 'WARNING'
                                ? 'text-amber-400'
                                : ev.level === 'SKIP'
                                  ? 'text-slate-400'
                                  : 'text-sky-400'
                        }
                      >
                        {ev.level}
                      </span>
                      {' · '}
                      <span className="text-slate-300">{ev.event_type}</span>
                    </td>
                    <td className="py-2.5 px-4 font-mono text-[11px] text-slate-300">
                      <div>{ev.operation}</div>
                      {ev.rule_id && <div className="text-slate-500">{ev.rule_id}</div>}
                    </td>
                    <td className="py-2.5 px-4 font-mono text-[11px] text-slate-400 whitespace-nowrap">
                      {ev.source_peer_id || '—'}
                      {ev.destination_peer_id ? ` → ${ev.destination_peer_id}` : ''}
                      {ev.source_message_id ? ` (#${ev.source_message_id})` : ''}
                    </td>
                    <td className="py-2.5 px-4 font-mono text-[11px] text-slate-200">
                      {ev.diagnostic_message}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="px-4 py-3 border-t border-slate-800 bg-slate-950/40 flex items-center justify-between text-xs text-slate-400">
          <span className="font-mono">
            Total Events: {data.total} · Page {data.page} of {totalPages}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// ============================================================================
// 2. Statistics & Source Edit / Delete Synchronization View
// ============================================================================
export const StatisticsAndSyncView: React.FC<{
  stats: any;
  mappings: any[];
  onRefresh: () => void;
  notify: (msg: string, type?: 'success' | 'error') => void;
}> = ({ stats, mappings, onRefresh, notify }) => {
  const [editingMapping, setEditingMapping] = useState<any | null>(null);
  const [editedCaption, setEditedCaption] = useState('');

  const handlePropagateEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingMapping) return;
    try {
      const res = await apiRequest<{ updatedCount: number; details: string[] }>(
        '/api/v1/sync/simulate-edit',
        {
          method: 'POST',
          body: JSON.stringify({
            source_peer_id: editingMapping.source_peer_id,
            source_message_id: editingMapping.source_message_id,
            new_caption: editedCaption,
          }),
        }
      );
      notify(
        `Source edit propagated (${res.updatedCount} destination message(s) updated)`,
        'success'
      );
      setEditingMapping(null);
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handlePropagateDelete = async (m: any) => {
    try {
      const res = await apiRequest<{ deletedCount: number; failedCount: number }>(
        '/api/v1/sync/simulate-delete',
        {
          method: 'POST',
          body: JSON.stringify({
            source_peer_id: m.source_peer_id,
            source_message_id: m.source_message_id,
          }),
        }
      );
      notify(
        `Source delete propagated (${res.deletedCount} destination copy deleted)`,
        'success'
      );
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const g = stats?.global || {
    successful_deliveries: 0,
    skipped_messages: 0,
    failed_deliveries: 0,
    retry_count: 0,
    pending_queue_size: 0,
    avg_latency_ms: 0,
  };

  return (
    <div className="space-y-6">
      {/* Global Aggregate Counters */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
        {[
          ['Successful Deliveries', g.successful_deliveries, 'text-emerald-400'],
          ['Skipped (Dedup/Filter)', g.skipped_messages, 'text-slate-200'],
          ['Failed Deliveries', g.failed_deliveries, 'text-red-400'],
          ['Pending Queue Size', g.pending_queue_size, 'text-sky-400'],
          ['Retry Attempts', g.retry_count, 'text-amber-400'],
          ['Avg Delivery Latency', `${g.avg_latency_ms} ms`, 'text-slate-200'],
        ].map(([label, val, color]) => (
          <div
            key={String(label)}
            className="p-4 bg-slate-900 border border-slate-800 rounded-lg"
          >
            <div className="text-xs text-slate-400">{label}</div>
            <div className={`text-xl font-mono font-semibold mt-1 ${color}`}>{val}</div>
          </div>
        ))}
      </div>

      {/* Per-Rule & Per-Destination Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800 text-sm font-semibold text-slate-100">
            Per-Rule Persistent Statistics
          </div>
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/60 text-slate-400">
                <th className="py-2.5 px-4">Rule</th>
                <th className="py-2.5 px-4 text-right">Delivered</th>
                <th className="py-2.5 px-4 text-right">Skipped</th>
                <th className="py-2.5 px-4 text-right">Failed</th>
                <th className="py-2.5 px-4 text-right">Avg Latency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 font-mono">
              {(stats?.per_rule || []).map((r: any) => (
                <tr key={r.rule_id}>
                  <td className="py-2.5 px-4 font-sans text-slate-200">{r.rule_name}</td>
                  <td className="py-2.5 px-4 text-right text-emerald-400">
                    {r.successful_deliveries}
                  </td>
                  <td className="py-2.5 px-4 text-right text-slate-300">{r.skipped_messages}</td>
                  <td className="py-2.5 px-4 text-right text-red-400">{r.failed_deliveries}</td>
                  <td className="py-2.5 px-4 text-right text-slate-400">{r.avg_latency_ms}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800 text-sm font-semibold text-slate-100">
            Per-Destination Persistent Statistics
          </div>
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/60 text-slate-400">
                <th className="py-2.5 px-4">Destination Chat</th>
                <th className="py-2.5 px-4 text-right">Delivered</th>
                <th className="py-2.5 px-4 text-right">Skipped</th>
                <th className="py-2.5 px-4 text-right">Failed</th>
                <th className="py-2.5 px-4 text-right">Avg Latency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 font-mono">
              {(stats?.per_destination || []).map((d: any) => (
                <tr key={d.destination_peer_id}>
                  <td className="py-2.5 px-4 font-sans text-slate-200">{d.destination_title}</td>
                  <td className="py-2.5 px-4 text-right text-emerald-400">
                    {d.successful_deliveries}
                  </td>
                  <td className="py-2.5 px-4 text-right text-slate-300">{d.skipped_messages}</td>
                  <td className="py-2.5 px-4 text-right text-red-400">{d.failed_deliveries}</td>
                  <td className="py-2.5 px-4 text-right text-slate-400">{d.avg_latency_ms}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Source-to-Destination Message Mappings (Edit & Delete Synchronization) */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-100">
              Source-to-Destination Message Mappings (Edit & Delete Synchronization)
            </h3>
            <p className="text-xs text-slate-400">
              Tracks every destination copy created by this platform. Test propagating a source edit or deletion below.
            </p>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/60 text-slate-400">
                <th className="py-3 px-4">Source Message</th>
                <th className="py-3 px-4">Tracked Destination Copy</th>
                <th className="py-3 px-4">Rule & Mode</th>
                <th className="py-3 px-4">Current Synced Caption</th>
                <th className="py-3 px-4 text-right">Test Synchronization</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {mappings.map((m) => (
                <tr key={m.id} className="hover:bg-slate-800/40">
                  <td className="py-3 px-4 font-mono text-slate-200">
                    {m.source_title || m.source_peer_id} #{m.source_message_id}
                  </td>
                  <td className="py-3 px-4 font-mono">
                    <span className="text-sky-400">
                      {m.destination_title || m.destination_peer_id} #{m.destination_message_id}
                    </span>
                    {Boolean(m.is_deleted_on_dest) && (
                      <span className="ml-2 text-red-400">(DELETED)</span>
                    )}
                  </td>
                  <td className="py-3 px-4 font-mono text-slate-300">
                    {m.rule_name || m.rule_id} · {m.delivery_mode}
                  </td>
                  <td className="py-3 px-4 font-mono text-[11px] text-slate-300 max-w-xs truncate">
                    {m.last_synced_caption || '(Native Forward)'}
                  </td>
                  <td className="py-3 px-4 text-right whitespace-nowrap">
                    {!m.is_deleted_on_dest && (
                      <div className="inline-flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => {
                            setEditingMapping(m);
                            setEditedCaption(
                              m.last_synced_caption ||
                                'Updated.Release.2026.2160p.UHD.BluRay.Remux.mkv'
                            );
                          }}
                          className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 rounded"
                        >
                          Simulate Source Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => handlePropagateDelete(m)}
                          className="px-2.5 py-1 text-xs bg-red-950/60 hover:bg-red-900/60 text-red-300 border border-red-800 rounded"
                        >
                          Simulate Source Delete
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {editingMapping && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
          <form
            onSubmit={handlePropagateEdit}
            className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-lg p-6 space-y-4"
          >
            <h3 className="text-base font-semibold text-slate-100">
              Propagate Source Message Edit (#{editingMapping.source_message_id})
            </h3>
            <p className="text-xs text-slate-400">
              Re-runs the rule's caption transformation pipeline on the updated source caption and edits all tracked Copy-mode destination messages.
            </p>
            <textarea
              rows={3}
              value={editedCaption}
              onChange={(e) => setEditedCaption(e.target.value)}
              className="w-full p-3 text-xs font-mono bg-slate-950 border border-slate-800 rounded text-slate-100"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditingMapping(null)}
                className="px-4 py-2 text-xs bg-slate-800 text-slate-300 rounded-md"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-2 text-xs bg-sky-600 text-white rounded-md font-medium"
              >
                Propagate Edit to Destinations
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};

// ============================================================================
// 3. Settings & Telegram Personal-Account MTProto Authentication View
// ============================================================================
export const SettingsAndTelegramAuthView: React.FC<{
  settings: AppSettings;
  telegram: any;
  onRefresh: () => void;
  notify: (msg: string, type?: 'success' | 'error') => void;
}> = ({ settings, telegram, onRefresh, notify }) => {
  const [draft, setDraft] = useState<AppSettings>(settings);

  // Telegram Auth Form State
  const [apiIdInput, setApiIdInput] = useState(String(telegram?.api_id || '20400192'));
  const [apiHashInput, setApiHashInput] = useState('a1b2c3d4e5f60718293a4b5c6d7e8f90');
  const [phoneInput, setPhoneInput] = useState('+14155550199');
  const [useTestSandbox, setUseTestSandbox] = useState(true);
  const [require2faSandbox, setRequire2faSandbox] = useState(true);
  const [loginCodeInput, setLoginCodeInput] = useState('48291');
  const [twoStepPasswordInput, setTwoStepPasswordInput] = useState('');
  const [authBusy, setAuthBusy] = useState(false);

  useEffect(() => {
    setDraft(settings);
  }, [settings]);

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiRequest('/api/v1/settings', {
        method: 'PUT',
        body: JSON.stringify(draft),
      });
      if (draft.theme === 'light') {
        document.documentElement.classList.remove('dark');
      } else {
        document.documentElement.classList.add('dark');
      }
      notify('Global settings saved to SQLite', 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleConfigureApi = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthBusy(true);
    try {
      await apiRequest('/api/v1/telegram/config', {
        method: 'POST',
        body: JSON.stringify({ api_id: Number(apiIdInput), api_hash: apiHashInput }),
      });
      notify('Saved Telegram API ID & AES-256-GCM encrypted API Hash', 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    } finally {
      setAuthBusy(false);
    }
  };

  const handleRequestCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthBusy(true);
    try {
      await apiRequest('/api/v1/telegram/login/phone', {
        method: 'POST',
        body: JSON.stringify({
          phone_number: phoneInput,
          use_test_dc_sandbox: useTestSandbox,
          require_2fa_in_sandbox: require2faSandbox,
        }),
      });
      notify('Login code requested. Enter the verification code.', 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    } finally {
      setAuthBusy(false);
    }
  };

  const handleVerifyCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthBusy(true);
    try {
      const st = await apiRequest('/api/v1/telegram/login/code', {
        method: 'POST',
        body: JSON.stringify({ code: loginCodeInput }),
      });
      if (st.connection_state === 'AWAITING_TWO_STEP_PASSWORD') {
        notify('Code verified. Two-Step Verification password required.', 'success');
      } else {
        notify('Telegram personal account authenticated & session encrypted!', 'success');
      }
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    } finally {
      setAuthBusy(false);
    }
  };

  const handleVerify2FA = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthBusy(true);
    try {
      await apiRequest('/api/v1/telegram/login/password', {
        method: 'POST',
        body: JSON.stringify({ password: twoStepPasswordInput }),
      });
      setTwoStepPasswordInput('');
      notify('2FA verified! Session encrypted at rest with AES-256-GCM.', 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    } finally {
      setAuthBusy(false);
    }
  };

  const handleReconnect = async () => {
    setAuthBusy(true);
    try {
      await apiRequest('/api/v1/telegram/reconnect', { method: 'POST' });
      notify('Reconnected using persisted AES-256-GCM encrypted session', 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    } finally {
      setAuthBusy(false);
    }
  };

  const handleLogoutTelegram = async () => {
    setAuthBusy(true);
    try {
      await apiRequest('/api/v1/telegram/logout', { method: 'POST' });
      notify('Disconnected Telegram session and wiped encrypted session row', 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    } finally {
      setAuthBusy(false);
    }
  };

  const handleCleanupLogs = async () => {
    try {
      const res = await apiRequest<{ deleted_rows: number }>('/api/v1/maintenance/cleanup-logs', {
        method: 'POST',
      });
      notify(
        `Cleaned up ${res.deleted_rows} expired log entries (persistent statistics preserved)`,
        'success'
      );
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleClearDedup = async () => {
    try {
      const res = await apiRequest<{ cleared_rows: number }>('/api/v1/maintenance/clear-dedup', {
        method: 'POST',
      });
      notify(`Cleared ${res.cleared_rows} deduplication record(s)`, 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  return (
    <div className="space-y-6">
      {/* Telegram Personal-Account MTProto Authentication Card */}
      <div className="p-6 bg-slate-900 border border-slate-800 rounded-lg space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <h3 className="text-base font-semibold text-slate-100 flex items-center gap-2">
              <KeyRound className="w-4 h-4 text-sky-400" />
              <span>Telegram Personal-Account MTProto Authentication</span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Authenticates as a personal Telegram user via MTProto. Session material is encrypted with AES-256-GCM before storage and never exposed to the browser.
            </p>
          </div>
          <div className="text-right font-mono text-xs">
            <div>
              State:{' '}
              <span
                className={
                  telegram?.connection_state === 'CONNECTED'
                    ? 'text-emerald-400 font-semibold'
                    : 'text-amber-400 font-semibold'
                }
              >
                {telegram?.connection_state}
              </span>
            </div>
            <div className="text-[11px] text-slate-400">
              Key Fingerprint: {telegram?.session_key_fingerprint} · Persisted Session:{' '}
              {telegram?.has_encrypted_session ? 'YES' : 'NO'}
            </div>
          </div>
        </div>

        {telegram?.last_error && (
          <div className="p-3 bg-red-950/60 border border-red-800 rounded text-xs text-red-200 font-mono">
            Authentication Error: {telegram.last_error}
          </div>
        )}

        {/* Step-by-Step MTProto State Wizard */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Step 1: API ID & API Hash */}
          <form
            onSubmit={handleConfigureApi}
            className="p-4 bg-slate-950 border border-slate-800 rounded-md space-y-3"
          >
            <div className="text-xs font-semibold text-slate-200">
              Step 1. Configure Telegram API ID & API Hash (my.telegram.org)
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">API ID</label>
                <input
                  type="number"
                  required
                  value={apiIdInput}
                  onChange={(e) => setApiIdInput(e.target.value)}
                  className="w-full px-3 py-1.5 text-xs font-mono bg-slate-900 border border-slate-800 rounded text-slate-100"
                />
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">
                  API Hash (Encrypted on Save)
                </label>
                <input
                  type="password"
                  required
                  value={apiHashInput}
                  onChange={(e) => setApiHashInput(e.target.value)}
                  className="w-full px-3 py-1.5 text-xs font-mono bg-slate-900 border border-slate-800 rounded text-slate-100"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={authBusy}
              className="px-3.5 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-100 rounded"
            >
              Save API Credentials
            </button>
          </form>

          {/* Step 2 / 3 / 4: Phone -> Code -> 2FA Password */}
          <div className="p-4 bg-slate-950 border border-slate-800 rounded-md space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold text-slate-200">
                Step 2. Personal Account Login & 2FA Verification
              </div>
              <div className="flex items-center gap-2">
                {telegram?.has_encrypted_session && (
                  <button
                    type="button"
                    disabled={authBusy}
                    onClick={handleReconnect}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-sky-300 rounded"
                  >
                    <RefreshCw className="w-3 h-3" /> Reconnect Session
                  </button>
                )}
                {telegram?.connection_state === 'CONNECTED' && (
                  <button
                    type="button"
                    disabled={authBusy}
                    onClick={handleLogoutTelegram}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-red-950/60 hover:bg-red-900/60 text-red-300 border border-red-800 rounded"
                  >
                    <LogOut className="w-3 h-3" /> Logout Session
                  </button>
                )}
              </div>
            </div>

            {telegram?.connection_state === 'CONNECTED' ? (
              <div className="p-3 bg-emerald-950/40 border border-emerald-800/80 rounded text-xs space-y-1">
                <div className="text-emerald-300 font-semibold flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4" /> Authenticated as{' '}
                  {telegram.account_display_name} (@{telegram.account_username})
                </div>
                <div className="text-slate-300 font-mono text-[11px]">
                  Phone: {telegram.phone_number_masked} · User ID: {telegram.account_user_id} ·
                  Last Connected: {telegram.last_connected_at}
                </div>
              </div>
            ) : telegram?.connection_state === 'AWAITING_LOGIN_CODE' ? (
              <form onSubmit={handleVerifyCode} className="space-y-2">
                <label className="block text-[11px] text-amber-300">
                  Enter Telegram Login Code sent to {telegram.phone_number_masked} (e.g. 48291 in Test DC mode):
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    required
                    value={loginCodeInput}
                    onChange={(e) => setLoginCodeInput(e.target.value)}
                    placeholder="5-digit code"
                    className="flex-1 px-3 py-1.5 text-xs font-mono bg-slate-900 border border-slate-800 rounded text-slate-100"
                  />
                  <button
                    type="submit"
                    disabled={authBusy}
                    className="px-4 py-1.5 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded"
                  >
                    Verify Code
                  </button>
                </div>
              </form>
            ) : telegram?.connection_state === 'AWAITING_TWO_STEP_PASSWORD' ? (
              <form onSubmit={handleVerify2FA} className="space-y-2">
                <label className="block text-[11px] text-amber-300">
                  Two-Step Verification (2FA) Cloud Password Required:
                </label>
                <div className="flex gap-2">
                  <input
                    type="password"
                    required
                    value={twoStepPasswordInput}
                    onChange={(e) => setTwoStepPasswordInput(e.target.value)}
                    placeholder="Enter 2FA cloud password..."
                    className="flex-1 px-3 py-1.5 text-xs font-mono bg-slate-900 border border-slate-800 rounded text-slate-100"
                  />
                  <button
                    type="submit"
                    disabled={authBusy}
                    className="px-4 py-1.5 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded"
                  >
                    Verify 2FA Password
                  </button>
                </div>
              </form>
            ) : (
              <form onSubmit={handleRequestCode} className="space-y-2.5">
                <div className="flex gap-2">
                  <input
                    type="text"
                    required
                    value={phoneInput}
                    onChange={(e) => setPhoneInput(e.target.value)}
                    placeholder="+14155550199"
                    className="flex-1 px-3 py-1.5 text-xs font-mono bg-slate-900 border border-slate-800 rounded text-slate-100"
                  />
                  <button
                    type="submit"
                    disabled={authBusy}
                    className="px-4 py-1.5 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded whitespace-nowrap"
                  >
                    Request Login Code
                  </button>
                </div>
                <div className="flex flex-wrap items-center gap-4 text-[11px] text-slate-400">
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={useTestSandbox}
                      onChange={(e) => setUseTestSandbox(e.target.checked)}
                    />
                    <span>Use Safe Test Account DC Sandbox (no production SMS required)</span>
                  </label>
                  {useTestSandbox && (
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={require2faSandbox}
                        onChange={(e) => setRequire2faSandbox(e.target.checked)}
                      />
                      <span>Simulate 2FA Password Challenge</span>
                    </label>
                  )}
                </div>
              </form>
            )}
          </div>
        </div>
      </div>

      {/* Global Operational & Pacing Settings */}
      <form
        onSubmit={handleSaveSettings}
        className="p-6 bg-slate-900 border border-slate-800 rounded-lg space-y-5"
      >
        <h3 className="text-base font-semibold text-slate-100 border-b border-slate-800 pb-3">
          Global Forwarding, Pacing, Deduplication & Storage Settings
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-slate-200">
          <label className="flex items-center gap-2.5 p-3 bg-slate-950 border border-slate-800 rounded-md cursor-pointer">
            <input
              type="checkbox"
              checked={draft.forwarding_enabled}
              onChange={(e) => setDraft({ ...draft, forwarding_enabled: e.target.checked })}
            />
            <div>
              <div className="font-semibold">Global Forwarding Enabled</div>
              <div className="text-[11px] text-slate-400">Master switch for queue delivery worker</div>
            </div>
          </label>

          <label className="flex items-center gap-2.5 p-3 bg-slate-950 border border-slate-800 rounded-md cursor-pointer">
            <input
              type="checkbox"
              checked={draft.resume_worker_on_restart}
              onChange={(e) => setDraft({ ...draft, resume_worker_on_restart: e.target.checked })}
            />
            <div>
              <div className="font-semibold">Resume Worker on Container Restart</div>
              <div className="text-[11px] text-slate-400">
                Automatically resumes queue/backfill on VPS/Docker restart
              </div>
            </div>
          </label>

          <label className="flex items-center gap-2.5 p-3 bg-slate-950 border border-slate-800 rounded-md cursor-pointer">
            <input
              type="checkbox"
              checked={draft.auto_catchup_on_startup}
              onChange={(e) => setDraft({ ...draft, auto_catchup_on_startup: e.target.checked })}
            />
            <div>
              <div className="font-semibold">Auto Catch-Up on Startup</div>
              <div className="text-[11px] text-slate-400">
                Scan source_cursors for missed messages automatically on startup
              </div>
            </div>
          </label>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Persistent Deduplication Scope
            </label>
            <select
              value={draft.deduplication_scope}
              onChange={(e) =>
                setDraft({ ...draft, deduplication_scope: e.target.value as any })
              }
              className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            >
              <option value="PER_DESTINATION">Per-Destination (Default)</option>
              <option value="PER_RULE">Per-Rule</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Global Send Delay (ms)
            </label>
            <input
              type="number"
              min={0}
              max={60000}
              value={draft.global_send_delay_ms}
              onChange={(e) =>
                setDraft({ ...draft, global_send_delay_ms: Number(e.target.value) })
              }
              className="w-full px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Minimum Send Interval (ms)
            </label>
            <input
              type="number"
              min={0}
              max={60000}
              value={draft.min_send_interval_ms}
              onChange={(e) =>
                setDraft({ ...draft, min_send_interval_ms: Number(e.target.value) })
              }
              className="w-full px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Delivery Concurrency (1 – 10)
            </label>
            <input
              type="number"
              min={1}
              max={10}
              value={draft.delivery_concurrency}
              onChange={(e) =>
                setDraft({ ...draft, delivery_concurrency: Number(e.target.value) })
              }
              className="w-full px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Max Queue Depth (Backpressure Limit)
            </label>
            <input
              type="number"
              min={50}
              max={50000}
              value={draft.max_queue_depth}
              onChange={(e) => setDraft({ ...draft, max_queue_depth: Number(e.target.value) })}
              className="w-full px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Default Retry Count (0 – 10)
            </label>
            <input
              type="number"
              min={0}
              max={10}
              value={draft.default_retry_count}
              onChange={(e) =>
                setDraft({ ...draft, default_retry_count: Number(e.target.value) })
              }
              className="w-full px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Log Retention (Days)
            </label>
            <input
              type="number"
              min={1}
              max={365}
              value={draft.log_retention_days}
              onChange={(e) =>
                setDraft({ ...draft, log_retention_days: Number(e.target.value) })
              }
              className="w-full px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Interface Theme
            </label>
            <select
              value={draft.theme}
              onChange={(e) => setDraft({ ...draft, theme: e.target.value as any })}
              className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            >
              <option value="dark">Dark (Slate Default)</option>
              <option value="light">Light</option>
              <option value="system">System</option>
            </select>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4 pt-3 border-t border-slate-800">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCleanupLogs}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-md"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>Run Log Retention Cleanup</span>
            </button>
            <button
              type="button"
              onClick={handleClearDedup}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs bg-slate-800 hover:bg-slate-700 text-amber-300 rounded-md"
            >
              <span>Reset Deduplication Table</span>
            </button>
          </div>

          <button
            type="submit"
            className="px-5 py-2 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-md"
          >
            Save All Settings
          </button>
        </div>
      </form>
    </div>
  );
};

// ============================================================================
// 4. About, Architecture Feasibility, Test Runner & Rust Code Inspector
// ============================================================================
export const AboutAndDiagnosticsView: React.FC<{
  notify: (msg: string, type?: 'success' | 'error') => void;
}> = ({ notify }) => {
  const [testReport, setTestReport] = useState<any | null>(null);
  const [runningTests, setRunningTests] = useState(false);
  const [diagData, setDiagData] = useState<any | null>(null);
  const [selectedFile, setSelectedFile] = useState<string>('src-rust/classifier.rs');

  const handleRunTests = async () => {
    setRunningTests(true);
    try {
      const rep = await apiRequest('/api/v1/maintenance/run-tests', { method: 'POST' });
      setTestReport(rep);
      notify(`Executed ${rep.total} automated test suites (${rep.passed} passed)`, 'success');
    } catch (err: any) {
      notify(err.message, 'error');
    } finally {
      setRunningTests(false);
    }
  };

  useEffect(() => {
    handleRunTests();
    apiRequest('/api/v1/diagnostics/source-files')
      .then((res) => setDiagData(res))
      .catch(() => {});
  }, []);

  const currentFileObj = diagData?.files?.find((f: any) => f.path === selectedFile);

  return (
    <div className="space-y-6">
      {/* Automated Unit & Integration Test Suite Runner */}
      <div className="p-6 bg-slate-900 border border-slate-800 rounded-lg space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold text-slate-100 flex items-center gap-2">
              <ShieldCheck className="w-5 h-5 text-emerald-400" />
              <span>Automated Unit & Integration Verification Suite</span>
            </h3>
            <p className="text-xs text-slate-400">
              Verifies message-type filters, numeric sender filters, keywords, safe regex, file conditions, MOVIE/TV/COMBINED/SPLIT classification, caption transformations, midnight-crossing schedules, priority/exclusive-stop, deduplication, and AES-256-GCM encryption.
            </p>
          </div>
          <button
            type="button"
            disabled={runningTests}
            onClick={handleRunTests}
            className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-md"
          >
            <Play className="w-3.5 h-3.5" />
            <span>{runningTests ? 'Running Suite...' : 'Re-Run Automated Tests'}</span>
          </button>
        </div>

        {testReport && (
          <div className="border border-slate-800 rounded-md overflow-hidden">
            <div className="px-4 py-2.5 bg-slate-950 border-b border-slate-800 flex items-center justify-between text-xs font-mono">
              <span className="text-emerald-400 font-semibold">
                PASSED: {testReport.passed} / {testReport.total} SUITES (Failed: {testReport.failed})
              </span>
              <span className="text-slate-400">
                Execution Time: {testReport.duration_ms}ms · Process RSS:{' '}
                {diagData?.memory?.rss_mb ?? '—'} MB
              </span>
            </div>
            <div className="divide-y divide-slate-800 bg-slate-950/50 text-xs font-mono">
              {testReport.results.map((r: any, idx: number) => (
                <div
                  key={idx}
                  className="px-4 py-2.5 flex flex-wrap items-center justify-between gap-2"
                >
                  <div>
                    <span className={r.passed ? 'text-emerald-400' : 'text-red-400'}>
                      [{r.passed ? 'PASS' : 'FAIL'}]
                    </span>{' '}
                    <span className="text-slate-400">{r.suite} ::</span>{' '}
                    <span className="text-slate-100 font-sans font-medium">{r.name}</span>
                    <div className="text-[11px] text-slate-400 mt-0.5">{r.detail}</div>
                  </div>
                  <span className="text-slate-500">{r.duration_ms}ms</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Rust Modular Monolith & Docker Deployment File Inspector */}
      <div className="p-6 bg-slate-900 border border-slate-800 rounded-lg space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold text-slate-100 flex items-center gap-2">
              <FileCode2 className="w-5 h-5 text-sky-400" />
              <span>Repository Deliverable Inspector (Rust Backend, Migrations, Dockerfile & Docs)</span>
            </h3>
            <p className="text-xs text-slate-400">
              Inspect the complete Rust modular monolith source files (`src-rust/*`), SQL migrations, `Dockerfile`, `compose.yaml`, and architecture documentation directly in the workspace.
            </p>
          </div>
          <select
            value={selectedFile}
            onChange={(e) => setSelectedFile(e.target.value)}
            className="px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
          >
            {(diagData?.files || []).map((f: any) => (
              <option key={f.path} value={f.path}>
                {f.path} ({f.size_bytes} bytes)
              </option>
            ))}
          </select>
        </div>

        {currentFileObj && (
          <pre className="p-4 bg-slate-950 border border-slate-800 rounded-md text-xs font-mono text-slate-200 overflow-x-auto max-h-[480px] overflow-y-auto">
            {currentFileObj.content}
          </pre>
        )}
      </div>
    </div>
  );
};
