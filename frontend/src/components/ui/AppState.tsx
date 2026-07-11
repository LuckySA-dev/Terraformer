import {
  Cable,
  CircleAlert,
  Inbox,
  LoaderCircle,
  ShieldCheck,
  ShieldOff,
  TriangleAlert,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { isDisconnectedError } from '../../api/client';
import { Button } from './Button';

export type AppStateKind = 'empty' | 'loading' | 'error' | 'disconnected' | 'unsupported';

interface AppStateProps {
  kind: AppStateKind;
  title: string;
  message: string;
  actionLabel?: string;
  onAction?: () => void;
  compact?: boolean;
  accessory?: ReactNode;
}

const icons = {
  empty: Inbox,
  loading: LoaderCircle,
  error: CircleAlert,
  disconnected: Cable,
  unsupported: ShieldOff,
} as const;

export function AppState({
  kind,
  title,
  message,
  actionLabel,
  onAction,
  compact = false,
  accessory,
}: AppStateProps) {
  const Icon = icons[kind];
  return (
    <div className={`app-state app-state--${kind} ${compact ? 'app-state--compact' : ''}`.trim()}>
      <div className="app-state__icon" aria-hidden="true">
        <Icon size={compact ? 18 : 24} className={kind === 'loading' ? 'spin' : ''} />
      </div>
      <div className="app-state__copy">
        <h3>{title}</h3>
        <p>{message}</p>
      </div>
      {accessory}
      {actionLabel !== undefined && onAction !== undefined ? (
        <Button size="small" onClick={onAction}>
          {actionLabel}
        </Button>
      ) : null}
    </div>
  );
}

export function QueryErrorState({
  error,
  onRetry,
  compact = false,
}: {
  error: unknown;
  onRetry: () => void;
  compact?: boolean;
}) {
  const disconnected = isDisconnectedError(error);
  return (
    <AppState
      kind={disconnected ? 'disconnected' : 'error'}
      title={disconnected ? 'Local service disconnected' : 'Could not load this data'}
      message={
        disconnected
          ? 'The browser cannot reach the local API. Check that the app services are running.'
          : error instanceof Error
            ? error.message
            : 'An unexpected error occurred.'
      }
      actionLabel="Try again"
      onAction={onRetry}
      compact={compact}
    />
  );
}

export function InlineNotice({
  tone,
  title,
  children,
}: PropsWithChildren<{ tone: 'safe' | 'warning' | 'danger' | 'info'; title: string }>) {
  const Icon = tone === 'warning' || tone === 'danger' ? TriangleAlert : ShieldCheck;
  return (
    <div className={`inline-notice inline-notice--${tone}`}>
      <Icon size={17} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <span>{children}</span>
      </div>
    </div>
  );
}

type PropsWithChildren<T> = T & { children?: ReactNode };
