import type { ButtonHTMLAttributes, PropsWithChildren } from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'small' | 'medium';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  busy?: boolean;
}

export function Button({
  children,
  className = '',
  variant = 'secondary',
  size = 'medium',
  busy = false,
  disabled,
  type = 'button',
  ...props
}: PropsWithChildren<ButtonProps>) {
  return (
    <button
      {...props}
      type={type}
      className={`button button--${variant} button--${size} ${className}`.trim()}
      disabled={disabled === true || busy}
      aria-busy={busy}
    >
      {busy ? <span className="button__spinner" aria-hidden="true" /> : null}
      {children}
    </button>
  );
}
