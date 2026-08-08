import { AlertTriangle, XCircle } from 'lucide-react';
import { ApiError } from '../../api/client';

/**
 * Renders a device connection failure as the stage that failed plus what to do
 * about it.
 *
 * The backend already returns `code`, `phase`, `retryable` and often
 * `recommended_action`; the UI previously showed only the one-line message, so
 * an operator saw "the device rejected the credential profile" for what was
 * really an algorithm mismatch.
 */

const STAGES = ['tcp_connection', 'ssh_negotiation', 'host_key_verification', 'authentication'] as const;

type Stage = (typeof STAGES)[number];

const STAGE_LABELS: Record<Stage, string> = {
  tcp_connection: 'Reach the device',
  ssh_negotiation: 'Agree on encryption',
  host_key_verification: 'Verify identity',
  authentication: 'Sign in',
};

// Extra guidance for causes whose generic message sends operators down the
// wrong path. Keyed by the backend error code.
const EXTRA_GUIDANCE: Record<string, string> = {
  legacy_ssh_negotiation_failed:
    'This is not a password problem. The device offers only algorithms this client disables by default. Raise the SSH compatibility mode, and if it is a Catalyst 2960/2960-X or ISR 1941, check whether its RSA host key is smaller than 1024 bits.',
  device_connection_refused:
    'Nothing is listening on that port. On GNS3/EVE-NG the console port is usually not 22, and SSH often has to be enabled on the node first.',
  device_name_resolution_failed:
    'The address could not be resolved. From a container, a lab on this machine is reachable as host.docker.internal rather than localhost.',
  device_host_key_changed:
    'The device presented a different host key than the one pinned. On a virtual lab this is normal after a node restart and lab devices can be re-pinned; on real hardware, confirm the device identity before trusting it.',
};

interface ConnectionErrorProps {
  error: unknown;
  /** Shown when the failure is not an ApiError (network drop, abort). */
  fallback?: string;
}

interface Parsed {
  message: string;
  code?: string;
  phase?: string;
  retryable?: boolean;
  recommendedAction?: string;
}

function parse(error: unknown, fallback: string): Parsed {
  if (!(error instanceof ApiError)) return { message: fallback };
  const details = error.details;
  const read = (key: string): string | undefined => {
    if (typeof details !== 'object' || details === null || !(key in details)) return undefined;
    const value = (details as Record<string, unknown>)[key];
    return typeof value === 'string' ? value : undefined;
  };
  const retryable =
    typeof details === 'object' && details !== null && 'retryable' in details
      ? (details as Record<string, unknown>).retryable === true
      : undefined;
  const phase = read('phase');
  const recommendedAction = read('recommended_action');
  return {
    message: error.message,
    code: error.code,
    ...(phase === undefined ? {} : { phase }),
    ...(retryable === undefined ? {} : { retryable }),
    ...(recommendedAction === undefined ? {} : { recommendedAction }),
  };
}

function isStage(value: string | undefined): value is Stage {
  return STAGES.includes(value as Stage);
}

export function ConnectionError({
  error,
  fallback = 'The connection could not complete.',
}: ConnectionErrorProps) {
  const parsed = parse(error, fallback);
  const failedAt = isStage(parsed.phase) ? parsed.phase : undefined;
  const extra = parsed.code === undefined ? undefined : EXTRA_GUIDANCE[parsed.code];

  return (
    <div className="connection-error" role="alert">
      <div className="connection-error__headline">
        <XCircle size={17} aria-hidden />
        <span>{parsed.message}</span>
      </div>

      {failedAt === undefined ? null : (
        <ol className="connection-error__stages" aria-label="Connection stages">
          {STAGES.map((stage) => {
            const index = STAGES.indexOf(stage);
            const failedIndex = STAGES.indexOf(failedAt);
            const state = index < failedIndex ? 'done' : index === failedIndex ? 'failed' : 'pending';
            return (
              <li key={stage} className={`connection-error__stage connection-error__stage--${state}`}>
                <span className="connection-error__stage-dot" aria-hidden />
                <span>{STAGE_LABELS[stage]}</span>
                {state === 'failed' ? <span className="connection-error__stage-tag">failed here</span> : null}
              </li>
            );
          })}
        </ol>
      )}

      {parsed.recommendedAction === undefined ? null : (
        <p className="connection-error__action">{parsed.recommendedAction}</p>
      )}

      {extra === undefined ? null : (
        <p className="connection-error__hint">
          <AlertTriangle size={14} aria-hidden /> {extra}
        </p>
      )}

      {parsed.retryable === true ? (
        <p className="connection-error__retry">This one is worth retrying.</p>
      ) : null}
    </div>
  );
}
