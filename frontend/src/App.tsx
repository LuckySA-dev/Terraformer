import { AccessGate } from './features/access/AccessGate';
import { AppShell } from './components/AppShell';

export default function App() {
  return (
    <AccessGate>
      {({ health, onLogout }) => <AppShell health={health} onLogout={onLogout} />}
    </AccessGate>
  );
}
