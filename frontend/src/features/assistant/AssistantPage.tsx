import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound } from 'lucide-react';
import { useState } from 'react';
import { ApiError } from '../../api/client';
import { api } from '../../api/network';
import { AppState, InlineNotice, QueryErrorState } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import type { ProviderProfile, ProviderProfileInput } from '../../types/api';
import { ProviderProfileForm } from './ProviderProfileForm';
import { ProviderProfileList } from './ProviderProfileList';
import type { ProviderProfileTestResult } from './ProviderProfileList';

type ProviderDialog = { mode: 'create' } | { mode: 'edit'; profile: ProviderProfile } | null;

/**
 * Key management only.
 *
 * The chat itself is the right-hand sidebar on Device inventory and Topology,
 * where the devices it can be pointed at are already on screen. This page
 * exists so there is one place to put an API key, and one place to check
 * whether the endpoint behind it still answers.
 */
export function AssistantPage() {
  const queryClient = useQueryClient();
  const [providerDialog, setProviderDialog] = useState<ProviderDialog>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProviderProfile>();

  const profiles = useQuery({
    queryKey: ['provider-profiles'],
    queryFn: api.providerProfiles,
    retry: false,
  });

  const saveProfile = useMutation({
    mutationFn: ({
      input,
      current,
    }: {
      input: Partial<ProviderProfileInput>;
      current?: ProviderProfile;
    }) =>
      current !== undefined
        ? api.updateProviderProfile(current.id, input)
        : api.createProviderProfile({
            name: input.name ?? '',
            base_url: input.base_url ?? '',
            ...(input.provider_type !== undefined ? { provider_type: input.provider_type } : {}),
            ...(input.api_key !== undefined ? { api_key: input.api_key } : {}),
          }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['provider-profiles'] });
      setProviderDialog(null);
    },
  });

  const deleteProfile = useMutation({
    mutationFn: (profile: ProviderProfile) => api.deleteProviderProfile(profile.id),
    onSuccess: async () => {
      setDeleteTarget(undefined);
      await queryClient.invalidateQueries({ queryKey: ['provider-profiles'] });
    },
  });

  const testProfile = useMutation({
    mutationFn: (profile: ProviderProfile) => api.providerProfileModels(profile.id),
  });
  const profileTestResult: ProviderProfileTestResult | undefined =
    testProfile.variables === undefined
      ? undefined
      : testProfile.isSuccess
        ? {
            profileId: testProfile.variables.id,
            ok: true,
            message:
              testProfile.data.models.length > 0
                ? `Reachable -- ${String(testProfile.data.models.length)} model(s) available.`
                : 'Reachable, but the provider returned no models.',
          }
        : testProfile.isError
          ? {
              profileId: testProfile.variables.id,
              ok: false,
              message: 'Could not reach that endpoint.',
            }
          : undefined;

  const gatewayDisabled =
    profiles.error instanceof ApiError && profiles.error.code === 'ai_gateway_disabled_by_policy';

  return (
    <main className="activity-page provider-keys-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">PHASE 4 / BYOK ASSISTANT</span>
          <h1>AI provider keys</h1>
          <p>
            Add a key here once, then use the assistant from a device, the topology, or anywhere
            else it appears. This app never runs or bundles a model.
          </p>
        </div>
        {gatewayDisabled ? null : (
          <div className="page-header__actions">
            <Button variant="primary" onClick={() => setProviderDialog({ mode: 'create' })}>
              <KeyRound size={16} /> Add provider
            </Button>
          </div>
        )}
      </header>

      <section className="activity-panel provider-keys-panel">
        {gatewayDisabled ? (
          <AppState
            kind="unsupported"
            title="The assistant is turned off"
            message="This local deployment has AI_GATEWAY_ENABLED=false (the default). Set it to true in .env and restart the stack to turn on chat, read-only device tools, and AI-drafted Change Plans -- the assistant never runs or bundles a model itself, it proxies to a provider you configure once this is on."
          />
        ) : profiles.isPending ? (
          <AppState
            kind="loading"
            title="Loading profiles"
            message="Reading provider profile metadata…"
          />
        ) : profiles.isError ? (
          <QueryErrorState error={profiles.error} onRetry={() => void profiles.refetch()} />
        ) : (
          <>
            <InlineNotice tone="safe" title="Where the assistant appears">
              This page holds the keys. The chat itself opens as the right-hand sidebar from
              Device inventory or Topology, where it can be pointed at the devices you mean.
            </InlineNotice>
            <ProviderProfileList
              profiles={profiles.data}
              onCreate={() => setProviderDialog({ mode: 'create' })}
              onEdit={(profile) => setProviderDialog({ mode: 'edit', profile })}
              onDelete={setDeleteTarget}
              onTest={(profile) => testProfile.mutate(profile)}
              testingProfileId={testProfile.isPending ? testProfile.variables.id : undefined}
              testResult={profileTestResult}
            />
          </>
        )}
      </section>

      <Modal
        open={providerDialog !== null}
        title={
          providerDialog?.mode === 'edit' ? 'Edit provider profile' : 'New provider profile'
        }
        description="Pick your provider and paste its API key -- the base URL is filled in for you."
        onClose={() => setProviderDialog(null)}
      >
        {providerDialog === null ? null : (
          <ProviderProfileForm
            {...(providerDialog.mode === 'edit' ? { profile: providerDialog.profile } : {})}
            onCancel={() => setProviderDialog(null)}
            onSubmit={(input) =>
              saveProfile
                .mutateAsync({
                  input,
                  ...(providerDialog.mode === 'edit' ? { current: providerDialog.profile } : {}),
                })
                .then(() => undefined)
            }
            error={saveProfile.error?.message}
          />
        )}
      </Modal>

      <Modal
        open={deleteTarget !== undefined}
        title="Remove provider profile?"
        description="Assistant sessions using this profile will need a different one to keep chatting."
        onClose={() => setDeleteTarget(undefined)}
        size="small"
        footer={
          <>
            <Button onClick={() => setDeleteTarget(undefined)}>Cancel</Button>
            <Button
              variant="danger"
              busy={deleteProfile.isPending}
              onClick={() => {
                if (deleteTarget !== undefined) deleteProfile.mutate(deleteTarget);
              }}
            >
              Remove profile
            </Button>
          </>
        }
      >
        <div className="delete-summary">
          <div className="device-avatar">
            <KeyRound size={20} />
          </div>
          <div>
            <strong>{deleteTarget?.name}</strong>
          </div>
        </div>
        {deleteProfile.error === null ? null : (
          <div className="form-error" role="alert">
            {deleteProfile.error.message}
          </div>
        )}
      </Modal>
    </main>
  );
}
