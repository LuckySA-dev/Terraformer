import { Plus, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { ConsoleTransport, SshCompatibility } from '../../types/api';
import { SshWebSocketTransport } from '../terminal/SshWebSocketTransport';
import { TerminalSession } from '../terminal/TerminalSession';

const MAX_TERMINALS = 3;

export function TerminalPanel({
  deviceId,
  sshCompatibility = 'modern',
  consoleTransport = 'ssh',
}: {
  deviceId: string;
  sshCompatibility?: SshCompatibility;
  consoleTransport?: ConsoleTransport;
}) {
  const [sessions, setSessions] = useState([1]);
  const [active, setActive] = useState(1);
  const nextId = useRef(2);
  const tabRefs = useRef(new Map<number, HTMLButtonElement>());
  const pendingFocus = useRef<number | undefined>(undefined);
  const requiresGroup1Acknowledgement = sshCompatibility === 'cisco_legacy_group1';
  const requiresVeryOldAcknowledgement = sshCompatibility === 'very_old_ssh';
  const isTelnet = consoleTransport === 'telnet';
  const requireAuthorization =
    requiresGroup1Acknowledgement || requiresVeryOldAcknowledgement || isTelnet;

  const add = () => {
    if (sessions.length >= MAX_TERMINALS) return;
    const id = nextId.current++;
    setSessions((current) => [...current, id]);
    setActive(id);
  };
  const remove = (id: number) => {
    const remaining = sessions.filter((item) => item !== id);
    const nextSessions = remaining.length === 0 ? [nextId.current++] : remaining;
    const nextActive = active === id
      ? nextSessions[Math.min(sessions.indexOf(id), nextSessions.length - 1)]
      : active;
    setSessions(nextSessions);
    if (nextActive !== undefined && active === id) {
      pendingFocus.current = nextActive;
      setActive(nextActive);
    }
  };

  useEffect(() => {
    if (pendingFocus.current === undefined) return;
    tabRefs.current.get(pendingFocus.current)?.focus();
    pendingFocus.current = undefined;
  }, [sessions]);

  return (
    <div className="terminal-panel">
      <div className="terminal-tabs" role="tablist" aria-label="Terminal sessions">
        {sessions.map((id, index) => (
          <div key={id} className={active === id ? 'is-active' : ''}>
            <button
              ref={(element) => {
                if (element === null) tabRefs.current.delete(id);
                else tabRefs.current.set(id, element);
              }}
              id={`terminal-tab-${String(id)}`}
              type="button"
              role="tab"
              aria-selected={active === id}
              aria-controls={`terminal-panel-${String(id)}`}
              tabIndex={active === id ? 0 : -1}
              onClick={() => setActive(id)}
            >
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
        <div
          key={id}
          id={`terminal-panel-${String(id)}`}
          role="tabpanel"
          aria-labelledby={`terminal-tab-${String(id)}`}
          hidden={id !== active}
        >
          <TerminalSession
            createTransport={(authorizationAcknowledged) => new SshWebSocketTransport(
              deviceId,
              requiresGroup1Acknowledgement && authorizationAcknowledged,
              requiresVeryOldAcknowledgement && authorizationAcknowledged,
              isTelnet && authorizationAcknowledged,
            )}
            warningTitle={isTelnet
              ? 'Telnet Direct Mode — cleartext, no rollback protection'
              : 'Direct Mode — no rollback protection'}
            warningBody={isTelnet
              ? 'This console is unencrypted and the device identity cannot be verified, so anything typed — including passwords — is visible on the network. Terraformer never sends the stored credentials over Telnet. Commands run exactly as typed and are not parsed, approved, recorded, or undone.'
              : 'Commands run on the device exactly as typed and may change its configuration. The app does not parse, approve, record, or automatically undo terminal commands.'}
            acknowledgementLabel={isTelnet
              ? 'I understand this Telnet console sends everything in cleartext and cannot verify the device identity.'
              : requiresVeryOldAcknowledgement
                ? 'I understand Very Old SSH uses obsolete cryptographic algorithms and is a last-resort exception.'
                : requiresGroup1Acknowledgement
                  ? 'I understand Group1 is a last-resort per-device SSH exception.'
                  : 'I understand — open Direct Mode'}
            requireAuthorization={requireAuthorization}
            openLabel="I understand — open Direct Mode"
            inputPolicy={{ lineEnding: 'raw', localEcho: false, confirmMultiline: true }}
            ariaLabel="Device terminal"
            note="Idle sessions close after 15 minutes. Output is capped and never saved by the app."
            active={id === active}
          />
        </div>
      ))}
    </div>
  );
}
