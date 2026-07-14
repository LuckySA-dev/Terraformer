import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { Plus, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { InlineNotice } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';

const MAX_TERMINALS = 3;

type TerminalStatus = 'waiting' | 'connecting' | 'connected' | 'closed' | 'error';

interface ServerMessage {
  type: 'status' | 'output' | 'error';
  status?: TerminalStatus;
  data?: string;
  message?: string;
}

function websocketUrl(deviceId: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/terminal/${encodeURIComponent(deviceId)}`;
}

function TerminalSession({ deviceId }: { deviceId: string }) {
  const container = useRef<HTMLDivElement>(null);
  const [accepted, setAccepted] = useState(false);
  const [status, setStatus] = useState<TerminalStatus>('waiting');
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (!accepted || container.current === null) return;
    let disposed = false;
    const terminal = new Terminal({
      convertEol: true,
      cursorBlink: true,
      fontFamily: '"DM Mono", monospace',
      fontSize: 12,
      scrollback: 2_000,
      theme: { background: '#10191b', foreground: '#b8cbc6' },
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(container.current);
    fit.fit();

    const socket = new WebSocket(websocketUrl(deviceId));
    const input = terminal.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data }));
      }
    });
    socket.onopen = () => {
      socket.send(JSON.stringify({ type: 'accept_direct_mode' }));
    };
    socket.onmessage = (event) => {
      let message: ServerMessage;
      try {
        message = JSON.parse(String(event.data)) as ServerMessage;
      } catch {
        setError('The terminal server returned an invalid message.');
        setStatus('error');
        return;
      }
      if (message.type === 'output' && typeof message.data === 'string') {
        terminal.write(message.data);
      } else if (message.type === 'status' && message.status !== undefined) {
        setStatus(message.status);
      } else if (message.type === 'error') {
        setError(message.message ?? 'The terminal session failed.');
        setStatus('error');
      }
    };
    socket.onerror = () => {
      setError('Unable to reach the terminal service.');
      setStatus('error');
    };
    socket.onclose = () => {
      if (!disposed) setStatus((current) => (current === 'error' ? current : 'closed'));
    };

    const resize = () => {
      fit.fit();
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(
          JSON.stringify({ type: 'resize', columns: terminal.cols, rows: terminal.rows }),
        );
      }
    };
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(resize);
    observer?.observe(container.current);
    window.addEventListener('resize', resize);

    return () => {
      disposed = true;
      observer?.disconnect();
      window.removeEventListener('resize', resize);
      input.dispose();
      socket.close();
      terminal.dispose();
    };
  }, [accepted, deviceId]);

  if (!accepted) {
    return (
      <div className="terminal-consent">
        <InlineNotice tone="warning" title="Direct Mode — no rollback protection">
          Commands run on the device exactly as typed and may change its configuration. The app does
          not parse, approve, record, or automatically undo terminal commands.
        </InlineNotice>
        <Button size="small" onClick={() => { setError(undefined); setStatus('connecting'); setAccepted(true); }}>
          I understand — open Direct Mode
        </Button>
      </div>
    );
  }

  return (
    <div className="terminal-session">
      <div className="terminal-session__status">
        <span>DIRECT MODE</span>
        <span>{status.toUpperCase()}</span>
      </div>
      <div ref={container} className="terminal-session__canvas" aria-label="Device terminal" />
      {error === undefined ? null : <div className="form-error" role="alert">{error}</div>}
      {status === 'closed' || status === 'error' ? (
        <Button size="small" variant="ghost" onClick={() => setAccepted(false)}>
          Confirm and open a new session
        </Button>
      ) : null}
    </div>
  );
}

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
          <TerminalSession deviceId={deviceId} />
        </div>
      ))}
      <p className="terminal-note">Idle sessions close after 15 minutes. Output is capped and never saved by the app.</p>
    </div>
  );
}
