import {
  Activity,
  Database,
  HardDrive,
  KeyRound,
  LockKeyhole,
  Network,
  Router,
  Server,
  ShieldCheck,
} from 'lucide-react';
import { useState } from 'react';
import type { HealthResponse } from '../types/api';
import { Badge } from './ui/Badge';
import { ActivityPage } from '../features/inventory/ActivityPage';
import { InventoryPage } from '../features/inventory/InventoryPage';

type ViewId = 'inventory' | 'activity';

interface AppShellProps {
  health: HealthResponse;
  onLogout: () => Promise<void>;
}

const healthy = (status: HealthResponse['status']) => status === 'ok';

export function AppShell({ health, onLogout }: AppShellProps) {
  const [view, setView] = useState<ViewId>('inventory');
  const [loggingOut, setLoggingOut] = useState(false);

  const logout = async () => {
    setLoggingOut(true);
    try {
      await onLogout();
    } finally {
      setLoggingOut(false);
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <header className="sidebar__brand">
          <div className="brand-mark" aria-hidden="true">
            <Network size={21} />
          </div>
          <div>
            <strong>Terraformer</strong>
            <span>Network playground</span>
          </div>
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
            onClick={() => setView('inventory')}
            aria-current={view === 'inventory' ? 'page' : undefined}
          >
            <Router size={18} />
            <span>Device inventory</span>
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
            <strong>Read-only safety mode</strong>
            <p>Writes, reloads, and configuration changes are not implemented.</p>
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
        {view === 'inventory' ? <InventoryPage /> : <ActivityPage />}
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
            <ShieldCheck size={12} /> Read only
          </span>
          <span className="status-separator" />
          <span>v{health.version}</span>
        </div>
      </footer>
    </div>
  );
}
