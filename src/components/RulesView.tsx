import React, { useState } from 'react';
import { ForwardingRule } from '../server/types';
import { apiRequest } from '../api';
import { RuleEditorModal } from './RuleEditorModal';
import {
  Plus,
  Copy,
  Trash2,
  Edit3,
  Download,
  Upload,
  Play,
  ArrowUp,
  ArrowDown,
  CheckCircle2,
  AlertTriangle,
  BookOpen,
} from 'lucide-react';

interface RulesViewProps {
  rules: ForwardingRule[];
  chats: any[];
  recipes: any[];
  onRefresh: () => void;
  notify: (msg: string, type?: 'success' | 'error') => void;
}

export const RulesView: React.FC<RulesViewProps> = ({
  rules,
  chats,
  recipes,
  onRefresh,
  notify,
}) => {
  const [search, setSearch] = useState('');
  const [editingRule, setEditingRule] = useState<ForwardingRule | null | undefined>(undefined);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Import & Recipes Modal state
  const [showImportModal, setShowImportModal] = useState(false);
  const [importJsonText, setImportJsonText] = useState('');
  const [importPreview, setImportPreview] = useState<any | null>(null);
  const [conflictStrategy, setConflictStrategy] = useState<'REMAP_CONFLICTS' | 'REPLACE_EXISTING'>(
    'REMAP_CONFLICTS'
  );
  const [peerRemap, setPeerRemap] = useState<Record<string, string>>({});

  // Chain Rule Tester state
  const [showChainTester, setShowChainTester] = useState(false);
  const [testFilename, setTestFilename] = useState(
    'Shogun.2024.S01E01-E10.COMPLETE.2160p.WEB-DL.HEVC.mkv.001'
  );
  const [testCaption, setTestCaption] = useState(
    '📦 [TG] Shogun.2024.S01E01-E10.COMPLETE.2160p.WEB-DL.HEVC.mkv.001 @scene_raw_ingest https://t.me/promo #shogun'
  );
  const [testSizeMb, setTestSizeMb] = useState(18500);
  const [testSourcePeer, setTestSourcePeer] = useState('-1001000000001');
  const [chainResult, setChainResult] = useState<any | null>(null);

  const chatTitleMap = new Map(chats.map((c) => [String(c.peer_id), c.title]));

  const filteredRules = rules.filter((r) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      r.name.toLowerCase().includes(q) ||
      r.id.toLowerCase().includes(q) ||
      r.description.toLowerCase().includes(q) ||
      r.source_peer_id.toLowerCase().includes(q)
    );
  });

  const handleToggleRule = async (r: ForwardingRule) => {
    try {
      await apiRequest(`/api/v1/rules/${r.id}/toggle`, {
        method: 'POST',
        body: JSON.stringify({ enabled: !r.enabled }),
      });
      notify(`${!r.enabled ? 'Enabled' : 'Disabled'} rule "${r.name}"`, 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleDuplicateRule = async (r: ForwardingRule) => {
    try {
      await apiRequest(`/api/v1/rules/${r.id}/duplicate`, { method: 'POST' });
      notify(`Duplicated rule "${r.name}"`, 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleDeleteRule = async (id: string) => {
    try {
      await apiRequest(`/api/v1/rules/${id}`, { method: 'DELETE' });
      setConfirmDeleteId(null);
      notify('Rule deleted', 'success');
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleNudgePriority = async (r: ForwardingRule, delta: number) => {
    const nextPrio = Math.max(0, Math.min(100, r.priority + delta));
    try {
      await apiRequest('/api/v1/rules/reorder', {
        method: 'POST',
        body: JSON.stringify({
          items: [{ id: r.id, priority: nextPrio, secondary_order: r.secondary_order }],
        }),
      });
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleExportJson = async () => {
    try {
      const data = await apiRequest('/api/v1/rules/export');
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `teleroute-rules-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      notify('Exported rules JSON (credentials and session material excluded)', 'success');
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handlePreviewImport = async (rawJson: string) => {
    try {
      const parsed = JSON.parse(rawJson);
      const preview = await apiRequest('/api/v1/rules/import/preview', {
        method: 'POST',
        body: JSON.stringify(parsed),
      });
      setImportPreview(preview);
    } catch (err: any) {
      notify(`Import validation error: ${err.message}`, 'error');
    }
  };

  const handleApplyImport = async () => {
    try {
      const parsed = JSON.parse(importJsonText);
      const res = await apiRequest<{ imported_count: number }>('/api/v1/rules/import/apply', {
        method: 'POST',
        body: JSON.stringify({
          data: parsed,
          conflict_strategy: conflictStrategy,
          peer_remap: peerRemap,
        }),
      });
      notify(`Imported ${res.imported_count} rule(s) into SQLite`, 'success');
      setShowImportModal(false);
      setImportPreview(null);
      onRefresh();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleRunChainTest = async () => {
    try {
      const res = await apiRequest('/api/v1/rules/test', {
        method: 'POST',
        body: JSON.stringify({
          evaluate_all_chain: true,
          message: {
            message_id: 8888,
            source_peer_id: testSourcePeer,
            chat_type: 'CHANNEL',
            media_type: 'DOCUMENT',
            is_album: false,
            is_first_in_album: true,
            text: null,
            caption: testCaption,
            filename: testFilename || null,
            file_size_bytes: testSizeMb ? Math.round(testSizeMb * 1024 * 1024) : null,
            sender_user_id: null,
            is_sender_admin: true,
            is_anonymous_admin: true,
            is_sender_verified: false,
            timestamp_utc: new Date().toISOString(),
          },
        }),
      });
      setChainResult(res);
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  return (
    <div className="space-y-6">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3 flex-1 min-w-[260px]">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter rules by name, ID, source peer, or description..."
            className="w-full max-w-md px-3.5 py-2 text-xs bg-slate-900 border border-slate-800 rounded-md text-slate-100"
          />
          <span className="text-xs text-slate-400 font-mono whitespace-nowrap">
            {filteredRules.length} of {rules.length} rules
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowChainTester(!showChainTester)}
            className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-800 rounded-md whitespace-nowrap"
          >
            <Play className="w-3.5 h-3.5 text-sky-400" />
            <span>Test Rule Chain</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setImportJsonText('');
              setImportPreview(null);
              setShowImportModal(true);
            }}
            className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-800 rounded-md whitespace-nowrap"
          >
            <Upload className="w-3.5 h-3.5" />
            <span>Import / Recipes</span>
          </button>
          <button
            type="button"
            onClick={handleExportJson}
            className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-800 rounded-md whitespace-nowrap"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export JSON</span>
          </button>
          <button
            type="button"
            onClick={() => setEditingRule(null)}
            className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-md whitespace-nowrap"
          >
            <Plus className="w-4 h-4" />
            <span>New Rule</span>
          </button>
        </div>
      </div>

      {/* Interactive Priority Chain Tester Drawer */}
      {showChainTester && (
        <div className="p-5 bg-slate-900 border border-slate-800 rounded-lg space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-slate-100">
                Priority Chain & Exclusive-Stop Dry-Run Simulator
              </h3>
              <p className="text-xs text-slate-400">
                Evaluates all enabled rules for the selected source chat in descending priority order without sending messages.
              </p>
            </div>
            <button
              type="button"
              onClick={handleRunChainTest}
              className="px-4 py-2 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-md"
            >
              Evaluate Priority Chain
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div>
              <label className="block text-[11px] text-slate-400 mb-1">Source Chat</label>
              <select
                value={testSourcePeer}
                onChange={(e) => setTestSourcePeer(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded text-slate-200"
              >
                {chats.map((c) => (
                  <option key={c.peer_id} value={c.peer_id}>
                    {c.title} ({c.peer_id})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[11px] text-slate-400 mb-1">Sample Filename</label>
              <input
                type="text"
                value={testFilename}
                onChange={(e) => setTestFilename(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs font-mono bg-slate-950 border border-slate-800 rounded text-slate-200"
              />
            </div>
            <div>
              <label className="block text-[11px] text-slate-400 mb-1">File Size (MB)</label>
              <input
                type="number"
                value={testSizeMb}
                onChange={(e) => setTestSizeMb(Number(e.target.value))}
                className="w-full px-2.5 py-1.5 text-xs font-mono bg-slate-950 border border-slate-800 rounded text-slate-200"
              />
            </div>
            <div>
              <label className="block text-[11px] text-slate-400 mb-1">Sample Caption</label>
              <input
                type="text"
                value={testCaption}
                onChange={(e) => setTestCaption(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs font-mono bg-slate-950 border border-slate-800 rounded text-slate-200"
              />
            </div>
          </div>

          {chainResult && (
            <div className="border border-slate-800 rounded-md overflow-hidden">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="bg-slate-950 text-slate-400 border-b border-slate-800">
                    <th className="py-2 px-3">Prio</th>
                    <th className="py-2 px-3">Rule</th>
                    <th className="py-2 px-3">Evaluation Outcome</th>
                    <th className="py-2 px-3">Detected Categories</th>
                    <th className="py-2 px-3">Target Destinations</th>
                    <th className="py-2 px-3">Caption Preview / Fail Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 bg-slate-950/50">
                  {chainResult.reports.map((rep: any) => (
                    <tr key={rep.rule_id}>
                      <td className="py-2 px-3 font-mono text-slate-300">{rep.priority}</td>
                      <td className="py-2 px-3 font-medium text-slate-200">{rep.rule_name}</td>
                      <td className="py-2 px-3 font-mono">
                        {rep.skipped_due_to_earlier_exclusive_stop ? (
                          <span className="text-amber-400">HALTED BY EXCLUSIVE-STOP</span>
                        ) : rep.matched ? (
                          <span className="text-emerald-400">
                            MATCHED {rep.exclusive_stop_triggered ? '· STOPS LOWER' : ''}
                          </span>
                        ) : (
                          <span className="text-slate-500">NO MATCH (Continues)</span>
                        )}
                      </td>
                      <td className="py-2 px-3 font-mono text-slate-300">
                        {rep.assigned_categories.join(' · ') || 'NONE'}
                      </td>
                      <td className="py-2 px-3 font-mono text-slate-300">
                        {rep.target_destinations.join(', ') || '—'}
                      </td>
                      <td className="py-2 px-3 font-mono text-[11px] text-slate-400 max-w-xs truncate">
                        {rep.matched
                          ? rep.transformed_caption
                          : rep.failed_conditions.join('; ')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Rules Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/60 text-[11px] font-medium text-slate-400">
                <th className="py-3 px-4">Priority</th>
                <th className="py-3 px-4">Rule Name & Description</th>
                <th className="py-3 px-4">Source → Destinations</th>
                <th className="py-3 px-4">Filters & Categories</th>
                <th className="py-3 px-4">Mode & Sync</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-xs">
              {filteredRules.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-slate-400">
                    No forwarding rules match your current search. Click "New Rule" or "Import / Recipes" to add one.
                  </td>
                </tr>
              ) : (
                filteredRules.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3 px-4 font-mono whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-semibold text-slate-100">{r.priority}</span>
                        <span className="text-slate-500">#{r.secondary_order}</span>
                        <div className="flex flex-col ml-1">
                          <button
                            type="button"
                            title="Increase priority"
                            onClick={() => handleNudgePriority(r, 5)}
                            className="text-slate-500 hover:text-slate-200"
                          >
                            <ArrowUp className="w-3 h-3" />
                          </button>
                          <button
                            type="button"
                            title="Decrease priority"
                            onClick={() => handleNudgePriority(r, -5)}
                            className="text-slate-500 hover:text-slate-200"
                          >
                            <ArrowDown className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                      {r.exclusive_stop && (
                        <div className="text-[11px] text-amber-400 mt-0.5">Exclusive-Stop</div>
                      )}
                    </td>

                    <td className="py-3 px-4 max-w-xs">
                      <div className="font-semibold text-slate-100">{r.name}</div>
                      <div className="text-[11px] text-slate-400 line-clamp-2 mt-0.5">
                        {r.description || r.id}
                      </div>
                    </td>

                    <td className="py-3 px-4">
                      <div className="text-slate-200 font-medium">
                        {chatTitleMap.get(r.source_peer_id) || r.source_peer_id}
                      </div>
                      <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                        →{' '}
                        {r.destination_peer_ids
                          .map((d) => chatTitleMap.get(d) || d)
                          .join(' · ')}
                      </div>
                    </td>

                    <td className="py-3 px-4">
                      <div className="text-slate-300 font-mono text-[11px]">
                        Type: {r.filters.message_type_filter}
                        {r.filters.min_file_size_mb ? ` · >=${r.filters.min_file_size_mb}MB` : ''}
                      </div>
                      <div className="text-slate-400 text-[11px] mt-0.5">
                        {r.categories.enabled && r.categories.selected.length > 0
                          ? `Categories (${r.categories.match_mode}): ${r.categories.selected.join(' · ')}`
                          : 'Categories: All'}
                        {r.schedule.enabled
                          ? ` · Sched: ${r.schedule.start_time}-${r.schedule.end_time} ${r.schedule.timezone}`
                          : ''}
                      </div>
                    </td>

                    <td className="py-3 px-4 font-mono text-[11px] text-slate-300 whitespace-nowrap">
                      <div>
                        {r.delivery_mode} · Delay {r.delay_seconds}s · Retries {r.max_retries}
                      </div>
                      <div className="text-slate-400 mt-0.5">
                        Sync: {r.sync_edits ? 'Edit' : 'No-Edit'} /{' '}
                        {r.sync_deletes ? 'Delete' : 'No-Delete'}
                      </div>
                    </td>

                    <td className="py-3 px-4 whitespace-nowrap">
                      <button
                        type="button"
                        onClick={() => handleToggleRule(r)}
                        className={`px-2.5 py-1 rounded text-xs font-medium border transition-colors ${
                          r.enabled
                            ? 'bg-emerald-950/60 border-emerald-800 text-emerald-300'
                            : 'bg-slate-950 border-slate-800 text-slate-400'
                        }`}
                      >
                        {r.enabled ? 'Enabled' : 'Disabled'}
                      </button>
                    </td>

                    <td className="py-3 px-4 text-right whitespace-nowrap">
                      <div className="inline-flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setEditingRule(r)}
                          className="p-1.5 text-slate-400 hover:text-slate-100 rounded hover:bg-slate-800"
                          title="Edit rule"
                        >
                          <Edit3 className="w-4 h-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDuplicateRule(r)}
                          className="p-1.5 text-slate-400 hover:text-slate-100 rounded hover:bg-slate-800"
                          title="Duplicate rule"
                        >
                          <Copy className="w-4 h-4" />
                        </button>
                        {confirmDeleteId === r.id ? (
                          <div className="inline-flex items-center gap-1 ml-1">
                            <button
                              type="button"
                              onClick={() => handleDeleteRule(r.id)}
                              className="px-2 py-1 text-[11px] bg-red-600 text-white rounded"
                            >
                              Confirm
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmDeleteId(null)}
                              className="px-2 py-1 text-[11px] bg-slate-800 text-slate-300 rounded"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setConfirmDeleteId(r.id)}
                            className="p-1.5 text-slate-400 hover:text-red-400 rounded hover:bg-slate-800"
                            title="Delete rule"
                          >
                            <Trash2 className="w-4 h-4" />
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

      {/* Rule Editor Modal */}
      {editingRule !== undefined && (
        <RuleEditorModal
          initialRule={editingRule}
          chats={chats}
          onClose={() => setEditingRule(undefined)}
          onSaved={() => {
            setEditingRule(undefined);
            onRefresh();
          }}
          notify={notify}
        />
      )}

      {/* Import & Built-in Recipes Modal */}
      {showImportModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 overflow-y-auto">
          <div className="w-full max-w-4xl bg-slate-900 border border-slate-800 rounded-lg p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-base font-semibold text-slate-100">
                  Import Rules JSON & Built-in Example Recipes
                </h3>
                <p className="text-xs text-slate-400">
                  Validates schema, detects duplicate rule IDs, and flags unresolved chat identifiers before applying.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowImportModal(false)}
                className="text-xs text-slate-400 hover:text-slate-200"
              >
                Close
              </button>
            </div>

            {/* 4 Built-in Recipes */}
            <div>
              <div className="text-xs font-medium text-slate-300 mb-2 flex items-center gap-1.5">
                <BookOpen className="w-4 h-4 text-sky-400" />
                <span>Load Built-in Configuration Recipe:</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                {recipes.map((rec: any) => (
                  <button
                    key={rec.recipe_name}
                    type="button"
                    onClick={() => {
                      const str = JSON.stringify(rec, null, 2);
                      setImportJsonText(str);
                      handlePreviewImport(str);
                    }}
                    className="p-3 bg-slate-950 hover:bg-slate-800/70 border border-slate-800 rounded-md text-left"
                  >
                    <div className="text-xs font-mono font-semibold text-sky-400">
                      {rec.recipe_name}.json ({rec.rules?.length || 0} rules)
                    </div>
                    <div className="text-[11px] text-slate-300 mt-1">{rec.description}</div>
                    <div className="text-[11px] text-slate-500 mt-1">
                      {rec.placeholder_instructions}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Rule Export / Recipe JSON Payload
              </label>
              <textarea
                rows={7}
                value={importJsonText}
                onChange={(e) => {
                  setImportJsonText(e.target.value);
                  setImportPreview(null);
                }}
                placeholder='Paste exported JSON or click one of the 4 recipe cards above...'
                className="w-full p-3 text-xs font-mono bg-slate-950 border border-slate-800 rounded-md text-slate-200"
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <label className="text-xs text-slate-300">ID Conflict Strategy:</label>
                <select
                  value={conflictStrategy}
                  onChange={(e) => setConflictStrategy(e.target.value as any)}
                  className="px-2.5 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded text-slate-200"
                >
                  <option value="REMAP_CONFLICTS">Safe Remap (Generate new IDs for conflicts)</option>
                  <option value="REPLACE_EXISTING">Replace Existing Rules with Same ID</option>
                </select>
              </div>
              <button
                type="button"
                onClick={() => handlePreviewImport(importJsonText)}
                className="px-4 py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-100 rounded-md"
              >
                Validate & Preview Import
              </button>
            </div>

            {importPreview && (
              <div className="p-4 bg-slate-950 border border-slate-800 rounded-md space-y-3 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-semibold flex items-center gap-1.5">
                    {importPreview.valid ? (
                      <span className="text-emerald-400 flex items-center gap-1">
                        <CheckCircle2 className="w-4 h-4" /> Schema Valid ({importPreview.rule_count} rules)
                      </span>
                    ) : (
                      <span className="text-red-400 flex items-center gap-1">
                        <AlertTriangle className="w-4 h-4" /> Validation Failed
                      </span>
                    )}
                  </span>
                  <span className="font-mono text-slate-400">
                    Conflicting IDs: {importPreview.conflicting_ids.length} · Unresolved Chats:{' '}
                    {importPreview.unresolved_chat_ids.length}
                  </span>
                </div>

                {importPreview.validation_errors?.length > 0 && (
                  <div className="p-2.5 bg-red-950/50 border border-red-800 rounded text-red-200 font-mono text-[11px]">
                    {importPreview.validation_errors.map((e: string, i: number) => (
                      <div key={i}>• {e}</div>
                    ))}
                  </div>
                )}

                {importPreview.unresolved_chat_ids?.length > 0 && (
                  <div className="space-y-2 pt-1">
                    <div className="text-amber-300 font-medium">
                      Unresolved Placeholder Chat IDs Detected — Optional Remap to Accessible Chat:
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {importPreview.unresolved_chat_ids.map((unresolvedId: string) => (
                        <div
                          key={unresolvedId}
                          className="flex items-center justify-between gap-2 p-2 bg-slate-900 border border-slate-800 rounded"
                        >
                          <span className="font-mono text-slate-300">{unresolvedId}</span>
                          <select
                            value={peerRemap[unresolvedId] || ''}
                            onChange={(e) =>
                              setPeerRemap({ ...peerRemap, [unresolvedId]: e.target.value })
                            }
                            className="px-2 py-1 text-xs bg-slate-950 border border-slate-800 rounded text-slate-200"
                          >
                            <option value="">Keep original ({unresolvedId})</option>
                            {chats.map((c) => (
                              <option key={c.peer_id} value={c.peer_id}>
                                Map to {c.title} ({c.peer_id})
                              </option>
                            ))}
                          </select>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex justify-end pt-2">
                  <button
                    type="button"
                    disabled={!importPreview.valid}
                    onClick={handleApplyImport}
                    className="px-4 py-2 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-md disabled:opacity-50"
                  >
                    Confirm & Import {importPreview.rule_count} Rule(s)
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
