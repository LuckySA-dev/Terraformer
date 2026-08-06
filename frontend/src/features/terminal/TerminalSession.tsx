import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { InlineNotice } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { prepareTerminalInput, type TerminalInputPolicy } from './inputPolicy';
import {
  TERMINAL_CLEANUP_TIMEOUT_MS,
  TerminalTransportError,
  type TerminalFailure,
  type TerminalTransport,
  type TerminalTransportEvent,
} from './transport';

interface TerminalSessionProps {
  createTransport: (authorizationAcknowledged: boolean) => TerminalTransport;
  warningTitle: string;
  warningBody: string;
  acknowledgementLabel: string;
  requireAuthorization?: boolean;
  inputPolicy: TerminalInputPolicy;
  ariaLabel: string;
  note: string;
  openLabel?: string;
  openDisabled?: boolean;
  configuration?: ReactNode;
  onReset?: () => void;
  active?: boolean;
}

interface SessionToken {
  disposed: boolean;
}

async function withCleanupTimeout(cleanup: Promise<void>, milliseconds: number): Promise<void> {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      cleanup,
      new Promise<void>((_resolve, reject) => {
        timeout = setTimeout(
          () => reject(new TerminalTransportError('cleanup_timed_out', 'Cleanup timed out')),
          milliseconds,
        );
      }),
    ]);
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}

function sanitizedError(error: unknown, fallback: TerminalFailure): TerminalFailure {
  return error instanceof TerminalTransportError
    ? { code: error.code, message: error.message, retryable: false }
    : fallback;
}

export function TerminalSession({
  createTransport,
  warningTitle,
  warningBody,
  acknowledgementLabel,
  requireAuthorization = false,
  inputPolicy,
  ariaLabel,
  note,
  openLabel,
  openDisabled = false,
  configuration,
  onReset,
  active = true,
}: TerminalSessionProps) {
  const container = useRef<HTMLDivElement>(null);
  const errorContainer = useRef<HTMLDivElement>(null);
  const transportRef = useRef<TerminalTransport | null>(null);
  const terminal = useRef<Terminal | null>(null);
  const fitAddon = useRef<FitAddon | null>(null);
  const inputSubscription = useRef<{ dispose(): void } | null>(null);
  const resizeObserver = useRef<ResizeObserver | null>(null);
  const resizeHandler = useRef<(() => void) | null>(null);
  const pageHideHandler = useRef<(() => void) | null>(null);
  const sessionToken = useRef<SessionToken | null>(null);
  const shutdownPromise = useRef<Promise<void> | null>(null);
  const shutdownRef = useRef<(error?: TerminalFailure, disposed?: boolean) => Promise<void>>(
    () => Promise.resolve(),
  );
  const acceptingInput = useRef(false);
  const activeRef = useRef(active);
  const [accepted, setAccepted] = useState(false);
  const [authorized, setAuthorized] = useState(false);
  const [reopenBlocked, setReopenBlocked] = useState(false);
  const [status, setStatus] = useState<'idle' | 'connecting' | 'connected'>('idle');
  const [error, setError] = useState<TerminalFailure>();
  const [pendingPaste, setPendingPaste] = useState<{
    data: string;
    lineCount: number;
    characterCount: number;
  }>();

  useEffect(() => {
    if (error?.retryable !== true || (requireAuthorization && !authorized)) return;
    errorContainer.current?.querySelector('button')?.focus();
  }, [authorized, error, requireAuthorization]);

  const clearAllSessionRefs = () => {
    transportRef.current = null;
    terminal.current = null;
    fitAddon.current = null;
    inputSubscription.current = null;
    resizeObserver.current = null;
    resizeHandler.current = null;
    pageHideHandler.current = null;
    sessionToken.current = null;
  };

  const shutdown = async (shutdownError?: TerminalFailure, disposed = false) => {
    if (shutdownPromise.current !== null) return shutdownPromise.current;
    shutdownPromise.current = (async () => {
      acceptingInput.current = false;
      setPendingPaste(undefined);
      const blockReopen = transportRef.current?.kind === 'ssh'
        && shutdownError !== undefined
        && !shutdownError.retryable;
      const deadlineAt = Date.now() + TERMINAL_CLEANUP_TIMEOUT_MS;
      try {
        await withCleanupTimeout(
          transportRef.current?.close(deadlineAt) ?? Promise.resolve(),
          TERMINAL_CLEANUP_TIMEOUT_MS,
        );
      } catch {
        shutdownError = {
          code: 'cleanup_timed_out',
          message: 'Cleanup timed out',
          retryable: true,
        };
      } finally {
        inputSubscription.current?.dispose();
        resizeObserver.current?.disconnect();
        if (resizeHandler.current !== null) {
          window.removeEventListener('resize', resizeHandler.current);
        }
        if (pageHideHandler.current !== null) {
          window.removeEventListener('pagehide', pageHideHandler.current);
        }
        fitAddon.current?.dispose();
        terminal.current?.dispose();
        clearAllSessionRefs();
        if (!disposed) {
          setStatus('idle');
          setError(shutdownError);
          setReopenBlocked(blockReopen);
          setAccepted(false);
          setAuthorized(false);
          onReset?.();
        }
      }
    })();
    return shutdownPromise.current;
  };

  useEffect(() => {
    shutdownRef.current = shutdown;
  });

  useEffect(() => {
    activeRef.current = active;
    if (!active) {
      queueMicrotask(() => {
        setPendingPaste(undefined);
        setAuthorized(false);
      });
    }
  }, [active]);

  useEffect(() => () => {
    if (sessionToken.current !== null) sessionToken.current.disposed = true;
    void shutdownRef.current(undefined, true);
  }, []);

  const failWrite = (writeError: unknown, token: SessionToken) => {
    if (token.disposed) return;
    token.disposed = true;
    setPendingPaste(undefined);
    void shutdown(
      sanitizedError(writeError, {
        code: 'terminal_write_failed',
        message: 'Terminal write failed',
        retryable: false,
      }),
    );
  };

  const send = (data: string, token: SessionToken) => {
    const currentTransport = transportRef.current;
    if (!acceptingInput.current || token.disposed || currentTransport === null) return;
    void currentTransport.write(data).then(() => {
      if (!token.disposed && inputPolicy.localEcho) terminal.current?.write(data);
    }).catch((writeError: unknown) => failWrite(writeError, token));
  };

  const handleTransportEvent = (event: TerminalTransportEvent, token: SessionToken) => {
    if (token.disposed) return;
    if (event.type === 'output') {
      terminal.current?.write(event.data);
    } else if (event.type === 'status' && event.status === 'closed') {
      token.disposed = true;
      setPendingPaste(undefined);
      void shutdown();
    } else if (
      event.type === 'status'
      && (event.status === 'connecting' || event.status === 'connected')
    ) {
      acceptingInput.current = event.status === 'connected';
      setStatus(event.status);
    } else if (event.type === 'error') {
      token.disposed = true;
      setPendingPaste(undefined);
      void shutdown({
        code: event.code,
        message: event.message,
        retryable: event.retryable ?? false,
        ...(event.phase === undefined ? {} : { phase: event.phase }),
        ...(event.recommendedAction === undefined
          ? {}
          : { recommendedAction: event.recommendedAction }),
      });
    }
  };

  const open = () => {
    if (openDisabled || (requireAuthorization && !authorized) || container.current === null) return;
    const authorizationAcknowledged = authorized;
    setAuthorized(false);
    shutdownPromise.current = null;
    setError(undefined);
    setReopenBlocked(false);
    setPendingPaste(undefined);
    setAccepted(true);
    setStatus('connecting');
    const token = { disposed: false };
    sessionToken.current = token;

    try {
      const transport = createTransport(authorizationAcknowledged);
      transportRef.current = transport;
      const nextTerminal = new Terminal({
        allowProposedApi: false,
        convertEol: true,
        cursorBlink: true,
        fontFamily: '"DM Mono", monospace',
        fontSize: 12,
        scrollback: 2_000,
        theme: { background: '#10191b', foreground: '#b8cbc6' },
        windowOptions: {},
        linkHandler: null,
      });
      const nextFitAddon = new FitAddon();
      terminal.current = nextTerminal;
      fitAddon.current = nextFitAddon;
      nextTerminal.loadAddon(nextFitAddon);
      nextTerminal.open(container.current);
      nextFitAddon.fit();
      acceptingInput.current = false;

      inputSubscription.current = nextTerminal.onData((input) => {
        if (!activeRef.current || !acceptingInput.current || token.disposed) return;
        const prepared = prepareTerminalInput(input, inputPolicy);
        if (prepared.byteCount > 4_096) {
          setPendingPaste(undefined);
          setError({
            code: 'terminal_input_limit',
            message: 'Terminal input is too large.',
            retryable: false,
          });
          return;
        }
        setError(undefined);
        if (prepared.requiresConfirmation) {
          setPendingPaste({
            data: prepared.data,
            lineCount: prepared.lineCount,
            characterCount: prepared.characterCount,
          });
        } else {
          send(prepared.data, token);
        }
      });
      const resize = () => {
        if (token.disposed) return;
        nextFitAddon.fit();
        transport.resize(nextTerminal.cols, nextTerminal.rows);
      };
      resizeHandler.current = resize;
      resizeObserver.current = typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(resize);
      resizeObserver.current?.observe(container.current);
      window.addEventListener('resize', resize);
      const pageHide = () => {
        token.disposed = true;
        void shutdown();
      };
      pageHideHandler.current = pageHide;
      window.addEventListener('pagehide', pageHide);

      void transport.open((event) => handleTransportEvent(event, token)).catch((openError: unknown) => {
        if (token.disposed) return;
        token.disposed = true;
        void shutdown(sanitizedError(openError, {
          code: 'terminal_open_failed',
          message: 'Unable to open the terminal session.',
          retryable: true,
        }));
      });
    } catch (openError) {
      token.disposed = true;
      void shutdown(sanitizedError(openError, {
        code: 'terminal_open_failed',
        message: 'Unable to open the terminal session.',
        retryable: true,
      }));
    }
  };

  const disconnect = () => {
    if (sessionToken.current !== null) sessionToken.current.disposed = true;
    void shutdown();
  };

  const confirmPaste = () => {
    const pending = pendingPaste;
    const token = sessionToken.current;
    setPendingPaste(undefined);
    if (pending !== undefined && token !== null) send(pending.data, token);
  };

  return (
    <div className="terminal-session">
      {!accepted && !reopenBlocked ? (
        <div className="terminal-consent">
          <InlineNotice tone="warning" title={warningTitle}>{warningBody}</InlineNotice>
          {configuration}
          {requireAuthorization ? (
            <label className="usb-console-authorization">
              <input
                type="checkbox"
                checked={authorized}
                onChange={(event) => setAuthorized(event.target.checked)}
              />
              {acknowledgementLabel}
            </label>
          ) : null}
          <Button
            size="small"
            disabled={openDisabled || (requireAuthorization && !authorized)}
            onClick={open}
          >
            {openLabel ?? (requireAuthorization ? 'Open terminal session' : acknowledgementLabel)}
          </Button>
        </div>
      ) : null}
      <div hidden={!accepted}>
        <div className="terminal-session__status">
          <span>DIRECT MODE</span>
          <span>{status.toUpperCase()}</span>
        </div>
        <div ref={container} className="terminal-session__canvas" aria-label={ariaLabel} />
        {pendingPaste === undefined ? null : (
          <div className="terminal-multiline-warning" role="alert">
            <span>
              {pendingPaste.lineCount} lines and {pendingPaste.characterCount} characters are
              waiting. Review before sending.
            </span>
            <div className="terminal-session__actions">
              <Button size="small" onClick={confirmPaste}>
                Send {pendingPaste.lineCount} lines
              </Button>
              <Button size="small" variant="ghost" onClick={() => setPendingPaste(undefined)}>
                Cancel
              </Button>
            </div>
          </div>
        )}
        <div className="terminal-session__actions">
          <Button size="small" variant="ghost" onClick={disconnect}>Disconnect</Button>
        </div>
      </div>
      {error === undefined ? null : (
        <div ref={errorContainer} className="form-error" role="alert">
          <span>{error.message}</span>
          {error.recommendedAction === undefined ? null : <span>{error.recommendedAction}</span>}
          {error.retryable ? (
            <Button
              size="small"
              disabled={openDisabled || (requireAuthorization && !authorized)}
              onClick={open}
            >
              Retry
            </Button>
          ) : null}
        </div>
      )}
      <p className="terminal-note">{note}</p>
    </div>
  );
}
