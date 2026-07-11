import type { PropsWithChildren } from 'react';

export type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'purple';

interface BadgeProps {
  tone?: BadgeTone;
  dot?: boolean;
  className?: string;
}

export function Badge({
  children,
  tone = 'neutral',
  dot = false,
  className = '',
}: PropsWithChildren<BadgeProps>) {
  return (
    <span className={`badge badge--${tone} ${className}`.trim()}>
      {dot ? <span className="badge__dot" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
