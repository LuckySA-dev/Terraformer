import { zodResolver } from '@hookform/resolvers/zod';
import { Eye, EyeOff, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import type { CredentialProfileInput } from '../../types/api';
import { InlineNotice } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { InputField } from '../../components/ui/FormField';

const credentialSchema = z.object({
  name: z.string().trim().min(1, 'Enter a profile name.').max(100),
  username: z.string().trim().min(1, 'Enter a username.').max(255),
  password: z.string().min(1, 'Enter the device password.').max(1024),
  enable_password: z.string().max(1024),
});

type CredentialFields = z.infer<typeof credentialSchema>;

interface CredentialFormProps {
  onSubmit: (input: CredentialProfileInput) => Promise<void>;
  onCancel: () => void;
  error?: string | undefined;
}

export function CredentialForm({ onSubmit, onCancel, error }: CredentialFormProps) {
  const [showSecrets, setShowSecrets] = useState(false);
  const form = useForm<CredentialFields>({
    resolver: zodResolver(credentialSchema),
    defaultValues: { name: '', username: '', password: '', enable_password: '' },
  });

  const submit = async (values: CredentialFields) => {
    const input: CredentialProfileInput = {
      name: values.name,
      username: values.username,
      password: values.password,
      ...(values.enable_password.length > 0 ? { enable_password: values.enable_password } : {}),
    };
    await onSubmit(input);
  };

  return (
    <form className="stack-form" onSubmit={form.handleSubmit(submit)} noValidate>
      <InlineNotice tone="safe" title="Encrypted at rest">
        Secret values are sent only to the local API and never returned after this profile is saved.
      </InlineNotice>
      <InputField
        label="Profile name"
        placeholder="Lab admin"
        autoComplete="off"
        error={form.formState.errors.name?.message}
        {...form.register('name')}
      />
      <InputField
        label="Device username"
        placeholder="automation"
        autoComplete="username"
        error={form.formState.errors.username?.message}
        {...form.register('username')}
      />
      <InputField
        label="Device password"
        type={showSecrets ? 'text' : 'password'}
        autoComplete="new-password"
        error={form.formState.errors.password?.message}
        action={
          <button
            type="button"
            className="field-action"
            onClick={() => setShowSecrets((current) => !current)}
            aria-label={showSecrets ? 'Hide passwords' : 'Show passwords'}
          >
            {showSecrets ? <EyeOff size={14} /> : <Eye size={14} />}
            {showSecrets ? 'Hide' : 'Show'}
          </button>
        }
        {...form.register('password')}
      />
      <InputField
        label="Enable password"
        type={showSecrets ? 'text' : 'password'}
        autoComplete="new-password"
        hint="Optional. Used only for read commands that require enable mode."
        error={form.formState.errors.enable_password?.message}
        {...form.register('enable_password')}
      />
      {error === undefined ? null : (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}
      <div className="form-actions">
        <Button onClick={onCancel}>Cancel</Button>
        <Button type="submit" variant="primary" busy={form.formState.isSubmitting}>
          <ShieldCheck size={16} /> Save encrypted profile
        </Button>
      </div>
    </form>
  );
}
