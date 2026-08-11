import { zodResolver } from '@hookform/resolvers/zod';
import { Eye, EyeOff, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { z } from 'zod';
import type { CredentialProfile, CredentialProfileInput } from '../../types/api';
import { InlineNotice } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { InputField } from '../../components/ui/FormField';

const credentialFieldsSchema = z.object({
  name: z.string().trim().min(1, 'Enter a profile name.').max(100),
  username: z.string().max(255),
  password: z.string().max(1024),
  enable_password: z.string().max(1024),
  clear_enable_password: z.boolean(),
});

type CredentialFields = z.infer<typeof credentialFieldsSchema>;

// Username and password are only required outright when creating a new
// profile. Editing an existing one reads back has_username/has_password
// booleans, never the values themselves, so a blank field there means
// "leave this unchanged," not "clear it" — enforced below, not by the schema.
function credentialSchema(isEditing: boolean) {
  return credentialFieldsSchema.superRefine((value, context) => {
    if (isEditing) return;
    if (value.username.trim().length === 0) {
      context.addIssue({ code: 'custom', path: ['username'], message: 'Enter a username.' });
    }
    if (value.password.length === 0) {
      context.addIssue({ code: 'custom', path: ['password'], message: 'Enter the device password.' });
    }
  });
}

interface CredentialFormProps {
  credential?: CredentialProfile;
  onSubmit: (input: Partial<CredentialProfileInput>) => Promise<void>;
  onCancel: () => void;
  error?: string | undefined;
}

export function CredentialForm({ credential, onSubmit, onCancel, error }: CredentialFormProps) {
  const [showSecrets, setShowSecrets] = useState(false);
  const isEditing = credential !== undefined;
  const form = useForm<CredentialFields>({
    resolver: zodResolver(credentialSchema(isEditing)),
    defaultValues: {
      name: credential?.name ?? '',
      username: '',
      password: '',
      enable_password: '',
      clear_enable_password: false,
    },
  });
  const clearEnablePassword = useWatch({ control: form.control, name: 'clear_enable_password' });

  const submit = async (values: CredentialFields) => {
    const input: Partial<CredentialProfileInput> = {
      name: values.name.trim(),
      ...(values.username.trim().length > 0 ? { username: values.username.trim() } : {}),
      ...(values.password.length > 0 ? { password: values.password } : {}),
      ...(values.enable_password.length > 0 && !clearEnablePassword
        ? { enable_password: values.enable_password }
        : {}),
      ...(isEditing && clearEnablePassword ? { clear_enable_password: true } : {}),
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
        hint={isEditing ? 'Leave blank to keep the current username.' : undefined}
        error={form.formState.errors.username?.message}
        {...form.register('username')}
      />
      <InputField
        label="Device password"
        type={showSecrets ? 'text' : 'password'}
        autoComplete="new-password"
        hint={isEditing ? 'Leave blank to keep the current password.' : undefined}
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
        disabled={clearEnablePassword}
        hint={
          isEditing
            ? 'Optional. Leave blank to keep the current value.'
            : 'Optional. Used only for read commands that require enable mode.'
        }
        error={form.formState.errors.enable_password?.message}
        {...form.register('enable_password')}
      />
      {isEditing && credential.has_enable_password ? (
        <label className="usb-console-echo">
          <input type="checkbox" {...form.register('clear_enable_password')} />
          Clear the saved enable password
        </label>
      ) : null}
      {error === undefined ? null : (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}
      <div className="form-actions">
        <Button onClick={onCancel}>Cancel</Button>
        <Button type="submit" variant="primary" busy={form.formState.isSubmitting}>
          <ShieldCheck size={16} /> {isEditing ? 'Save changes' : 'Save encrypted profile'}
        </Button>
      </div>
    </form>
  );
}
