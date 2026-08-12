import {
  Activity,
  Database,
  HardDrive,
  KeyRound,
  LockKeyhole,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Router,
  ScanSearch,
  Server,
  ShieldCheck,
} from 'lucide-react';
import { lazy, Suspense, useState } from 'react';
import type { HealthResponse } from '../types/api';
import { AppState } from './ui/AppState';
import { Badge } from './ui/Badge';
import { ActivityPage } from '../features/inventory/ActivityPage';
import { InventoryPage } from '../features/inventory/InventoryPage';

const TopologyPage = lazy(() => import('../features/topology/TopologyPage'));
const AnalysisPage = lazy(() =>
  import('../features/analysis/AnalysisPage').then((module) => ({ default: module.AnalysisPage })),
);

type ViewId = 'inventory' | 'topology' | 'analysis' | 'activity';

interface AppShellProps {
  health: HealthResponse;
  onLogout: () => Promise<void>;
}

const healthy = (status: HealthResponse['status']) => status === 'ok';

const SIDEBAR_COLLAPSED_KEY = 'terraformer.sidebar.collapsed';

export function AppShell({ health, onLogout }: AppShellProps) {
  const [view, setView] = useState<ViewId>('inventory');
  const [loggingOut, setLoggingOut] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1',
  );
  const [focusDeviceId, setFocusDeviceId] = useState<string>();

  const toggleSidebar = () => {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? '1' : '0');
  };

  // Two distinct entry points, not one: a plain nav click must clear any
  // device carried over from Topology, or reopening Inventory later would
  // silently re-select a stale device the operator never asked for.
  const goToInventory = () => {
    setFocusDeviceId(undefined);
    setView('inventory');
  };
  const focusDeviceInInventory = (deviceId: string) => {
    setFocusDeviceId(deviceId);
    setView('inventory');
  };

  const logout = async () => {
    setLoggingOut(true);
    try {
      await onLogout();
    } finally {
      setLoggingOut(false);
    }
  };

  return (
    <div className={sidebarCollapsed ? 'app-shell app-shell--sidebar-collapsed' : 'app-shell'}>
      <aside className="sidebar">
        <header className="sidebar__brand">
          <div className="brand-mark" aria-hidden="true">
            <Network size={21} />
          </div>
          <div className="sidebar__brand-text">
            <strong>Terraformer</strong>
            <span>Network playground</span>
          </div>
          <button
            type="button"
            className="icon-button sidebar__collapse"
            onClick={toggleSidebar}
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </header>
        <div className="environment-chip">
          <span className="environment-chip__dot" />
          <div>
            <strong>Local workspace</strong>
            <span>Single-user · Phase 0–2</span>
          </div>
        </div>
        <nav className="sidebar__nav" aria-label="Main navigation">
          <span className="sidebar__section-label">WORKSPACE</span>
          <button
            type="button"
            className={view === 'inventory' ? 'is-active' : ''}
            onClick={goToInventory}
            aria-current={view === 'inventory' ? 'page' : undefined}
          >
            <Router size={18} />
            <span>Device inventory</span>
          </button>
          <button
            type="button"
            className={view === 'topology' ? 'is-active' : ''}
            onClick={() => setView('topology')}
            aria-current={view === 'topology' ? 'page' : undefined}
          >
            <Network size={18} />
            <span>Topology</span>
          </button>
          <button
            type="button"
            className={view === 'analysis' ? 'is-active' : ''}
            onClick={() => setView('analysis')}
            aria-current={view === 'analysis' ? 'page' : undefined}
          >
            <ScanSearch size={18} />
            <span>Configuration analysis</span>
          </button>
          <button
            type="button"
            className={view === 'activity' ? 'is-active' : ''}
            onClick={() => setView('activity')}
            aria-current={view === 'activity' ? 'page' : undefined}
          >
            <Activity size={18} />
            <span>Event timeline</span>
          </button>
        </nav>
        <div className="sidebar__spacer" />
        <section className="safety-card">
          <div className="safety-card__icon">
            <ShieldCheck size={18} />
          </div>
          <div>
            <strong>Structured automation is read-only</strong>
            <p>Direct Mode terminals are manual and can change hardware.</p>
          </div>
          <Badge tone="success">ENFORCED</Badge>
        </section>
        <button className="session-button" type="button" onClick={() => void logout()} disabled={loggingOut}>
          <span className="session-button__icon">
            <KeyRound size={16} />
          </span>
          <span>
            <strong>Local admin</strong>
            <small>{loggingOut ? 'Locking…' : 'Lock workspace'}</small>
          </span>
          <LockKeyhole size={15} />
        </button>
      </aside>

      <div className="app-shell__content">
        {view === 'inventory' ? (
          <InventoryPage focusDeviceId={focusDeviceId} />
        ) : view === 'topology' ? (
          <Suspense
            fallback={
              <AppState
                kind="loading"
                title="Loading topology"
                message="Preparing the read-only graph..."
              />
            }
          >
            <TopologyPage onFocusDevice={focusDeviceInInventory} />
          </Suspense>
        ) : view === 'analysis' ? (
          <Suspense
            fallback={
              <AppState
                kind="loading"
                title="Loading analysis"
                message="Preparing the configuration analysis view..."
              />
            }
          >
            <AnalysisPage />
          </Suspense>
        ) : (
          <ActivityPage />
        )}
      </div>

      <footer className="status-bar">
        <div className="status-bar__group">
          <span className={healthy(health.status) ? 'status-dot is-ok' : 'status-dot is-warning'} />
          <strong>API {health.status}</strong>
          <span className="status-separator" />
          <span>
            <Database size={12} /> Database {health.checks.database.status}
          </span>
          <span>
            <HardDrive size={12} /> Redis {health.checks.redis.status}
          </span>
          <span>
            <Server size={12} /> Worker {health.checks.worker.status}
          </span>
        </div>
        <div className="status-bar__group">
          <span>
            <ShieldCheck size={12} /> Structured writes require explicit preview and apply
          </span>
          <span className="status-separator" />
          <span>v{health.version}</span>
        </div>
      </footer>
    </div>
  );
}
