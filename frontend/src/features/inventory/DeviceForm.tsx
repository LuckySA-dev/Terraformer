import { zodResolver } from '@hookform/resolvers/zod';
import { CheckCircle2, KeyRound, PlugZap, RotateCcw, ShieldCheck, XCircle } from 'lucide-react';
import { useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { z } from 'zod';
import { ApiError } from '../../api/client';
import { api } from '../../api/network';
import type {
  ConnectionTestResult,
  CredentialProfile,
  Device,
  DeviceInput,
  HostKeyCandidate,
} from '../../types/api';
import { SSH_MODES_BY_VENDOR, SSH_MODE_LABELS } from '../../types/api';
import { InlineNotice } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { ConnectionError } from '../../components/ui/ConnectionError';
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
  vendor: z.enum(['cisco_iosxe', 'fortinet_fortios', 'generic']),
  credential_profile_id: z.uuid('Select a credential profile.'),
  ssh_compatibility: z.enum(['modern', 'cisco_legacy', 'cisco_legacy_group1', 'very_old_ssh']),
  is_lab: z.boolean(),
  console_transport: z.enum(['ssh', 'telnet']),
  group1_risk_acknowledged: z.boolean(),
  very_old_risk_acknowledged: z.boolean(),
}).superRefine((value, context) => {
  if (value.ssh_compatibility === 'cisco_legacy_group1' && !value.group1_risk_acknowledged) {
    context.addIssue({
      code: 'custom',
      path: ['group1_risk_acknowledged'],
      message: 'Acknowledge the Group1 risk before testing this connection.',
    });
  }
  if (value.ssh_compatibility === 'very_old_ssh' && !value.very_old_risk_acknowledged) {
    context.addIssue({
      code: 'custom',
      path: ['very_old_risk_acknowledged'],
      message: 'Acknowledge the Very Old SSH risk before testing this connection.',
    });
  }
  // Mirrors the backend guard so the operator is told immediately rather than
  // after a failed round trip.
  if (value.console_transport === 'telnet' && !value.is_lab) {
    context.addIssue({
      code: 'custom',
      path: ['console_transport'],
      message: 'A telnet console is only available for lab devices.',
    });
  }
  if (!SSH_MODES_BY_VENDOR[value.vendor].includes(value.ssh_compatibility)) {
    context.addIssue({
      code: 'custom',
      path: ['ssh_compatibility'],
      message: 'This compatibility mode is not available for the selected platform driver.',
    });
  }
});

type DeviceFields = z.infer<typeof deviceSchema>;
type ConnectionState = 'uninspected' | 'candidate' | 'confirmed' | 'testing' | 'passed' | 'failed';

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
    very_old_risk_acknowledged: input.very_old_risk_acknowledged,
  });

/** Host-key problems are cleared by inspecting again, not by retrying. */
const HOST_KEY_CODES = new Set([
  'device_host_key_unknown',
  'device_host_key_changed',
  'host_key_candidate_expired',
  'host_key_candidate_mismatch',
]);

const isHostKeyError = (error: unknown): boolean =>
  error instanceof ApiError && HOST_KEY_CODES.has(error.code);

export function DeviceForm({
  device,
  initial,
  credentials,
  onSubmit,
  onCancel,
  onCreateCredential,
  error,
}: DeviceFormProps) {
  const [connectionState, setConnectionState] = useState<ConnectionState>('uninspected');
  const [candidate, setCandidate] = useState<HostKeyCandidate>();
  const [candidateBinding, setCandidateBinding] = useState<string>();
  const [testResult, setTestResult] = useState<ConnectionTestResult>();
  // Holds the thrown error, not a pre-flattened string, so ConnectionError can
  // use the phase and recommended action the backend already sends.
  const [testError, setTestError] = useState<unknown>();
  const [blockedReason, setBlockedReason] = useState<string>();
  const form = useForm<DeviceFields>({
    resolver: zodResolver(deviceSchema),
    defaultValues: {
      name: device?.name ?? '',
      management_address: device?.management_address ?? initial?.management_address ?? '',
      port: device?.port ?? initial?.port ?? 22,
      vendor: device?.vendor ?? 'cisco_iosxe',
      credential_profile_id: device?.credential_profile_id ?? '',
      ssh_compatibility: device?.ssh_compatibility ?? 'modern',
      is_lab: device?.is_lab ?? false,
      console_transport: device?.console_transport ?? 'ssh',
      group1_risk_acknowledged: false,
      very_old_risk_acknowledged: false,
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
    is_lab: values.is_lab,
    console_transport: values.console_transport,
    group1_risk_acknowledged: values.group1_risk_acknowledged,
    very_old_risk_acknowledged: values.very_old_risk_acknowledged,
  });

  const currentFingerprint = JSON.stringify({
    management_address: watchedConnection.management_address?.trim() ?? '',
    port: watchedConnection.port ?? 0,
    vendor: watchedConnection.vendor ?? '',
    credential_profile_id: watchedConnection.credential_profile_id ?? '',
    ssh_compatibility: watchedConnection.ssh_compatibility ?? 'modern',
    group1_risk_acknowledged: watchedConnection.group1_risk_acknowledged ?? false,
    very_old_risk_acknowledged: watchedConnection.very_old_risk_acknowledged ?? false,
  });

  const clearConnectionState = () => {
    setCandidate(undefined);
    setCandidateBinding(undefined);
    setConnectionState('uninspected');
    setTestResult(undefined);
    setTestError(undefined);
    setBlockedReason(undefined);
  };

  const inspectHostKey = async () => {
    const valid = await form.trigger();
    if (!valid) return;
    const input = toInput(form.getValues());
    setConnectionState('testing');
    setTestError(undefined);
    setTestResult(undefined);
    try {
      const result = await api.collectHostKeyCandidate(input);
      setCandidate(result);
      setCandidateBinding(fingerprint(input));
      setConnectionState('candidate');
    } catch (connectionError) {
      setCandidate(undefined);
      setCandidateBinding(undefined);
      setConnectionState('failed');
      setTestError(connectionError);
    }
  };

  const testConnection = async () => {
    const valid = await form.trigger();
    if (!valid || connectionState !== 'confirmed' || candidate === undefined) return;
    const input = { ...toInput(form.getValues()), host_key_candidate_id: candidate.id };
    setConnectionState('testing');
    setTestError(undefined);
    setTestResult(undefined);
    try {
      const result = await api.testCandidateConnection(input);
      setTestResult(result);
      setConnectionState(result.reachable ? 'passed' : 'failed');
    } catch (connectionError) {
      setConnectionState('failed');
      setTestError(connectionError);
      if (isHostKeyError(connectionError)) {
        setCandidate(undefined);
        setCandidateBinding(undefined);
      }
    }
  };

  const submit = async (values: DeviceFields) => {
    const input = toInput(values);
    if (
      candidate === undefined ||
      candidateBinding !== fingerprint(input) ||
      connectionState !== 'passed' ||
      testResult?.reachable !== true
    ) {
      setBlockedReason('Test this exact connection successfully before saving.');
      return;
    }
    await onSubmit({ ...input, host_key_candidate_id: candidate.id });
  };
  const exactCandidate = candidate !== undefined && candidateBinding === currentFingerprint;
  const readyToSave = connectionState === 'passed' && testResult?.reachable === true && exactCandidate;

  // A disabled Save button used to give no reason at all. Name the step that is
  // still outstanding instead.
  const saveBlockedBecause = readyToSave
    ? undefined
    : !exactCandidate
      ? 'Inspect the SSH host key for these exact connection settings.'
      : connectionState === 'candidate'
        ? 'Confirm you verified the fingerprint.'
        : connectionState !== 'passed'
          ? 'Run Test connection and let it succeed.'
          : 'Test connection did not report the device as reachable.';

  const availableModes = SSH_MODES_BY_VENDOR[watchedConnection.vendor ?? 'cisco_iosxe'];
  const steps = [
    { label: 'Inspect host key', done: exactCandidate },
    {
      label: 'Verify fingerprint',
      done: connectionState === 'confirmed' || connectionState === 'passed',
    },
    { label: 'Test connection', done: readyToSave },
  ];

  return (
    <form className="stack-form" onSubmit={form.handleSubmit(submit)} noValidate>
      <InlineNotice tone="safe" title="Read-only connection">
        A connection happens only when you select Test connection. Current phases run show commands only and
        never writes, reloads, or saves configuration.
      </InlineNotice>
      <ol className="device-form__steps" aria-label="Steps required before saving">
        {steps.map((step, index) => (
          <li
            key={step.label}
            className={`device-form__step${step.done ? ' device-form__step--done' : ''}`}
          >
            <span className="device-form__step-number" aria-hidden>
              {step.done ? '✓' : index + 1}
            </span>
            {step.label}
          </li>
        ))}
      </ol>
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
          {...form.register('vendor', {
            onChange: (e: React.ChangeEvent<HTMLSelectElement>) => {
              clearConnectionState();
              // Fall back to the safe mode whenever the new vendor does not
              // support the one currently selected, so the form never holds a
              // combination the backend rejects.
              const vendor = e.target.value as keyof typeof SSH_MODES_BY_VENDOR;
              const allowed = SSH_MODES_BY_VENDOR[vendor];
              if (!allowed.includes(form.getValues('ssh_compatibility'))) {
                form.setValue('ssh_compatibility', 'modern', { shouldValidate: true });
                form.setValue('group1_risk_acknowledged', false, { shouldValidate: true });
                form.setValue('very_old_risk_acknowledged', false, { shouldValidate: true });
              }
            },
          })}
        >
          <option value="cisco_iosxe">Cisco IOS / IOS-XE</option>
          <option value="fortinet_fortios">Fortinet FortiOS (connection test & terminal only)</option>
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
          {...form.register('management_address', { onChange: clearConnectionState })}
        />
        <InputField
          label="SSH port"
          type="number"
          inputMode="numeric"
          min={1}
          max={65_535}
          error={form.formState.errors.port?.message}
          {...form.register('port', { valueAsNumber: true, onChange: clearConnectionState })}
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
        {...form.register('credential_profile_id', { onChange: clearConnectionState })}
      >
        <option value="">Select a profile</option>
        {credentials.map((credential) => (
          <option key={credential.id} value={credential.id}>
            {credential.name}
          </option>
        ))}
      </SelectField>
      <div className="form-grid form-grid--two">
        <SelectField
          label="Device kind"
          hint="Lab devices may re-pin their SSH host key after a restart."
          {...form.register('is_lab', {
            setValueAs: (value: string | boolean) => value === true || value === 'true',
            onChange: () => {
              clearConnectionState();
              form.setValue('console_transport', 'ssh', { shouldValidate: true });
            },
          })}
        >
          <option value="false">Physical / production device</option>
          <option value="true">Virtual lab (GNS3, EVE-NG)</option>
        </SelectField>
        <SelectField
          label="Console transport"
          error={form.formState.errors.console_transport?.message}
          hint="Telnet is cleartext and only offered for lab devices."
          {...form.register('console_transport', { onChange: clearConnectionState })}
        >
          <option value="ssh">SSH</option>
          {watchedConnection.is_lab === true ? <option value="telnet">Telnet</option> : null}
        </SelectField>
      </div>
      {watchedConnection.console_transport === 'telnet' ? (
        <InlineNotice tone="warning" title="Telnet sends everything in cleartext">
          There is no encryption and no host identity to verify, so the SSH host-key pin does not
          apply. Terraformer never sends the stored credentials over Telnet — type them into the
          session yourself. The server must also have TELNET_ENABLED set.
        </InlineNotice>
      ) : null}
      <SelectField
        label="SSH compatibility"
        error={form.formState.errors.ssh_compatibility?.message}
        hint={
          SSH_MODE_LABELS[watchedConnection.ssh_compatibility ?? 'modern'].hint
        }
        {...form.register('ssh_compatibility', {
          onChange: () => {
            clearConnectionState();
            form.setValue('group1_risk_acknowledged', false, { shouldValidate: true });
            form.setValue('very_old_risk_acknowledged', false, { shouldValidate: true });
          },
        })}
      >
        {availableModes.map((mode) => (
          <option key={mode} value={mode}>
            {SSH_MODE_LABELS[mode].label}
          </option>
        ))}
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
            <input
              type="checkbox"
              {...form.register('group1_risk_acknowledged', { onChange: clearConnectionState })}
            />
            I accept the Group1 risk for this device.
          </label>
          {form.formState.errors.group1_risk_acknowledged === undefined ? null : (
            <span className="field__error" role="alert">
              {form.formState.errors.group1_risk_acknowledged.message}
            </span>
          )}
        </>
      ) : null}
      {watchedConnection.ssh_compatibility === 'very_old_ssh' ? (
        <>
          <InlineNotice tone="warning" title="Last-resort obsolete cryptography exception">
            Very Old SSH re-enables obsolete algorithms (such as 3DES, DSS, and Group1) as a last-resort per-device exception. It is never an automatic fallback.
          </InlineNotice>
          <label className="usb-console-echo">
            <input
              type="checkbox"
              {...form.register('very_old_risk_acknowledged', { onChange: clearConnectionState })}
            />
            I accept the Very Old SSH cryptography risk for this device.
          </label>
          {form.formState.errors.very_old_risk_acknowledged === undefined ? null : (
            <span className="field__error" role="alert">
              {form.formState.errors.very_old_risk_acknowledged.message}
            </span>
          )}
        </>
      ) : null}

      <div className="connection-test">
        <div className="connection-test__header">
          <div>
            <strong>SSH host identity</strong>
            <span>Inspect and verify before credentials are sent</span>
          </div>
          <Button onClick={() => void inspectHostKey()} busy={connectionState === 'testing'}>
            <KeyRound size={16} /> {candidate === undefined ? 'Inspect SSH host key' : 'Inspect again'}
          </Button>
        </div>
        {exactCandidate ? (
          <div className="host-key-candidate">
            <span><strong>{candidate.algorithm}</strong> {candidate.fingerprint}</span>
            <label>
              <input
                type="checkbox"
                checked={connectionState === 'confirmed' || connectionState === 'passed'}
                disabled={connectionState === 'testing' || connectionState === 'passed'}
                onChange={(event) => setConnectionState(event.target.checked ? 'confirmed' : 'candidate')}
              />
              I verified this fingerprint with the device owner.
            </label>
          </div>
        ) : null}
        <div className="connection-test__header">
          <div>
            <strong>Explicit connection check</strong>
            <span>Required before this record can be saved</span>
          </div>
          <Button
            onClick={() => void testConnection()}
            busy={connectionState === 'testing'}
            disabled={connectionState !== 'confirmed'}
          >
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
          <ConnectionError
            error={testError}
            fallback="The connection test could not complete."
          />
        )}
        {isHostKeyError(testError) ? (
          <p className="connection-test__followup">Inspect the SSH host key again to continue.</p>
        ) : null}
      </div>
      {error === undefined ? null : (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}
      {blockedReason === undefined ? null : (
        <div className="form-error" role="alert">
          {blockedReason}
        </div>
      )}
      <div className="form-actions">
        {readyToSave ? null : (
          <span className="form-actions__blocked">{saveBlockedBecause}</span>
        )}
        <Button onClick={onCancel}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!readyToSave} busy={form.formState.isSubmitting}>
          <ShieldCheck size={16} /> {device === undefined ? 'Save device' : 'Save changes'}
        </Button>
      </div>
    </form>
  );
}
