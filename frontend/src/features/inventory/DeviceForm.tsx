import { zodResolver } from '@hookform/resolvers/zod';
import { CheckCircle2, KeyRound, PlugZap, RotateCcw, ShieldCheck, XCircle } from 'lucide-react';
import { useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { z } from 'zod';
import { ApiError } from '../../api/client';
import { api } from '../../api/network';
import type { ConnectionTestResult, CredentialProfile, Device, DeviceInput } from '../../types/api';
import { InlineNotice } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { InputField, SelectField } from '../../components/ui/FormField';

const addressPattern = /^(?=.{1,253}$)[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?$/;

const deviceSchema = z.object({
  name: z.string().trim().min(1, 'Enter a display name.').max(100),
  management_address: z
    .string()
    .trim()
    .min(1, 'Enter a management address.')
    .regex(addressPattern, 'Enter a valid IPv4 address or DNS hostname.')
    .refine((value) => !value.includes('..'), 'Enter a valid IPv4 address or DNS hostname.'),
  port: z.number().int().min(1, 'Port must be between 1 and 65535.').max(65_535),
  vendor: z.enum(['cisco_iosxe', 'generic']),
  credential_profile_id: z.uuid('Select a credential profile.'),
  ssh_compatibility: z.enum(['modern', 'cisco_legacy', 'cisco_legacy_group1']),
  group1_risk_acknowledged: z.boolean(),
}).superRefine((value, context) => {
  if (value.ssh_compatibility === 'cisco_legacy_group1' && !value.group1_risk_acknowledged) {
    context.addIssue({
      code: 'custom',
      path: ['group1_risk_acknowledged'],
      message: 'Acknowledge the Group1 risk before testing this connection.',
    });
  }
});

type DeviceFields = z.infer<typeof deviceSchema>;

interface DeviceFormProps {
  device?: Device;
  initial?: Pick<DeviceInput, 'management_address' | 'port'>;
  credentials: CredentialProfile[];
  onSubmit: (input: DeviceInput) => Promise<void>;
  onCancel: () => void;
  onCreateCredential: () => void;
  error?: string | undefined;
}

const fingerprint = (input: DeviceInput): string =>
  JSON.stringify({
    management_address: input.management_address,
    port: input.port,
    vendor: input.vendor,
    credential_profile_id: input.credential_profile_id,
    ssh_compatibility: input.ssh_compatibility,
    group1_risk_acknowledged: input.group1_risk_acknowledged,
  });

function connectionErrorText(error: unknown): string {
  if (!(error instanceof ApiError)) return 'The connection test could not complete.';
  const details = error.details;
  const recommendedAction =
    typeof details === 'object' &&
    details !== null &&
    'recommended_action' in details &&
    typeof details.recommended_action === 'string'
      ? details.recommended_action
      : undefined;
  return recommendedAction === undefined ? error.message : `${error.message} ${recommendedAction}`;
}

export function DeviceForm({
  device,
  initial,
  credentials,
  onSubmit,
  onCancel,
  onCreateCredential,
  error,
}: DeviceFormProps) {
  const [testedFingerprint, setTestedFingerprint] = useState<string>();
  const [testResult, setTestResult] = useState<ConnectionTestResult>();
  const [testError, setTestError] = useState<string>();
  const [testing, setTesting] = useState(false);
  const form = useForm<DeviceFields>({
    resolver: zodResolver(deviceSchema),
    defaultValues: {
      name: device?.name ?? '',
      management_address: device?.management_address ?? initial?.management_address ?? '',
      port: device?.port ?? initial?.port ?? 22,
      vendor: device?.vendor === 'generic' ? 'generic' : 'cisco_iosxe',
      credential_profile_id: device?.credential_profile_id ?? '',
      ssh_compatibility: device?.ssh_compatibility ?? 'modern',
      group1_risk_acknowledged: false,
    },
  });
  const watchedConnection = useWatch({ control: form.control });

  const toInput = (values: DeviceFields): DeviceInput => ({
    name: values.name.trim(),
    management_address: values.management_address.trim(),
    port: values.port,
    vendor: values.vendor,
    credential_profile_id: values.credential_profile_id,
    ssh_compatibility: values.ssh_compatibility,
    group1_risk_acknowledged: values.group1_risk_acknowledged,
  });

  const testConnection = async () => {
    const valid = await form.trigger();
    if (!valid) return;
    const input = toInput(form.getValues());
    setTesting(true);
    setTestError(undefined);
    setTestResult(undefined);
    try {
      const result = await api.testCandidateConnection(input);
      setTestResult(result);
      setTestedFingerprint(result.reachable ? fingerprint(input) : undefined);
    } catch (connectionError) {
      setTestedFingerprint(undefined);
      setTestError(connectionErrorText(connectionError));
    } finally {
      setTesting(false);
    }
  };

  const submit = async (values: DeviceFields) => {
    const input = toInput(values);
    if (testedFingerprint !== fingerprint(input) || testResult?.reachable !== true) {
      setTestError('Test this exact connection successfully before saving.');
      return;
    }
    await onSubmit(input);
  };

  const currentFingerprint = JSON.stringify({
    management_address: watchedConnection.management_address?.trim() ?? '',
    port: watchedConnection.port ?? 0,
    vendor: watchedConnection.vendor ?? '',
    credential_profile_id: watchedConnection.credential_profile_id ?? '',
    ssh_compatibility: watchedConnection.ssh_compatibility ?? 'modern',
    group1_risk_acknowledged: watchedConnection.group1_risk_acknowledged ?? false,
  });
  const readyToSave = testResult?.reachable === true && testedFingerprint === currentFingerprint;

  return (
    <form className="stack-form" onSubmit={form.handleSubmit(submit)} noValidate>
      <InlineNotice tone="safe" title="Read-only connection">
        A connection happens only when you select Test connection. Current phases run show commands only and
        never writes, reloads, or saves configuration.
      </InlineNotice>
      <div className="form-grid form-grid--two">
        <InputField
          label="Device name"
          placeholder="Core switch"
          autoComplete="off"
          error={form.formState.errors.name?.message}
          {...form.register('name')}
        />
        <SelectField
          label="Platform driver"
          error={form.formState.errors.vendor?.message}
          {...form.register('vendor')}
        >
          <option value="cisco_iosxe">Cisco IOS / IOS-XE</option>
          <option value="generic">Generic (connection test only)</option>
        </SelectField>
      </div>
      <div className="form-grid form-grid--address">
        <InputField
          label="Management address"
          placeholder="192.0.2.10"
          autoComplete="off"
          spellCheck={false}
          error={form.formState.errors.management_address?.message}
          {...form.register('management_address')}
        />
        <InputField
          label="SSH port"
          type="number"
          inputMode="numeric"
          min={1}
          max={65_535}
          error={form.formState.errors.port?.message}
          {...form.register('port', { valueAsNumber: true })}
        />
      </div>
      <SelectField
        label="Credential profile"
        error={form.formState.errors.credential_profile_id?.message}
        hint="Only the profile identifier is stored on this device record."
        action={
          <button type="button" className="field-action" onClick={onCreateCredential}>
            <KeyRound size={14} /> New profile
          </button>
        }
        {...form.register('credential_profile_id')}
      >
        <option value="">Select a profile</option>
        {credentials.map((credential) => (
          <option key={credential.id} value={credential.id}>
            {credential.name}
          </option>
        ))}
      </SelectField>
      <SelectField
        label="SSH compatibility"
        error={form.formState.errors.ssh_compatibility?.message}
        hint="Modern is the default for every new device."
        {...form.register('ssh_compatibility', {
          onChange: () =>
            form.setValue('group1_risk_acknowledged', false, { shouldValidate: true }),
        })}
      >
        <option value="modern">Modern</option>
        <option value="cisco_legacy">Cisco legacy</option>
        <option value="cisco_legacy_group1">Cisco legacy + Group1</option>
      </SelectField>
      {watchedConnection.ssh_compatibility === 'cisco_legacy' ? (
        <InlineNotice tone="warning" title="Per-device SSH exception">
          This is a per-device exception. Terraformer never uses legacy SSH as an automatic fallback.
        </InlineNotice>
      ) : null}
      {watchedConnection.ssh_compatibility === 'cisco_legacy_group1' ? (
        <>
          <InlineNotice tone="warning" title="Last-resort Group1 exception">
            Group1 is a last-resort per-device exception and is never an automatic fallback.
          </InlineNotice>
          <label className="usb-console-echo">
            <input type="checkbox" {...form.register('group1_risk_acknowledged')} />
            I accept the Group1 risk for this device.
          </label>
          {form.formState.errors.group1_risk_acknowledged === undefined ? null : (
            <span className="field__error" role="alert">
              {form.formState.errors.group1_risk_acknowledged.message}
            </span>
          )}
        </>
      ) : null}

      <div className="connection-test">
        <div className="connection-test__header">
          <div>
            <strong>Explicit connection check</strong>
            <span>Required before this record can be saved</span>
          </div>
          <Button onClick={() => void testConnection()} busy={testing}>
            {testResult === undefined ? <PlugZap size={16} /> : <RotateCcw size={16} />}
            {testResult === undefined ? 'Test connection' : 'Test again'}
          </Button>
        </div>
        {testResult === undefined && testError === undefined ? (
          <div className="connection-test__idle">No connection has been attempted.</div>
        ) : null}
        {testResult?.reachable === true ? (
          <div className="connection-test__result connection-test__result--success" role="status">
            <CheckCircle2 size={17} />
            <span>
              <strong>Read-only connection successful</strong>
              {testResult.driver}
              {` · ${String(testResult.latency_ms)} ms`}
            </span>
          </div>
        ) : null}
        {testResult?.reachable === false ? (
          <div className="connection-test__result connection-test__result--error" role="alert">
            <XCircle size={17} />
            <span>
              <strong>Device is unreachable</strong>
              {testResult.message}
            </span>
          </div>
        ) : null}
        {testError === undefined ? null : (
          <div className="connection-test__result connection-test__result--error" role="alert">
            <XCircle size={17} />
            <span>{testError}</span>
          </div>
        )}
      </div>
      {error === undefined ? null : (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}
      <div className="form-actions">
        <Button onClick={onCancel}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!readyToSave} busy={form.formState.isSubmitting}>
          <ShieldCheck size={16} /> {device === undefined ? 'Save device' : 'Save changes'}
        </Button>
      </div>
    </form>
  );
}
