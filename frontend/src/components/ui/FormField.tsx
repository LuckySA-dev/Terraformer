import { useId } from 'react';
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
  // Unique per instance rather than derived from the label. Several config
  // windows can be open at once, and each renders its own "Hostname" field:
  // deriving the id put two of them in the document, which is invalid HTML
  // and made a label focus the other window's input.
  const generatedId = useId();
  const inputId = id ?? generatedId;
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
  // Unique per instance rather than derived from the label. Several config
  // windows can be open at once, and each renders its own "Hostname" field:
  // deriving the id put two of them in the document, which is invalid HTML
  // and made a label focus the other window's input.
  const generatedId = useId();
  const inputId = id ?? generatedId;
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
