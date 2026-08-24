import { zodResolver } from '@hookform/resolvers/zod';
import { Eye, EyeOff, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { z } from 'zod';
import type { ProviderProfile, ProviderProfileInput } from '../../types/api';
import { InlineNotice } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { InputField } from '../../components/ui/FormField';

const providerFieldsSchema = z.object({
  name: z.string().trim().min(1, 'Enter a profile name.').max(100),
  base_url: z.string().trim().min(1, 'Enter a base URL.').max(500),
  model_id: z.string().trim().min(1, 'Enter a model ID.').max(200),
  api_key: z.string().max(4096),
  clear_api_key: z.boolean(),
});

type ProviderFields = z.infer<typeof providerFieldsSchema>;

interface ProviderProfileFormProps {
  profile?: ProviderProfile;
  onSubmit: (input: Partial<ProviderProfileInput>) => Promise<void>;
  onCancel: () => void;
  error?: string | undefined;
}

export function ProviderProfileForm({ profile, onSubmit, onCancel, error }: ProviderProfileFormProps) {
  const [showSecrets, setShowSecrets] = useState(false);
  const isEditing = profile !== undefined;
  const form = useForm<ProviderFields>({
    resolver: zodResolver(providerFieldsSchema),
    defaultValues: {
      name: profile?.name ?? '',
      base_url: profile?.base_url ?? '',
      model_id: profile?.model_id ?? '',
      api_key: '',
      clear_api_key: false,
    },
  });
  const clearApiKey = useWatch({ control: form.control, name: 'clear_api_key' });

  const submit = async (values: ProviderFields) => {
    const input: Partial<ProviderProfileInput> = {
      name: values.name.trim(),
      base_url: values.base_url.trim(),
      model_id: values.model_id.trim(),
      ...(values.api_key.length > 0 && !clearApiKey ? { api_key: values.api_key } : {}),
      ...(isEditing && clearApiKey ? { clear_api_key: true } : {}),
    };
    await onSubmit(input);
  };

  return (
    <form className="stack-form" onSubmit={form.handleSubmit(submit)} noValidate>
      <InlineNotice tone="safe" title="BYOK, encrypted at rest">
        No model runs in this application -- requests proxy to whatever endpoint you name below.
        The API key is sent only to the local API and never returned after this profile is saved.
      </InlineNotice>
      <InputField
        label="Profile name"
        placeholder="Local Ollama"
        autoComplete="off"
        error={form.formState.errors.name?.message}
        {...form.register('name')}
      />
      <InputField
        label="Base URL"
        placeholder="http://localhost:11434/v1"
        autoComplete="off"
        hint="Any OpenAI-compatible endpoint -- OpenAI itself, a self-hosted Ollama, LM Studio, etc."
        error={form.formState.errors.base_url?.message}
        {...form.register('base_url')}
      />
      <InputField
        label="Model ID"
        placeholder="llama3.1"
        autoComplete="off"
        error={form.formState.errors.model_id?.message}
        {...form.register('model_id')}
      />
      <InputField
        label="API key"
        type={showSecrets ? 'text' : 'password'}
        autoComplete="new-password"
        disabled={clearApiKey}
        hint={
          isEditing
            ? 'Optional. Leave blank to keep the current value.'
            : 'Optional -- some local endpoints need no key.'
        }
        action={
          <button
            type="button"
            className="field-action"
            onClick={() => setShowSecrets((current) => !current)}
            aria-label={showSecrets ? 'Hide API key' : 'Show API key'}
          >
            {showSecrets ? <EyeOff size={14} /> : <Eye size={14} />}
            {showSecrets ? 'Hide' : 'Show'}
          </button>
        }
        {...form.register('api_key')}
      />
      {isEditing && profile.has_api_key ? (
        <label className="usb-console-echo">
          <input type="checkbox" {...form.register('clear_api_key')} />
          Clear the saved API key
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
          <ShieldCheck size={16} /> {isEditing ? 'Save changes' : 'Save profile'}
        </Button>
      </div>
    </form>
  );
}
