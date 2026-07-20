import { Plus, X } from 'lucide-react';
import { useRef, useState } from 'react';
import { SshWebSocketTransport } from '../terminal/SshWebSocketTransport';
import { TerminalSession } from '../terminal/TerminalSession';

const MAX_TERMINALS = 3;

export function TerminalPanel({ deviceId }: { deviceId: string }) {
  const [sessions, setSessions] = useState([1]);
  const [active, setActive] = useState(1);
  const nextId = useRef(2);

  const add = () => {
    if (sessions.length >= MAX_TERMINALS) return;
    const id = nextId.current++;
    setSessions((current) => [...current, id]);
    setActive(id);
  };
  const remove = (id: number) => {
    const remaining = sessions.filter((item) => item !== id);
    setSessions(remaining.length === 0 ? [nextId.current++] : remaining);
    if (active === id) setActive(remaining.at(-1) ?? nextId.current - 1);
  };

  return (
    <div className="terminal-panel">
      <div className="terminal-tabs" role="tablist" aria-label="Terminal sessions">
        {sessions.map((id, index) => (
          <div key={id} className={active === id ? 'is-active' : ''}>
            <button type="button" role="tab" aria-selected={active === id} onClick={() => setActive(id)}>
              Terminal {index + 1}
            </button>
            <button type="button" aria-label={`Close terminal ${String(index + 1)}`} onClick={() => remove(id)}>
              <X size={12} />
            </button>
          </div>
        ))}
        <button type="button" className="terminal-tabs__add" onClick={add} disabled={sessions.length >= MAX_TERMINALS}>
          <Plus size={12} /> New terminal
        </button>
      </div>
      {sessions.map((id) => (
        <div key={id} hidden={id !== active}>
          <TerminalSession
            createTransport={() => new SshWebSocketTransport(deviceId)}
            warningTitle="Direct Mode — no rollback protection"
            warningBody="Commands run on the device exactly as typed and may change its configuration. The app does not parse, approve, record, or automatically undo terminal commands."
            acknowledgementLabel="I understand — open Direct Mode"
            inputPolicy={{ lineEnding: 'raw', localEcho: false, confirmMultiline: false }}
            ariaLabel="Device terminal"
            note="Idle sessions close after 15 minutes. Output is capped and never saved by the app."
          />
        </div>
      ))}
    </div>
  );
}
