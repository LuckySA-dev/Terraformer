import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react';

interface FieldShellProps {
  label: string;
  htmlFor: string;
  error?: string | undefined;
  hint?: string | undefined;
  action?: ReactNode | undefined;
  children: ReactNode;
}

function FieldShell({ label, htmlFor, error, hint, action, children }: FieldShellProps) {
  return (
    <div className="field">
      <div className="field__label-row">
        <label htmlFor={htmlFor}>{label}</label>
        {action}
      </div>
      {children}
      {error === undefined ? null : (
        <span className="field__error" role="alert">
          {error}
        </span>
      )}
      {error === undefined && hint !== undefined ? <span className="field__hint">{hint}</span> : null}
    </div>
  );
}

interface InputFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string | undefined;
  hint?: string | undefined;
  action?: ReactNode | undefined;
}

export function InputField({ label, error, hint, action, id, className = '', ...props }: InputFieldProps) {
  const inputId = id ?? props.name ?? label.toLowerCase().replaceAll(' ', '-');
  return (
    <FieldShell
      label={label}
      htmlFor={inputId}
      {...(error !== undefined ? { error } : {})}
      {...(hint !== undefined ? { hint } : {})}
      {...(action !== undefined ? { action } : {})}
    >
      <input
        {...props}
        id={inputId}
        className={`input ${error === undefined ? '' : 'input--error'} ${className}`.trim()}
        aria-invalid={error === undefined ? undefined : true}
      />
    </FieldShell>
  );
}

interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  error?: string | undefined;
  hint?: string | undefined;
  action?: ReactNode | undefined;
  children: ReactNode;
}

export function SelectField({
  label,
  error,
  hint,
  action,
  id,
  className = '',
  children,
  ...props
}: SelectFieldProps) {
  const inputId = id ?? props.name ?? label.toLowerCase().replaceAll(' ', '-');
  return (
    <FieldShell
      label={label}
      htmlFor={inputId}
      {...(error !== undefined ? { error } : {})}
      {...(hint !== undefined ? { hint } : {})}
      {...(action !== undefined ? { action } : {})}
    >
      <select
        {...props}
        id={inputId}
        className={`input select ${error === undefined ? '' : 'input--error'} ${className}`.trim()}
        aria-invalid={error === undefined ? undefined : true}
      >
        {children}
      </select>
    </FieldShell>
  );
}
