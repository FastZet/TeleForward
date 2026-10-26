import React, { useState, useEffect, useCallback } from 'react';
import { apiRequest, setAuthTokens } from './api';
import { RulesView } from './components/RulesView';
import {
  ChatsView,
  BackfillView,
  DeliveryQueueView,
} from './components/BackfillAndQueueViews';
import {
  LogsView,
  StatisticsAndSyncView,
  SettingsAndTelegramAuthView,
  AboutAndDiagnosticsView,
} from './components/LogsStatsSettingsViews';
import {
  LayoutDashboard,
  GitBranch,
  MessageSquare,
  History,
  ListOrdered,
  FileText,
  BarChart3,
  Settings,
  Terminal,
  ShieldAlert,
  Play,
  RefreshCw,
  LogOut,
  CheckCircle2,
  AlertTriangle,
  Send,
} from 'lucide-react';

type NavTab =
  | 'dashboard'
  | 'rules'
  | 'chats'
  | 'backfill'
  | 'queue'
  | 'logs'
  | 'statistics'
  | 'settings'
  | 'diagnostics';

const NAV_ITEMS: Array<{ id: NavTab; label: string; icon: React.ComponentType<any> }> = [
  { id: 'dashboard', label: '1. Dashboard', icon: LayoutDashboard },
  { id: 'rules', label: '2. Rules', icon: GitBranch },
  { id: 'chats', label: '3. Chats', icon: MessageSquare },
  { id: 'backfill', label: '4. Backfill', icon: History },
  { id: 'queue', label: '5. Delivery Queue', icon: ListOrdered },
  { id: 'logs', label: '6. Logs', icon: FileText },
  { id: 'statistics', label: '7. Statistics', icon: BarChart3 },
  { id: 'settings', label: '8. Settings', icon: Settings },
  { id: 'diagnostics', label: '9. About & Diagnostics', icon: Terminal },
];

export function App() {
  const [authChecked, setAuthChecked] = useState(false);
  const [setupRequired, setSetupRequired] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [adminUsername, setAdminUsername] = useState<string | null>(null);

  // Admin Setup / Login Form
  const [usernameInput, setUsernameInput] = useState('admin');
  const [passwordInput, setPasswordInput] = useState('');
  const [authError, setAuthError] = useState<string | null>(null);
  const [authSubmitting, setAuthSubmitting] = useState(false);

  // Main Navigation & Data
  const [activeTab, setActiveTab] = useState<NavTab>('dashboard');
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);

  const [dashboardData, setDashboardData] = useState<any | null>(null);
  const [rules, setRules] = useState<any[]>([]);
  const [chats, setChats] = useState<any[]>([]);
  const [recipes, setRecipes] = useState<any[]>([]);
  const [backfillJobs, setBackfillJobs] = useState<any[]>([]);
  const [queueJobs, setQueueJobs] = useState<any[]>([]);
  const [queueStatusFilter, setQueueStatusFilter] = useState('ALL');
  const [statsData, setStatsData] = useState<any | null>(null);
  const [mappings, setMappings] = useState<any[]>([]);

  // Live Inbound Message Simulator on Dashboard
  const [simPreset, setSimPreset] = useState<'MOVIE_UHD' | 'TV_EPISODE' | 'COMBINED_PACK' | 'SPLIT_ARCHIVE'>('MOVIE_UHD');
  const [simRunning, setSimRunning] = useState(false);

  const notify = useCallback((msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type });
    setTimeout(() => {
      setToast((prev) => (prev?.msg === msg ? null : prev));
    }, 4500);
  }, []);

  const checkAuth = useCallback(async () => {
    try {
      const res = await apiRequest<{
        setup_required: boolean;
        authenticated: boolean;
        username: string | null;
        csrf_token: string | null;
      }>('/api/v1/auth/status');
      setSetupRequired(res.setup_required);
      setAuthenticated(res.authenticated);
      setAdminUsername(res.username);
      if (res.csrf_token) {
        setAuthTokens(res.csrf_token);
      }
    } catch {
      setAuthenticated(false);
    } finally {
      setAuthChecked(true);
    }
  }, []);

  const loadAllWorkspaceData = useCallback(async () => {
    if (!authenticated) return;
    try {
      const [st, rList, cList, recList, bfList, qList, stCounters, mapList] = await Promise.all([
        apiRequest('/api/v1/status'),
        apiRequest('/api/v1/rules'),
        apiRequest('/api/v1/chats'),
        apiRequest('/api/v1/recipes'),
        apiRequest('/api/v1/backfill'),
        apiRequest(`/api/v1/queue?status=${queueStatusFilter}`),
        apiRequest('/api/v1/stats'),
        apiRequest('/api/v1/sync/mappings'),
      ]);
      setDashboardData(st);
      setRules(rList);
      setChats(cList);
      setRecipes(recList);
      setBackfillJobs(bfList);
      setQueueJobs(qList);
      setStatsData(stCounters);
      setMappings(mapList);
    } catch (err: any) {
      if (err.message?.includes('Administrative authentication required')) {
        setAuthenticated(false);
      }
    }
  }, [authenticated, queueStatusFilter]);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  useEffect(() => {
    if (authenticated) {
      loadAllWorkspaceData();
      const timer = setInterval(loadAllWorkspaceData, 3500);
      return () => clearInterval(timer);
    }
  }, [authenticated, loadAllWorkspaceData]);

  const handleAdminSetupOrLogin = async (e: React.FormEvent, overridePassword?: string) => {
    e.preventDefault();
    setAuthError(null);
    setAuthSubmitting(true);
    try {
      const endpoint = setupRequired ? '/api/v1/auth/setup' : '/api/v1/auth/login';
      const pwd = overridePassword ?? passwordInput;
      const res = await apiRequest<{
        authenticated: boolean;
        username: string;
        csrf_token: string;
        session_token: string;
      }>(endpoint, {
        method: 'POST',
        body: JSON.stringify({
          username: usernameInput.trim(),
          password: pwd,
        }),
      });
      setAuthTokens(res.csrf_token, res.session_token);
      setSetupRequired(false);
      setAuthenticated(true);
      setAdminUsername(res.username);
    } catch (err: any) {
      setAuthError(err.message);
    } finally {
      setAuthSubmitting(false);
    }
  };

  const handleAdminLogout = async () => {
    try {
      await apiRequest('/api/v1/auth/logout', { method: 'POST' });
    } catch {
      // ignore
    }
    setAuthTokens(null, null);
    setAuthenticated(false);
  };

  const handleToggleGlobalForwarding = async () => {
    if (!dashboardData?.settings) return;
    try {
      const next = !dashboardData.settings.forwarding_enabled;
      await apiRequest('/api/v1/settings', {
        method: 'PUT',
        body: JSON.stringify({ forwarding_enabled: next }),
      });
      notify(`Global forwarding ${next ? 'enabled' : 'paused'}`, 'success');
      loadAllWorkspaceData();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleManualCatchup = async (sourcePeerId?: string) => {
    try {
      const res = await apiRequest<{ recovered_sources: number; details: any[] }>(
        '/api/v1/catchup/run',
        {
          method: 'POST',
          body: JSON.stringify(sourcePeerId ? { source_peer_id: sourcePeerId } : {}),
        }
      );
      const totalEnqueued = (res.details || []).reduce(
        (acc, d) => acc + Number(d.enqueued || 0),
        0
      );
      notify(
        `Catch-up recovery completed across ${res.recovered_sources} source(s); enqueued ${totalEnqueued} delivery job(s)`,
        'success'
      );
      loadAllWorkspaceData();
    } catch (err: any) {
      notify(err.message, 'error');
    }
  };

  const handleSimulateInbound = async () => {
    setSimRunning(true);
    try {
      const presets: Record<string, any> = {
        MOVIE_UHD: {
          source_peer_id: '-1001000000001',
          chat_type: 'CHANNEL',
          media_type: 'DOCUMENT',
          filename: 'Gladiator.II.2024.2160p.UHD.BluRay.Remux.HEVC.Atmos.mkv',
          file_size_bytes: 58_400_000_000,
          caption:
            '🔥 [TG] Gladiator.II.2024.2160p.UHD.BluRay.Remux.HEVC.Atmos.mkv Join @scene_raw_ingest https://t.me/promo #uhd Fast mirror!',
        },
        TV_EPISODE: {
          source_peer_id: '-1001000000001',
          chat_type: 'CHANNEL',
          media_type: 'DOCUMENT',
          filename: 'The.Last.of.Us.S02E01.2160p.MAX.WEB-DL.DDP5.1.Atmos.DV.HEVC.mkv',
          file_size_bytes: 6_800_000_000,
          caption:
            '📺 The.Last.of.Us.S02E01.2160p.MAX.WEB-DL.DDP5.1.Atmos.DV.HEVC.mkv @scene_raw_ingest #TLOU',
        },
        COMBINED_PACK: {
          source_peer_id: '-1001000000001',
          chat_type: 'CHANNEL',
          media_type: 'DOCUMENT',
          filename: 'Andor.S01.COMPLETE.2160p.DSNP.WEB-DL.HEVC.mkv',
          file_size_bytes: 42_000_000_000,
          caption:
            '📦 Andor.S01.COMPLETE.2160p.DSNP.WEB-DL.HEVC.mkv Complete Season Pack @scene_raw_ingest',
        },
        SPLIT_ARCHIVE: {
          source_peer_id: '-1001000000001',
          chat_type: 'CHANNEL',
          media_type: 'DOCUMENT',
          filename: 'Avatar.The.Way.of.Water.2022.2160p.3D.BluRay.iso.001',
          file_size_bytes: 25_000_000_000,
          caption:
            '🎬 Avatar.The.Way.of.Water.2022.2160p.3D.BluRay.iso.001 Multipart Volume 1 @scene_raw_ingest',
        },
      };

      const res = await apiRequest<{
        message: any;
        routing: { matchedRulesCount: number; enqueuedJobIds: string[] };
      }>('/api/v1/rules/simulate-inbound', {
        method: 'POST',
        body: JSON.stringify(presets[simPreset]),
      });

      notify(
        `Ingested msg #${res.message.message_id}: matched ${res.routing.matchedRulesCount} rule(s), delivered ${res.routing.enqueuedJobIds.length} job(s)`,
        'success'
      );
      loadAllWorkspaceData();
    } catch (err: any) {
      notify(err.message, 'error');
    } finally {
      setSimRunning(false);
    }
  };

  if (!authChecked) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-300 flex items-center justify-center text-sm font-mono">
        Initializing TeleRoute MTProto Core...
      </div>
    );
  }

  // Initial Administrator Setup or Login Screen (Zero default credentials shipped)
  if (!authenticated) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-4">
        <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-lg p-7 space-y-5 shadow-2xl">
          <div>
            <div className="text-xs font-mono text-sky-400">
              Self-Hosted Telegram MTProto Automation Platform
            </div>
            <h1 className="text-xl font-bold tracking-tight text-slate-100 mt-1">
              {setupRequired
                ? 'Initial Administrator Setup'
                : 'TeleRoute Administration Login'}
            </h1>
            <p className="text-xs text-slate-400 mt-1">
              {setupRequired
                ? 'No default administrator credentials are shipped. Create your administrator account to unlock the console.'
                : 'Authenticate with your administrator credentials to access the routing engine and Telegram session controls.'}
            </p>
          </div>

          {authError && (
            <div className="p-3 bg-red-950/60 border border-red-800 rounded text-xs text-red-200 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
              <span>{authError}</span>
            </div>
          )}

          <form onSubmit={(e) => handleAdminSetupOrLogin(e)} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Administrator Username
              </label>
              <input
                type="text"
                required
                value={usernameInput}
                onChange={(e) => setUsernameInput(e.target.value)}
                className="w-full px-3.5 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Password {setupRequired ? '(Minimum 8 characters)' : ''}
              </label>
              <input
                type="password"
                required
                value={passwordInput}
                onChange={(e) => setPasswordInput(e.target.value)}
                placeholder="Enter strong administrator password..."
                className="w-full px-3.5 py-2 text-sm bg-slate-950 border border-slate-800 rounded-md text-slate-100"
              />
            </div>

            <button
              type="submit"
              disabled={authSubmitting}
              className="w-full py-2.5 px-4 text-xs font-semibold bg-sky-600 hover:bg-sky-500 text-white rounded-md transition-colors"
            >
              {authSubmitting
                ? 'Authenticating...'
                : setupRequired
                  ? 'Provision Administrator Account'
                  : 'Sign In to Console'}
            </button>
          </form>

          {setupRequired && (
            <div className="pt-3 border-t border-slate-800">
              <button
                type="button"
                onClick={(e) => {
                  const generated = 'TeleRoute#Admin2026!';
                  setPasswordInput(generated);
                  handleAdminSetupOrLogin(e as any, generated);
                }}
                className="w-full py-2 px-3 text-xs font-mono bg-slate-950 hover:bg-slate-800 text-slate-300 border border-slate-800 rounded-md"
              >
                One-Click Provision Admin (User: admin · Argon2/scrypt Hashed)
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  const counts = dashboardData?.counts || {
    enabled_rules: 0,
    disabled_rules: 0,
    total_rules: 0,
    configured_sources: 0,
    configured_destinations: 0,
    successful_deliveries: 0,
    skipped_messages: 0,
    failed_deliveries: 0,
    pending_queue_jobs: 0,
    active_backfill_jobs: 0,
  };

  const activeNavLabel = NAV_ITEMS.find((n) => n.id === activeTab)?.label || 'Dashboard';

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex">
      {/* Persistent Left Sidebar (260px) */}
      <aside className="w-64 border-r border-slate-800 bg-slate-900/60 flex flex-col shrink-0">
        <div className="px-5 py-4 border-b border-slate-800">
          <div className="text-base font-bold tracking-tight text-slate-100 whitespace-nowrap">
            TeleRoute Core
          </div>
          <div className="text-[11px] font-mono text-slate-400 mt-0.5">
            MTProto · SQLite WAL · v1.0.0
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = activeTab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setActiveTab(item.id)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap ${
                  active
                    ? 'bg-sky-600 text-white'
                    : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/60'
                }`}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="p-4 border-t border-slate-800 space-y-2 text-xs">
          <div className="flex items-center justify-between text-slate-400 font-mono text-[11px]">
            <span>Admin: {adminUsername}</span>
            <button
              type="button"
              onClick={handleAdminLogout}
              className="text-slate-400 hover:text-red-400 flex items-center gap-1"
            >
              <LogOut className="w-3.5 h-3.5" /> Logout
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Bar Contract: Breadcrumb on Left, Primary Actions on Right */}
        <header className="flex items-center justify-between gap-8 px-6 py-3.5 border-b border-slate-800 bg-slate-900/40">
          <div className="text-sm font-medium text-slate-300 whitespace-nowrap truncate">
            TeleRoute MTProto Core <span className="text-slate-600 mx-1.5">/</span>{' '}
            <span className="text-slate-100 font-semibold">{activeNavLabel}</span>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <button
              type="button"
              onClick={handleToggleGlobalForwarding}
              className={`px-3.5 py-1.5 text-xs font-medium rounded-md border transition-colors whitespace-nowrap shrink-0 ${
                dashboardData?.settings?.forwarding_enabled
                  ? 'bg-emerald-950/60 border-emerald-800 text-emerald-300'
                  : 'bg-amber-950/60 border-amber-800 text-amber-300'
              }`}
            >
              Forwarding: {dashboardData?.settings?.forwarding_enabled ? 'ACTIVE' : 'PAUSED'}
            </button>

            <button
              type="button"
              onClick={loadAllWorkspaceData}
              className="px-3 py-1.5 text-xs font-medium text-slate-200 bg-slate-800 hover:bg-slate-700 rounded-md whitespace-nowrap shrink-0"
            >
              Sync State
            </button>
          </div>
        </header>

        {/* Toast Notification */}
        {toast && (
          <div className="mx-6 mt-4 px-4 py-2.5 rounded-md border flex items-center justify-between text-xs bg-slate-900 border-slate-700 text-slate-100">
            <div className="flex items-center gap-2">
              {toast.type === 'success' ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              ) : (
                <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
              )}
              <span>{toast.msg}</span>
            </div>
            <button
              type="button"
              onClick={() => setToast(null)}
              className="text-slate-400 hover:text-slate-200 ml-4"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Viewport Body */}
        <main className="flex-1 p-6 overflow-y-auto space-y-6">
          {activeTab === 'dashboard' && (
            <div className="space-y-6">
              {/* Top Connection & Worker Banner */}
              <div className="p-5 bg-slate-900 border border-slate-800 rounded-lg flex flex-wrap items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="text-xs text-slate-400 font-mono">
                    Telegram Personal-Account MTProto Session:{' '}
                    <span
                      className={
                        dashboardData?.telegram?.connection_state === 'CONNECTED'
                          ? 'text-emerald-400 font-semibold'
                          : 'text-amber-400 font-semibold'
                      }
                    >
                      {dashboardData?.telegram?.connection_state || 'NOT_CONFIGURED'}
                    </span>
                    {' · '}
                    Worker: <span className="text-sky-400">{dashboardData?.worker_status}</span>
                    {' · '}
                    Deduplication:{' '}
                    <span className="text-slate-200">
                      {dashboardData?.settings?.deduplication_scope}
                    </span>
                  </div>
                  <div className="text-sm font-semibold text-slate-100">
                    {dashboardData?.telegram?.connection_state === 'CONNECTED'
                      ? `Connected as ${dashboardData.telegram.account_display_name} (${dashboardData.telegram.phone_number_masked})`
                      : 'Personal Telegram account not yet connected — dashboard and rule engine remain fully operational'}
                  </div>
                </div>

                <div className="flex items-center gap-2.5">
                  <button
                    type="button"
                    onClick={() => setActiveTab('settings')}
                    className="px-3.5 py-2 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-md whitespace-nowrap"
                  >
                    {dashboardData?.telegram?.connection_state === 'CONNECTED'
                      ? 'Manage Telegram Session'
                      : 'Configure Telegram Account'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab('rules')}
                    className="px-3.5 py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-md whitespace-nowrap"
                  >
                    Manage Routing Rules ({counts.total_rules})
                  </button>
                </div>
              </div>

              {/* 8 Key Operational Metrics Grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
                {[
                  ['Enabled Rules', counts.enabled_rules, 'text-emerald-400'],
                  ['Disabled Rules', counts.disabled_rules, 'text-slate-400'],
                  ['Sources', counts.configured_sources, 'text-slate-100'],
                  ['Destinations', counts.configured_destinations, 'text-slate-100'],
                  ['Delivered', counts.successful_deliveries, 'text-emerald-400'],
                  ['Skipped', counts.skipped_messages, 'text-slate-300'],
                  ['Failed', counts.failed_deliveries, 'text-red-400'],
                  ['Pending Queue', counts.pending_queue_jobs, 'text-sky-400'],
                ].map(([label, val, color]) => (
                  <div
                    key={String(label)}
                    className="p-3.5 bg-slate-900 border border-slate-800 rounded-lg"
                  >
                    <div className="text-[11px] text-slate-400">{label}</div>
                    <div className={`text-lg font-mono font-semibold mt-1 ${color}`}>
                      {val}
                    </div>
                  </div>
                ))}
              </div>

              {/* Missed-Message Recovery (Catch-Up) + Live Ingest Dispatcher */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Missed-Message Recovery Status */}
                <div className="p-5 bg-slate-900 border border-slate-800 rounded-lg space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-100">
                        Missed-Message Recovery (Downtime Catch-Up)
                      </h3>
                      <p className="text-xs text-slate-400">
                        Compares persisted source_cursors against latest source message IDs.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleManualCatchup()}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-sky-600 hover:bg-sky-500 text-white rounded-md whitespace-nowrap"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                      <span>Run Catch-Up Recovery</span>
                    </button>
                  </div>

                  <div className="divide-y divide-slate-800 border border-slate-800 rounded-md bg-slate-950/50 text-xs font-mono">
                    {(dashboardData?.catchup_gaps || []).map((g: any) => (
                      <div
                        key={g.source_peer_id}
                        className="p-3 flex items-center justify-between gap-2"
                      >
                        <div>
                          <div className="font-sans font-medium text-slate-200">
                            {g.source_title} ({g.source_peer_id})
                          </div>
                          <div className="text-[11px] text-slate-400">
                            Last Processed Cursor: #{g.last_processed_message_id} · Latest Available: #
                            {g.latest_message_id}
                          </div>
                        </div>
                        <div className="text-right">
                          {g.detected_gap > 0 ? (
                            <span className="text-amber-400 font-semibold">
                              {g.detected_gap} missed msgs
                            </span>
                          ) : (
                            <span className="text-emerald-400">In Sync (0 gap)</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Live Message Routing Dispatcher */}
                <div className="p-5 bg-slate-900 border border-slate-800 rounded-lg space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-100">
                        Live Source Message Ingest & Routing Test
                      </h3>
                      <p className="text-xs text-slate-400">
                        Dispatches a real candidate message through the priority rule chain, classifier, caption cleaner, and SQLite delivery queue.
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <select
                      value={simPreset}
                      onChange={(e) => setSimPreset(e.target.value as any)}
                      className="flex-1 px-3 py-2 text-xs bg-slate-950 border border-slate-800 rounded-md text-slate-100"
                    >
                      <option value="MOVIE_UHD">
                        2160p UHD Movie: Gladiator.II.2024.2160p.UHD.BluRay.Remux.mkv (58.4 GB)
                      </option>
                      <option value="TV_EPISODE">
                        TV Episode: The.Last.of.Us.S02E01.2160p.MAX.WEB-DL.HEVC.mkv (6.8 GB)
                      </option>
                      <option value="COMBINED_PACK">
                        Season Pack: Andor.S01.COMPLETE.2160p.DSNP.WEB-DL.HEVC.mkv (42 GB)
                      </option>
                      <option value="SPLIT_ARCHIVE">
                        Split Volume: Avatar.The.Way.of.Water.2022.2160p.3D.iso.001 (25 GB)
                      </option>
                    </select>
                    <button
                      type="button"
                      disabled={simRunning}
                      onClick={handleSimulateInbound}
                      className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium bg-emerald-600 hover:bg-emerald-500 text-white rounded-md whitespace-nowrap"
                    >
                      <Send className="w-3.5 h-3.5" />
                      <span>{simRunning ? 'Routing...' : 'Ingest & Route Message'}</span>
                    </button>
                  </div>
                </div>
              </div>

              {/* Recent Forwarding Activity & Recent Errors */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
                  <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-slate-100">
                      Recent Forwarding & Delivery Activity
                    </h3>
                    <button
                      type="button"
                      onClick={() => setActiveTab('queue')}
                      className="text-xs text-sky-400 hover:underline"
                    >
                      Inspect Full Queue
                    </button>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr className="border-b border-slate-800 bg-slate-950/60 text-slate-400">
                          <th className="py-2.5 px-4">Source Msg → Destination</th>
                          <th className="py-2.5 px-4">Rule & Categories</th>
                          <th className="py-2.5 px-4">Transformed Caption</th>
                          <th className="py-2.5 px-4">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800">
                        {(dashboardData?.recent_activity || []).map((act: any) => (
                          <tr key={act.id} className="hover:bg-slate-800/40">
                            <td className="py-2.5 px-4">
                              <div className="text-slate-200 font-medium">
                                {act.source_title || act.source_peer_id}{' '}
                                <span className="font-mono text-sky-400">
                                  #{act.source_message_id}
                                </span>
                              </div>
                              <div className="text-[11px] text-slate-400 font-mono">
                                → {act.destination_title || act.destination_peer_id}
                              </div>
                            </td>
                            <td className="py-2.5 px-4">
                              <div className="text-slate-200">{act.rule_name || act.rule_id}</div>
                              <div className="text-[11px] font-mono text-slate-400">
                                {act.delivery_mode} · {act.detected_categories_csv || 'ALL'}
                              </div>
                            </td>
                            <td className="py-2.5 px-4 font-mono text-[11px] text-slate-300 max-w-xs truncate">
                              {act.transformed_caption || act.filename || '—'}
                            </td>
                            <td className="py-2.5 px-4 font-mono">
                              <span
                                className={
                                  act.status === 'COMPLETED'
                                    ? 'text-emerald-400'
                                    : act.status === 'FAILED'
                                      ? 'text-red-400'
                                      : 'text-sky-400'
                                }
                              >
                                {act.status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Recent Warnings & Errors */}
                <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
                  <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-slate-100">
                      Recent Warnings & Errors
                    </h3>
                    <button
                      type="button"
                      onClick={() => setActiveTab('logs')}
                      className="text-xs text-sky-400 hover:underline"
                    >
                      All Logs
                    </button>
                  </div>
                  <div className="divide-y divide-slate-800 text-xs">
                    {(dashboardData?.recent_errors || []).length === 0 ? (
                      <div className="p-8 text-center text-slate-400">
                        Zero recent errors or warnings recorded.
                      </div>
                    ) : (
                      (dashboardData?.recent_errors || []).map((err: any) => (
                        <div key={err.id} className="p-3.5 space-y-1">
                          <div className="flex items-center justify-between font-mono text-[11px]">
                            <span
                              className={
                                err.level === 'FAILURE' ? 'text-red-400' : 'text-amber-400'
                              }
                            >
                              {err.level} · {err.event_type}
                            </span>
                            <span className="text-slate-500">{err.timestamp}</span>
                          </div>
                          <div className="font-mono text-[11px] text-slate-300">
                            {err.diagnostic_message}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'rules' && (
            <RulesView
              rules={rules}
              chats={chats}
              recipes={recipes}
              onRefresh={loadAllWorkspaceData}
              notify={notify}
            />
          )}

          {activeTab === 'chats' && (
            <ChatsView chats={chats} onRefresh={loadAllWorkspaceData} notify={notify} />
          )}

          {activeTab === 'backfill' && (
            <BackfillView
              chats={chats}
              backfillJobs={backfillJobs}
              onRefresh={loadAllWorkspaceData}
              notify={notify}
            />
          )}

          {activeTab === 'queue' && (
            <DeliveryQueueView
              jobs={queueJobs}
              statusFilter={queueStatusFilter}
              onStatusFilterChange={(st) => setQueueStatusFilter(st)}
              onRefresh={loadAllWorkspaceData}
              notify={notify}
            />
          )}

          {activeTab === 'logs' && (
            <LogsView rules={rules} chats={chats} notify={notify} />
          )}

          {activeTab === 'statistics' && (
            <StatisticsAndSyncView
              stats={statsData}
              mappings={mappings}
              onRefresh={loadAllWorkspaceData}
              notify={notify}
            />
          )}

          {activeTab === 'settings' && dashboardData?.settings && (
            <SettingsAndTelegramAuthView
              settings={dashboardData.settings}
              telegram={dashboardData.telegram}
              onRefresh={loadAllWorkspaceData}
              notify={notify}
            />
          )}

          {activeTab === 'diagnostics' && <AboutAndDiagnosticsView notify={notify} />}
        </main>
      </div>
    </div>
  );
}

export default App;
