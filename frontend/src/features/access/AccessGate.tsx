import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, KeyRound, LockKeyhole, Network, ServerCog, ShieldCheck } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import type { ReactNode } from 'react';
import { api } from '../../api/network';
import type { HealthResponse } from '../../types/api';
import { AppState, QueryErrorState } from '../../components/ui/AppState';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { InputField } from '../../components/ui/FormField';

interface AccessGateProps {
  children: (props: { health: HealthResponse; onLogout: () => Promise<void> }) => ReactNode;
}

const setupSchema = z
  .object({
    master_password: z
      .string()
      .min(12, 'Use at least 12 characters.')
      .max(256, 'Use no more than 256 characters.'),
    confirm_password: z.string(),
  })
  .refine((value) => value.master_password === value.confirm_password, {
    message: 'Passwords do not match.',
    path: ['confirm_password'],
  });

const loginSchema = z.object({
  master_password: z.string().min(1, 'Enter your master password.'),
});

type SetupFields = z.infer<typeof setupSchema>;
type LoginFields = z.infer<typeof loginSchema>;

function BrandPanel() {
  return (
    <section className="access-brand" aria-label="Product introduction">
      <div className="brand-mark brand-mark--large" aria-hidden="true">
        <Network size={28} />
      </div>
      <Badge tone="info">LOCAL CONTROL WORKBENCH</Badge>
      <h1>Know what is running before anything changes.</h1>
      <p>
        Terraformer connects to your Cisco lab over the management network and records observed state in
        one safe, local workspace.
      </p>
      <ul className="access-benefits">
        <li>
          <ShieldCheck size={18} />
          <span>
            <strong>Read-only foundation</strong>
            Phase 0–1 never applies configuration changes.
          </span>
        </li>
        <li>
          <LockKeyhole size={18} />
          <span>
            <strong>Secrets stay server-side</strong>
            Credentials never return to this browser after saving.
          </span>
        </li>
        <li>
          <ServerCog size={18} />
          <span>
            <strong>Observed, not simulated</strong>
            Facts, interfaces, and snapshots come from devices you explicitly test.
          </span>
        </li>
      </ul>
    </section>
  );
}

function SetupScreen({ onComplete }: { onComplete: () => void }) {
  const form = useForm<SetupFields>({
    resolver: zodResolver(setupSchema),
    defaultValues: { master_password: '', confirm_password: '' },
  });
  const setup = useMutation({
    mutationFn: async ({ master_password }: SetupFields) => {
      await api.setup(master_password);
      return api.login(master_password);
    },
    onSuccess: onComplete,
  });

  return (
    <main className="access-page">
      <BrandPanel />
      <section className="access-card" aria-labelledby="setup-title">
        <div className="access-card__step">FIRST-RUN SETUP</div>
        <div className="access-card__icon" aria-hidden="true">
          <KeyRound size={22} />
        </div>
        <h2 id="setup-title">Secure this local workspace</h2>
        <p>Create the master password used to unlock encrypted credential profiles on this machine.</p>
        <form onSubmit={form.handleSubmit((values) => setup.mutate(values))} noValidate>
          <InputField
            label="Master password"
            type="password"
            autoComplete="new-password"
            placeholder="At least 12 characters"
            error={form.formState.errors.master_password?.message}
            {...form.register('master_password')}
          />
          <InputField
            label="Confirm master password"
            type="password"
            autoComplete="new-password"
            placeholder="Repeat your password"
            error={form.formState.errors.confirm_password?.message}
            {...form.register('confirm_password')}
          />
          {setup.error === null ? null : (
            <div className="form-error" role="alert">
              {setup.error.message}
            </div>
          )}
          <Button type="submit" variant="primary" busy={setup.isPending} className="button--full">
            Create secure workspace
          </Button>
        </form>
        <div className="access-footnote">
          <ShieldCheck size={15} />
          Recovery is intentionally unavailable. Store this password safely.
        </div>
      </section>
    </main>
  );
}

function LoginScreen({ onComplete }: { onComplete: () => void }) {
  const form = useForm<LoginFields>({
    resolver: zodResolver(loginSchema),
    defaultValues: { master_password: '' },
  });
  const login = useMutation({
    mutationFn: ({ master_password }: LoginFields) => api.login(master_password),
    onSuccess: onComplete,
  });

  return (
    <main className="access-page">
      <BrandPanel />
      <section className="access-card" aria-labelledby="login-title">
        <div className="access-card__step">LOCAL SESSION</div>
        <div className="access-card__icon" aria-hidden="true">
          <LockKeyhole size={22} />
        </div>
        <h2 id="login-title">Unlock Terraformer</h2>
        <p>Enter the master password for this machine. It is sent only to the local API.</p>
        <form onSubmit={form.handleSubmit((values) => login.mutate(values))} noValidate>
          <InputField
            label="Master password"
            type="password"
            autoComplete="current-password"
            autoFocus
            error={form.formState.errors.master_password?.message}
            {...form.register('master_password')}
          />
          {login.error === null ? null : (
            <div className="form-error" role="alert">
              {login.error.message}
            </div>
          )}
          <Button type="submit" variant="primary" busy={login.isPending} className="button--full">
            Unlock workspace
          </Button>
        </form>
        <div className="access-footnote">
          <Check size={15} />
          Single-user session · bound to this local deployment
        </div>
      </section>
    </main>
  );
}

function ServicesUnavailable({ health, retry }: { health: HealthResponse; retry: () => void }) {
  return (
    <main className="centered-page">
      <div className="centered-page__brand">
        <Network size={22} /> Terraformer
      </div>
      <AppState
        kind="error"
        title="Local services are not ready"
        message="Terraformer is running, but a required local service is unavailable. No device connections have been attempted."
        actionLabel="Check again"
        onAction={retry}
      />
      <div className="service-checks" aria-label="Service health">
        {Object.entries(health.checks).map(([name, check]) => (
          <div key={name}>
            <span>{name}</span>
            <Badge tone={check.status === 'ok' ? 'success' : 'danger'} dot>
              {check.status}
            </Badge>
          </div>
        ))}
      </div>
    </main>
  );
}

export function AccessGate({ children }: AccessGateProps) {
  const queryClient = useQueryClient();
  const health = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    retry: false,
    refetchInterval: 15_000,
  });
  const setup = useQuery({
    queryKey: ['setup'],
    queryFn: api.setupStatus,
    enabled: health.data !== undefined,
    retry: false,
  });
  const session = useQuery({
    queryKey: ['session'],
    queryFn: api.session,
    enabled: setup.data?.configured === true,
    retry: false,
  });

  if (health.isPending) {
    return (
      <main className="centered-page">
        <AppState kind="loading" title="Starting local workspace" message="Checking the API and local services…" />
      </main>
    );
  }
  if (health.isError) {
    return (
      <main className="centered-page">
        <QueryErrorState error={health.error} onRetry={() => void health.refetch()} />
      </main>
    );
  }

  const operationalStatuses = new Set<HealthResponse['status']>(['ok', 'degraded']);
  if (!operationalStatuses.has(health.data.status)) {
    return <ServicesUnavailable health={health.data} retry={() => void health.refetch()} />;
  }
  if (setup.isPending) {
    return (
      <main className="centered-page">
        <AppState kind="loading" title="Checking setup" message="Reading the local workspace state…" />
      </main>
    );
  }
  if (setup.isError) {
    return (
      <main className="centered-page">
        <QueryErrorState error={setup.error} onRetry={() => void setup.refetch()} />
      </main>
    );
  }
  if (!setup.data.configured) {
    return (
      <SetupScreen
        onComplete={() => {
          void queryClient.invalidateQueries({ queryKey: ['setup'] });
          void queryClient.invalidateQueries({ queryKey: ['session'] });
        }}
      />
    );
  }
  if (session.isPending) {
    return (
      <main className="centered-page">
        <AppState kind="loading" title="Restoring local session" message="Checking this browser session…" />
      </main>
    );
  }
  if (session.isError || !session.data.authenticated) {
    return (
      <LoginScreen
        onComplete={() => {
          void queryClient.invalidateQueries({ queryKey: ['session'] });
        }}
      />
    );
  }

  return children({
    health: health.data,
    onLogout: async () => {
      await api.logout();
      queryClient.clear();
      await queryClient.invalidateQueries({ queryKey: ['health'] });
      await queryClient.invalidateQueries({ queryKey: ['setup'] });
      await queryClient.invalidateQueries({ queryKey: ['session'] });
    },
  });
}
