import { zodResolver } from '@hookform/resolvers/zod';
import { Eye, EyeOff, RefreshCw, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { z } from 'zod';
import { api } from '../../api/network';
import type { ProviderProfile, ProviderProfileInput, ProviderType } from '../../types/api';
import { InlineNotice } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { InputField, SelectField } from '../../components/ui/FormField';

const providerFieldsSchema = z.object({
  name: z.string().trim().min(1, 'Enter a profile name.').max(100),
  provider_type: z.enum(['openai_compatible', 'anthropic']),
  base_url: z.string().trim().min(1, 'Enter a base URL.').max(500),
  api_key: z.string().max(4096),
  clear_api_key: z.boolean(),
});

type ProviderFields = z.infer<typeof providerFieldsSchema>;

// A base URL is a published constant per provider, not something the operator
// should have to dig out of docs -- only the key is theirs. providerType
// selects the backend adapter: everything here speaks the OpenAI wire format
// except Anthropic, whose own API is a different format rather than just a
// different URL.
interface ProviderPreset {
  label: string;
  baseUrl: string;
  providerType: ProviderType;
}

const PROVIDER_PRESET_GROUPS: { group: string; presets: ProviderPreset[] }[] = [
  {
    group: 'One key, every model',
    presets: [
      {
        label: 'OpenRouter',
        baseUrl: 'https://openrouter.ai/api/v1',
        providerType: 'openai_compatible',
      },
    ],
  },
  {
    group: 'One key, that provider only',
    presets: [
      {
        label: 'Anthropic (Claude)',
        baseUrl: 'https://api.anthropic.com',
        providerType: 'anthropic',
      },
      {
        label: 'OpenAI',
        baseUrl: 'https://api.openai.com/v1',
        providerType: 'openai_compatible',
      },
      // Gemini's docs require the trailing slash; the openai SDK re-adds it
      // after our base_url validator strips it, so this stays correct.
      {
        label: 'Google Gemini',
        baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai/',
        providerType: 'openai_compatible',
      },
      { label: 'Mistral', baseUrl: 'https://api.mistral.ai/v1', providerType: 'openai_compatible' },
      {
        label: 'DeepSeek',
        baseUrl: 'https://api.deepseek.com/v1',
        providerType: 'openai_compatible',
      },
      { label: 'xAI (Grok)', baseUrl: 'https://api.x.ai/v1', providerType: 'openai_compatible' },
      {
        label: 'Groq',
        baseUrl: 'https://api.groq.com/openai/v1',
        providerType: 'openai_compatible',
      },
      {
        label: 'Together AI',
        baseUrl: 'https://api.together.xyz/v1',
        providerType: 'openai_compatible',
      },
    ],
  },
  {
    group: 'Runs on your own machine',
    presets: [
      {
        label: 'Ollama (local)',
        baseUrl: 'http://localhost:11434/v1',
        providerType: 'openai_compatible',
      },
      {
        label: 'LM Studio (local)',
        baseUrl: 'http://localhost:1234/v1',
        providerType: 'openai_compatible',
      },
    ],
  },
  {
    group: 'Anything else',
    presets: [{ label: 'Custom', baseUrl: '', providerType: 'openai_compatible' }],
  },
];

const PROVIDER_PRESETS = PROVIDER_PRESET_GROUPS.flatMap((entry) => entry.presets);

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
      provider_type: profile?.provider_type ?? 'openai_compatible',
      base_url: profile?.base_url ?? '',
      api_key: '',
      clear_api_key: false,
    },
  });
  const clearApiKey = useWatch({ control: form.control, name: 'clear_api_key' });
  const baseUrl = useWatch({ control: form.control, name: 'base_url' });
  const apiKey = useWatch({ control: form.control, name: 'api_key' });
  const providerType = useWatch({ control: form.control, name: 'provider_type' });

  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<string>();
  const [verifyError, setVerifyError] = useState<string>();

  const verifyConnection = async () => {
    const trimmedBaseUrl = baseUrl.trim();
    if (trimmedBaseUrl === '') {
      setVerifyError('Enter a base URL first.');
      setVerifyResult(undefined);
      return;
    }
    setVerifying(true);
    setVerifyError(undefined);
    setVerifyResult(undefined);
    try {
      const response = await api.listProviderModels(
        trimmedBaseUrl,
        apiKey.trim() || undefined,
        providerType,
      );
      setVerifyResult(
        response.models.length > 0
          ? `Reachable -- ${String(response.models.length)} model(s) available. You'll pick one when you start a chat.`
          : 'Reachable, but the provider returned no models.',
      );
    } catch {
      setVerifyError('Could not reach that endpoint.');
    } finally {
      setVerifying(false);
    }
  };

  const submit = async (values: ProviderFields) => {
    const input: Partial<ProviderProfileInput> = {
      name: values.name.trim(),
      provider_type: values.provider_type,
      base_url: values.base_url.trim(),
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
      <SelectField
        label="Provider"
        hint="Fills in the base URL for you -- you only need the API key. OpenRouter reaches Claude, Gemini, GPT and more on one key."
        defaultValue=""
        onChange={(event) => {
          const preset = PROVIDER_PRESETS.find((candidate) => candidate.label === event.target.value);
          setVerifyResult(undefined);
          setVerifyError(undefined);
          if (!preset) return;
          form.setValue('provider_type', preset.providerType, { shouldDirty: true });
          if (preset.baseUrl !== '') {
            form.setValue('base_url', preset.baseUrl, { shouldValidate: true, shouldDirty: true });
          }
        }}
      >
        <option value="" disabled>
          Choose a provider...
        </option>
        {PROVIDER_PRESET_GROUPS.map((entry) => (
          <optgroup key={entry.group} label={entry.group}>
            {entry.presets.map((preset) => (
              <option key={preset.label} value={preset.label}>
                {preset.label}
              </option>
            ))}
          </optgroup>
        ))}
      </SelectField>
      <InputField
        label="Base URL"
        placeholder="http://localhost:11434/v1"
        autoComplete="off"
        hint={
          verifyResult ??
          'Any OpenAI-compatible endpoint -- OpenAI itself, a self-hosted Ollama, LM Studio, etc.'
        }
        error={form.formState.errors.base_url?.message ?? verifyError}
        action={
          <button
            type="button"
            className="field-action"
            onClick={() => void verifyConnection()}
            disabled={verifying}
          >
            <RefreshCw size={14} className={verifying ? 'spin' : undefined} />
            {verifying ? 'Verifying...' : 'Verify connection'}
          </button>
        }
        {...form.register('base_url')}
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
