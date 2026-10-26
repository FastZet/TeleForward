import React, { useState } from 'react';
import { apiRequest } from '../api';
import {
  RefreshCw,
  Plus,
  Play,
  Pause,
  Square,
  RotateCcw,
  Eye,
  XCircle,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react';

// ============================================================================
// 1. Chats & Destination Management View
// ============================================================================
export const ChatsView: React.FC<{
  chats: any[];
  onRefresh: () => void;
  notify: (msg: string, type?: 'success' | 'error') => void;
}> = ({ chats, onRefresh, notify }) => {
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('ALL');
  const [showAddModal, setShowAddModal] = useState(false);
  const [newPeerId, setNewPeerId] = useState('-1002000000555');
  const [newTitle, setNewTitle] = useState('');
  const [newType, setNewType] = useState('CHANNEL');
  const [newUsername, setNewUsername] = useState('');
  const [newCanSend, setNewCanSend] = useState(true);
  const [inspectedChatId, setInspectedChatId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<any[]>([]);

  const filtered = chats.filter((c) => {
    if (typeFilter !== 'ALL' && c.chat_type !== typeFilter) return false;
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      String(c.title).toLowerCase().includes(q) ||
      String(c.username || '').toLowerCase().includes(q) ||
      String(c.peer_id).toLowerCase().includes(q)
    );
  });

  const handleRefreshDialogs = async () => {
    try {
      await apiRequest('/api/v1/chats/refresh', { method: 'POST' });
      notify('Refreshed Telegram dialog list and permission flags', 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleAddChat = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiRequest('/api/v1/chats', {
        method: 'POST',
        body: JSON.stringify({
          peer_id: newPeerId,
          title: newTitle,
          chat_type: newType,
          username: newUsername || null,
          can_read: true,
          can_send: newCanSend,
          can_edit: newCanSend,
          can_delete: newCanSend,
          is_accessible: true,
          permission_error: newCanSend
            ? null
            : 'CHAT_WRITE_FORBIDDEN: Read-only channel access',
        }),
      });
      notify(`Registered chat ${newTitle} (${newPeerId})`, 'success');
      setShowAddModal(false);
      setNewTitle('');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleInspectMessages = async (peerId: string) => {
    try {
      const msgs = await apiRequest<any[]>(`/api/v1/chats/${encodeURIComponent(peerId)}/messages`);
      setInspectedChatId(peerId);
      setChatMessages(msgs);
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by title, @username, or numeric peer ID..."
            className="w-72 px-3.5 py-2 text-xs bg-slate-900 border border-slate-800 rounded-md text-slate-100"
          />
          <div className="flex items-center gap-1 p-1 bg-slate-900 border border-slate-800 rounded-md">
            {['ALL', 'CHANNEL', 'SUPERGROUP', 'GROUP', 'PRIVATE'].map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTypeFilter(t)}
                className={`px-2.5 py-1 text-xs font-medium rounded transition-colors whitespace-nowrap ${
                  typeFilter === t
                    ? 'bg-sky-600 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRefreshDialogs}
            className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-800 rounded-md"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh Dialogs</span>
          </button>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-md"
          >
            <Plus className="w-4 h-4" />
            <span>Register Peer ID</span>
          </button>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-950/60 text-[11px] font-medium text-slate-400">
              <th className="py-3 px-4">Peer Identifier</th>
              <th className="py-3 px-4">Title & Username</th>
              <th className="py-3 px-4">Type</th>
              <th className="py-3 px-4">Permissions</th>
              <th className="py-3 px-4">Latest Msg ID</th>
              <th className="py-3 px-4 text-right">History</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 text-xs">
            {filtered.map((c) => (
              <tr key={c.peer_id} className="hover:bg-slate-800/40">
                <td className="py-3 px-4 font-mono text-slate-200">{c.peer_id}</td>
                <td className="py-3 px-4">
                  <div className="font-semibold text-slate-100">{c.title}</div>
                  <div className="text-[11px] text-slate-400 font-mono">
                    {c.username ? `@${c.username}` : 'Private / No public username'}
                  </div>
                  {c.permission_error && (
                    <div className="text-[11px] text-amber-400 font-mono mt-1">
                      {c.permission_error}
                    </div>
                  )}
                </td>
                <td className="py-3 px-4 font-mono text-slate-300">{c.chat_type}</td>
                <td className="py-3 px-4 font-mono text-[11px]">
                  <span className={c.can_read ? 'text-emerald-400' : 'text-red-400'}>
                    Read:{c.can_read ? 'Yes' : 'No'}
                  </span>
                  {' · '}
                  <span className={c.can_send ? 'text-emerald-400' : 'text-amber-400'}>
                    Send:{c.can_send ? 'Yes' : 'No'}
                  </span>
                  {' · '}
                  <span className="text-slate-400">
                    Edit:{c.can_edit ? 'Yes' : 'No'} / Del:{c.can_delete ? 'Yes' : 'No'}
                  </span>
                </td>
                <td className="py-3 px-4 font-mono text-slate-300">
                  #{c.last_message_id ?? '—'}
                </td>
                <td className="py-3 px-4 text-right">
                  <button
                    type="button"
                    onClick={() => handleInspectMessages(c.peer_id)}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 rounded"
                  >
                    <Eye className="w-3.5 h-3.5" />
                    <span>Inspect History</span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Historical Messages Inspector */}
      {inspectedChatId && (
        <div className="p-5 bg-slate-900 border border-slate-800 rounded-lg space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-100">
              Accessible Message History for Peer <span className="font-mono">{inspectedChatId}</span> ({chatMessages.length} messages)
            </h3>
            <button
              type="button"
              onClick={() => setInspectedChatId(null)}
              className="text-xs text-slate-400 hover:text-slate-200"
            >
              Close Inspector
            </button>
          </div>
          <div className="border border-slate-800 rounded-md overflow-hidden max-h-72 overflow-y-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-950 text-slate-400 border-b border-slate-800">
                  <th className="py-2 px-3">Msg ID</th>
                  <th className="py-2 px-3">Media Type</th>
                  <th className="py-2 px-3">Filename</th>
                  <th className="py-2 px-3">Size</th>
                  <th className="py-2 px-3">Caption / Text</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-950/40">
                {chatMessages.map((m) => (
                  <tr key={m.message_id}>
                    <td className="py-2 px-3 font-mono text-sky-400">#{m.message_id}</td>
                    <td className="py-2 px-3 font-mono text-slate-300">{m.media_type}</td>
                    <td className="py-2 px-3 font-mono text-slate-200">{m.filename || '—'}</td>
                    <td className="py-2 px-3 font-mono text-slate-400">
                      {m.file_size_bytes
                        ? `${(m.file_size_bytes / (1024 * 1024)).toFixed(0)} MB`
                        : '—'}
                    </td>
                    <td className="py-2 px-3 text-slate-300 max-w-md truncate">
                      {m.caption || m.text || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Register Peer Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
          <form
            onSubmit={handleAddChat}
            className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-lg p-6 space-y-4"
          >
            <h3 className="text-base font-semibold text-slate-100">Register Telegram Chat Peer</h3>
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Stable Telegram Numeric Peer ID *
              </label>
              <input
                type="text"
                required
                value={newPeerId}
                onChange={(e) => setNewPeerId(e.target.value)}
                className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Chat Title *</label>
              <input
                type="text"
                required
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="e.g. Vault Sci-Fi Archive"
                className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Chat Type</label>
                <select
                  value={newType}
                  onChange={(e) => setNewType(e.target.value)}
                  className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                >
                  <option value="CHANNEL">CHANNEL</option>
                  <option value="SUPERGROUP">SUPERGROUP</option>
                  <option value="GROUP">GROUP</option>
                  <option value="PRIVATE">PRIVATE</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Username (optional)
                </label>
                <input
                  type="text"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  placeholder="vault_scifi"
                  className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                />
              </div>
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-200">
              <input
                type="checkbox"
                checked={newCanSend}
                onChange={(e) => setNewCanSend(e.target.checked)}
              />
              <span>Account has Send / Write Permission in this chat</span>
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="px-4 py-2 text-xs bg-slate-800 text-slate-300 rounded-md"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-2 text-xs bg-sky-600 text-white rounded-md font-medium"
              >
                Save Chat Peer
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};

// ============================================================================
// 2. Historical Backfill View
// ============================================================================
export const BackfillView: React.FC<{
  chats: any[];
  backfillJobs: any[];
  onRefresh: () => void;
  notify: (msg: string, type?: 'success' | 'error') => void;
}> = ({ chats, backfillJobs, onRefresh, notify }) => {
  const [name, setName] = useState('Historical Scan — Scene Raw Feed');
  const [sourcePeerId, setSourcePeerId] = useState('-1001000000001');
  const [mode, setMode] = useState<'ALL_ACCESSIBLE' | 'LAST_N' | 'UNPROCESSED_ONLY' | 'MESSAGE_ID_RANGE'>(
    'ALL_ACCESSIBLE'
  );
  const [lastN, setLastN] = useState(100);
  const [startId, setStartId] = useState<string>('1001');
  const [endId, setEndId] = useState<string>('1012');
  const [direction, setDirection] = useState<'OLDEST_FIRST' | 'NEWEST_FIRST'>('OLDEST_FIRST');
  const [batchSize, setBatchSize] = useState(4);
  const [rateLimit, setRateLimit] = useState(30);
  const [preview, setPreview] = useState<any | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);

  const handlePreview = async () => {
    setLoadingPreview(true);
    try {
      const res = await apiRequest('/api/v1/backfill/preview', {
        method: 'POST',
        body: JSON.stringify({
          source_peer_id: sourcePeerId,
          mode,
          last_n_count: lastN,
          start_message_id: startId ? Number(startId) : null,
          end_message_id: endId ? Number(endId) : null,
          direction,
        }),
      });
      setPreview(res);
    } catch (err: any) {
      notify(err.message, 'error');
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleStartBackfill = async () => {
    try {
      await apiRequest('/api/v1/backfill', {
        method: 'POST',
        body: JSON.stringify({
          name,
          source_peer_id: sourcePeerId,
          mode,
          last_n_count: mode === 'LAST_N' ? lastN : null,
          start_message_id: mode === 'MESSAGE_ID_RANGE' && startId ? Number(startId) : null,
          end_message_id: mode === 'MESSAGE_ID_RANGE' && endId ? Number(endId) : null,
          direction,
          batch_size: batchSize,
          rate_limit_per_min: rateLimit,
        }),
      });
      notify('Started resumable historical backfill job', 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleJobAction = async (id: string, action: 'pause' | 'resume' | 'stop' | 'restart') => {
    try {
      await apiRequest(`/api/v1/backfill/${id}/action`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      });
      notify(`Backfill job ${action}d`, 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  return (
    <div className="space-y-6">
      {/* Configuration & Dry-Run Preview Card */}
      <div className="p-6 bg-slate-900 border border-slate-800 rounded-lg space-y-5">
        <div>
          <h3 className="text-base font-semibold text-slate-100">
            Configure Resumable Historical Backfill Job
          </h3>
          <p className="text-xs text-slate-400">
            Fetches bounded pages and persists the current message cursor in SQLite after every batch so container restarts resume seamlessly.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Job Label</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Source Chat</label>
            <select
              value={sourcePeerId}
              onChange={(e) => setSourcePeerId(e.target.value)}
              className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            >
              {chats.map((c) => (
                <option key={c.peer_id} value={c.peer_id}>
                  {c.title} ({c.peer_id})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Backfill Mode</label>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as any)}
              className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            >
              <option value="ALL_ACCESSIBLE">1. All Accessible Messages</option>
              <option value="LAST_N">2. Last N Messages (50 to 5,000)</option>
              <option value="UNPROCESSED_ONLY">3. Messages Not Previously Processed</option>
              <option value="MESSAGE_ID_RANGE">4. Selected Message-ID Range</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {mode === 'LAST_N' && (
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Last N Count (50 – 5,000)
              </label>
              <input
                type="number"
                min={50}
                max={5000}
                value={lastN}
                onChange={(e) => setLastN(Number(e.target.value))}
                className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
              />
            </div>
          )}

          {mode === 'MESSAGE_ID_RANGE' && (
            <>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Start Message ID (blank = oldest)
                </label>
                <input
                  type="number"
                  value={startId}
                  onChange={(e) => setStartId(e.target.value)}
                  className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  End Message ID (blank = latest)
                </label>
                <input
                  type="number"
                  value={endId}
                  onChange={(e) => setEndId(e.target.value)}
                  className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                />
              </div>
            </>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Scan Direction
            </label>
            <select
              value={direction}
              onChange={(e) => setDirection(e.target.value as any)}
              className="w-full px-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            >
              <option value="OLDEST_FIRST">Oldest-First (Chronological)</option>
              <option value="NEWEST_FIRST">Newest-First (Reverse)</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Bounded Page Batch Size
            </label>
            <input
              type="number"
              min={1}
              max={200}
              value={batchSize}
              onChange={(e) => setBatchSize(Number(e.target.value))}
              className="w-full px-3 py-2 text-sm font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-100"
            />
          </div>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <button
            type="button"
            disabled={loadingPreview}
            onClick={handlePreview}
            className="px-4 py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-100 rounded-md"
          >
            {loadingPreview ? 'Scanning Dry-Run...' : '1. Dry-Run Preview (Does Not Send)'}
          </button>
          <button
            type="button"
            onClick={handleStartBackfill}
            className="px-4 py-2 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-md"
          >
            2. Start Resumable Backfill Job
          </button>
        </div>

        {preview && (
          <div className="p-4 bg-slate-950 border border-slate-800 rounded-md space-y-3 text-xs">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
              <span className="font-semibold text-slate-200">
                Dry-Run Preview Report · Range: <span className="font-mono">{preview.selected_range}</span>
              </span>
              <span className="font-mono text-slate-400">
                Estimated Duration: ~{preview.estimated_duration_seconds}s
              </span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4 font-mono">
              <div>
                <div className="text-[11px] text-slate-400">Examined</div>
                <div className="text-base font-semibold text-slate-100">{preview.examined_count}</div>
              </div>
              <div>
                <div className="text-[11px] text-slate-400">Matching Rules</div>
                <div className="text-base font-semibold text-emerald-400">{preview.matching_count}</div>
              </div>
              <div>
                <div className="text-[11px] text-slate-400">Expected Skips</div>
                <div className="text-base font-semibold text-slate-300">{preview.expected_skipped_count}</div>
              </div>
              <div>
                <div className="text-[11px] text-slate-400">Delivery Modes</div>
                <div className="text-sm text-sky-400">
                  {preview.expected_delivery_modes.join(', ') || 'NONE'}
                </div>
              </div>
              <div>
                <div className="text-[11px] text-slate-400">Target Destinations</div>
                <div className="text-xs text-slate-300">
                  {Object.entries(preview.destination_breakdown)
                    .map(([peer, cnt]) => `${peer}: ${cnt}`)
                    .join(' · ') || 'None'}
                </div>
              </div>
            </div>
            {preview.configuration_warnings?.length > 0 && (
              <div className="text-amber-400 font-mono text-[11px]">
                Warnings: {preview.configuration_warnings.join('; ')}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Persisted Backfill Jobs List */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-100">
            Persisted Historical Backfill Jobs ({backfillJobs.length})
          </h3>
        </div>
        <div className="divide-y divide-slate-800">
          {backfillJobs.length === 0 ? (
            <div className="p-8 text-center text-xs text-slate-400">
              No backfill jobs created yet. Run a Dry-Run Preview or start a job above.
            </div>
          ) : (
            backfillJobs.map((job) => {
              const pct =
                job.total_estimated > 0
                  ? Math.min(100, Math.round((job.examined_count / job.total_estimated) * 100))
                  : 100;
              return (
                <div key={job.id} className="p-4 space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="text-sm font-semibold text-slate-100">{job.name}</div>
                      <div className="text-xs text-slate-400 font-mono">
                        {job.id} · Source {job.source_peer_id} · Mode {job.mode} · Direction{' '}
                        {job.direction}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-sky-400 mr-2">
                        Status: {job.status} · Cursor: #{job.current_cursor_message_id ?? 'Start'}
                      </span>
                      {job.status === 'RUNNING' && (
                        <button
                          type="button"
                          onClick={() => handleJobAction(job.id, 'pause')}
                          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-amber-300 rounded"
                        >
                          <Pause className="w-3.5 h-3.5" /> Pause
                        </button>
                      )}
                      {job.status === 'PAUSED' && (
                        <button
                          type="button"
                          onClick={() => handleJobAction(job.id, 'resume')}
                          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-sky-600 hover:bg-sky-500 text-white rounded"
                        >
                          <Play className="w-3.5 h-3.5" /> Resume
                        </button>
                      )}
                      {['RUNNING', 'PAUSED'].includes(job.status) && (
                        <button
                          type="button"
                          onClick={() => handleJobAction(job.id, 'stop')}
                          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-red-300 rounded"
                        >
                          <Square className="w-3.5 h-3.5" /> Stop
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleJobAction(job.id, 'restart')}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 rounded"
                      >
                        <RotateCcw className="w-3.5 h-3.5" /> Restart from Beginning
                      </button>
                    </div>
                  </div>

                  <div className="w-full h-2 bg-slate-950 rounded overflow-hidden">
                    <div
                      className="h-full bg-sky-500 transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>

                  <div className="flex flex-wrap items-center gap-6 text-xs font-mono text-slate-300">
                    <span>
                      Examined: {job.examined_count} / {job.total_estimated} ({pct}%)
                    </span>
                    <span className="text-emerald-400">Matched: {job.matched_count}</span>
                    <span className="text-sky-400">Delivered: {job.forwarded_count}</span>
                    <span className="text-slate-400">Skipped: {job.skipped_count}</span>
                    <span className="text-red-400">Failed: {job.failed_count}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

// ============================================================================
// 3. Durable Delivery Queue View
// ============================================================================
export const DeliveryQueueView: React.FC<{
  jobs: any[];
  statusFilter: string;
  onStatusFilterChange: (s: string) => void;
  onRefresh: () => void;
  notify: (msg: string, type?: 'success' | 'error') => void;
}> = ({ jobs, statusFilter, onStatusFilterChange, onRefresh, notify }) => {
  const [selectedJob, setSelectedJob] = useState<any | null>(null);

  const handleProcessNow = async () => {
    try {
      const res = await apiRequest<{ completed: number; failed: number }>(
        '/api/v1/queue/process-now',
        { method: 'POST' }
      );
      notify(
        `Processed queue tick (${res.completed} completed, ${res.failed} failed)`,
        'success'
      );
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleCancelJob = async (id: string) => {
    try {
      await apiRequest(`/api/v1/queue/${id}/cancel`, { method: 'POST' });
      notify(`Cancelled job ${id}`, 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-1 p-1 bg-slate-900 border border-slate-800 rounded-md overflow-x-auto">
          {[
            'ALL',
            'PENDING',
            'PROCESSING',
            'RETRY_SCHEDULED',
            'COMPLETED',
            'FAILED',
            'CANCELLED',
          ].map((st) => (
            <button
              key={st}
              type="button"
              onClick={() => onStatusFilterChange(st)}
              className={`px-2.5 py-1 text-xs font-medium rounded transition-colors whitespace-nowrap ${
                statusFilter === st
                  ? 'bg-sky-600 text-white'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {st}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={handleProcessNow}
          className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-md"
        >
          <Play className="w-3.5 h-3.5" />
          <span>Process Eligible Queue Jobs Now</span>
        </button>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/60 text-[11px] font-medium text-slate-400">
                <th className="py-3 px-4">Job ID & Origin</th>
                <th className="py-3 px-4">Source Msg → Destination</th>
                <th className="py-3 px-4">Rule & Mode</th>
                <th className="py-3 px-4">Status & Attempts</th>
                <th className="py-3 px-4">Next Eligible / Completed</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-xs">
              {jobs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-slate-400">
                    No delivery jobs in state {statusFilter}.
                  </td>
                </tr>
              ) : (
                jobs.map((j) => (
                  <tr key={j.id} className="hover:bg-slate-800/40">
                    <td className="py-3 px-4 font-mono">
                      <div className="text-slate-200">{j.id}</div>
                      <div className="text-[11px] text-slate-400">
                        {j.origin_type} · {j.detected_categories_csv || 'GENERAL'}
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <div className="text-slate-200 font-medium">
                        {j.source_title || j.source_peer_id} #{j.source_message_id}
                      </div>
                      <div className="text-[11px] text-slate-400 font-mono">
                        → {j.destination_title || j.destination_peer_id}{' '}
                        {j.destination_message_id ? `(msg #${j.destination_message_id})` : ''}
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <div className="text-slate-200">{j.rule_name || j.rule_id}</div>
                      <div className="text-[11px] font-mono text-slate-400">{j.delivery_mode}</div>
                    </td>
                    <td className="py-3 px-4 font-mono">
                      <div
                        className={
                          j.status === 'COMPLETED'
                            ? 'text-emerald-400'
                            : j.status === 'FAILED'
                              ? 'text-red-400'
                              : j.status === 'RETRY_SCHEDULED'
                                ? 'text-amber-400'
                                : 'text-sky-400'
                        }
                      >
                        {j.status} ({j.attempt_count}/{j.max_retries})
                      </div>
                      {j.last_error && (
                        <div className="text-[11px] text-red-300 max-w-xs truncate">
                          {j.last_error}
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-4 font-mono text-[11px] text-slate-400">
                      {j.completed_at || j.next_eligible_at}
                    </td>
                    <td className="py-3 px-4 text-right whitespace-nowrap">
                      <div className="inline-flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setSelectedJob(j)}
                          className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 rounded"
                        >
                          Inspect
                        </button>
                        {['PENDING', 'RETRY_SCHEDULED'].includes(j.status) && (
                          <button
                            type="button"
                            onClick={() => handleCancelJob(j.id)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-red-950/60 hover:bg-red-900/60 text-red-300 border border-red-800 rounded"
                          >
                            <XCircle className="w-3.5 h-3.5" /> Cancel
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selectedJob && (
        <div className="p-5 bg-slate-900 border border-slate-800 rounded-lg space-y-3 text-xs">
          <div className="flex items-center justify-between border-b border-slate-800 pb-2">
            <div className="font-semibold text-slate-100 font-mono">
              Job Details: {selectedJob.id} · Idempotency Key: {selectedJob.idempotency_key}
            </div>
            <button
              type="button"
              onClick={() => setSelectedJob(null)}
              className="text-slate-400 hover:text-slate-200"
            >
              Close
            </button>
          </div>
          <div>
            <div className="text-slate-400 mb-1">Transformed Caption Payload:</div>
            <pre className="p-3 bg-slate-950 border border-slate-800 rounded font-mono text-slate-200 whitespace-pre-wrap">
              {selectedJob.transformed_caption || '(Native Forward / No Caption)'}
            </pre>
          </div>
          <div>
            <div className="text-slate-400 mb-1">
              Delivery Attempts ({selectedJob.attempts?.length || 0}):
            </div>
            <div className="space-y-1 font-mono">
              {(selectedJob.attempts || []).map((a: any) => (
                <div
                  key={a.id}
                  className="p-2 bg-slate-950 border border-slate-800 rounded flex items-center justify-between"
                >
                  <span>
                    Attempt #{a.attempt_number} · {a.status} · {a.duration_ms}ms
                  </span>
                  <span className="text-slate-400">
                    {a.error_message || 'Delivered OK'} ({a.attempted_at})
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
